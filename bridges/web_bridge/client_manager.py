"""Client session manager: tracks WebSocket connections and their subscriptions.

Framework-agnostic enough that the WebSocket *send* is delegated to a callable
the caller supplies (`async def send_json(payload: dict) -> None`). The actual
FastAPI/Starlette `WebSocket.send_json` is wrapped at the call site in
`server.py`. This keeps the unit tests free of a FastAPI dependency.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from topic_router import Subscription, TopicRouter


SendJson = Callable[[dict], Awaitable[None]]


@dataclass
class ClientSession:
    client_id: str
    send_json: SendJson
    subscriptions: Dict[str, Subscription] = field(default_factory=dict)
    connected_at_ns: int = 0
    messages_sent: int = 0
    messages_received: int = 0


class ClientManager:
    def __init__(self, router: TopicRouter):
        self.router = router
        self._clients: Dict[str, ClientSession] = {}

    # ── lifecycle ────────────────────────────────────────────────────────

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def add_client(self, send_json: SendJson,
                   client_id: Optional[str] = None) -> ClientSession:
        cid = client_id or str(uuid.uuid4())[:8]
        session = ClientSession(
            client_id=cid,
            send_json=send_json,
            connected_at_ns=time.time_ns(),
        )
        self._clients[cid] = session
        return session

    def remove_client(self, client_id: str) -> None:
        self._clients.pop(client_id, None)

    # ── inbound message handlers (return a response dict; caller sends) ──

    def handle_subscribe(self, session: ClientSession, msg: dict) -> dict:
        sub_id = str(msg.get("id") or uuid.uuid4().hex[:8])
        pattern = msg.get("pattern") or ""
        if not pattern:
            return {"type": "error", "ref_id": sub_id, "message": "Missing pattern"}
        msg_types = msg.get("msg_types")
        max_rate = msg.get("max_rate_hz")
        try:
            max_rate_f = float(max_rate) if max_rate is not None else None
        except (TypeError, ValueError):
            return {"type": "error", "ref_id": sub_id,
                    "message": "max_rate_hz must be a number"}
        sub = Subscription(
            id=sub_id,
            pattern=pattern,
            msg_types=set(msg_types) if msg_types else None,
            max_rate_hz=max_rate_f,
        )
        session.subscriptions[sub_id] = sub
        return {"type": "subscribed", "id": sub_id, "pattern": pattern, "status": "ok"}

    def handle_unsubscribe(self, session: ClientSession, msg: dict) -> dict:
        sub_id = str(msg.get("id") or "")
        if sub_id and sub_id in session.subscriptions:
            del session.subscriptions[sub_id]
            return {"type": "unsubscribed", "id": sub_id, "status": "ok"}
        return {"type": "error", "ref_id": sub_id, "message": "Unknown subscription"}

    # ── outbound dispatch (DDS → WebSocket clients) ──────────────────────

    def matching_subs(self, logical_topic: str, msg_type: str,
                       now_ns: int) -> List[tuple]:
        """Return ``[(session, sub)...]`` for everyone subscribed to this msg.

        Pulled out so tests can verify routing without invoking ``send_json``.
        """
        out: List[tuple] = []
        for session in self._clients.values():
            for sub in session.subscriptions.values():
                if self.router.match(logical_topic, msg_type, sub, now_ns):
                    out.append((session, sub))
        return out

    async def dispatch(self, logical_topic: str, msg_type: str,
                        payload: Any, timestamp_ns: int) -> int:
        """Route a DDS envelope to all matching clients. Returns how many
        WebSocket sends were attempted (sent — failures dropped silently)."""
        now_ns = time.time_ns()
        self.router.update_stats(logical_topic, msg_type, timestamp_ns)

        # Group by session: each session gets ONE data message even if
        # multiple of its subscriptions matched.
        per_session: Dict[str, List[Subscription]] = {}
        for session, sub in self.matching_subs(logical_topic, msg_type, now_ns):
            per_session.setdefault(session.client_id, []).append(sub)
        if not per_session:
            return 0

        sent = 0
        dead: List[str] = []
        for cid, subs in per_session.items():
            session = self._clients.get(cid)
            if session is None:
                continue
            data_msg = {
                "type": "data",
                "sub_id": subs[0].id,            # the first matching subscription
                "msg_type": msg_type,
                "logical_topic": logical_topic,
                "timestamp_ns": int(timestamp_ns),
                "payload": payload,
            }
            try:
                await session.send_json(data_msg)
                session.messages_sent += 1
                for sub in subs:
                    sub.last_sent_ns = now_ns
                sent += 1
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.remove_client(cid)
        return sent

    # ── stats / introspection ────────────────────────────────────────────

    def session_summaries(self) -> List[dict]:
        return [
            {
                "client_id": s.client_id,
                "subscriptions": len(s.subscriptions),
                "messages_sent": s.messages_sent,
                "messages_received": s.messages_received,
                "connected_for_s": (time.time_ns() - s.connected_at_ns) / 1e9,
            }
            for s in self._clients.values()
        ]
