import json
import os

import requests
from flask import Blueprint, Response, redirect, request, stream_with_context

import db as dbm

from ..db_helpers import get_conn
from ..paths import PUBLIC_ROOT
from ..telegram_client import tg_get_file_url
from ..validators import html_escape, json_error


bp = Blueprint("media", __name__)


@bp.get("/api/media/<file_id>")
def api_media(file_id: str):
    """媒体文件代理接口：优先走本地 local_path，其次才重定向 Telegram。"""
    file_id = (file_id or "").strip()
    if not file_id:
        return json_error(400, "BAD_FILE_ID")
    session_id = (request.args.get("session_id") or "").strip()
    access_token = (request.args.get("token") or request.args.get("session_access_token") or "").strip()
    if not session_id or not access_token:
        return json_error(401, "BAD_SESSION_TOKEN")

    def expired_placeholder(kind: str = "photo"):
        label = "图片已过期"
        if kind == "video":
            label = "视频已过期"
        elif kind == "document":
            label = "文件已过期"
        safe_label = html_escape(label)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" fill="#f3f4f6"/>
  <rect x="1" y="1" width="638" height="358" fill="none" stroke="#d1d5db"/>
  <text x="320" y="180" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" fill="#6b7280">{safe_label}</text>
</svg>"""
        return Response(svg, mimetype="image/svg+xml", status=410)

    conn = get_conn()
    owner_session_id = dbm.media_owner_session_id(conn, file_id)
    if not owner_session_id:
        return json_error(404, "MEDIA_NOT_FOUND")
    if not dbm.session_verify_access_token(conn, session_id, access_token):
        return json_error(401, "BAD_SESSION_TOKEN")
    if owner_session_id != session_id:
        return json_error(403, "MEDIA_SESSION_MISMATCH")

    try:
        asset = dbm.media_asset_get_by_file_id(conn, file_id)
        if asset:
            rel = str(asset.get("local_path") or "").lstrip("/")
            abs_path = os.path.join(PUBLIC_ROOT, rel)
            if asset.get("deleted_ts"):
                return expired_placeholder(asset.get("kind") or "photo")
            if rel and os.path.exists(abs_path):
                return redirect("/" + rel)
            dbm.media_asset_mark_deleted(conn, file_id)
            return expired_placeholder(asset.get("kind") or "photo")
    except Exception:
        pass

    # 1) 先查 events.local_path（单媒体消息会写在这里）
    try:
        row = conn.execute(
            "SELECT local_path FROM events WHERE file_id=? AND local_path<>'' ORDER BY id DESC LIMIT 1",
            (file_id,)
        ).fetchone()
        if row and row[0]:
            rel = str(row[0]).lstrip("/")
            abs_path = os.path.join(PUBLIC_ROOT, rel)
            if os.path.exists(abs_path):
                return redirect("/" + rel)
    except Exception:
        pass

    # 2) 再查 events.media_json（note 的媒体在 media_json 里）
    try:
        pat1 = f'%"file_id":"{file_id}"%'
        pat2 = f'%"file_id": "{file_id}"%'
        rows = conn.execute(
            "SELECT media_json FROM events WHERE media_json LIKE ? OR media_json LIKE ? ORDER BY id DESC LIMIT 10",
            (pat1, pat2)
        ).fetchall()

        for r in rows:
            mj = r[0] or ""
            try:
                arr = json.loads(mj) if mj else []
            except Exception:
                arr = []
            if not isinstance(arr, list):
                continue
            for m in arr:
                if not isinstance(m, dict):
                    continue
                if (m.get("file_id") or "") != file_id:
                    continue
                rel = str(m.get("local_path") or "").lstrip("/")
                if not rel:
                    continue
                abs_path = os.path.join(PUBLIC_ROOT, rel)
                if os.path.exists(abs_path):
                    return redirect("/" + rel)
    except Exception:
        pass

    # 3) 兜底：后端代理 Telegram 文件，避免 BOT_TOKEN 出现在浏览器 Location/Referer。
    try:
        file_url = tg_get_file_url(file_id)
        upstream = requests.get(file_url, stream=True, timeout=(3, 15))
        upstream.raise_for_status()

        def generate():
            try:
                yield from upstream.iter_content(8192)
            finally:
                close = getattr(upstream, "close", None)
                if close:
                    close()

        return Response(
            stream_with_context(generate()),
            mimetype=upstream.headers.get("Content-Type") or "application/octet-stream",
        )
    except Exception:
        return expired_placeholder("photo")
