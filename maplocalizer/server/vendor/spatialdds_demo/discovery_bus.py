"""
Typed discovery on the bus: keyed `Announce`, dispose-aware subscription.

`spatial::disco::Announce` is `@key string service_id`, so with
RELIABLE + TRANSIENT_LOCAL + KEEP_LAST(1) each service is its own instance:

* a late joiner receives the current announce of **every** live service, not
  one sample overall;
* disposing an instance says "this service is gone", which is the eviction
  signal a discovery cache should act on.

Neither was expressible while every announce rode one unkeyed envelope.

Departure is signalled twice, deliberately. Spec C.5 has dispose as the MUST
and `Depart` as a SHOULD; the demo does both because it bridges to transports
(MQTT, WebSocket) where DDS instance state does not exist and only a message
crosses over.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from cyclonedds.domain import DomainParticipant

from spatialdds_demo import typed_transport as tt
from spatialdds_demo.json_mapping import to_json
from spatialdds_demo.topics import (
    TOPIC_DISCOVERY_ANNOUNCE_V1,
    TOPIC_DISCOVERY_DEPART_V1,
    validate_topic_meta,
)
from spatialdds_idl.builtin import Time
from spatialdds_idl.spatial.disco import Announce, Depart

ANNOUNCE_PROFILE = "DISCOVERY_ANNOUNCE"
DEPART_PROFILE = "DISCOVERY_ANNOUNCE"  # latched too: a departure must not be missed


class NonConformantAnnounce(ValueError):
    """An announce that the repo's own conformance rules reject."""


def validate_announce(announce: Announce) -> None:
    """
    Check an announce against the rules the repo already encodes, before it
    reaches the bus.

    Findings 5.2: these validators existed but were called only from tests, so
    the flagship demo had been publishing announces its own conformance code
    would reject. Refusing at the writer is the difference between a rule and
    a decoration.
    """
    if not announce.service_id:
        raise NonConformantAnnounce("Announce.service_id is required (it is the key)")
    if not announce.manifest_uri:
        raise NonConformantAnnounce(
            f"{announce.service_id}: Announce.manifest_uri is required"
        )
    topics = [to_json(t) for t in (announce.topics or [])]
    ok, errors = validate_topic_meta(topics)
    if not ok:
        raise NonConformantAnnounce(
            f"{announce.service_id}: TopicMeta violates 3.3.2/3.3.3 — "
            + "; ".join(errors)
        )


@dataclass
class AnnounceEvent:
    """An announce arriving, or a service leaving."""

    service_id: str
    announce: Optional[Announce]     # None when the service departed
    alive: bool

    @property
    def departed(self) -> bool:
        return not self.alive


class AnnouncePublisher:
    """
    Publishes typed announces, and cleans up after itself on close.

    ``validate`` is on by default: a non-conformant announce raises instead of
    reaching the bus.
    """

    def __init__(self, participant: DomainParticipant, *, validate: bool = True):
        self._participant = participant
        self._validate = validate
        self._published: Dict[str, Announce] = {}
        self._lock = threading.Lock()
        self._writer = tt.make_writer(
            participant, TOPIC_DISCOVERY_ANNOUNCE_V1, Announce, ANNOUNCE_PROFILE,
        )
        self._depart_writer = tt.make_writer(
            participant, TOPIC_DISCOVERY_DEPART_V1, Depart, DEPART_PROFILE,
        )

    def publish(self, announce: Announce) -> None:
        if self._validate:
            validate_announce(announce)
        self._writer.write(announce)
        with self._lock:
            self._published[announce.service_id] = announce

    def depart(self, service_id: str, stamp: Optional[Time] = None) -> None:
        """Dispose the instance (spec MUST) and publish Depart (spec SHOULD)."""
        with self._lock:
            announce = self._published.pop(service_id, None)
        if announce is not None:
            self._writer.dispose(announce)
        self._depart_writer.write(
            Depart(service_id=service_id, stamp=stamp or Time(sec=0, nanosec=0))
        )

    def close(self) -> None:
        """Depart every service this publisher announced."""
        with self._lock:
            service_ids = list(self._published)
        for service_id in service_ids:
            self.depart(service_id)


class AnnounceSubscriber:
    """
    Reads announces and turns instance state into per-service events.

    A disposed instance arrives with no key fields, only an instance handle, so
    handles seen alive are remembered in order to name the service that left.
    """

    def __init__(self, participant: DomainParticipant):
        self._reader = tt.make_reader(
            participant, TOPIC_DISCOVERY_ANNOUNCE_V1, Announce, ANNOUNCE_PROFILE,
        )
        self._depart_reader = tt.make_reader(
            participant, TOPIC_DISCOVERY_DEPART_V1, Depart, DEPART_PROFILE,
        )
        self._handles: Dict[int, str] = {}

    def poll(self) -> List[AnnounceEvent]:
        events: List[AnnounceEvent] = []

        for sample in tt.take_with_state(self._reader):
            if sample.data is not None:
                service_id = sample.data.service_id
                if sample.instance_handle is not None:
                    self._handles[sample.instance_handle] = service_id
                events.append(AnnounceEvent(service_id, sample.data, True))
            else:
                service_id = self._handles.get(sample.instance_handle or -1, "")
                if service_id:
                    events.append(AnnounceEvent(service_id, None, False))

        # Depart is the bridgeable signal: DDS instance state does not cross to
        # MQTT or a WebSocket, so a message carries the same fact.
        for depart in tt.take_samples(self._depart_reader):
            events.append(AnnounceEvent(depart.service_id, None, False))

        return events
