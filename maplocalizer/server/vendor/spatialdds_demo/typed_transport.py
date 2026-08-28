"""
Typed SpatialDDS endpoints: one DDS topic per logical topic, spec types, spec QoS.

This replaces the JSON envelope. The mapping is direct:

    envelope field            typed home
    ---------------------     ---------------------------------------------
    logical_topic             the DDS topic name
    msg_type                  the DDS type
    payload_json              the sample itself
    stamp_ns                  each type's own `stamp` field
    request_id                `query_id` on CoverageQuery / CoverageResponse,
                              or the demo struct's own correlation field

Every endpoint in the demo is created here, so the §3.3.3 profile table is
load-bearing rather than decorative: you cannot create a reader or writer
without naming a QoS profile, and an unregistered name raises.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type

from cyclonedds.core import InstanceState, Qos
from cyclonedds.domain import DomainParticipant
from cyclonedds.pub import DataWriter
from cyclonedds.sub import DataReader
from cyclonedds.topic import Topic

from spatialdds_demo import qos_profiles

# One Topic object per (participant, name) — CycloneDDS rejects a second Topic
# for the same name, and callers legitimately want a reader and a writer.
_topic_cache: Dict[Tuple[int, str], Topic] = {}
_topic_lock = threading.Lock()


def get_topic(participant: DomainParticipant, topic_name: str, datatype: Type) -> Topic:
    key = (id(participant), topic_name)
    with _topic_lock:
        topic = _topic_cache.get(key)
        if topic is None:
            topic = Topic(participant, topic_name, datatype)
            _topic_cache[key] = topic
        return topic


def make_writer(
    participant: DomainParticipant,
    topic_name: str,
    datatype: Type,
    qos_profile: str,
    *,
    lifespan_sec: Optional[float] = None,
) -> DataWriter:
    """
    A writer on ``topic_name`` carrying ``datatype`` with ``qos_profile``'s QoS.

    ``lifespan_sec`` maps a payload TTL (e.g. ``Announce.ttl_sec``) onto DDS
    Lifespan, so the middleware expires stale samples instead of every consumer
    re-deriving staleness.
    """
    topic = get_topic(participant, topic_name, datatype)
    return DataWriter(
        participant, topic,
        qos=qos_profiles.qos_for(qos_profile, lifespan_sec=lifespan_sec),
    )


def make_reader(
    participant: DomainParticipant,
    topic_name: str,
    datatype: Type,
    qos_profile: str,
    *,
    lifespan_sec: Optional[float] = None,
    ignore_local: bool = False,
    keep_all: bool = False,
) -> DataReader:
    """
    A reader on ``topic_name`` matching ``make_writer``'s QoS.

    ``ignore_local`` adds IGNORE_LOCAL_PARTICIPANT, so the reader never sees
    what writers in its own participant published. That is what a bridge
    needs: it republishes onto DDS what it received from elsewhere, and
    without this it reads its own output straight back. DDS answers this at
    the middleware, so nothing has to ride in the payload to mark it.

    ``keep_all`` replaces the profile's history with KEEP_ALL, for the one
    shape a per-topic profile cannot express: a reply topic that *many*
    services write to in answer to one request. `CoverageResponse` carries no
    ``@key``, so every responder's reply lands on the same instance; under the
    profile's KEEP_LAST(1) the second reply overwrites the first before a
    reader polling at any sane interval can take it, and the querier silently
    sees one service where several answered. History is a reader-side policy,
    so raising it here changes nothing for anyone else on the topic.
    """
    from cyclonedds.core import Policy

    qos = qos_profiles.qos_for(qos_profile, lifespan_sec=lifespan_sec)
    if keep_all:
        qos = Qos(*(p for p in qos if not isinstance(p, type(Policy.History.KeepLast(1)))),
                  Policy.History.KeepAll)
    if ignore_local:
        qos = Qos(*qos, Policy.IgnoreLocal.Participant)
    topic = get_topic(participant, topic_name, datatype)
    return DataReader(participant, topic, qos=qos)


# --- instance lifecycle -----------------------------------------------------

def dispose(writer: DataWriter, sample: Any) -> None:
    """
    Dispose the sample's instance: "this thing is gone", not "this topic is".

    Only meaningful on a keyed type. For `Announce` (keyed on `service_id`)
    this is the eviction signal a discovery consumer should act on, and it is
    what the demo could not express while everything rode one unkeyed envelope.
    """
    writer.dispose(sample)


@dataclass
class TypedSample:
    """
    One reader sample, with the instance facts a cache needs.

    ``data`` is None when the instance was disposed or lost its writers: DDS
    delivers that as an InvalidSample carrying no key fields, only the handle.
    Callers therefore track ``instance_handle -> key`` from the alive samples
    they have already seen, which is what :class:`AnnounceCache` does.
    """

    data: Optional[Any]
    alive: bool
    instance_handle: Optional[int]

    @property
    def disposed(self) -> bool:
        return not self.alive


def take_samples(reader: DataReader, *, n: int = 100) -> List[Any]:
    """Valid samples only — for callers that do not care about disposal."""
    return [s.data for s in take_with_state(reader, n=n) if s.data is not None]


def take_with_state(reader: DataReader, *, n: int = 100) -> List[TypedSample]:
    """
    Samples plus their instance state, so callers can act on disposal.

    This is the per-instance signal the demo could not express while
    everything rode one unkeyed envelope: "this service is gone", rather than
    "this topic is gone".
    """
    out: List[TypedSample] = []
    for sample in (reader.take(N=n) or []):
        if sample is None:
            continue
        info = getattr(sample, "sample_info", None)
        handle = getattr(info, "instance_handle", None) if info else None
        valid = getattr(info, "valid_data", True) if info else True
        state = getattr(info, "instance_state", InstanceState.Alive) if info else InstanceState.Alive
        alive = bool(valid) and state == InstanceState.Alive
        out.append(TypedSample(
            data=sample if valid else None,
            alive=alive,
            instance_handle=handle,
        ))
    return out


@dataclass
class TopicSample:
    """A sample plus the topic it arrived on."""

    topic: str
    type_name: str
    data: Any
    alive: bool = True
    instance_handle: Optional[int] = None


class MultiTopicSubscriber:
    """
    One reader per typed topic, discovered rather than hardcoded.

    This is what replaces the envelope's "single reader sees everything". The
    envelope bought that convenience by putting every stream in one QoS lane;
    here each topic keeps its own type and its own profile, and the consumer
    pays for it by having to learn which topics exist.

    Topics come from announced ``TopicMeta`` rows — the spec-native path, since
    a service already advertises its topics with their type and QoS profile.
    Unknown types are skipped, not fatal: §3.3.2 treats unregistered values as
    extension points.
    """

    def __init__(self, participant: DomainParticipant, *,
                 ignore_local: bool = False):
        self._participant = participant
        self._ignore_local = ignore_local
        self._readers: Dict[str, Tuple[Any, str]] = {}   # topic -> (reader, type_name)
        self._lock = threading.Lock()

    @property
    def topics(self) -> List[str]:
        with self._lock:
            return sorted(self._readers)

    def subscribe(self, topic: str, datatype: Type, qos_profile: str,
                  type_name: str = "") -> bool:
        """Add a reader for one topic. False if already subscribed."""
        with self._lock:
            if topic in self._readers:
                return False
        reader = make_reader(self._participant, topic, datatype, qos_profile,
                             ignore_local=self._ignore_local)
        with self._lock:
            self._readers[topic] = (reader, type_name or datatype.__name__)
        return True

    def subscribe_from_topic_meta(self, topics: Any) -> List[str]:
        """
        Subscribe to every announced topic whose type this build can resolve.

        ``topics`` is an announce's ``TopicMeta`` sequence (typed rows or the
        JSON equivalent). Returns the topics newly subscribed.
        """
        from spatialdds_demo import topic_types

        added: List[str] = []
        for row in topics or []:
            name = _meta_field(row, "name")
            type_name = _meta_field(row, "type")
            qos_profile = _meta_field(row, "qos_profile")
            if not (name and type_name and qos_profile):
                continue
            datatype = topic_types.try_resolve(type_name)
            if datatype is None:
                continue
            try:
                if self.subscribe(name, datatype, qos_profile, type_name):
                    added.append(name)
            except Exception:
                # A topic whose QoS profile this build does not know, or a
                # type mismatch with an existing endpoint. Skip it rather than
                # taking the whole consumer down.
                continue
        return added

    def poll(self, *, n: int = 100) -> List[TopicSample]:
        with self._lock:
            readers = list(self._readers.items())
        out: List[TopicSample] = []
        for topic, (reader, type_name) in readers:
            for sample in take_with_state(reader, n=n):
                out.append(TopicSample(
                    topic=topic, type_name=type_name, data=sample.data,
                    alive=sample.alive, instance_handle=sample.instance_handle,
                ))
        return out


def _meta_field(row: Any, field: str) -> str:
    if isinstance(row, dict):
        return str(row.get(field) or "")
    return str(getattr(row, field, "") or "")


class TypedDictWriter:
    """
    A typed writer fed with JSON dicts.

    The demo's publishers build payloads as dicts and always have. This keeps
    that, while putting a real typed sample on the wire: the dict is built into
    the struct before writing, so a malformed payload fails at the publisher
    rather than becoming an opaque string a consumer discovers later.

    It is a migration aid, not a hiding place — the bus carries the type, and
    `from_json` refuses anything that is not a complete, well-formed sample.
    """

    def __init__(self, participant: DomainParticipant, topic: str, datatype: Type,
                 qos_profile: str, *, lifespan_sec: Optional[float] = None):
        self.topic = topic
        self.datatype = datatype
        self._writer = make_writer(
            participant, topic, datatype, qos_profile, lifespan_sec=lifespan_sec)

    def write(self, payload: Any) -> None:
        from spatialdds_demo.json_mapping import from_json

        sample = payload if isinstance(payload, self.datatype) else from_json(
            self.datatype, payload)
        self._writer.write(sample)

    def dispose(self, payload: Any) -> None:
        from spatialdds_demo.json_mapping import from_json

        sample = payload if isinstance(payload, self.datatype) else from_json(
            self.datatype, payload)
        self._writer.dispose(sample)


def samples_as_json(samples: List[TopicSample]) -> List[Tuple[str, str, Any]]:
    """``(topic, type_name, dict)`` for consumers that work in JSON."""
    from spatialdds_demo.json_mapping import to_json

    return [
        (s.topic, s.type_name, to_json(s.data))
        for s in samples if s.data is not None
    ]
