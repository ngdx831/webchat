import time
from threading import Lock

from config import (
    MEDIA_TTL_SECONDS,
    SESSION_IDLE_TTL_SECONDS,
    SESSION_TTL_SECONDS,
)
from shared.session_cleanup import (
    cleanup_expired_media_files,
    cleanup_expired_sessions,
)

from .paths import PUBLIC_ROOT
from .telegram_client import tg_delete_topic


_cleanup_lock = Lock()
_last_cleanup_at = 0.0
CLEANUP_INTERVAL_SECONDS = 60


def cleanup_expired_once(conn) -> None:
    global _last_cleanup_at
    now = time.time()
    if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
        return
    with _cleanup_lock:
        now = time.time()
        if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
            return
        _last_cleanup_at = now
        results = cleanup_expired_sessions(
            conn,
            public_root=PUBLIC_ROOT,
            delete_topic=tg_delete_topic,
            max_age_seconds=SESSION_TTL_SECONDS,
            idle_seconds=SESSION_IDLE_TTL_SECONDS,
        )
        media_deleted = cleanup_expired_media_files(
            conn,
            public_root=PUBLIC_ROOT,
            media_ttl_seconds=MEDIA_TTL_SECONDS,
        )
        if results:
            deleted = len(results)
            topics = sum(1 for item in results if item.topic_deleted)
            media = sum(item.media_deleted for item in results)
            print(f"Expired sessions cleaned: sessions={deleted}, topics={topics}, media={media}")
        if media_deleted:
            print(f"Expired media cleaned: media={media_deleted}")
