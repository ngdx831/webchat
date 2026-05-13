import asyncio
from typing import Any, Callable

import db as dbm
from config import DB_PATH
from .db_lifecycle import track_connection


async def to_thread(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(func, *args, **kwargs)


async def open_context():
    def _open():
        conn = track_connection(dbm.get_conn(DB_PATH))
        dbm.init_db(conn)
        return conn

    return await asyncio.to_thread(_open)


async def call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(func, *args, **kwargs)
