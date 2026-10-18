# Copyright 2026 Open AR Cloud
# Licensed under the MIT License.
# SPDX-License-Identifier: MIT
"""
A SpatialDDS 1.7 client still gets a pose out of the 1.8 service.

This is not a nicety. The AR client deployed against this service publishes 1.7
`VpsRequest` and will keep doing so until it migrates, so if the 1.8 cutover broke the
cross-era lane it would take the running demo down with it. The compatibility is a claim
the IDL makes — every type here is `@extensibility(APPENDABLE)`, and `FrameRef` grew from
four members to eight by appending — and a claim worth measuring rather than trusting,
because the cost of it being wrong is paid by somebody else's deployment.

Two directions, both of them real:

  1.7 writer -> 1.8 reader   the deployed client asking this service for a fix
  1.8 writer -> 1.7 reader   this service answering it

**Why separate participants.** cyclonedds-python checks Python class identity in
`write()`, so a 1.7 `VpsRequest` instance cannot be handed to a writer created with the
1.8 class *in one process* — `TypeError: ... is not of type VpsRequest`. That is an API
constraint of the binding, not a statement about the wire, and conflating the two would
read as "the eras are incompatible" when they are not. Each era gets its own participant
here, which is also the real topology: two processes, two builds, one bus.
"""

import sys
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
for p in (str(HERE), str(HERE / "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from cyclonedds.domain import DomainParticipant                     # noqa: E402

from spatialdds_demo import blob as blobmod, typed_transport as tt  # noqa: E402

# The two eras, side by side. This is the only place in the tree that imports both.
from spatialdds_idl.spatial.argeo import VpsRequest as Req17        # noqa: E402
from spatialdds_idl.spatial.argeo import VpsResponse as Resp17      # noqa: E402
from spatialdds_idl.spatial.common import FrameRef as Frame17       # noqa: E402
from spatialdds_idl.spatial.core import BlobChunk as Chunk17        # noqa: E402
from spatialdds_idl.spatial.core import BlobRef as Ref17            # noqa: E402

from spatialdds_idl18.spatial.argeo import VpsRequest as Req18      # noqa: E402
from spatialdds_idl18.spatial.argeo import VpsResponse as Resp18    # noqa: E402

from oscp.geopose import GeoPose, Position, Quaternion              # noqa: E402
from oscp.spatialdds_types import (                                 # noqa: E402
    CoordConvention, CoordScale, CoordScaleTargetUnit, CovMatrix,
    FrameRef, FramedPose, PoseSE3, QuaternionXYZW, Vec3,
)
import spatialdds.service as svc                                    # noqa: E402

DOMAIN = 49
SERVICE_ID = "svc:vps:oarc/interop;v=2026-q3"
MAP_ID = "interopmap"
SCALE = 0.2417


def _outcome():
    fr = FrameRef(
        uuid=MAP_ID, fqn=f"openvps/hloc/{MAP_ID}/colmap_world",
        has_coord_convention=True, coord_convention=CoordConvention.CV,
        has_coord_scale=True,
        coord_scale=CoordScale(CoordScaleTargetUnit.SI_METER, SCALE))
    fp = FramedPose(
        pose=PoseSE3(Vec3(1.5, -2.0, 3.25), QuaternionXYZW(0.0, 0.0, 0.0, 1.0)),
        frame_ref=fr, cov=CovMatrix())
    return svc.LocalizeOutcome(
        framed_poses=[fp],
        geoposes=[GeoPose(position=Position(47.4979, 19.0402, 100.0),
                          quaternion=Quaternion(0.0, 0.0, 0.0, 1.0))],
        confidence=0.83, map_id=MAP_ID, georeferenced=True)


class CrossEraLocalization(unittest.TestCase):
    IMAGE = b"\x89JPEG-query-" * 9000

    def setUp(self):
        # The service, on 1.8 — the build this batch produces.
        self.dp_service = DomainParticipant(DOMAIN)
        self.service = svc.VpsService(
            self.dp_service, SERVICE_ID, lambda image, req: _outcome())

        # The client, on 1.7 — the build already deployed.
        self.dp_client = DomainParticipant(DOMAIN)
        self.req_w17 = tt.make_writer(
            self.dp_client, svc.TOPIC_VPS_QUERY, Req17, svc.QOS_VPS_REQ)
        self.blob_w17 = tt.make_writer(
            self.dp_client, svc.TOPIC_BLOB_CHUNK, Chunk17, svc.QOS_BLOB)
        self.resp_r17 = tt.make_reader(
            self.dp_client, svc.TOPIC_VPS_RESULT, Resp17, svc.QOS_VPS_RESP)
        time.sleep(0.6)   # discovery across two participants

    def _send_17(self):
        """A request exactly as the 1.7 client builds it: a four-member FrameRef."""
        qid, blob_id = str(uuid.uuid4()), str(uuid.uuid4())
        ref = blobmod.blob_ref(blob_id, svc.ROLE_QUERY_IMAGE, self.IMAGE)
        self.req_w17.write(Req17(
            query_id=qid, service_id=SERVICE_ID,
            client_frame_ref=Frame17(uuid="c", fqn="client/body",
                                     has_coord_convention=False, coord_convention=0),
            has_prior_geopose=False,
            prior_geopose=_empty_geopose_17(),
            query_blobs=[Ref17(blob_id=ref["blob_id"], role=ref["role"],
                               checksum=ref["checksum"])],
            query_stream_id="", has_quality_requirements=False,
            quality_requirements=_qr_17(),
            stamp=svc.now_time(),
        ))
        for c in blobmod.chunk(blob_id, self.IMAGE, cls=Chunk17):
            self.blob_w17.write(c)
        return qid

    def _pump(self, qid, seconds=8.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.service.poll()
            for r in tt.take_samples(self.resp_r17):
                if r.query_id == qid:
                    return r
            time.sleep(0.05)
        return None

    def test_a_1_7_client_still_gets_a_pose(self):
        """The deployed client's request is answered by the migrated service."""
        qid = self._send_17()
        r = self._pump(qid)
        self.assertIsNotNone(
            r, "a 1.7 VpsRequest got no 1.8 reply — the cross-era lane is broken, which "
               "would take the deployed AR client down")
        self.assertEqual(str(r.status).rsplit(".", 1)[-1], "VPS_SUCCESS")
        self.assertTrue(r.has_node_geo)
        self.assertAlmostEqual(r.node_geo.poses[0].pose.t[0], 1.5, places=6)

    def test_the_1_7_reader_sees_the_appended_members_it_has_no_field_for(self):
        """The reply decodes for a 1.7 reader, and its four-member FrameRef is intact.

        The service now writes an eight-member `FrameRef`. A 1.7 reader has four fields for
        it, so the scale quartet is invisible there — which is exactly what APPENDABLE
        promises and the reason the deployed client keeps working. What must survive is
        everything the 1.7 reader does have a field for.
        """
        qid = self._send_17()
        r = self._pump(qid)
        self.assertIsNotNone(r, "no reply")
        fr = r.node_geo.poses[0].frame_ref
        self.assertEqual(fr.fqn, f"openvps/hloc/{MAP_ID}/colmap_world")
        self.assertEqual(str(fr.coord_convention).rsplit(".", 1)[-1], "CV")
        self.assertFalse(hasattr(fr, "meters_per_unit"),
                         "the 1.7 binding should have no field for the 1.8 scale members; "
                         "if it does, the wrong tree is on sys.path")

    def test_the_two_request_types_are_the_same_wire_type(self):
        """Same typename, same member count — which is why the lane matches at all."""
        import dataclasses
        self.assertEqual(Req17.__idl_typename__, Req18.__idl_typename__)
        self.assertEqual(Resp17.__idl_typename__, Resp18.__idl_typename__)
        self.assertEqual(len(dataclasses.fields(Req17)), len(dataclasses.fields(Req18)))
        self.assertEqual(len(dataclasses.fields(Resp17)), len(dataclasses.fields(Resp18)))


def _qr_17():
    from spatialdds_idl.spatial.argeo import QualityRequirements
    return QualityRequirements(max_rmse_m=0.0, min_confidence=0.0)


def _empty_geopose_17():
    from spatialdds_demo.json_mapping import from_json
    from spatialdds_demo.payloads import COV_NONE
    from spatialdds_idl.builtin import Time
    from spatialdds_idl.spatial.core import CovMatrix as Cov17, GeoPose as Geo17
    return Geo17(lat_deg=0.0, lon_deg=0.0, alt_m=0.0, q=[0.0, 0.0, 0.0, 1.0],
                 stamp=Time(sec=0, nanosec=0), cov=from_json(Cov17, dict(COV_NONE)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
