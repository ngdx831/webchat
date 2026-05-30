import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

import db as dbm
from config import DB_PATH, MEDIA_TTL_SECONDS

from ..auth import widget_owner_enabled
from ..customer_bots import _bot_token, binding_for_bot, is_main_bot
from ..media import save_media_from_token, save_webchat_media
from ..pending import handle_pending_action_message
from ..relay import (
    ensure_support_thread,
    send_event_to_customer,
    send_support_media,
    send_support_text,
)
from ..runtime import dp


logger = logging.getLogger(__name__)


async def handle_customer_private_message(msg: Message, active_bot: Bot, binding: Dict[str, Any]) -> None:
    if msg.from_user and msg.from_user.is_bot:
        return
    if msg.chat.type not in {"private"}:
        return

    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        return await _handle_customer_private_message_with_conn(conn, msg, active_bot, binding)


async def _handle_customer_private_message_with_conn(conn, msg: Message, active_bot: Bot, binding: Dict[str, Any]) -> None:
    key = binding["key"]
    widget = dbm.widget_get(conn, key)
    if not widget_owner_enabled(conn, widget):
        await msg.answer("客服入口暂不可用。")
        return

    visitor_id = str(msg.from_user.id if msg.from_user else msg.chat.id)
    source_code = dbm.source_click_latest(conn, key, "telegram", visitor_id)
    session = dbm.session_find_customer(conn, int(binding["id"]), int(msg.chat.id))
    session_created = False
    if not session:
        session_id = uuid.uuid4().hex
        dbm.session_create_if_missing(
            conn,
            session_id,
            key,
            int(widget["forum_chat_id"]),
            channel="telegram",
            source_code=source_code,
            visitor_id=visitor_id,
            customer_chat_id=int(msg.chat.id),
            bot_binding_id=int(binding["id"]),
        )
        if source_code:
            dbm.source_session_add(conn, key, source_code, "telegram", visitor_id, session_id)
        dbm.ensure_system_event(conn, session_id, "Telegram 客户机器人会话已创建。", marker="tg_customer")
        session = dbm.session_get(conn, session_id)
        session_created = True
    if not session:
        await msg.answer("创建客服会话失败，请稍后再试。")
        return

    enabled = int((widget or {}).get("enabled") or 0)
    offline_msg = (widget or {}).get("offline_msg") or ""
    display_name = (widget or {}).get("display_name") or key
    forum_chat_id = int(widget["forum_chat_id"])
    from_label = msg.from_user.full_name if msg.from_user else "Telegram 客户"

    if msg.text:
        text = msg.text.strip()
        if text.startswith("/"):
            await msg.answer("请直接发送咨询内容，或使用 /start 查看常见问题。")
            return
        dbm.event_add(conn, session["session_id"], role="user", kind="text", text=text)
        dbm.session_touch(conn, session["session_id"])
        # 离线且首次会话：先回复下班留言，再转发到客服群
        if enabled == 0 and session_created and offline_msg:
            await msg.answer(offline_msg)
        thread_id = await ensure_support_thread(conn, session, widget)
        await send_support_text(forum_chat_id, thread_id, text, label=f"{from_label}（TG）")
        if enabled != 0 and session_created:
            await msg.answer("已转人工客服，请稍等。")
        return

    file_id = ""
    file_unique_id = ""
    kind = "document"
    caption = (msg.caption or "").strip()
    if msg.photo:
        p = msg.photo[-1]
        file_id = p.file_id
        file_unique_id = p.file_unique_id
        kind = "photo"
    elif msg.video:
        v = msg.video
        file_id = v.file_id
        file_unique_id = v.file_unique_id
        kind = "video"
    elif msg.document:
        d = msg.document
        file_id = d.file_id
        file_unique_id = d.file_unique_id
        kind = "document"

    if not file_id:
        await msg.answer("暂不支持这种消息类型，请发送文字、图片、视频或文件。")
        return

    try:
        local_path = await save_media_from_token(_bot_token(active_bot), file_id, file_unique_id)
        dbm.event_add(
            conn,
            session["session_id"],
            role="user",
            kind=kind,
            caption=caption,
            file_id=file_id,
            local_path=local_path,
        )
        dbm.session_touch(conn, session["session_id"])
        dbm.media_asset_upsert(conn, session["session_id"], file_id, kind, local_path, ttl_seconds=MEDIA_TTL_SECONDS)
        if enabled == 0 and session_created and offline_msg:
            await msg.answer(offline_msg)
        thread_id = await ensure_support_thread(conn, session, widget)
        await send_support_media(forum_chat_id, thread_id, kind, local_path, caption=caption)
        if enabled != 0 and session_created:
            await msg.answer("已转人工客服，请稍等。")
    except Exception as exc:
        await msg.answer(f"媒体转发失败，请改用文字描述。错误：{exc}")


# =============== 客服媒体处理：笔记缓冲（media_group合并） ===============

_WEBCHAT_NOTE_BUF: Dict[str, Dict] = {}


async def _finalize_webchat_note(group_id: str):
    """合并media_group为单个笔记事件，并推送网页"""
    buf = _WEBCHAT_NOTE_BUF.get(group_id)
    if not buf:
        return

    media_list = buf["media_list"]
    caption = buf["caption"]
    session_id = buf["session_id"]
    from_name = buf["from_name"]

    _WEBCHAT_NOTE_BUF.pop(group_id, None)

    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        return await _finalize_webchat_note_with_conn(conn, media_list, caption, session_id, from_name)


async def _finalize_webchat_note_with_conn(conn, media_list, caption, session_id, from_name):
    session = dbm.session_get(conn, session_id)
    if not session:
        return

    downloaded_media = []
    for m in media_list:
        try:
            rel_path = await save_webchat_media(m["file_id"], m["file_unique_id"])
            dbm.media_asset_upsert(
                conn,
                session_id,
                m["file_id"],
                m["type"],
                rel_path,
                ttl_seconds=MEDIA_TTL_SECONDS,
            )
            downloaded_media.append({
                "type": m["type"],
                "file_id": m["file_id"],
                "local_path": rel_path,
            })
        except Exception:
            logger.warning("下载媒体失败: file_id=%s", m["file_id"], exc_info=True)

    if not downloaded_media:
        return

    media_json = json.dumps(downloaded_media, ensure_ascii=False)

    title = "客服笔记"
    body = caption or ""
    if caption:
        lines = caption.split("\n", 1)
        if len(lines) > 1:
            title = lines[0][:30]
            body = lines[1]
        else:
            title = caption[:30]

    event_id = dbm.event_add(
        conn,
        session_id,
        role="agent",
        kind="note",
        text=json.dumps({"title": title, "body": body}, ensure_ascii=False),
        caption="",
        file_id="",
        from_name=from_name,
        local_path="",
        media_json=media_json
    )

    event_data = {
        "id": event_id,
        "session_id": session_id,
        "role": "agent",
        "kind": "note",
        "title": title,
        "body": body,
        "media": downloaded_media,
        "from_name": from_name,
    }
    await send_event_to_customer(conn, session, event_data)


def _schedule_webchat_note(group_id: str, delay: float = 1.5):
    buf = _WEBCHAT_NOTE_BUF.get(group_id)
    if not buf:
        return
    t: Optional[asyncio.Task] = buf.get("task")
    if t and not t.done():
        t.cancel()
    buf["task"] = asyncio.create_task(_delayed_webchat_note(group_id, delay))


async def _delayed_webchat_note(group_id: str, delay: float):
    await asyncio.sleep(delay)
    await _finalize_webchat_note(group_id)


# ================== 关键：处理话题消息 -> 推送网页 ==================

@dp.message()
async def handle_forum_topic_reply(msg: Message, bot: Bot):
    """
    只要客服在 TG 话题里说话/发媒体，这里就会写入 events 并调用 /internal/notify 推送到网页 SSE。
    """
    binding = binding_for_bot(bot)
    if binding:
        await handle_customer_private_message(msg, bot, binding)
        return
    if not is_main_bot(bot):
        return
    if await handle_pending_action_message(msg, bot):
        return
    if not msg.message_thread_id:
        return
    if msg.from_user and msg.from_user.is_bot:
        return
    if msg.chat.type != "supergroup":
        return

    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        return await _handle_forum_topic_reply_with_conn(conn, msg)


async def _handle_forum_topic_reply_with_conn(conn, msg: Message):
    session = dbm.session_get_by_thread(conn, int(msg.chat.id), int(msg.message_thread_id))
    if not session:
        return
    session_id = session["session_id"]

    from_name = None
    if msg.from_user:
        from_name = (msg.from_user.full_name or msg.from_user.username or "").strip() or None

    # media_group：合并为 note
    if msg.media_group_id:
        gid = str(msg.media_group_id)
        buf = _WEBCHAT_NOTE_BUF.get(gid)
        if not buf:
            _WEBCHAT_NOTE_BUF[gid] = {
                "media_list": [],
                "caption": "",
                "task": None,
                "session_id": session_id,
                "from_name": from_name,
            }
            buf = _WEBCHAT_NOTE_BUF[gid]

        if msg.photo:
            p = msg.photo[-1]
            buf["media_list"].append({"type": "photo", "file_id": p.file_id, "file_unique_id": p.file_unique_id})
        elif msg.video:
            v = msg.video
            buf["media_list"].append({"type": "video", "file_id": v.file_id, "file_unique_id": v.file_unique_id})
        elif msg.document:
            d = msg.document
            buf["media_list"].append({"type": "document", "file_id": d.file_id, "file_unique_id": d.file_unique_id})

        cap = (msg.caption or "").strip()
        if cap:
            buf["caption"] = cap

        _schedule_webchat_note(gid, delay=1.5)
        return

    # 纯文本
    if msg.text:
        text = msg.text.strip()
        event_id = dbm.event_add(conn, session_id, role="agent", kind="text", text=text, file_id="", caption="", from_name=from_name)
        event_data = {"id": event_id, "session_id": session_id, "role": "agent", "kind": "text", "text": text, "from_name": from_name}
        await send_event_to_customer(conn, session, event_data)
        return

    # 单媒体
    file_id = None
    caption = (msg.caption or "").strip() or None
    kind = "media"
    local_path = ""

    if msg.photo:
        p = msg.photo[-1]
        file_id = p.file_id
        kind = "photo"
        try:
            local_path = await save_webchat_media(file_id, p.file_unique_id)
        except Exception:
            logger.warning("下载图片失败: file_id=%s", file_id, exc_info=True)
    elif msg.video:
        v = msg.video
        file_id = v.file_id
        kind = "video"
        try:
            local_path = await save_webchat_media(file_id, v.file_unique_id)
        except Exception:
            logger.warning("下载视频失败: file_id=%s", file_id, exc_info=True)
    elif msg.document:
        d = msg.document
        file_id = d.file_id
        kind = "document"
        try:
            local_path = await save_webchat_media(file_id, d.file_unique_id)
        except Exception:
            logger.warning("下载文档失败: file_id=%s", file_id, exc_info=True)

    if file_id:
        event_id = dbm.event_add(
            conn, session_id,
            role="agent",
            kind=kind,
            text="",
            file_id=file_id,
            caption=caption,
            from_name=from_name,
            local_path=local_path
        )
        if local_path:
            dbm.media_asset_upsert(conn, session_id, file_id, kind, local_path, ttl_seconds=MEDIA_TTL_SECONDS)
        event_data = {
            "id": event_id,
            "session_id": session_id,
            "role": "agent",
            "kind": kind,
            "file_id": file_id,
            "caption": caption,
            "from_name": from_name,
            "local_path": local_path,
        }
        await send_event_to_customer(conn, session, event_data)
