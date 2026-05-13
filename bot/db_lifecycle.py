import contextlib
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, List, Optional

from aiogram import BaseMiddleware, Dispatcher


_connections: ContextVar[Optional[List[Any]]] = ContextVar("bot_db_connections", default=None)


def track_connection(conn):
    bucket = _connections.get()
    if bucket is not None:
        bucket.append(conn)
    return conn


class DbConnectionCleanupMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Any,
        data: dict,
    ) -> Any:
        token = _connections.set([])
        try:
            return await handler(event, data)
        finally:
            bucket = _connections.get() or []
            _connections.reset(token)
            for conn in reversed(bucket):
                with contextlib.suppress(Exception):
                    conn.close()


def register_db_cleanup_middleware(dispatcher: Dispatcher) -> None:
    dispatcher.update.middleware(DbConnectionCleanupMiddleware())
