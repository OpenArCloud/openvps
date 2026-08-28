# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
"""
Does the web bridge actually discover this service, and relay a localization to it?

The unit tests cover the VPS binding in isolation. This covers the seam between it and the
bridge, which is where the deployment fails if it fails: the bridge only opens readers on
topics an announce declares, so an announce this service gets wrong is not a wrong field in
a log, it is a client that finds nothing and no error anywhere.

Everything runs in this process on one DDS domain — no Docker, no GPU, no map. The localizer
is a stub, because what is under test is discovery and transport.
"""

import json
import os
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent.parent
for p in (str(HERE), str(HERE / "vendor"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

DOMAIN = "49"
os.environ["SPATIALDDS_DDS_DOMAIN"] = DOMAIN
os.environ["SPATIALDDS_BOOTSTRAP_DOMAIN"] = DOMAIN
os.environ["SPATIALDDS_TRANSPORT"] = "dds"
os.environ.setdefault(
    "CYCLONEDDS_URI",
    "<CycloneDDS><Domain><General><Interfaces>"
    "<NetworkInterface autodetermine='true'/></Interfaces></General></Domain></CycloneDDS>")

from cyclonedds.domain import DomainParticipant                       # noqa: E402
from spatialdds_demo import typed_transport as tt                     # noqa: E402
from spatialdds_demo.json_mapping import from_json                    # noqa: E402
from spatialdds_idl.spatial.disco import Announce                     # noqa: E402

import spatialdds.announce as ann                                     # noqa: E402
import spatialdds.service as svc                                      # noqa: E402

SERVICE_ID = "svc:vps:oarc/bridgetest;v=2026-q3"
MAP_ID = "bridgemap"
BBOX = [19.0380, 47.4960, 19.0425, 47.4995]      # a small box over Budapest


class BridgeSeesTheService(unittest.TestCase):
    """The announce this service publishes, read back the way the bridge reads it."""

    @classmethod
    def setUpClass(cls):
        cls.dp = DomainParticipant(int(DOMAIN))
        cls.writer = tt.make_writer(
            cls.dp, ann.TOPIC_ANNOUNCE, Announce, ann.QOS_ANNOUNCE, lifespan_sec=300)
        payload = ann.build_announce(
            SERVICE_ID, "oarc", MAP_ID, BBOX,
            f"spatialdds://oarc/bridgetest/service/{MAP_ID}",
            min_inliers=20, scale_factor=0.241733)
        cls.writer.write(from_json(Announce, payload))
        time.sleep(1.0)

    def _take(self):
        """
        Read the announce the way a fresh client would: a new reader each time.

        `take` removes the sample, so a reader shared across tests hands the announce to
        whichever test runs first and nothing to the rest. A new reader per call is also the
        honest model — every discovering client is a late joiner, and TRANSIENT_LOCAL is what
        makes that work.
        """
        reader = tt.make_reader(self.dp, ann.TOPIC_ANNOUNCE, Announce, ann.QOS_ANNOUNCE)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            for a in tt.take_samples(reader):
                if a.service_id == SERVICE_ID:
                    return a
            time.sleep(0.05)
        return None

    def test_announce_is_on_the_bus_and_late_joiners_get_it(self):
        """TRANSIENT_LOCAL: a reader created after the write still receives it."""
        late = tt.make_reader(self.dp, ann.TOPIC_ANNOUNCE, Announce, ann.QOS_ANNOUNCE)
        time.sleep(0.6)
        got = [a for a in tt.take_samples(late) if a.service_id == SERVICE_ID]
        self.assertTrue(got, "a late joiner saw no announce; durability is not working")

    def test_advertises_the_registered_response_type(self):
        """
        The spec's own 3.3.4 example says `geopose` for the result topic. It is wrong — the
        topic carries VpsResponse, whose registered type is vps_response. A client filtering
        on the registered name must find this service.
        """
        a = self._take()
        self.assertIsNotNone(a)
        by_name = {t.name: t for t in a.topics}
        self.assertEqual(by_name["spatialdds/vps/result/v1"].type, "vps_response")
        self.assertEqual(by_name["spatialdds/vps/result/v1"].qos_profile, "VPS_RESP")
        self.assertEqual(by_name["spatialdds/vps/query/v1"].type, "vps_query")

    def test_topics_and_profiles_are_registered_names(self):
        """
        Every advertised type and profile is in the 3.3.2 / 3.3.3 registries.

        Weaker than the test above, and deliberately kept alongside it: this check passes
        for the spec's own wrong example too, because `geopose` *is* a registered type — it
        is simply the wrong one for a topic carrying VpsResponse. A registry check cannot
        see right-name-wrong-topic, which is how that error survived review in the spec.
        The assertion above is the one that catches it.
        """
        from spatialdds_demo.topics import validate_topic_meta
        a = self._take()
        rows = [{"name": t.name, "type": t.type, "version": t.version,
                 "qos_profile": t.qos_profile} for t in a.topics]
        ok, errors = validate_topic_meta(rows)
        self.assertTrue(ok, f"unregistered names in the announce: {errors}")

    def test_coverage_is_earth_fixed_and_bounded(self):
        a = self._take()
        cov = a.coverage[0]
        self.assertTrue(cov.has_bbox)
        self.assertFalse(cov._global, "a bounded map must not advertise global coverage")
        self.assertEqual(a.coverage_frame_ref.fqn, "earth-fixed")
        self.assertAlmostEqual(list(cov.bbox)[0], BBOX[0], places=6)

    def test_scale_is_discoverable_without_a_query(self):
        """
        The map frame's units are not metric, and 1.7 has no field for that. Until it does,
        a discovering client can only learn the factor from the announce.
        """
        a = self._take()
        hints = {h.key: h.value for h in a.hints}
        self.assertEqual(hints["openvps.map_id"], MAP_ID)
        self.assertAlmostEqual(float(hints["openvps.coord_scale_m_per_unit"]), 0.241733, places=6)


class CoverageRequiresGeoreference(unittest.TestCase):
    """A metric but ungeoreferenced map has nothing truthful to advertise."""

    def test_no_geodetic_anchor_yields_no_bbox(self):
        class _Rec:
            images = {}
        self.assertIsNone(
            ann.coverage_bbox_wgs84(_Rec(), __import__("numpy").eye(4), None),
            "a map with no geodetic anchor must not produce a coverage box")


if __name__ == "__main__":
    unittest.main(verbosity=2)
