"""
Moving bytes on the bus: chunking and reassembly.

The spec is explicit that heavy content is never inlined in a message —
messages carry a `BlobRef` (id + checksum) and the bytes travel as blob
chunks. That is the right design, and it is the reason `VisionFrame`,
`LidarFrame` and `RadTensorFrame` are all metadata plus a reference.

The demo uses `spatial::core::BlobChunk` directly. Finding 2 (spec batch 2)
reduced its `data` bound from `sequence<uint8, 262144>` to
`sequence<uint8, 65535>` — within cyclonedds-python's hard 65535 sequence
bound — so a Topic for that type now constructs and the reference Python
binding can move sensor data. The earlier demo-owned `oarc_demo::BlobChunk`
workaround is retired.

Chunks are keyed `(blob_id, index)`, so each is its own DDS instance: a
reassembler can tell a missing chunk from a late one, and a re-sent chunk
updates rather than duplicates.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from spatialdds_idl.spatial.core import BlobChunk

# cyclonedds-python's ceiling, not a choice. Keeping the constant here means
# the one place that has to change if the binding's limit moves is here.
MAX_CHUNK_BYTES = 65535

BLOB_TOPIC = "spatialdds/blob/chunk/v1"
BLOB_TYPE = "blob_chunk"
# Reliable and ordered: a blob with a hole in it is not a blob.
BLOB_PROFILE = "GEOM_TILE"


def chunk(blob_id: str, data: bytes,
          max_bytes: int = MAX_CHUNK_BYTES) -> Iterator[BlobChunk]:
    """Split ``data`` into ``BlobChunk`` samples, each with its own CRC32."""
    if max_bytes > MAX_CHUNK_BYTES:
        raise ValueError(
            f"{max_bytes} exceeds the binding's {MAX_CHUNK_BYTES}-byte ceiling")
    pieces = [data[i:i + max_bytes] for i in range(0, len(data), max_bytes)] or [b""]
    total = len(pieces)
    for index, piece in enumerate(pieces):
        yield BlobChunk(
            blob_id=str(blob_id), index=index, total_chunks=total,
            crc32=zlib.crc32(piece) & 0xFFFFFFFF, data=list(piece),
        )


def checksum(data: bytes) -> str:
    """The SHA-256 `BlobRef.checksum` names the whole blob."""
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


def blob_ref(blob_id: str, role: str, data: bytes) -> Dict[str, str]:
    """A complete ``spatial::core::BlobRef`` for ``data``."""
    return {"blob_id": str(blob_id), "role": str(role),
            "checksum": checksum(data)}


class CorruptChunk(ValueError):
    """A chunk whose bytes do not match the CRC32 it carries."""


@dataclass
class _Partial:
    total: int
    pieces: Dict[int, bytes] = field(default_factory=dict)


class Reassembler:
    """
    Collects chunks until a blob is whole.

    ``feed`` returns the bytes once the last missing chunk arrives, and None
    until then. A chunk whose CRC32 does not match its data raises rather
    than silently corrupting the result — the checksum is in the sample
    because someone is meant to check it.
    """

    def __init__(self, max_blobs: int = 32):
        self._partial: Dict[str, _Partial] = {}
        self._max_blobs = max_blobs

    def feed(self, sample: BlobChunk) -> Optional[bytes]:
        data = bytes(sample.data)
        if (zlib.crc32(data) & 0xFFFFFFFF) != sample.crc32:
            raise CorruptChunk(
                f"{sample.blob_id}[{sample.index}]: CRC32 mismatch")

        partial = self._partial.get(sample.blob_id)
        if partial is None:
            if len(self._partial) >= self._max_blobs:
                # Drop the least-recently-started blob rather than growing
                # without bound when a sender goes away mid-blob.
                self._partial.pop(next(iter(self._partial)))
            partial = _Partial(total=int(sample.total_chunks))
            self._partial[sample.blob_id] = partial
        partial.pieces[int(sample.index)] = data

        if len(partial.pieces) < partial.total:
            return None
        self._partial.pop(sample.blob_id, None)
        return b"".join(partial.pieces[i] for i in range(partial.total))

    @property
    def pending(self) -> List[str]:
        return sorted(self._partial)
