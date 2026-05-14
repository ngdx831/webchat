import os
from dataclasses import dataclass
from typing import Callable, List, Optional

import db as dbm
from shared.media_paths import media_path_candidates


@dataclass
class SessionCleanupResult:
    session_id: str
    topic_deleted: bool = False
    topic_error: str = ""
    media_deleted: int = 0


def resolve_public_media_path(public_root: str, rel_path: str) -> Optional[str]:
    candidates = media_path_candidates(rel_path, project_root=public_root)
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0] if candidates else None


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
    """过期会话清理：删 TG 话题（连同其全部消息）→ 删 DB 记录 → 删本地媒体。

    顺序保证：
    1) 先删话题，成功或确认已不存在后再动 DB；TG 删除失败则保留 DB，避免
       下次重启后无法重试。极端情况（权限/网络长期故障）会在下一轮 cleanup
       继续尝试。
    2) DB 删 session 时，FK ON DELETE CASCADE 会带走 events / media_assets /
       customer_marks / source_sessions（见 schema.py 与 connection.py 的
       PRAGMA foreign_keys=ON）。
    """
    results: List[SessionCleanupResult] = []
    for session in dbm.sessions_expired(conn, max_age_seconds, idle_seconds):
        session_id = session["session_id"]
        result = SessionCleanupResult(session_id=session_id)

        thread_id = session.get("thread_id")
        topic_ok = True
        if thread_id:
            topic_ok = False
            try:
                delete_topic(int(session["forum_chat_id"]), int(thread_id))
                result.topic_deleted = True
                topic_ok = True
            except Exception as exc:
                result.topic_error = str(exc)
                print(f"删除客服群话题失败: session={session_id}, error={exc}")

        if not topic_ok:
            # 话题没删干净就先保留 DB，等下一轮重试；media 也一并保留。
            results.append(result)
            continue

        result.media_deleted = delete_session_record_and_media(conn, session_id, public_root)
        results.append(result)

    return results
