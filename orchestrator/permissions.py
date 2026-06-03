"""Manages pending tool-use permission requests as asyncio Futures keyed by UUID."""
import asyncio
import logging
import uuid
from typing import Literal

log = logging.getLogger(__name__)

PendingPermission = asyncio.Future  # resolves to "allow" | "deny"

_pending: dict[str, PendingPermission] = {}


def create(request_id: str | None = None) -> tuple[str, asyncio.Future]:
    """Returns (request_id, future). Caller awaits the future for the decision."""
    rid = request_id or str(uuid.uuid4())
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _pending[rid] = fut
    log.info("PERM CREATE  rid=%s  pending_count=%d", rid, len(_pending))
    return rid, fut


def resolve(request_id: str, decision: Literal["allow", "deny"]) -> bool:
    """Called when user presses allow/deny button. Returns True if found."""
    log.info("PERM RESOLVE rid=%s  decision=%s  known_rids=%s",
             request_id, decision, list(_pending.keys()))
    fut = _pending.pop(request_id, None)
    if fut and not fut.done():
        fut.set_result(decision)
        log.info("PERM RESOLVE OK  rid=%s", request_id)
        return True
    log.warning("PERM RESOLVE MISS  rid=%s  fut=%s", request_id, fut)
    return False


def discard(request_id: str) -> None:
    """Remove a request from _pending without resolving it (used on timeout/cancel)."""
    _pending.pop(request_id, None)


def cancel_all_for(prefix: str) -> None:
    """Cancel all pending requests whose id starts with prefix (used on topic teardown)."""
    to_cancel = [rid for rid in list(_pending) if rid.startswith(prefix)]
    for rid in to_cancel:
        fut = _pending.pop(rid)
        if not fut.done():
            fut.cancel()
