"""
The JSON envelope transport, kept as the benchmarks' baseline arm.

Nothing in the demo publishes through this any more. It survives for one
reason: the benchmarks compare the envelope against typed topics, and a
comparison needs both arms. `require_dds_env` is the other reason — it
validates the DDS environment and has nothing to do with the envelope.

What it was: one struct on one topic, with the actual SpatialDDS payload
serialised to a JSON string inside it and the topic name demoted to a
string field. Every mechanism the spec relies on DDS *for* — per-topic QoS,
instances and keys, durability, content filtering, per-topic security,
XTypes evolution, and interoperability with any other conformant
participant — was unavailable by construction. See
`spatialdds_demo/stream.py` for what replaced it.

Do not add callers.
"""

import hashlib
import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional, Set, Tuple

from spatialdds_demo.topics import TOPIC_DISCOVERY_ANNOUNCE_V1, TOPIC_DDS_ENVELOPE_V1


class DDSTransport:
    def __init__(
        self,
        on_message_callback: Callable[[object], None],
        domain_id: int,
        local_sender_id: Optional[str] = None,
        poll_interval: float = 0.01,
    ):
        # 10 ms was hardcoded, and it is a latency floor: a sample that
        # arrives in 2 ms is not seen for up to 10. The benchmark passes
        # something tighter so its comparison measures serialisation and
        # transport rather than two different poll loops.
        self._poll_interval = poll_interval
        try:
            from cyclonedds.domain import DomainParticipant
            from cyclonedds.topic import Topic
            from cyclonedds.sub import DataReader
            from cyclonedds.pub import DataWriter
            from cyclonedds.idl import IdlStruct, types
        except Exception as exc:
            print(f"Failed to import Cyclone DDS Python bindings: {exc}")
            sys.exit(1)

        string_type = _idl_string(types)
        uint64_type = _idl_uint64(types)

        @dataclass
        class SpatialDDSEnvelope(IdlStruct):
            msg_type: string_type
            logical_topic: string_type
            payload_json: string_type
            stamp_ns: uint64_type
            request_id: string_type

        try:
            self._participant = DomainParticipant(domain_id)
            self._envelope_type = SpatialDDSEnvelope
            self._topic = Topic(self._participant, TOPIC_DDS_ENVELOPE_V1, self._envelope_type)
            self._writer = DataWriter(self._participant, self._topic)
            self._reader = DataReader(self._participant, self._topic)
        except Exception as exc:
            print(f"Failed to initialize Cyclone DDS: {exc}")
            sys.exit(1)
        self._callback = on_message_callback
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._domain_id = domain_id
        self._local_sender_id = local_sender_id
        self._sent_fingerprints: Deque[Tuple[str, str, str, str]] = deque(maxlen=512)
        self._sent_fingerprint_set: Set[Tuple[str, str, str, str]] = set()
        self._sent_msg_types: Set[str] = set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def publish(
        self, logical_topic: str, msg_type: str, payload_json: str, request_id: str = ""
    ) -> None:
        self.publish_on(self._writer, logical_topic, msg_type, payload_json, request_id)

    def publish_on(
        self,
        writer: object,
        logical_topic: str,
        msg_type: str,
        payload_json: str,
        request_id: str = "",
    ) -> None:
        envelope = self._envelope_type(
            msg_type=msg_type,
            logical_topic=logical_topic,
            payload_json=payload_json,
            stamp_ns=time.time_ns(),
            request_id=request_id or "",
        )
        self._record_sent(envelope)
        print(
            f"DDS_TX domain={self._domain_id} msg_type={msg_type} "
            f"logical_topic={logical_topic}"
        )
        writer.write(envelope)

    def create_announce_writer(self, ttl_sec: int) -> object:
        qos = _announce_qos(ttl_sec)
        topic = self._topic.__class__(
            self._participant, TOPIC_DISCOVERY_ANNOUNCE_V1, self._envelope_type
        )
        return self._writer.__class__(self._participant, topic, qos=qos)

    def create_announce_reader(self, ttl_sec: int) -> object:
        qos = _announce_qos(ttl_sec)
        topic = self._topic.__class__(
            self._participant, TOPIC_DISCOVERY_ANNOUNCE_V1, self._envelope_type
        )
        return self._reader.__class__(self._participant, topic, qos=qos)

    @staticmethod
    def announce_qos_summary(ttl_sec: int) -> str:
        return (
            "durability=TRANSIENT_LOCAL reliability=RELIABLE "
            f"history=KEEP_LAST(1) lifespan={ttl_sec}s"
        )

    def _poll(self) -> None:
        while not self._stop.is_set():
            samples = self._reader.take()
            if samples:
                for sample in samples:
                    if sample is None:
                        continue
                    if self._is_self_echo(sample):
                        continue
                    print(
                        "DDS_RX domain="
                        f"{self._domain_id} msg_type={sample.msg_type} "
                        f"logical_topic={sample.logical_topic}"
                    )
                    try:
                        self._callback(sample)
                    except Exception as exc:
                        print(f"DDS_RX callback error: {exc}")
            time.sleep(self._poll_interval)

    def _record_sent(self, envelope: object) -> None:
        if envelope.msg_type:
            self._sent_msg_types.add(envelope.msg_type)
        fingerprint = self._fingerprint(
            envelope.msg_type,
            envelope.logical_topic,
            envelope.request_id,
            envelope.payload_json,
        )
        if fingerprint in self._sent_fingerprint_set:
            return
        if len(self._sent_fingerprints) == self._sent_fingerprints.maxlen:
            oldest = self._sent_fingerprints.popleft()
            self._sent_fingerprint_set.discard(oldest)
        self._sent_fingerprints.append(fingerprint)
        self._sent_fingerprint_set.add(fingerprint)

    def _is_self_echo(self, envelope: object) -> bool:
        if self._local_sender_id:
            sender = _sender_id_from_payload(envelope.payload_json)
            if sender and sender == self._local_sender_id:
                return True
        fingerprint = self._fingerprint(
            envelope.msg_type,
            envelope.logical_topic,
            envelope.request_id,
            envelope.payload_json,
        )
        if envelope.msg_type in self._sent_msg_types:
            return fingerprint in self._sent_fingerprint_set
        return False

    @staticmethod
    def _fingerprint(msg_type: str, logical_topic: str, request_id: str, payload_json: str):
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        return (msg_type or "", logical_topic or "", request_id or "", payload_hash)


def _sender_id_from_payload(payload_json: str) -> Optional[str]:
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("from", "source_id", "sender_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    frame = payload.get("client_frame_ref")
    if isinstance(frame, dict):
        fqn = frame.get("fqn")
        if isinstance(fqn, str) and fqn:
            return fqn
    return None


def require_dds_env() -> int:
    transport = os.getenv("SPATIALDDS_TRANSPORT", "mock")
    if transport != "dds":
        print("SPATIALDDS_TRANSPORT is not set to dds; exiting.")
        sys.exit(1)

    uri = os.getenv("CYCLONEDDS_URI", "")
    if uri != "file:///etc/cyclonedds.xml":
        print("CYCLONEDDS_URI must be set to file:///etc/cyclonedds.xml")
        sys.exit(1)

    domain_str = os.getenv("SPATIALDDS_DDS_DOMAIN", "0")
    try:
        domain_id = int(domain_str)
    except ValueError:
        print(f"Invalid SPATIALDDS_DDS_DOMAIN value: {domain_str}")
        sys.exit(1)

    print("DDS transport enabled: Cyclone DDS")
    print(f"Domain: {domain_id}")
    print(f"CYCLONEDDS_URI: {uri}")
    return domain_id


def _idl_string(types_module):
    for name in ("string", "str", "String"):
        if hasattr(types_module, name):
            return getattr(types_module, name)
    return str


def _idl_uint64(types_module):
    for name in ("uint64", "uint64_t", "UInt64"):
        if hasattr(types_module, name):
            return getattr(types_module, name)
    return int


def _announce_qos(ttl_sec: int):
    from cyclonedds import qos, util

    ttl = max(1, int(ttl_sec))
    return qos.Qos(
        qos.Policy.Durability.TransientLocal,
        qos.Policy.Reliability.Reliable(util.duration(seconds=1)),
        qos.Policy.History.KeepLast(1),
        qos.Policy.Lifespan(util.duration(seconds=ttl)),
    )
