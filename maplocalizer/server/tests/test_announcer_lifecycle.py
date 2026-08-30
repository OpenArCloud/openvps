# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
"""
The announcer against the map lifecycle: appear on load, change on swap, vanish on unload.

Uses a stand-in for HlocLocalizer carrying only what the announcer reads — a reconstruction
with camera centres, a map-to-ENU matrix, a geodetic anchor and a frame_ref. That is the
whole of the coupling, and pinning it here is the point: if the announcer starts reaching
further into the localizer, this stops compiling and someone has to think about it.
"""

import os
import sys
import time
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
for p in (str(HERE), str(HERE / "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

DOMAIN = 50
os.environ.setdefault(
    "CYCLONEDDS_URI",
    "<CycloneDDS><Domain><General><Interfaces>"
    "<NetworkInterface autodetermine='true'/></Interfaces></General></Domain></CycloneDDS>")

from cyclonedds.domain import DomainParticipant                    # noqa: E402
from spatialdds_demo import typed_transport as tt                  # noqa: E402
from spatialdds_idl.spatial.disco import Announce                  # noqa: E402

from oscp.geopose import Position                                  # noqa: E402
from oscp.spatialdds_types import (                                # noqa: E402
    CoordConvention, CoordScale, CoordScaleTargetUnit, FrameRef,
)
import spatialdds.announce as ann                                  # noqa: E402

SCALE = 0.241733


class _Image:
    def __init__(self, xyz):
        self._c = np.asarray(xyz, dtype=float)

    def projection_center(self):
        return self._c


class _Reconstruction:
    """Four camera centres in a small square, in map units."""

    def __init__(self):
        self.images = {i: _Image(c) for i, c in enumerate(
            [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)])}


class _Transform:
    def __init__(self, map_id, georeferenced=True):
        # Uniform scale with no rotation, so the ENU extent is a predictable 10 * SCALE m.
        self.map_to_enu_transform = np.diag([SCALE, SCALE, SCALE, 1.0])
        self.geodetic_ref = Position(47.4979, 19.0402, 100.0) if georeferenced else None
        self.frame_ref = FrameRef(
            uuid=map_id, fqn=f"openvps/hloc/{map_id}/colmap_world",
            has_coord_convention=True, coord_convention=CoordConvention.CV,
            has_coord_scale=True,
            coord_scale=CoordScale(CoordScaleTargetUnit.SI_METER, SCALE))


class _Localizer:
    def __init__(self, map_id, georeferenced=True):
        self.reconstruction = _Reconstruction()
        self.map_transform_info = _Transform(map_id, georeferenced)


class AnnouncerLifecycle(unittest.TestCase):
    BASE = "svc:vps:oarc/lifecycle"

    def setUp(self):
        self.dp = DomainParticipant(DOMAIN)
        self.announcer = ann.ServiceAnnouncer(self.dp, self.BASE, "oarc")

    def tearDown(self):
        self.announcer.clear()

    def _live(self):
        """
        service_ids a fresh client would see as alive.

        Only alive samples carrying data are counted. A disposed instance arrives as an
        invalid sample with ``data`` None and no key fields — DDS carries the handle, not the
        key — so a disposed announce cannot be matched back to its service_id from the sample
        alone. A cache that needs to would track handle-to-key from the alive samples first,
        which is what the bridge's AnnounceCache does. Here, absence is the assertion.
        """
        reader = tt.make_reader(self.dp, ann.TOPIC_ANNOUNCE, Announce, ann.QOS_ANNOUNCE)
        time.sleep(0.5)
        return {s.data.service_id for s in tt.take_with_state(reader)
                if s.alive and s.data is not None
                and s.data.service_id.startswith(self.BASE)}

    def test_georeferenced_map_is_announced(self):
        self.assertTrue(self.announcer.set_map("mapA", _Localizer("mapA")))
        self.assertIn(f"{self.BASE};v=mapA", self._live())

    def test_ungeoreferenced_map_is_not_announced(self):
        """Metric and localizable, but with no position on Earth to advertise."""
        ok = self.announcer.set_map("mapB", _Localizer("mapB", georeferenced=False))
        self.assertFalse(ok)
        self.assertNotIn(f"{self.BASE};v=mapB", self._live())

    def test_swapping_maps_replaces_the_announcement(self):
        self.announcer.set_map("mapA", _Localizer("mapA"))
        self.announcer.set_map("mapC", _Localizer("mapC"))
        live = self._live()
        self.assertIn(f"{self.BASE};v=mapC", live)
        self.assertNotIn(f"{self.BASE};v=mapA", live,
                         "the previous map is still advertised after a swap")

    def test_clear_withdraws_it(self):
        self.announcer.set_map("mapA", _Localizer("mapA"))
        self.announcer.clear()
        self.assertNotIn(f"{self.BASE};v=mapA", self._live())

    def _announce_of(self, sid_suffix="mapA"):
        """The live announce for one map, read through a fresh reader."""
        reader = tt.make_reader(self.dp, ann.TOPIC_ANNOUNCE, Announce, ann.QOS_ANNOUNCE)
        time.sleep(0.5)
        want = f"{self.BASE};v={sid_suffix}"
        for s in tt.take_with_state(reader):
            if s.alive and s.data is not None and s.data.service_id == want:
                return s.data
        return None

    def test_refresh_restamps_the_announce(self):
        """
        A refresh must move Announce.stamp, not just the Lifespan.

        Re-writing the stored sample keeps the sample alive on the wire, because each write
        refreshes Lifespan — but it leaves the payload's own stamp frozen at the moment the
        map was loaded. The two liveness signals then disagree, and a consumer applying the
        only backstop the spec states (do not use an announce beyond stamp + ttl_sec) drops
        a service that is announcing every 150 s and answering requests. Observed on AWS:
        discovery returned an empty deployment while the localizer returned VPS_SUCCESS for
        the same map.
        """
        self.announcer.set_map("mapA", _Localizer("mapA"))
        first = self._announce_of()
        self.assertIsNotNone(first, "nothing announced")
        first_stamp = (first.stamp.sec, first.stamp.nanosec)

        # Pretend the refresh interval elapsed rather than sleeping through it.
        self.announcer._last_refresh -= (self.announcer._ttl / 2.0) + 1.0
        time.sleep(1.1)                      # so a second-resolution stamp can differ
        self.announcer.tick()

        second = self._announce_of()
        self.assertIsNotNone(second, "the refresh removed the announce")
        second_stamp = (second.stamp.sec, second.stamp.nanosec)

        self.assertGreater(second_stamp, first_stamp,
                           "tick() refreshed the Lifespan but left the payload stamp frozen")
        # Everything else must be the sample it was.
        self.assertEqual(second.service_id, first.service_id)
        self.assertEqual(list(second.coverage[0].bbox), list(first.coverage[0].bbox))
        self.assertEqual([(h.key, h.value) for h in second.hints],
                         [(h.key, h.value) for h in first.hints])

    def test_tick_inside_the_interval_writes_nothing(self):
        """The fix must not turn the refresh into a publish on every poll."""
        self.announcer.set_map("mapA", _Localizer("mapA"))
        before = self._announce_of()
        marker = self.announcer._last_refresh
        for _ in range(5):
            self.announcer.tick()
        self.assertEqual(self.announcer._last_refresh, marker,
                         "tick() published inside the refresh interval")
        after = self._announce_of()
        self.assertEqual((after.stamp.sec, after.stamp.nanosec),
                         (before.stamp.sec, before.stamp.nanosec))

    def test_coverage_is_padded_around_the_cameras(self):
        """
        The box covers the camera hull plus the pad, in metres, not the bare hull.

        The cameras span 10 map units = 2.42 m; the pad is 15 m a side. So the box must be
        much wider than the hull, and a box that merely contained the cameras would mean the
        padding never made it through the ENU conversion.
        """
        loc = _Localizer("mapA")
        bbox = ann.coverage_bbox_wgs84(
            loc.reconstruction, loc.map_transform_info.map_to_enu_transform,
            loc.map_transform_info.geodetic_ref)
        west, south, east, north = bbox
        # ~111 km per degree of latitude; the hull is 2.42 m, the pad 15 m each side.
        height_m = (north - south) * 111_320.0
        self.assertGreater(height_m, 25.0, "padding was lost")
        self.assertLess(height_m, 45.0, "box is far larger than hull plus padding")
        self.assertLess(west, east)
        self.assertLess(south, north)


if __name__ == "__main__":
    unittest.main(verbosity=2)
