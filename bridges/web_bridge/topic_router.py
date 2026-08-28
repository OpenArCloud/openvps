"""Topic router: pattern matching, rate limiting, topic stats.

Pure-Python — no FastAPI, no DDS, no async. Drives the web bridge's
per-client subscription logic. Tested in isolation with `test_router.py`.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Subscription:
    """One client's standing subscription on the bridge.

    ``msg_types`` of ``None`` accepts any msg_type. ``max_rate_hz`` of
    ``None`` (or non-positive) disables throttling. ``last_sent_ns`` is
    bookkeeping for the rate limiter — the router updates it after a
    successful match.
    """

    id: str
    pattern: str                          # glob on logical_topic
    msg_types: Optional[Set[str]] = None
    max_rate_hz: Optional[float] = None
    last_sent_ns: int = 0


@dataclass
class TopicStats:
    logical_topic: str
    msg_type: str
    last_seen_ns: int = 0
    message_count: int = 0
    first_seen_ns: int = 0

    @property
    def rate_hz(self) -> float:
        elapsed = (self.last_seen_ns - self.first_seen_ns) / 1e9
        if elapsed <= 0:
            return 0.0
        # We have N messages spanning (N-1) intervals of length ``elapsed/(N-1)``;
        # using N/elapsed is close enough for a stat displayed to humans.
        return self.message_count / elapsed


class TopicRouter:
    """Thread-safety: this object is mutated only from the asyncio thread
    in the server (the DDS poll thread enqueues, asyncio dispatches). No
    locking required as long as that invariant holds."""

    def __init__(self) -> None:
        self._stats: Dict[str, TopicStats] = {}

    # ── topic stats (passive bookkeeping) ────────────────────────────────

    def update_stats(self, logical_topic: str, msg_type: str,
                     timestamp_ns: int) -> None:
        if not logical_topic:
            return
        s = self._stats.get(logical_topic)
        if s is None:
            self._stats[logical_topic] = TopicStats(
                logical_topic=logical_topic,
                msg_type=msg_type,
                first_seen_ns=timestamp_ns,
                last_seen_ns=timestamp_ns,
                message_count=1,
            )
            return
        # If the msg_type changes on the same logical_topic that's interesting
        # but not a hard error — just keep the latest.
        s.msg_type = msg_type or s.msg_type
        s.last_seen_ns = timestamp_ns
        s.message_count += 1

    def get_topics(self, stale_threshold_s: float = 30.0,
                    now_ns: Optional[int] = None) -> List[TopicStats]:
        """Return topics seen within the staleness window (default 30s)."""
        if now_ns is None:
            now_ns = time.time_ns()
        cutoff = now_ns - int(stale_threshold_s * 1e9)
        return [s for s in self._stats.values() if s.last_seen_ns >= cutoff]

    # ── per-message routing ──────────────────────────────────────────────

    def match(self, logical_topic: str, msg_type: str,
              sub: Subscription, now_ns: int) -> bool:
        """Return True if this message should be delivered to this subscription.

        Side-effect-free; the caller is responsible for updating
        ``sub.last_sent_ns`` after actually dispatching.
        """
        if not fnmatch.fnmatchcase(logical_topic, sub.pattern):
            return False
        if sub.msg_types and msg_type not in sub.msg_types:
            return False
        if sub.max_rate_hz and sub.max_rate_hz > 0 and sub.last_sent_ns > 0:
            # last_sent_ns == 0 means "no message has matched yet" — let it
            # through so a freshly created subscription always sees its first
            # data point even if the rate is low.
            min_interval_ns = int(1e9 / sub.max_rate_hz)
            if (now_ns - sub.last_sent_ns) < min_interval_ns:
                return False
        return True
