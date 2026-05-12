import logging
from queue import Full
from threading import Lock
from typing import Any, Dict, List


logger = logging.getLogger(__name__)

_subscribers: Dict[str, List] = {}
_sub_lock = Lock()


def subscribe(session_id: str, queue) -> None:
    with _sub_lock:
        _subscribers.setdefault(session_id, []).append(queue)


def unsubscribe(session_id: str, queue) -> None:
    with _sub_lock:
        if session_id in _subscribers:
            try:
                _subscribers[session_id].remove(queue)
            except ValueError:
                pass
            if not _subscribers[session_id]:
                _subscribers.pop(session_id, None)


def broadcast_event(session_id: str, event: Dict[str, Any]) -> None:
    """向所有订阅者推送事件;塞不进去的订阅者视为掉线,主动踢出。"""
    dead: List = []
    with _sub_lock:
        qs = list(_subscribers.get(session_id, []))
    for q in qs:
        try:
            q.put_nowait(event)
        except Full:
            logger.warning("sse subscriber queue full; evicting session=%s", session_id)
            dead.append(q)
        except Exception:
            logger.exception("sse broadcast error session=%s", session_id)
            dead.append(q)
    if dead:
        with _sub_lock:
            existing = _subscribers.get(session_id, [])
            for q in dead:
                try:
                    existing.remove(q)
                except ValueError:
                    pass
            if not existing:
                _subscribers.pop(session_id, None)
