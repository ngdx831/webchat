import os
from dataclasses import dataclass
from typing import Callable, List, Optional

import db as dbm


@dataclass
class SessionCleanupResult:
    session_id: str
    topic_deleted: bool = False
    topic_error: str = ""
    media_deleted: int = 0


def resolve_public_media_path(public_root: str, rel_path: str) -> Optional[str]:
    rel = (rel_path or "").strip().lstrip("/\\")
    if not rel:
        return None

    root = os.path.abspath(public_root)
    candidate = os.path.abspath(os.path.join(root, rel))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return None
    except Exception:
        return None
    return candidate


def delete_media_files(public_root: str, media_paths: List[str]) -> int:
    deleted = 0
    seen = set()
    for rel_path in media_paths:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        abs_path = resolve_public_media_path(public_root, rel_path)
        if not abs_path or not os.path.isfile(abs_path):
            continue
        try:
            os.remove(abs_path)
            deleted += 1
        except Exception as exc:
            print(f"删除文件失败: {abs_path}, {exc}")
    return deleted


def cleanup_expired_media_files(conn, public_root: str, media_ttl_seconds: int) -> int:
    """Delete expired local media files while keeping chat events intact."""
    deleted = 0
    for asset in dbm.media_assets_expired(conn, media_ttl_seconds):
        file_id = asset.get("file_id") or ""
        rel_path = asset.get("local_path") or ""
        removed = delete_media_files(public_root, [rel_path])
        if removed:
            deleted += removed
        if file_id:
            dbm.media_asset_mark_deleted(conn, file_id)
    return deleted


def delete_session_record_and_media(conn, session_id: str, public_root: str) -> int:
    media_paths = dbm.session_get_media_paths(conn, session_id)
    dbm.session_delete(conn, session_id)
    try:
        return delete_media_files(public_root, media_paths)
    except Exception as exc:
        print(f"删除会话媒体文件失败: session={session_id}, error={exc}")
        return 0


def cleanup_expired_sessions(
    conn,
    public_root: str,
    delete_topic: Callable[[int, int], None],
    max_age_seconds: int,
    idle_seconds: int,
) -> List[SessionCleanupResult]:
    results: List[SessionCleanupResult] = []
    for session in dbm.sessions_expired(conn, max_age_seconds, idle_seconds):
        session_id = session["session_id"]
        result = SessionCleanupResult(session_id=session_id)

        thread_id = session.get("thread_id")
        if thread_id:
            try:
                delete_topic(int(session["forum_chat_id"]), int(thread_id))
                result.topic_deleted = True
            except Exception as exc:
                result.topic_error = str(exc)
                print(f"删除客服群话题失败: session={session_id}, error={exc}")

        result.media_deleted = delete_session_record_and_media(conn, session_id, public_root)
        results.append(result)

    return results
