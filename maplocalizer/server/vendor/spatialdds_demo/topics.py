from typing import List, Optional, Tuple

TOPIC_DISCOVERY_ANNOUNCE_V1 = "spatialdds/discovery/announce/v1"
TOPIC_DISCOVERY_DEPART_V1 = "spatialdds/discovery/depart/v1"
TOPIC_DISCOVERY_QUERY_V1 = "spatialdds/discovery/query/v1"
TOPIC_VPS_QUERY_V1 = "spatialdds/vps/query/v1"
TOPIC_VPS_RESULT_V1 = "spatialdds/vps/result/v1"
TOPIC_CATALOG_QUERY_V1 = "spatialdds/catalog/query/v1"
TOPIC_BOOTSTRAP_QUERY_V1 = "spatialdds/bootstrap/query/v1"
TOPIC_BOOTSTRAP_RESPONSE_V1 = "spatialdds/bootstrap/response/v1"
TOPIC_DDS_ENVELOPE_V1 = "spatialdds/envelope/v1"


def TOPIC_ANCHORS_DELTA(zone: str) -> str:
    return f"spatialdds/anchors/{zone}/delta/v1"


def TOPIC_CATALOG_REPLIES(client_id: str) -> str:
    return f"spatialdds/catalog/replies/{client_id}/v1"


def TOPIC_DISCOVERY_RESPONSE(query_id: str) -> str:
    return f"spatialdds/discovery/response/{query_id}"


# --- 1.7 registries (spec 3.3.2 typed topics, 3.3.3 QoS profiles) ---------
# Every Announce.topics[] entry and manifest topic reference MUST carry a
# type + version + qos_profile drawn from these tables, or a documented
# deployment-specific extension following the `myorg.depth_frame` /
# `DEPTH_LIVE` naming pattern.
REGISTERED_TOPIC_TYPES = {
    "geometry_tile",
    "video_frame",
    "radar_detection",
    "radar_tensor",
    "rf_beam",
    "radio_scan",
    "seg_mask",
    "desc_array",
    "map_meta",
    "map_alignment",
    "map_event",
    "spatial_zone",
    "spatial_event",
    "zone_state",
    # Informative example registrations (Appendix E): types defined only in the
    # example IDL, outside the normative conformance surface (spec batch-3
    # follow-up Q.3). The demo does not use them; kept here as valid names.
    "agent_status",
    "task_offer",
    "task_assignment",
    "navsat_status",
    "planned_trajectory",
    "entity_binding",
    "geopose",
    "vps_query",
    # Added in 1.7's findings-batch-2 revision, closing the gap between the
    # registry and the IDL. Every one of these is a stable type the demo had
    # to invent an `oarc.*` name for because discovery could not describe it.
    "framed_pose",
    "detection3d",
    "detection2d",
    "lidar_frame",
    "lidar_meta",
    "radar_tensor_meta",
    "video_meta",
    "rf_beam_meta",
    "imu_sample",
    "anchor_delta",
    "rad_sensor_meta",
    "radio_sensor_meta",
    # Added in 1.7 batch 3: the VPS request/response pair now has spec types
    # (argeo) and cross-source fused tracks have one (semantics). `tile_meta`
    # was dropped in the batch-3 follow-up — `geometry_tile` is the canonical
    # registry name for TileMeta.
    "vps_response",
    "fused_track",
    # Blob transfer is its own mechanism rather than a topic type, but a
    # lane carrying chunks still has to name something.
    "blob_chunk",
}

REGISTERED_QOS_PROFILES = {
    "GEOM_TILE",
    "VIDEO_LIVE",
    "VIDEO_ARCHIVE",
    "RADAR_RT",
    "RF_BEAM_RT",
    "RADIO_SCAN_RT",
    "SEG_MASK_RT",
    "DESC_BATCH",
    "MAP_META",
    "ZONE_META",
    "EVENT_RT",
    "POSE_RT",
    "VPS_REQ",
    "VPS_RESP",
    # Added alongside the registry rows they serve, so every registered type
    # now names a registered profile. The demo used to invent ANCHOR_DELTA
    # and borrow MAP_META for sensor metadata.
    "DET_RT",
    "LIDAR_RT",
    "IMU_RT",
    "SENSOR_META",
    "ANCHOR_DELTA",
}

def _deployment_topic_types() -> set:
    """
    Deployment-specific type names this demo documents and uses.

    Sourced from spatialdds_demo.topic_types.EXTENSIONS so the validator and
    the type registry cannot disagree — they did once, and the publish-path
    validator caught it, which is the point of having it there.

    Imported lazily: topic_types imports the generated bindings, and this
    module is imported by code that has no need of them.
    """
    names = {"anchor_delta"}   # anchors have no registered type or profile
    try:
        from spatialdds_demo.topic_types import EXTENSIONS
        names |= set(EXTENSIONS)
    except Exception:
        pass
    return names


# Every profile the demo uses is registered now; ANCHOR_DELTA was the last
# invented one and 1.7 adopted it.
DEPLOYMENT_QOS_PROFILES: set = set()


TOPIC_SOURCE_SPEC = "spec"
TOPIC_SOURCE_ANNOUNCE = "announce"
TOPIC_SOURCE_MANIFEST = "manifest"
TOPIC_SOURCE_REQUEST = "request"
TOPIC_SOURCE_ANNOUNCE_PREVIEW = "announce_preview"
TOPIC_SOURCE_FALLBACK = "fallback"
TOPIC_SOURCE_RUNTIME_CUSTOM = "runtime_custom"


def validate_topics_are_canonical(
    topics: List[str], service_kind: Optional[str] = None
) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    for topic in topics:
        if not topic.startswith("spatialdds/"):
            errors.append(f"Topic missing spatialdds/ prefix: {topic}")
        if "//" in topic:
            errors.append(f"Topic contains double slash: {topic}")
        if not topic.endswith("/v1"):
            errors.append(f"Topic missing /v1 suffix: {topic}")

    if service_kind == "VPS":
        if TOPIC_VPS_QUERY_V1 not in topics:
            errors.append("Missing VPS query topic for VPS service")
        if TOPIC_VPS_RESULT_V1 not in topics:
            errors.append("Missing VPS result topic for VPS service")

    return len(errors) == 0, errors


def validate_topic_meta(entries: List[dict]) -> Tuple[bool, List[str]]:
    """
    Validate TopicMeta rows against the 1.7 registries (spec 3.3.2/3.3.3).

    ``type``, ``version`` and ``qos_profile`` are all mandatory in 1.7. A
    value passes if it is registered, or if it is a documented
    deployment-specific extension.
    """
    errors: List[str] = []

    for entry in entries:
        name = entry.get("name") or "<unnamed>"

        topic_type = entry.get("type")
        if not topic_type:
            errors.append(f"{name}: TopicMeta.type is required")
        elif (
            topic_type not in REGISTERED_TOPIC_TYPES
            and topic_type not in _deployment_topic_types()
        ):
            errors.append(
                f"{name}: unregistered topic type '{topic_type}' "
                "(not in the 3.3.2 registry or the documented extensions)"
            )

        if not entry.get("version"):
            errors.append(f"{name}: TopicMeta.version is required")

        qos_profile = entry.get("qos_profile")
        if not qos_profile:
            errors.append(f"{name}: TopicMeta.qos_profile is required")
        elif (
            qos_profile not in REGISTERED_QOS_PROFILES
            and qos_profile not in DEPLOYMENT_QOS_PROFILES
        ):
            errors.append(
                f"{name}: unregistered QoS profile '{qos_profile}' "
                "(not in the 3.3.3 registry or the documented extensions)"
            )

    return len(errors) == 0, errors
