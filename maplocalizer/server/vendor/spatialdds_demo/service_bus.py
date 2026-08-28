"""
Typed request/reply for the demo's service flows: VPS localization and catalogue.

Both are request/reply over DDS, correlated by the `query_id` the request
carries and the response mirrors, rather than by the envelope's old
`request_id` string. Server, client and web bridge all go through here, so the
three cannot drift in topic name, QoS profile or correlation rule.

Type ownership:

* **VPS** — now fully spec types. `argeo::VpsRequest` / `VpsResponse`
  (registered as `vps_query` / `vps_response`, §3.3.2) carry the query imagery
  by `BlobRef` reference and the result in `argeo::NodeGeo`. The `oarc_demo`
  VPS copies are retired.
* **Catalogue** — still demo-owned: 1.7 has `ContentAnnounce` for advertising
  content but no query/response pair for asking a catalogue what is in an area.

The catalogue gap is catalogued in ar_demo/SPEC_COMPLIANCE.md.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from cyclonedds.domain import DomainParticipant

from spatialdds_demo import typed_transport as tt
from spatialdds_demo.topics import (
    TOPIC_BOOTSTRAP_QUERY_V1,
    TOPIC_BOOTSTRAP_RESPONSE_V1,
    TOPIC_CATALOG_QUERY_V1,
    TOPIC_DISCOVERY_QUERY_V1,
    TOPIC_VPS_QUERY_V1,
    TOPIC_VPS_RESULT_V1,
)
from spatialdds_idl.oarc_demo import (
    BootstrapQuery,
    BootstrapResponse,
    CatalogQuery,
    CatalogResponse,
)
from spatialdds_idl.spatial.argeo import VpsRequest, VpsResponse
from spatialdds_idl.spatial.disco import CoverageQuery, CoverageResponse

# How often a waiting client re-checks its reply reader. 20 ms is a fine
# default for a demo at demo rates, and it is also a hard latency floor: a
# reply that arrives in 2 ms is still not seen for up to 20. Callers that
# care — the latency benchmark, chiefly — pass something tighter, which is
# why it is a parameter rather than a constant in four loops.
DEFAULT_POLL_INTERVAL = 0.02

# Registered QoS profiles for these lanes (3.3.3).
VPS_REQ_PROFILE = "VPS_REQ"
VPS_RESP_PROFILE = "VPS_RESP"
# The catalogue is a demo protocol; it borrows the VPS request/reply profiles,
# which are the reliable ordered lanes its semantics call for.
CATALOG_REQ_PROFILE = "VPS_REQ"
CATALOG_RESP_PROFILE = "VPS_RESP"


class VpsService:
    """Server side of the localization exchange."""

    def __init__(self, participant: DomainParticipant):
        self._reader = tt.make_reader(
            participant, TOPIC_VPS_QUERY_V1, VpsRequest, VPS_REQ_PROFILE)
        self._writer = tt.make_writer(
            participant, TOPIC_VPS_RESULT_V1, VpsResponse, VPS_RESP_PROFILE)

    def take_requests(self) -> List[VpsRequest]:
        return tt.take_samples(self._reader)

    def reply(self, response: VpsResponse) -> None:
        self._writer.write(response)


class VpsClient:
    """Client side: publish a request, wait for the reply that matches it."""

    def __init__(self, participant: DomainParticipant):
        self._writer = tt.make_writer(
            participant, TOPIC_VPS_QUERY_V1, VpsRequest, VPS_REQ_PROFILE)
        self._reader = tt.make_reader(
            participant, TOPIC_VPS_RESULT_V1, VpsResponse, VPS_RESP_PROFILE)

    def request(self, request: VpsRequest, timeout: float = 10.0,
                poll_interval: float = DEFAULT_POLL_INTERVAL
                ) -> Optional[VpsResponse]:
        self._writer.write(request)
        return self.await_reply(request.query_id, timeout=timeout,
                                poll_interval=poll_interval)

    def await_reply(self, query_id: str, timeout: float = 10.0,
                    poll_interval: float = DEFAULT_POLL_INTERVAL
                    ) -> Optional[VpsResponse]:
        """
        Correlation is the query_id the response mirrors — no envelope needed.

        Replies for other requests are ignored rather than consumed-and-dropped
        where possible; at demo concurrency a single in-flight request is the
        normal case.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for response in tt.take_samples(self._reader):
                if response.query_id == query_id:
                    return response
            time.sleep(poll_interval)
        return None


class CatalogService:
    """Server side of the catalogue exchange. Replies on the query's reply_topic."""

    def __init__(self, participant: DomainParticipant):
        self._participant = participant
        self._reader = tt.make_reader(
            participant, TOPIC_CATALOG_QUERY_V1, CatalogQuery, CATALOG_REQ_PROFILE)
        self._reply_writers: Dict[str, object] = {}

    def take_queries(self) -> List[CatalogQuery]:
        return tt.take_samples(self._reader)

    def reply(self, reply_topic: str, response: CatalogResponse) -> None:
        writer = self._reply_writers.get(reply_topic)
        if writer is None:
            writer = tt.make_writer(
                self._participant, reply_topic, CatalogResponse, CATALOG_RESP_PROFILE)
            self._reply_writers[reply_topic] = writer
        writer.write(response)


class CatalogClient:
    """Client side: ask on the well-known topic, listen on a private reply topic."""

    def __init__(self, participant: DomainParticipant, reply_topic: str):
        self._reply_topic = reply_topic
        self._writer = tt.make_writer(
            participant, TOPIC_CATALOG_QUERY_V1, CatalogQuery, CATALOG_REQ_PROFILE)
        self._reader = tt.make_reader(
            participant, reply_topic, CatalogResponse, CATALOG_RESP_PROFILE)

    @property
    def reply_topic(self) -> str:
        return self._reply_topic

    def query(self, query: CatalogQuery, timeout: float = 6.0,
              poll_interval: float = DEFAULT_POLL_INTERVAL
              ) -> Optional[CatalogResponse]:
        self._writer.write(query)
        deadline = time.time() + timeout
        while time.time() < deadline:
            for response in tt.take_samples(self._reader):
                if response.query_id == query.query_id:
                    return response
            time.sleep(poll_interval)
        return None


# --- Coverage query: "who covers this area?" --------------------------------
# A spec flow, unlike VPS and catalogue: `CoverageQuery` and `CoverageResponse`
# are disco types, and C.5 puts the query on a well-known topic with the reply
# going to a topic the query names. Results are compact `ServiceSummary` rows —
# a consumer selects on the summary and takes detail from the retained
# Announce it already holds, or by resolving `manifest_uri`.
COVERAGE_QUERY_PROFILE = "ZONE_META"
COVERAGE_RESP_PROFILE = "ZONE_META"


class CoverageService:
    """Server side: read queries on the well-known topic, reply where asked."""

    def __init__(self, participant: DomainParticipant):
        self._participant = participant
        self._reader = tt.make_reader(
            participant, TOPIC_DISCOVERY_QUERY_V1, CoverageQuery,
            COVERAGE_QUERY_PROFILE)
        self._reply_writers: Dict[str, object] = {}

    def take_queries(self) -> List[CoverageQuery]:
        return tt.take_samples(self._reader)

    def reply(self, reply_topic: str, response: CoverageResponse) -> None:
        writer = self._reply_writers.get(reply_topic)
        if writer is None:
            writer = tt.make_writer(
                self._participant, reply_topic, CoverageResponse,
                COVERAGE_RESP_PROFILE)
            self._reply_writers[reply_topic] = writer
        writer.write(response)


class CoverageClient:
    """Client side: ask on the well-known topic, listen on a private reply topic."""

    def __init__(self, participant: DomainParticipant, reply_topic: str):
        self._reply_topic = reply_topic
        self._writer = tt.make_writer(
            participant, TOPIC_DISCOVERY_QUERY_V1, CoverageQuery,
            COVERAGE_QUERY_PROFILE)
        # KEEP_ALL, not the profile's KEEP_LAST(1): every service that covers
        # the queried area answers this one topic, and `CoverageResponse` has
        # no `@key`, so all of their replies share a single instance. At depth
        # 1 the last writer wins and the querier concludes one service exists
        # where several do — with nothing to indicate loss.
        self._reader = tt.make_reader(
            participant, reply_topic, CoverageResponse, COVERAGE_RESP_PROFILE,
            keep_all=True)

    @property
    def reply_topic(self) -> str:
        return self._reply_topic

    def query(self, query: CoverageQuery, timeout: float = 10.0,
              poll_interval: float = DEFAULT_POLL_INTERVAL
              ) -> Optional[CoverageResponse]:
        self._writer.write(query)
        deadline = time.time() + timeout
        while time.time() < deadline:
            for response in tt.take_samples(self._reader):
                if response.query_id == query.query_id:
                    return response
            time.sleep(poll_interval)
        return None

    def gather(self, query: CoverageQuery, window: float = 1.5,
               poll_interval: float = DEFAULT_POLL_INTERVAL
               ) -> List[CoverageResponse]:
        """
        Every response to one query, not just the first.

        Coverage discovery is one-to-many: the query goes to a well-known
        topic that every service reads, and each answers separately on the
        reply topic the query named. :meth:`query` returns as soon as one
        replies, which is right for a request/reply flow with a single
        responder and wrong here — it would find whichever service happened to
        answer first and silently miss the rest.

        There is no completion signal to wait for, because a querier cannot
        know how many services exist. So this collects for a fixed window.
        """
        self._writer.write(query)
        responses: List[CoverageResponse] = []
        seen_services: set = set()
        deadline = time.time() + window
        while time.time() < deadline:
            for response in tt.take_samples(self._reader):
                if response.query_id != query.query_id:
                    continue
                # A service that re-announces mid-window could answer twice.
                key = tuple(sorted(r.service_id for r in (response.results or [])))
                if key in seen_services and key != ():
                    continue
                seen_services.add(key)
                responses.append(response)
            time.sleep(poll_interval)
        return responses


# --- Bootstrap: "which domain and which manifests?" -------------------------
# Demo-owned. 1.7 has no bootstrap exchange — a participant is assumed to
# already know its domain id and QoS profile, which is exactly what a fresh
# device does not. Catalogued in ar_demo/SPEC_COMPLIANCE.md.
BOOTSTRAP_PROFILE = "MAP_META"


class BootstrapService:
    """Server side: answer a client asking how to join."""

    def __init__(self, participant: DomainParticipant):
        self._reader = tt.make_reader(
            participant, TOPIC_BOOTSTRAP_QUERY_V1, BootstrapQuery,
            BOOTSTRAP_PROFILE)
        self._writer = tt.make_writer(
            participant, TOPIC_BOOTSTRAP_RESPONSE_V1, BootstrapResponse,
            BOOTSTRAP_PROFILE)

    def take_queries(self) -> List[BootstrapQuery]:
        return tt.take_samples(self._reader)

    def reply(self, response: BootstrapResponse) -> None:
        self._writer.write(response)


class BootstrapClient:
    """Client side: ask, and wait for the answer addressed to us."""

    def __init__(self, participant: DomainParticipant):
        self._writer = tt.make_writer(
            participant, TOPIC_BOOTSTRAP_QUERY_V1, BootstrapQuery,
            BOOTSTRAP_PROFILE)
        self._reader = tt.make_reader(
            participant, TOPIC_BOOTSTRAP_RESPONSE_V1, BootstrapResponse,
            BOOTSTRAP_PROFILE)

    def request(self, query: BootstrapQuery, timeout: float = 5.0,
                retry_every: float = 1.0,
                poll_interval: float = DEFAULT_POLL_INTERVAL
                ) -> Optional[BootstrapResponse]:
        """
        Ask until answered or out of time.

        Retried because bootstrap is the one exchange that cannot assume
        discovery has settled: it is what a participant does *before* it
        knows anything about the deployment.
        """
        deadline = time.time() + timeout
        next_send = 0.0
        while time.time() < deadline:
            now = time.time()
            if now >= next_send:
                self._writer.write(query)
                next_send = now + retry_every
            for response in tt.take_samples(self._reader):
                if response.client_id == query.client_id:
                    return response
            time.sleep(poll_interval)
        return None
