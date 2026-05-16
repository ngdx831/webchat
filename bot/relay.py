import asyncio
import logging
import os
from contextlib import suppress
from typing import Any, Dict, List

import requests
from aiogram.types import (
    FSInputFile,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
)

import db as dbm
from config import API_HOST, API_PORT, RESOLVED_INTERNAL_TOKEN
from shared.session_presentation import format_session_header_html, make_topic_name

from .customer_bots import CUSTOMER_BOTS_BY_BINDING_ID
from .media import abs_public_path
from .rate_limit import safe_main_bot_call
from .runtime import get_main_bot
from .validators import html_escape


logger = logging.getLogger(__name__)

API_NOTIFY_URL = f"http://{API_HOST}:{API_PORT}/internal/notify"


# ================== 非阻塞 HTTP（避免 async handler 被 requests 卡住） ==================
try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None


def _internal_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {RESOLVED_INTERNAL_TOKEN}"} if RESOLVED_INTERNAL_TOKEN else {}


async def http_post_json(url: str, payload: Dict, timeout: float = 2.0) -> None:
    """优先 aiohttp；没有就用 asyncio.to_thread 包 requests。"""
    headers = _internal_headers()
    if aiohttp is not None:
        try:
            t = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=t) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    with suppress(Exception):
                        await resp.text()
            return
        except Exception:
            return

    def _sync():
        try:
            requests.post(url, json=payload, headers=headers, timeout=timeout)
        except Exception:
            pass

    await asyncio.to_thread(_sync)


async def notify_web(session_id: str, event_data: Dict) -> None:
    payload = dict(event_data or {})
    payload.setdefault("type", "msg")
    await http_post_json(API_NOTIFY_URL, {"session_id": session_id, "event": payload}, timeout=2.0)


async def ensure_support_thread(conn, session: Dict[str, Any], widget: Dict[str, Any]) -> int:
    thread_id = session.get("thread_id")
    if thread_id:
        return int(thread_id)

    key = session.get("key") or widget.get("key") or ""
    display_name = widget.get("display_name") or key
    forum_chat_id = int(widget["forum_chat_id"])
    source_code = session.get("source_code") or ""
    channel = session.get("channel") or "web"
    enabled = int(widget.get("enabled") if widget.get("enabled") is not None else 1)
    topic_name = make_topic_name(display_name, key, source_code)
    bot = get_main_bot()
    topic = await safe_main_bot_call(
        lambda: bot.create_forum_topic(chat_id=forum_chat_id, name=topic_name)
    )
    thread_id = int(topic.message_thread_id)
    dbm.session_set_thread(conn, session["session_id"], thread_id)

    header = format_session_header_html(
        session_id=session["session_id"],
        key=key,
        display_name=display_name,
        enabled=enabled,
        offline_msg=widget.get("offline_msg") or "",
        channel=channel,
        source_code=source_code,
    )
    await safe_main_bot_call(lambda: bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=thread_id,
        text=header,
        parse_mode="HTML",
        disable_web_page_preview=True,
    ))
    return thread_id


async def send_support_text(forum_chat_id: int, thread_id: int, text: str, label: str = "客户") -> None:
    body = f"👤 <b>{html_escape(label)}</b>：\n{html_escape(text)}"
    bot = get_main_bot()
    await safe_main_bot_call(lambda: bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=thread_id,
        text=body,
        parse_mode="HTML",
        disable_web_page_preview=True,
    ))


async def send_support_media(forum_chat_id: int, thread_id: int, kind: str, rel_path: str, caption: str = "") -> None:
    path = abs_public_path(rel_path)
    cap = caption or ""
    bot = get_main_bot()
    if kind == "photo":
        await safe_main_bot_call(lambda: bot.send_photo(
            chat_id=forum_chat_id, message_thread_id=thread_id, photo=FSInputFile(path), caption=cap,
        ))
    elif kind == "video":
        await safe_main_bot_call(lambda: bot.send_video(
            chat_id=forum_chat_id, message_thread_id=thread_id, video=FSInputFile(path), caption=cap,
        ))
    else:
        await safe_main_bot_call(lambda: bot.send_document(
            chat_id=forum_chat_id, message_thread_id=thread_id, document=FSInputFile(path), caption=cap,
        ))


async def _send_customer_media(customer_bot, chat_id: int, kind: str, rel_path: str, caption: str = "") -> None:
    path = abs_public_path(rel_path or "")
    if not rel_path or not os.path.exists(path):
        await customer_bot.send_message(chat_id=chat_id, text=f"Media unavailable: {kind or 'file'}")
        return

    try:
        if kind == "photo":
            await customer_bot.send_photo(chat_id=chat_id, photo=FSInputFile(path), caption=caption or "")
        elif kind == "video":
            await customer_bot.send_video(chat_id=chat_id, video=FSInputFile(path), caption=caption or "")
        else:
            await customer_bot.send_document(chat_id=chat_id, document=FSInputFile(path), caption=caption or "")
    except Exception as exc:
        logger.warning("customer media send failed: chat_id=%s kind=%s path=%s error=%s", chat_id, kind, rel_path, exc)
        await customer_bot.send_message(chat_id=chat_id, text=f"Media unavailable: {kind or 'file'}")


def _input_media_for(kind: str, path: str, caption: str = ""):
    if kind == "video":
        return InputMediaVideo(media=FSInputFile(path), caption=caption or None)
    if kind == "document":
        return InputMediaDocument(media=FSInputFile(path), caption=caption or None)
    return InputMediaPhoto(media=FSInputFile(path), caption=caption or None)


async def _send_customer_media_group(
    customer_bot,
    chat_id: int,
    items: List[Dict[str, Any]],
    caption: str = "",
) -> None:
    """以本地文件重新上传方式整组发出（最多 10 项），不带任何 forward 元信息。

    - TG sendMediaGroup 单组最多 10 项，多余的分批；
    - caption 只挂在第一项上，符合 TG 标准展示；
    - 任意一项的本地文件缺失时降级为逐条 _send_customer_media。
    """
    valid: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rel = item.get("local_path") or ""
        if not rel:
            continue
        abs_p = abs_public_path(rel)
        if not abs_p or not os.path.exists(abs_p):
            continue
        valid.append({
            "type": item.get("type") or "photo",
            "path": abs_p,
            "rel_path": rel,
        })

    if not valid:
        for item in items or []:
            await _send_customer_media(
                customer_bot,
                chat_id,
                (item or {}).get("type") or "document",
                (item or {}).get("local_path") or "",
                "",
            )
        return

    if len(valid) == 1:
        await _send_customer_media(customer_bot, chat_id, valid[0]["type"], valid[0]["rel_path"], caption)
        return

    for batch_start in range(0, len(valid), 10):
        batch = valid[batch_start:batch_start + 10]
        media: List[Any] = []
        for idx, it in enumerate(batch):
            cap = caption if (batch_start == 0 and idx == 0) else ""
            media.append(_input_media_for(it["type"], it["path"], cap))
        try:
            await customer_bot.send_media_group(chat_id=chat_id, media=media)
        except Exception as exc:
            logger.warning(
                "customer media_group send failed: chat_id=%s size=%s error=%s",
                chat_id, len(batch), exc,
            )
            for it in batch:
                await _send_customer_media(customer_bot, chat_id, it["type"], it["rel_path"], "")


async def send_event_to_customer(conn, session: Dict[str, Any], event: Dict[str, Any]) -> None:
    if session.get("channel") != "telegram":
        await notify_web(session["session_id"], event)
        return

    binding_id = session.get("bot_binding_id")
    customer_bot = CUSTOMER_BOTS_BY_BINDING_ID.get(int(binding_id or 0))
    if not customer_bot:
        logger.warning(
            "customer bot is not active: session_id=%s binding_id=%s",
            session.get("session_id"),
            binding_id,
        )
        return
    if not customer_bot or not session.get("customer_chat_id"):
        return

    chat_id = int(session["customer_chat_id"])
    kind = event.get("kind") or "text"
    caption = event.get("caption") or ""
    if kind == "text":
        await customer_bot.send_message(chat_id=chat_id, text=event.get("text") or "")
    elif kind == "photo":
        await _send_customer_media(customer_bot, chat_id, "photo", event.get("local_path") or "", caption)
    elif kind == "video":
        await _send_customer_media(customer_bot, chat_id, "video", event.get("local_path") or "", caption)
    elif kind == "document":
        await _send_customer_media(customer_bot, chat_id, "document", event.get("local_path") or "", caption)
    elif kind == "note":
        title = (event.get("title") or "").strip()
        body = (event.get("body") or "").strip()
        media_items = [m for m in (event.get("media") or []) if isinstance(m, dict)]
        note_caption = "\n".join([x for x in [title, body] if x]).strip()

        if not media_items:
            if note_caption:
                await customer_bot.send_message(chat_id=chat_id, text=note_caption)
            return

        # 整组媒体作为客户机器人发出的新消息，不带 forward 来源。
        # caption 直接挂在媒体组首项上，避免多发一条纯文本。
        await _send_customer_media_group(
            customer_bot,
            chat_id,
            media_items,
            caption=note_caption,
        )
