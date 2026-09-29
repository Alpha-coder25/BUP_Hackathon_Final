"""In-process pub/sub for dashboard SSE (`/api/stream`).

Decoupled from the simulator SSE: this brokers *our* platform events to the UI
(collection progress, allocation status changes, alert/recommendation updates,
health flips). In one-container deployment an in-process broker is enough;
the Redis list indirection keeps the door open for multi-process later.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque

log = logging.getLogger(__name__)

MAX_QUEUE = 100
HISTORY = 50  # replayed to each new subscriber (they may miss early events)
_history: deque[tuple[str, str]] = deque(maxlen=HISTORY)
_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

_redis = None
REDIS_URL = os.getenv("REDIS_URL", "")


def _redis_client():
    global _redis
    if REDIS_URL and _redis is None:
        import redis  # lazy: optional dependency path

        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def publish(event: str, payload: dict) -> None:
    """Thread-safe publish; each subscriber gets events on its own event loop."""
    data = json.dumps(payload, default=str)
    _history.append((event, data))
    for loop, q in list(_subscribers):
        try:
            loop.call_soon_threadsafe(q.put_nowait, (event, data))
        except RuntimeError:
            pass  # subscriber loop gone


def history() -> list[tuple[str, str]]:
    return list(_history)


def subscribe() -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
    q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
    loop = asyncio.get_running_loop()
    _subscribers.append((loop, q))
    return loop, q


def unsubscribe(entry: tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
    if entry in _subscribers:
        _subscribers.remove(entry)
