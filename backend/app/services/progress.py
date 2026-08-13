"""In-process event bus for Server-Sent Events (SSE) progress streaming.

Each session gets its own asyncio.Queue. The run worker publishes progress
messages; the SSE endpoint consumes them and streams to the browser.

Thread safety: the worker threads call `emit_sync` which schedules the put
onto the event loop safely via `loop.call_soon_threadsafe`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)

# One asyncio.Queue per active session_id
_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
_lock = threading.Lock()

# The running event loop (set at startup)
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Store a reference to the running loop so worker threads can schedule onto it."""
    global _loop
    _loop = loop


def subscribe(session_id: str) -> asyncio.Queue:
    """Create and register a new queue for a session SSE consumer."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _lock:
        _queues[session_id].append(q)
    return q


def unsubscribe(session_id: str, q: asyncio.Queue) -> None:
    """Remove a queue when the SSE client disconnects."""
    with _lock:
        try:
            _queues[session_id].remove(q)
        except ValueError:
            pass
        if not _queues[session_id]:
            _queues.pop(session_id, None)


def emit_sync(session_id: str, stage: str, message: str) -> None:
    """Publish a progress event from a worker thread (thread-safe)."""
    if _loop is None or _loop.is_closed():
        return
    event = {"stage": stage, "message": message}
    _loop.call_soon_threadsafe(_put_nowait_all, session_id, event)


def _put_nowait_all(session_id: str, event: dict) -> None:
    """Put event into every active queue for this session (runs on the event loop)."""
    with _lock:
        queues = list(_queues.get(session_id, []))
    for q in queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("SSE queue full for session %s — dropping event", session_id)
