import json
from typing import Any, Dict


def event_row_to_payload(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a DB event row into the frontend message payload."""
    kind = ev.get("kind") or "text"
    payload: Dict[str, Any] = {
        "id": ev.get("id"),
        "session_id": ev.get("session_id") or "",
        "role": ev.get("role"),
        "kind": kind,
        "from_name": ev.get("from_name") or "",
        "created_at": int(ev.get("created_ts") or 0),
        "text": ev.get("text") or "",
        "caption": ev.get("caption") or "",
        "file_id": ev.get("file_id") or "",
        "file_name": ev.get("file_name") or "",
        "local_path": ev.get("local_path") or "",
        "media_json": ev.get("media_json") or "",
    }

    if kind == "note":
        title = "客服笔记"
        body = ""
        raw_text = ev.get("text") or ""
        try:
            obj = json.loads(raw_text) if raw_text else {}
            if isinstance(obj, dict):
                title = (obj.get("title") or title)[:60]
                body = obj.get("body") or ""
            else:
                body = raw_text
        except Exception:
            body = raw_text

        media = []
        raw_media = ev.get("media_json") or ""
        try:
            arr = json.loads(raw_media) if raw_media else []
            if isinstance(arr, list):
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    media.append({
                        "type": item.get("type") or "photo",
                        "file_id": item.get("file_id") or "",
                        "local_path": item.get("local_path") or "",
                    })
        except Exception:
            pass

        payload.update({
            "title": title,
            "body": body,
            "media": media,
        })

    return payload
