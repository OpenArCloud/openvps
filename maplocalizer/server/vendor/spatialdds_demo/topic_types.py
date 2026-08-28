"""
Registered topic type name -> generated Python class.

`TopicMeta.type` names a type from the §3.3.2 registry (or a documented
deployment-specific extension). This table is what lets a consumer turn an
announced topic into a typed reader without a hardcoded topic list: read the
announce, look the type up here, subscribe.

That is the replacement for the envelope's `msg_type` string. The difference is
that `msg_type` was demo-private and resolvable only through a table each
consumer kept for itself, whereas these names are the spec's and the mapping
lives once.
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from spatialdds_idl.oarc_demo import (
    BootstrapQuery,
    BootstrapResponse,
    CatalogQuery,
    CatalogResponse,
    FusionCoverage,
)
from spatialdds_idl.spatial.anchors import AnchorDelta
from spatialdds_idl.spatial.argeo import VpsRequest, VpsResponse
from spatialdds_idl.spatial.semantics import (
    Detection2DSet, Detection3DSet, FusedTrackSet,
)
from spatialdds_idl.spatial.core import (
    BlobChunk,
    EntityBinding,
    FramedPose,
    GeoPose,
    NavSatStatus,
    PlannedTrajectory,
)
from spatialdds_idl.spatial.disco import Announce, CoverageQuery, CoverageResponse, Depart
from spatialdds_idl.spatial.events import SpatialEvent
from spatialdds_idl.spatial.vio import ImuSample
from spatialdds_idl.spatial.sensing.lidar import LidarFrame, LidarMeta
from spatialdds_idl.spatial.sensing.rad import (
    RadDetectionSet, RadTensorFrame, RadTensorMeta,
)
from spatialdds_idl.spatial.sensing.rf_beam import RfBeamFrame, RfBeamMeta
from spatialdds_idl.spatial.sensing.vision import VisionFrame, VisionMeta

# --- §3.3.2 registered types -----------------------------------------------
REGISTERED: Dict[str, Type] = {
    "geopose": GeoPose,
    "framed_pose": FramedPose,
    "navsat_status": NavSatStatus,
    "planned_trajectory": PlannedTrajectory,
    "entity_binding": EntityBinding,
    "spatial_event": SpatialEvent,
    "video_frame": VisionFrame,
    "video_meta": VisionMeta,
    "radar_tensor": RadTensorFrame,
    "radar_tensor_meta": RadTensorMeta,
    "radar_detection": RadDetectionSet,
    "detection3d": Detection3DSet,
    "detection2d": Detection2DSet,
    "fused_track": FusedTrackSet,
    "lidar_frame": LidarFrame,
    "lidar_meta": LidarMeta,
    "imu_sample": ImuSample,
    "anchor_delta": AnchorDelta,
    "vps_query": VpsRequest,
    "vps_response": VpsResponse,
    # Appendix E provisional: registered in 3.3.2, IDL under
    # idl/v1.7/provisional/. Provisional in the spec's sense — the type is
    # registered and stable enough to announce, its profile is not yet.
    "rf_beam": RfBeamFrame,
    "rf_beam_meta": RfBeamMeta,
    # Not in the 3.3.2 table — blob transfer is its own mechanism rather
    # than a topic type — but every consumer needs to resolve it, so it
    # lives with the registered names rather than as an extension.
    "blob_chunk": BlobChunk,
}

# --- deployment-specific extensions, named per §3.3.2 guidance --------------
# What is left after 1.7's findings-batch-2 revision. Each of these is a
# thing the spec still has no type for; everything else the demo used to
# carry an `oarc.*` name for now has a registered one.
EXTENSIONS: Dict[str, Type] = {
    # Fusion coverage metrics have no spec type — an aggregate diagnostic, not
    # track content (the fused tracks themselves are now the registered
    # `fused_track` -> semantics::FusedTrackSet).
    "oarc.fusion_coverage": FusionCoverage,
    # No catalogue query/response pair in 1.7; ContentAnnounce advertises
    # content but nothing asks a catalogue what is in an area.
    "oarc.catalog_query": CatalogQuery,
    "oarc.catalog_response": CatalogResponse,
    # No bootstrap exchange: a participant is assumed to already know its
    # domain id and QoS profile, which is what a fresh device does not.
    "oarc.bootstrap_query": BootstrapQuery,
    "oarc.bootstrap_response": BootstrapResponse,
}

ALL: Dict[str, Type] = {**REGISTERED, **EXTENSIONS}

# Types that are their own topic rather than being announced in TopicMeta.
WELL_KNOWN: Dict[str, Type] = {
    "spatialdds/discovery/announce/v1": Announce,
    "spatialdds/discovery/depart/v1": Depart,
    "spatialdds/discovery/query/v1": CoverageQuery,
}


class UnknownTopicType(KeyError):
    """A TopicMeta.type this build cannot map to a class."""


def resolve(type_name: str) -> Type:
    try:
        return ALL[type_name]
    except KeyError:
        raise UnknownTopicType(
            f"{type_name!r} is not a registered SpatialDDS type or a documented "
            f"extension. Known: {', '.join(sorted(ALL))}"
        ) from None


def try_resolve(type_name: str) -> Optional[Type]:
    """As :func:`resolve`, but None for an unknown type.

    A consumer should skip topics it cannot type rather than refusing to run:
    the bus may legitimately carry types this build has never heard of, and
    §3.3.2 says unknown values are extension points, not errors.
    """
    return ALL.get(type_name)
