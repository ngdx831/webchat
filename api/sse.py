from threading import Lock
from typing import Any, Dict, List


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
    with _sub_lock:
        qs = _subscribers.get(session_id, [])
        for q in qs:
            try:
                q.put_nowait(event)
            except Exception:
                pass
