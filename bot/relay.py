import asyncio
import logging
import os
from contextlib import suppress
from typing import Any, Dict

import requests
from aiogram.types import FSInputFile

import db as dbm
from config import API_HOST, API_PORT, RESOLVED_INTERNAL_TOKEN

from .customer_bots import CUSTOMER_BOTS_BY_BINDING_ID
from .media import abs_public_path
from .runtime import bot
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


def _rand_topic_tag(n: int = 4) -> str:
    import secrets
    import string
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(2, int(n))))


def _make_topic_name(display_name: str, key: str, channel: str = "web") -> str:
    prefix = "TG-" if channel == "telegram" else ""
    base = f"{prefix}{(display_name or key).strip() or key}({key})-{_rand_topic_tag(4)}"
    return base[:80]


async def ensure_support_thread(conn, session: Dict[str, Any], widget: Dict[str, Any]) -> int:
    thread_id = session.get("thread_id")
    if thread_id:
        return int(thread_id)

    key = session.get("key") or widget.get("key") or ""
    display_name = widget.get("display_name") or key
    forum_chat_id = int(widget["forum_chat_id"])
    topic_name = _make_topic_name(display_name, key, session.get("channel") or "web")
    topic = await bot.create_forum_topic(chat_id=forum_chat_id, name=topic_name)
    thread_id = int(topic.message_thread_id)
    dbm.session_set_thread(conn, session["session_id"], thread_id)

    source = session.get("source_code") or "-"
    channel = "Telegram 客户机器人" if session.get("channel") == "telegram" else "网页"
    header = (
        "🔔 <b>新咨询</b>\n"
        f"入口：<b>{html_escape(key)}</b>（{html_escape(display_name)}）\n"
        f"渠道：<b>{html_escape(channel)}</b>\n"
        f"来源：<code>{html_escape(source)}</code>\n"
        f"会话：<code>{html_escape(session['session_id'])}</code>\n"
        "——"
    )
    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=thread_id,
        text=header,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return thread_id


async def send_support_text(forum_chat_id: int, thread_id: int, text: str, label: str = "客户") -> None:
    body = f"👤 <b>{html_escape(label)}</b>：\n{html_escape(text)}"
    await bot.send_message(
        chat_id=forum_chat_id,
        message_thread_id=thread_id,
        text=body,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def send_support_media(forum_chat_id: int, thread_id: int, kind: str, rel_path: str, caption: str = "") -> None:
    path = abs_public_path(rel_path)
    cap = caption or ""
    if kind == "photo":
        await bot.send_photo(chat_id=forum_chat_id, message_thread_id=thread_id, photo=FSInputFile(path), caption=cap)
    elif kind == "video":
        await bot.send_video(chat_id=forum_chat_id, message_thread_id=thread_id, video=FSInputFile(path), caption=cap)
    else:
        await bot.send_document(chat_id=forum_chat_id, message_thread_id=thread_id, document=FSInputFile(path), caption=cap)


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
        title = event.get("title") or "客服笔记"
        body = event.get("body") or ""
        await customer_bot.send_message(chat_id=chat_id, text="\n".join([x for x in [title, body] if x]))
        for item in event.get("media") or []:
            if not isinstance(item, dict):
                continue
            await _send_customer_media(
                customer_bot,
                chat_id,
                item.get("type") or "document",
                item.get("local_path") or "",
                item.get("caption") or "",
            )
