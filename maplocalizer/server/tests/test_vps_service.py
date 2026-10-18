# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
"""
End-to-end over real DDS: a client publishes a chunked query image and takes the reply.

No GPU and no map — the localizer is a stub, because what is under test is the binding, not
hloc. Runs on a host with cyclonedds installed; the domain id is unusual to keep it off any
bus a developer happens to be running.
"""

import os
import sys
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
for p in (str(HERE), str(HERE / "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("CYCLONEDDS_URI",
                      "<CycloneDDS><Domain><General><Interfaces>"
                      "<NetworkInterface autodetermine='true'/></Interfaces>"
                      "</General></Domain></CycloneDDS>")

from cyclonedds.domain import DomainParticipant                    # noqa: E402
from spatialdds_demo import blob as blobmod, typed_transport as tt  # noqa: E402
from spatialdds_idl18.spatial.argeo import VpsRequest, VpsResponse, VpsStatus  # noqa: E402
from spatialdds_idl18.spatial.core import BlobChunk, BlobRef          # noqa: E402
from spatialdds_idl18.spatial.common import (                        # noqa: E402
    FrameRef as IdlFrameRef,
    ScaleStatus as IdlScaleStatus,
)

from oscp.geopose import GeoPose, Position, Quaternion              # noqa: E402
from oscp.spatialdds_types import (                                 # noqa: E402
    CoordConvention, CoordScale, CoordScaleTargetUnit, CovMatrix,
    FrameRef, FramedPose, PoseSE3, QuaternionXYZW, Vec3,
)
import spatialdds.service as svc                                    # noqa: E402

DOMAIN = 47
SERVICE_ID = "svc:vps:oarc/testville;v=2026-q3"
MAP_ID = "testmap"
SCALE = 0.2417   # metres per map unit, as measured on a real OpenVPS map


def _map_frame() -> FrameRef:
    return FrameRef(
        uuid=MAP_ID, fqn=f"openvps/hloc/{MAP_ID}/colmap_world",
        has_coord_convention=True, coord_convention=CoordConvention.CV,
        has_coord_scale=True,
        coord_scale=CoordScale(CoordScaleTargetUnit.SI_METER, SCALE),
    )


def _outcome(georeferenced=True):
    fr = _map_frame()
    fp = FramedPose(
        pose=PoseSE3(Vec3(1.5, -2.0, 3.25), QuaternionXYZW(0.0, 0.0, 0.0, 1.0)),
        frame_ref=fr, cov=CovMatrix(),
    )
    gps = [GeoPose(position=Position(47.4979, 19.0402, 100.0),
                   quaternion=Quaternion(0.0, 0.0, 0.0, 1.0))] if georeferenced else []
    return svc.LocalizeOutcome(framed_poses=[fp], geoposes=gps, confidence=0.83,
                               map_id=MAP_ID, georeferenced=georeferenced)


class VpsBinding(unittest.TestCase):
    IMAGE = b"\x89JPEG-query-" * 9000   # ~108 KB, so it spans several chunks

    def setUp(self):
        self.dp = DomainParticipant(DOMAIN)
        self.outcome = _outcome()
        self.calls = []

        def localize(image, req):
            self.calls.append((image, req))
            return self.outcome

        self.service = svc.VpsService(self.dp, SERVICE_ID, localize)
        self.req_w = tt.make_writer(self.dp, svc.TOPIC_VPS_QUERY, VpsRequest, svc.QOS_VPS_REQ)
        self.blob_w = tt.make_writer(self.dp, svc.TOPIC_BLOB_CHUNK, BlobChunk, svc.QOS_BLOB)
        self.resp_r = tt.make_reader(self.dp, svc.TOPIC_VPS_RESULT, VpsResponse, svc.QOS_VPS_RESP)
        time.sleep(0.4)   # discovery

    def _send(self, image=None, role=svc.ROLE_QUERY_IMAGE, service_id=SERVICE_ID):
        image = self.IMAGE if image is None else image
        qid = str(uuid.uuid4())
        blob_id = str(uuid.uuid4())
        ref = blobmod.blob_ref(blob_id, role, image)
        self.req_w.write(VpsRequest(
            query_id=qid, service_id=service_id,
            client_frame_ref=_client_frame(),
            has_prior_geopose=False, prior_geopose=svc._empty_geopose(),
            query_blobs=[BlobRef(blob_id=ref["blob_id"], role=ref["role"],
                                 checksum=ref["checksum"])],
            query_stream_id="", has_quality_requirements=False,
            quality_requirements=None if False else _qr(),
            stamp=svc.now_time(),
        ))
        for c in blobmod.chunk(blob_id, image, cls=BlobChunk):
            self.blob_w.write(c)
        return qid

    def _pump(self, qid, seconds=6.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.service.poll()
            for r in tt.take_samples(self.resp_r):
                if r.query_id == qid:
                    return r
            time.sleep(0.05)
        return None

    def test_chunked_image_localizes_and_replies(self):
        qid = self._send()
        r = self._pump(qid)
        self.assertIsNotNone(r, "no reply within the window")
        self.assertEqual(r.status, VpsStatus.VPS_SUCCESS)
        # The reply names the persistent identifier when the service knows no revision,
        # and base;v=<map> when it does. This service has no revision hook, so base.
        self.assertEqual(r.service_id, SERVICE_ID.split(";")[0])
        self.assertTrue(r.has_node_geo)
        self.assertAlmostEqual(r.confidence, 0.83, places=5)
        self.assertFalse(r.has_rmse_m, "no covariance available, so none should be claimed")

    def test_image_arrives_whole_and_intact(self):
        qid = self._send()
        self.assertIsNotNone(self._pump(qid))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], self.IMAGE, "reassembled image differs")

    def test_framed_pose_is_unscaled_and_labelled(self):
        qid = self._send()
        r = self._pump(qid)
        fp = r.node_geo.poses[0]
        # Raw map units on the wire; the factor is declared, not applied.
        self.assertAlmostEqual(fp.pose.t[0], 1.5, places=6)
        self.assertAlmostEqual(fp.pose.t[2], 3.25, places=6)
        self.assertEqual(str(fp.frame_ref.coord_convention).rsplit(".", 1)[-1], "CV")
        self.assertEqual(fp.frame_ref.fqn, f"openvps/hloc/{MAP_ID}/colmap_world")

    def test_scale_is_stated_on_the_wire(self):
        """The response's frame carries the map's metric scale, natively.

        This is the assertion that F1 is fixed, and it is deliberately an assertion about
        what *arrives* rather than about what the conversion builds. Before 1.8 the scale
        rode as a MetaKV that `frame_ref_to_idl` built and its only caller threw away
        (`idl_frame, _meta = ...`), so every published FramedPose named a frame that said
        nothing about its units. A test on the conversion would have passed throughout. The
        only test that could not is one that takes the sample off the bus and reads it.

        `SCALE_DERIVED`, not `SCALE_DECLARED`: this map's factor came from the norm of the
        map-to-ENU matrix, which is the spec's own example of a recovered scale. And
        `has_scale` must be true — false is not neutral, it is a claim that one map unit is
        one metre, which on a COLMAP frame is wrong by a factor of four.
        """
        qid = self._send()
        r = self._pump(qid)
        self.assertIsNotNone(r, "no reply")
        fr = r.node_geo.poses[0].frame_ref
        self.assertTrue(fr.has_scale, "has_scale false asserts metric, which this is not")
        self.assertEqual(str(fr.scale_status).rsplit(".", 1)[-1], "SCALE_DERIVED")
        self.assertAlmostEqual(fr.meters_per_unit, SCALE, places=6)
        self.assertEqual(fr.display_unit, "m")
        # The translation is still raw map units: the scale is declared, not applied.
        self.assertAlmostEqual(r.node_geo.poses[0].pose.t[0], 1.5, places=6)

    def test_unknown_scale_says_unknown_rather_than_metric(self):
        """A frame whose scale was never established must say so.

        1.8 is explicit that absence is not the unknown state: `has_scale == false` means
        the frame is metric. So a map with no scale has to set `has_scale` true and
        `SCALE_UNKNOWN`, which is the one case where the quartet carries no number.
        """
        fr = FrameRef(uuid=MAP_ID, fqn="openvps/hloc/nos/colmap_world",
                      has_coord_convention=True, coord_convention=CoordConvention.CV,
                      has_coord_scale=False)
        self.outcome = svc.LocalizeOutcome(
            framed_poses=[FramedPose(
                pose=PoseSE3(Vec3(1.0, 2.0, 3.0), QuaternionXYZW(0.0, 0.0, 0.0, 1.0)),
                frame_ref=fr, cov=CovMatrix())],
            geoposes=[], confidence=0.5, map_id=MAP_ID, georeferenced=False)
        qid = self._send()
        r = self._pump(qid)
        self.assertIsNotNone(r, "no reply")
        got = r.node_geo.poses[0].frame_ref
        self.assertTrue(got.has_scale)
        self.assertEqual(str(got.scale_status).rsplit(".", 1)[-1], "SCALE_UNKNOWN")

    def test_geopose_present_when_georeferenced(self):
        qid = self._send()
        r = self._pump(qid)
        self.assertTrue(r.node_geo.has_geopose)
        self.assertAlmostEqual(r.node_geo.geopose.lat_deg, 47.4979, places=6)

    def test_ungeoreferenced_map_yields_framed_pose_only(self):
        """A scale-only map: metric and localizable, but nothing to place on Earth."""
        self.outcome = _outcome(georeferenced=False)
        qid = self._send()
        r = self._pump(qid)
        self.assertEqual(r.status, VpsStatus.VPS_SUCCESS)
        self.assertFalse(r.node_geo.has_geopose)
        self.assertTrue(r.node_geo.poses, "the FramedPose is the whole of the answer here")

    def test_discovered_versioned_id_is_answered(self):
        """
        The announce advertises base;v=<map>, so a discovering client sends that back.

        Rejecting it was a real bug found on AWS: discovery worked, the service worked, and
        no request from a client that had actually discovered the service was ever answered
        — 45 seconds of silence with no error on either side.
        """
        qid = self._send(service_id=SERVICE_ID)
        self.assertIsNotNone(self._pump(qid),
                             "a client echoing the advertised service_id got no reply")

    def test_wrong_revision_is_refused_not_ignored(self):
        """Asking for a map this service is not serving gets an answer, not a timeout."""
        self.service._current_revision = lambda: "someothermap"
        qid = self._send(service_id=f"{SERVICE_ID.split(';')[0]};v=notloaded")
        r = self._pump(qid, seconds=5.0)
        self.assertIsNotNone(r, "a request for an unserved map must be refused, not dropped")
        self.assertEqual(r.status, VpsStatus.VPS_FAILED)

    def test_request_for_another_service_is_ignored(self):
        qid = self._send(service_id="svc:vps:someone/else;v=1")
        self.assertIsNone(self._pump(qid, seconds=2.0),
                          "answered a request addressed to a different service")
        self.assertEqual(self.calls, [])

    def test_missing_imagery_times_out_as_failed(self):
        self.service._assembly_timeout = 1.0
        qid = str(uuid.uuid4())
        blob_id = str(uuid.uuid4())
        ref = blobmod.blob_ref(blob_id, svc.ROLE_QUERY_IMAGE, self.IMAGE)
        self.req_w.write(VpsRequest(
            query_id=qid, service_id=SERVICE_ID,
            client_frame_ref=_client_frame(),
            has_prior_geopose=False, prior_geopose=svc._empty_geopose(),
            query_blobs=[BlobRef(blob_id=ref["blob_id"], role=ref["role"],
                                 checksum=ref["checksum"])],
            query_stream_id="", has_quality_requirements=False, quality_requirements=_qr(),
            stamp=svc.now_time(),
        ))   # deliberately never send the chunks
        r = self._pump(qid, seconds=6.0)
        self.assertIsNotNone(r, "a request that never completes must still be answered")
        self.assertEqual(r.status, VpsStatus.VPS_FAILED)
        self.assertFalse(r.has_node_geo)


def _client_frame() -> IdlFrameRef:
    """A client's body frame: metric, and saying so.

    Under 1.8 the scale quartet is not optional padding — leaving `has_scale` false would
    be a claim that the frame is metric rather than a statement that nothing was said. For
    a client body frame metric happens to be true, so this is the SCALE_DECLARED case, and
    it is the one the service's own map frame is not (see test_scale_is_stated_on_the_wire).
    """
    return IdlFrameRef(
        uuid="c", fqn="client/body", has_coord_convention=False, coord_convention=0,
        has_scale=True, scale_status=IdlScaleStatus.SCALE_DECLARED,
        meters_per_unit=1.0, display_unit="m")


def _qr():
    from spatialdds_idl18.spatial.argeo import QualityRequirements
    return QualityRequirements(max_rmse_m=0.0, min_confidence=0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
