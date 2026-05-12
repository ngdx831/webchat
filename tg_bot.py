# tg_bot.py
import asyncio
import re
import os
import json
import secrets
import string
import requests
import uuid
from contextlib import suppress
from typing import Any, Dict, Optional
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.filters import Command, CommandObject, CommandStart

from config import (
    BOT_TOKEN, ADMIN_IDS, DB_PATH, API_HOST, API_PORT,
    MEDIA_TTL_SECONDS, WEBCHAT_MEDIA_ROOT
)
import db as dbm
from session_cleanup import delete_session_record_and_media

API_NOTIFY_URL = f"http://{API_HOST}:{API_PORT}/internal/notify"


def _public_root_from_media_root() -> str:
    try:
        return os.path.abspath(os.path.join(WEBCHAT_MEDIA_ROOT, os.pardir, os.pardir))
    except Exception:
        return "/www/wwwroot/kefu.ws"


PUBLIC_ROOT = _public_root_from_media_root()


# ================== 非阻塞 HTTP（避免 async handler 被 requests 卡住） ==================
try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None


async def http_post_json(url: str, payload: Dict, timeout: float = 2.0) -> None:
    """优先 aiohttp；没有就用 asyncio.to_thread 包 requests。"""
    if aiohttp is not None:
        try:
            t = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=t) as session:
                async with session.post(url, json=payload) as resp:
                    with suppress(Exception):
                        await resp.text()
            return
        except Exception:
            return

    def _sync():
        try:
            requests.post(url, json=payload, timeout=timeout)
        except Exception:
            pass

    await asyncio.to_thread(_sync)


async def notify_web(session_id: str, event_data: Dict) -> None:
    await http_post_json(API_NOTIFY_URL, {"session_id": session_id, "event": event_data}, timeout=2.0)


KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
SOURCE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
RESERVED_KEYS = {"api", "assets", "favicon.ico", "health", "internal", "robots.txt", "static", "webchat", "widget"}


def validate_key(k: str) -> str:
    k2 = (k or "").strip()
    if not k2:
        raise ValueError("BAD_KEY_EMPTY")
    kl = k2.lower()
    if kl in RESERVED_KEYS or kl.startswith("api"):
        raise ValueError("BAD_KEY_RESERVED")
    if not KEY_RE.fullmatch(k2):
        raise ValueError("BAD_KEY_FORMAT")
    return k2


def explain_key_error(code: str) -> str:
    if code == "BAD_KEY_EMPTY":
        return "❌ key 不能为空"
    if code == "BAD_KEY_RESERVED":
        return "❌ key 禁止使用（保留字，或以 api 开头）"
    if code == "BAD_KEY_FORMAT":
        return "❌ key 格式不合法：仅允许英文/数字/_/-，长度 1~32，且必须英文/数字开头"
    return f"❌ 参数错误：{code}"


bot = Bot(BOT_TOKEN)
dp = Dispatcher()
CUSTOMER_BOTS_BY_TOKEN: Dict[str, Dict[str, Any]] = {}
CUSTOMER_BOTS_BY_BINDING_ID: Dict[int, Bot] = {}
CUSTOMER_BOT_POLLING_TASKS: Dict[int, asyncio.Task[Any]] = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def current_user_from_message(conn, msg: Message) -> Optional[Dict[str, Any]]:
    if not getattr(msg, "from_user", None):
        return None
    tg_user = msg.from_user
    user_id = int(tg_user.id)
    default_role = dbm.USER_ROLE_ADMIN if is_admin(user_id) else dbm.USER_ROLE_NORMAL
    username = getattr(tg_user, "username", "") or ""
    display_name = getattr(tg_user, "full_name", "") or username
    return dbm.user_upsert_from_telegram(
        conn,
        user_id,
        username,
        display_name,
        default_role=default_role,
    )


def is_vip_or_admin(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    return user.get("role") in {dbm.USER_ROLE_VIP, dbm.USER_ROLE_ADMIN}


def is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    return user.get("role") == dbm.USER_ROLE_ADMIN


def require_enabled_user(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user and int(user.get("enabled") or 0) == 1)


def require_owned_key(conn, user: Optional[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    if not require_enabled_user(user):
        return None
    if is_admin_user(user):
        return dbm.widget_get(conn, key)
    return dbm.widget_get_owned(conn, key, int(user["telegram_user_id"]))


def key_limit_for_role(role: str) -> Optional[int]:
    if role == dbm.USER_ROLE_ADMIN:
        return None
    if role == dbm.USER_ROLE_VIP:
        return 5
    return 1


def _user_display_role(user: Dict[str, Any]) -> str:
    return str(user.get("role") or dbm.USER_ROLE_NORMAL)


def _widget_owner_has_vip_features(conn, widget: Optional[Dict[str, Any]]) -> bool:
    if not widget or widget.get("owner_user_id") is None:
        return False
    owner = dbm.user_get(conn, int(widget["owner_user_id"]))
    return bool(require_enabled_user(owner) and is_vip_or_admin(owner))


def _widget_owner_enabled(conn, widget: Optional[Dict[str, Any]]) -> bool:
    if not widget or widget.get("owner_user_id") is None:
        return False
    owner = dbm.user_get(conn, int(widget["owner_user_id"]))
    return require_enabled_user(owner)


def validate_source_code(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value if SOURCE_RE.fullmatch(value) else ""


def _bot_token(active_bot: Optional[Bot]) -> str:
    return str(getattr(active_bot, "token", "") or "")


def is_main_bot(active_bot: Optional[Bot]) -> bool:
    return _bot_token(active_bot) == BOT_TOKEN


def binding_for_bot(active_bot: Optional[Bot]) -> Optional[Dict[str, Any]]:
    return CUSTOMER_BOTS_BY_TOKEN.get(_bot_token(active_bot))


def _register_customer_bot_binding(binding: Dict[str, Any], customer_bot: Bot) -> int:
    binding_id = int(binding["id"])
    token = _bot_token(customer_bot) or str(binding.get("bot_token") or "")
    binding["bot_token"] = token
    CUSTOMER_BOTS_BY_TOKEN[token] = binding
    CUSTOMER_BOTS_BY_BINDING_ID[binding_id] = customer_bot
    return binding_id


async def _run_customer_bot_polling(binding_id: int, customer_bot: Bot) -> None:
    try:
        await dp._polling(
            bot=customer_bot,
            polling_timeout=10,
            handle_as_tasks=True,
            allowed_updates=dp.resolve_used_update_types(),
            dispatcher=dp,
            bots=(customer_bot,),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"Customer bot polling stopped: binding_id={binding_id}, error={exc}")
    finally:
        task = asyncio.current_task()
        if CUSTOMER_BOT_POLLING_TASKS.get(binding_id) is task:
            CUSTOMER_BOT_POLLING_TASKS.pop(binding_id, None)


async def activate_customer_bot_binding(
    binding: Dict[str, Any],
    customer_bot: Bot,
    start_polling: bool = True,
) -> bool:
    """Register a customer-side bot and optionally start polling it immediately."""
    binding_id = int(binding["id"])
    existing_bot = CUSTOMER_BOTS_BY_BINDING_ID.get(binding_id)
    if existing_bot is not None and existing_bot is not customer_bot:
        await deactivate_customer_bot_binding(binding_id)

    _register_customer_bot_binding(binding, customer_bot)

    if not start_polling:
        return False

    task = CUSTOMER_BOT_POLLING_TASKS.get(binding_id)
    if task and not task.done():
        return False

    CUSTOMER_BOT_POLLING_TASKS[binding_id] = asyncio.create_task(
        _run_customer_bot_polling(binding_id, customer_bot),
        name=f"customer-bot-polling-{binding_id}",
    )
    return True


async def deactivate_customer_bot_binding(binding_id: int) -> None:
    binding_id = int(binding_id)
    task = CUSTOMER_BOT_POLLING_TASKS.pop(binding_id, None)
    if task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    customer_bot = CUSTOMER_BOTS_BY_BINDING_ID.pop(binding_id, None)
    if customer_bot:
        CUSTOMER_BOTS_BY_TOKEN.pop(_bot_token(customer_bot), None)
        with suppress(Exception):
            await customer_bot.session.close()


async def shutdown_customer_bots(*args: Any, **kwargs: Any) -> None:
    for binding_id in list(CUSTOMER_BOT_POLLING_TASKS):
        await deactivate_customer_bot_binding(binding_id)


with suppress(Exception):
    dp.shutdown.register(shutdown_customer_bots)


def _html_escape(s: str) -> str:
    s = s or ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def _rand_topic_tag(n: int = 4) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(2, int(n))))


def _make_topic_name(display_name: str, key: str, channel: str = "web") -> str:
    prefix = "TG-" if channel == "telegram" else ""
    base = f"{prefix}{(display_name or key).strip() or key}({key})-{_rand_topic_tag(4)}"
    return base[:80]


# =============== 通用权限/目录工具（兼容 root/www） ===============

def _try_chown_www(path: str) -> None:
    try:
        if os.geteuid() != 0:
            return
        import pwd, grp
        uid = pwd.getpwnam("www").pw_uid
        gid = grp.getgrnam("www").gr_gid
        os.chown(path, uid, gid)
    except Exception:
        pass


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o775)
    except Exception:
        pass
    _try_chown_www(path)


# =============== 通过 HTTP Bot API 下载文件 ===============

def tg_http_call(method: str, payload: Dict) -> Dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"TG_API_ERROR:{data}")
    return data


def tg_http_call_with_token(token: str, method: str, payload: Dict) -> Dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"TG_API_ERROR:{data}")
    return data


def tg_get_file_path(file_id: str) -> str:
    data = tg_http_call("getFile", {"file_id": file_id})
    return data["result"]["file_path"]


def tg_get_file_path_with_token(token: str, file_id: str) -> str:
    data = tg_http_call_with_token(token, "getFile", {"file_id": file_id})
    return data["result"]["file_path"]


def download_file_to(path_url: str, dest_path: str) -> None:
    with requests.get(path_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


async def save_webchat_media(file_id: str, file_unique_id: str) -> str:
    """
    下载客服媒体文件到 WEBCHAT_MEDIA_ROOT/YYYYMM/xxx.ext
    返回 rel_path：webchat/media/YYYYMM/xxx.ext
    """
    file_path = await asyncio.to_thread(tg_get_file_path, file_id)
    _, ext = os.path.splitext(file_path)
    ext = ext or ".bin"

    ym = datetime.now().strftime("%Y%m")
    out_dir = os.path.join(WEBCHAT_MEDIA_ROOT, ym)
    ensure_dir(out_dir)

    fname = f"{file_unique_id}{ext}"
    abs_path = os.path.join(out_dir, fname)

    if not os.path.exists(abs_path):
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        await asyncio.to_thread(download_file_to, url, abs_path)
        try:
            os.chmod(abs_path, 0o664)
        except Exception:
            pass
        _try_chown_www(abs_path)

    rel_path = f"webchat/media/{ym}/{fname}"
    return rel_path


async def save_media_from_token(token: str, file_id: str, file_unique_id: str) -> str:
    file_path = await asyncio.to_thread(tg_get_file_path_with_token, token, file_id)
    _, ext = os.path.splitext(file_path)
    ext = ext or ".bin"
    ym = datetime.now().strftime("%Y%m")
    out_dir = os.path.join(WEBCHAT_MEDIA_ROOT, ym)
    ensure_dir(out_dir)
    fname = f"{file_unique_id}{ext}"
    abs_path = os.path.join(out_dir, fname)
    if not os.path.exists(abs_path):
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        await asyncio.to_thread(download_file_to, url, abs_path)
        with suppress(Exception):
            os.chmod(abs_path, 0o664)
        _try_chown_www(abs_path)
    return f"webchat/media/{ym}/{fname}"


def abs_public_path(rel_path: str) -> str:
    return os.path.join(PUBLIC_ROOT, (rel_path or "").lstrip("/\\"))


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
        f"入口：<b>{_html_escape(key)}</b>（{_html_escape(display_name)}）\n"
        f"渠道：<b>{_html_escape(channel)}</b>\n"
        f"来源：<code>{_html_escape(source)}</code>\n"
        f"会话：<code>{_html_escape(session['session_id'])}</code>\n"
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
    body = f"👤 <b>{_html_escape(label)}</b>：\n{_html_escape(text)}"
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


async def send_event_to_customer(conn, session: Dict[str, Any], event: Dict[str, Any]) -> None:
    if session.get("channel") != "telegram":
        await notify_web(session["session_id"], event)
        return

    binding_id = session.get("bot_binding_id")
    customer_bot = CUSTOMER_BOTS_BY_BINDING_ID.get(int(binding_id or 0))
    if not customer_bot:
        binding = dbm.bot_binding_get(conn, int(binding_id or 0)) if binding_id else None
        if binding:
            customer_bot = Bot(binding["bot_token"])
            CUSTOMER_BOTS_BY_BINDING_ID[int(binding["id"])] = customer_bot
    if not customer_bot or not session.get("customer_chat_id"):
        return

    chat_id = int(session["customer_chat_id"])
    kind = event.get("kind") or "text"
    caption = event.get("caption") or ""
    if kind == "text":
        await customer_bot.send_message(chat_id=chat_id, text=event.get("text") or "")
    elif kind == "photo":
        path = abs_public_path(event.get("local_path") or "")
        await customer_bot.send_photo(chat_id=chat_id, photo=FSInputFile(path), caption=caption)
    elif kind == "video":
        path = abs_public_path(event.get("local_path") or "")
        await customer_bot.send_video(chat_id=chat_id, video=FSInputFile(path), caption=caption)
    elif kind == "document":
        path = abs_public_path(event.get("local_path") or "")
        await customer_bot.send_document(chat_id=chat_id, document=FSInputFile(path), caption=caption)
    elif kind == "note":
        title = event.get("title") or "客服笔记"
        body = event.get("body") or ""
        await customer_bot.send_message(chat_id=chat_id, text="\n".join([x for x in [title, body] if x]))


# ================== 命令 ==================

@dp.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject, bot: Bot):
    binding = binding_for_bot(bot)
    if binding:
        await customer_cmd_start(msg, command, bot, binding)
        return

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    user = current_user_from_message(conn, msg)
    if user and not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    if is_admin_user(user):
        await msg.reply(
            "✅ 后台机器人已启动\n\n"
            "请使用 /adminhelp 查看管理员命令。\n\n"
            "管理命令：\n"
            "• /kadd <key> <forum_chat_id> <显示名>\n"
            "• /kdel <key>\n"
            "• /kls   （含在线/离线状态）\n"
            "• /koff <key> [离线提示]\n"
            "• /kon <key>\n"
            "• /kmsg <key> <离线提示>\n"
            "• /botadd <key> <bot_token> [bot_username]\n"
            "• /botdel <key> [bot_username]\n"
            "• /botls [key]\n"
            "• /qradd <key> <标题>|<答案>\n"
            "• /qrls <key>\n"
            "• /qrdel <key> <编号>\n"
            "• /stats <key> [来源]\n"
            "• /statdel <key> [来源]\n"
            "• /id（在群里发，返回群ID & 是否开启话题）\n\n"
            "客服会话管理：\n"
            "• /valid - 标记有效客户\n"
            "• /deal - 标记成交客户\n"
            "• /end - 结束当前会话（删除话题、数据、媒体）"
        )
    else:
        await msg.reply("这是网页客服系统的后台机器人，不提供普通聊天功能。")


async def customer_cmd_start(msg: Message, command: CommandObject, active_bot: Bot, binding: Dict[str, Any]) -> None:
    key = binding["key"]
    source_code = validate_source_code(command.args or "")
    visitor_id = str(msg.from_user.id if msg.from_user else msg.chat.id)
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    widget = dbm.widget_get(conn, key)
    if not _widget_owner_enabled(conn, widget):
        await active_bot.send_message(chat_id=msg.chat.id, text="客服入口暂不可用。")
        return
    if source_code:
        dbm.source_click_add(conn, key, source_code, "telegram", visitor_id)

    replies = dbm.quick_reply_list(conn, key) if _widget_owner_has_vip_features(conn, widget) else []
    keyboard = None
    if replies:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=item["title"], callback_data=f"qr:{item['id']}")]
                for item in replies[:9]
            ]
        )
    help_link = dbm.setting_get(conn, "help_link", "")
    welcome_text = (widget or {}).get("welcome_text") or "请选择常见问题，或直接发送消息联系人工客服。"
    text_lines = [welcome_text]
    if help_link:
        text_lines.extend(["", f"Help: {help_link}"])
    if replies:
        text_lines.extend(["", "请选择常见问题，或直接发送消息联系人工客服。"])
    await active_bot.send_message(
        chat_id=msg.chat.id,
        text="\n".join(text_lines),
        reply_markup=keyboard,
    )


@dp.message(Command("help"))
async def cmd_help(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    admin_contact = dbm.setting_get(conn, "admin_contact", "Please contact admin.")
    lines = [
        "User commands:",
        "/keyadd <key> <display_name>",
        "/myinfo",
        "/keyinfo <key>",
        "/keydel <key>",
        "/tokenadd <key>",
        "/groupbind <key>",
        "/welcome <key>",
        f"Admin contact: {admin_contact}",
    ]
    if is_vip_or_admin(user):
        lines.extend([
            "",
            "VIP commands:",
            "/qradd <key> <title>|<answer>",
            "/qrls <key>",
            "/qrdel <key> <id>",
            "/stats <key> [source]",
            "/statdel <key> [source]",
        ])
    if is_admin_user(user):
        lines.extend(["", "Admin commands: /adminhelp"])
    await msg.reply("\n".join(lines))


@dp.message(Command("adminhelp"))
async def cmd_adminhelp(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    if not is_admin_user(user):
        await msg.reply("Permission denied.")
        return
    await msg.reply(
        "Admin commands:\n"
        "/userls [normal|vip|admin|disabled]\n"
        "/userget <telegram_user_id>\n"
        "/userset <telegram_user_id> <normal|vip|admin>\n"
        "/userban <telegram_user_id>\n"
        "/userunban <telegram_user_id>\n"
        "/userkeys <telegram_user_id>\n"
        "/adminkeyinfo <key>\n"
        "/adminkeydel <key>\n"
        "/helplink <URL>\n"
        "/admincontact <text>"
    )


@dp.message(Command("helplink"))
async def cmd_helplink(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    if not is_admin_user(user):
        await msg.reply("Permission denied.")
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.reply("Usage: /helplink <URL>")
        return
    value = parts[1].strip()
    dbm.setting_set(conn, "help_link", value)
    await msg.reply(f"help_link: {value}")


@dp.message(Command("admincontact"))
async def cmd_admincontact(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    if not is_admin_user(user):
        await msg.reply("Permission denied.")
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.reply("Usage: /admincontact <text>")
        return
    value = parts[1].strip()
    dbm.setting_set(conn, "admin_contact", value)
    await msg.reply(f"admin_contact: {value}")


async def _admin_context_or_reply(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return None, None, False
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return conn, user, False
    if not is_admin_user(user):
        await msg.reply("Permission denied.")
        return conn, user, False
    return conn, user, True


def _format_user_line(user: Dict[str, Any]) -> str:
    username = user.get("username") or "-"
    return (
        f"{user['telegram_user_id']} @{username} "
        f"role={user.get('role') or ''} enabled={int(user.get('enabled') or 0)}"
    )


def _parse_user_id_arg(text: str) -> Optional[int]:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].strip())
    except Exception:
        return None


@dp.message(Command("userls"))
async def cmd_userls(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    parts = (msg.text or "").split(maxsplit=1)
    flt = parts[1].strip().lower() if len(parts) > 1 else ""
    if flt == "disabled":
        rows = [row for row in dbm.user_list(conn, limit=200) if int(row.get("enabled") or 0) == 0]
    elif flt in dbm.USER_ROLES:
        rows = dbm.user_list(conn, role=flt, limit=200)
    elif flt:
        await msg.reply("Usage: /userls [normal|vip|admin|disabled]")
        return
    else:
        rows = dbm.user_list(conn, limit=200)

    if not rows:
        await msg.reply("(no users)")
        return
    await msg.reply("Users:\n" + "\n".join(_format_user_line(row) for row in rows))


@dp.message(Command("userget"))
async def cmd_userget(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    user_id = _parse_user_id_arg(msg.text or "")
    if user_id is None:
        await msg.reply("Usage: /userget <telegram_user_id>")
        return
    user = dbm.user_get(conn, user_id)
    if not user:
        await msg.reply(f"User not found: {user_id}")
        return
    await msg.reply(
        "User:\n"
        f"id: {user['telegram_user_id']}\n"
        f"username: {user.get('username') or ''}\n"
        f"display_name: {user.get('display_name') or ''}\n"
        f"role: {user.get('role') or ''}\n"
        f"enabled: {int(user.get('enabled') or 0)}\n"
        f"vip_until: {user.get('vip_until') or ''}"
    )


@dp.message(Command("userset"))
async def cmd_userset(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage: /userset <telegram_user_id> <normal|vip|admin>")
        return
    try:
        user_id = int(parts[1])
    except Exception:
        await msg.reply("telegram_user_id must be a number.")
        return
    try:
        user = dbm.user_set_role(conn, user_id, parts[2].strip())
    except ValueError:
        await msg.reply("Role must be normal, vip, or admin.")
        return
    if not user:
        await msg.reply(f"User not found: {user_id}")
        return
    await msg.reply(f"User updated: {user_id}\nrole: {user['role']}")


@dp.message(Command("userban"))
async def cmd_userban(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    user_id = _parse_user_id_arg(msg.text or "")
    if user_id is None:
        await msg.reply("Usage: /userban <telegram_user_id>")
        return
    user = dbm.user_set_enabled(conn, user_id, False)
    if not user:
        await msg.reply(f"User not found: {user_id}")
        return
    await msg.reply(f"User updated: {user_id}\nenabled: {int(user.get('enabled') or 0)}")


@dp.message(Command("userunban"))
async def cmd_userunban(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    user_id = _parse_user_id_arg(msg.text or "")
    if user_id is None:
        await msg.reply("Usage: /userunban <telegram_user_id>")
        return
    user = dbm.user_set_enabled(conn, user_id, True)
    if not user:
        await msg.reply(f"User not found: {user_id}")
        return
    await msg.reply(f"User updated: {user_id}\nenabled: {int(user.get('enabled') or 0)}")


@dp.message(Command("userkeys"))
async def cmd_userkeys(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    user_id = _parse_user_id_arg(msg.text or "")
    if user_id is None:
        await msg.reply("Usage: /userkeys <telegram_user_id>")
        return
    if not dbm.user_get(conn, user_id):
        await msg.reply(f"User not found: {user_id}")
        return
    rows = dbm.widget_list_by_owner(conn, user_id, limit=200)
    if not rows:
        await msg.reply(f"(no keys for user {user_id})")
        return
    lines = [f"Keys for user {user_id}:"]
    for row in rows:
        status = "online" if int(row.get("enabled") or 0) else "offline"
        lines.append(f"- {row['key']}: {row.get('display_name') or ''} {status}")
    await msg.reply("\n".join(lines))


@dp.message(Command("adminkeyinfo"))
async def cmd_adminkeyinfo(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /adminkeyinfo <key>")
        return
    try:
        key = validate_key(parts[1].strip())
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return
    widget = dbm.widget_get(conn, key)
    if not widget:
        await msg.reply(f"Key not found: {key}")
        return
    owner = dbm.user_get(conn, int(widget["owner_user_id"])) if widget.get("owner_user_id") is not None else None
    lines = [
        "Key:",
        f"key: {widget['key']}",
        f"display_name: {widget.get('display_name') or ''}",
        f"owner_user_id: {widget.get('owner_user_id') if widget.get('owner_user_id') is not None else '-'}",
        f"owner_role: {(owner or {}).get('role') or '-'}",
        f"owner_enabled: {int((owner or {}).get('enabled') or 0) if owner else '-'}",
        f"forum_chat_id: {widget.get('forum_chat_id')}",
        f"enabled: {int(widget.get('enabled') or 0)}",
        f"offline_msg: {widget.get('offline_msg') or ''}",
        f"welcome_text: {widget.get('welcome_text') or ''}",
    ]
    bindings = dbm.bot_binding_list(conn, key)
    if bindings:
        lines.append("bot_bindings:")
        for row in bindings:
            status = "enabled" if int(row.get("enabled") or 0) else "disabled"
            lines.append(f"- #{row['id']} @{row.get('bot_username') or '-'} {status}")
    await msg.reply("\n".join(lines))


@dp.message(Command("adminkeydel"))
async def cmd_adminkeydel(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /adminkeydel <key>")
        return
    try:
        key = validate_key(parts[1].strip())
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return
    if not dbm.widget_get(conn, key):
        await msg.reply(f"Key not found: {key}")
        return
    bindings = dbm.bot_binding_list(conn, key)
    for row in bindings:
        await deactivate_customer_bot_binding(int(row["id"]))
    binding_count = dbm.bot_binding_delete(conn, key)
    deleted = dbm.widget_del(conn, key)
    await msg.reply(
        f"Key deleted: {key}\nbot_bindings_deleted: {binding_count}"
        if deleted else f"Key not found: {key}"
    )


def _key_info_text(widget: Dict[str, Any]) -> str:
    status = "online" if int(widget.get("enabled") or 0) else "offline"
    return (
        f"key: {widget['key']}\n"
        f"display_name: {widget.get('display_name') or ''}\n"
        f"forum_chat_id: {widget.get('forum_chat_id')}\n"
        f"status: {status}"
    )


def _open_user_context(msg: Message):
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    user = current_user_from_message(conn, msg)
    return conn, user


def _vip_key_context(msg: Message, key: str):
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        return conn, user, None, "Account disabled. Please contact admin."
    if not is_vip_or_admin(user):
        return conn, user, None, "VIP feature required. Please contact admin."
    widget = require_owned_key(conn, user, key)
    if not widget:
        return conn, user, None, "Permission denied or key not found."
    return conn, user, widget, ""


async def _bind_customer_bot_token(
    conn,
    user: Optional[Dict[str, Any]],
    key: str,
    token: str,
    bot_username: str = "",
):
    widget = require_owned_key(conn, user, key)
    if not widget:
        return None, None, "", "Permission denied or key not found."

    try:
        probe = Bot(token)
        me = await probe.get_me()
        username = bot_username or (getattr(me, "username", "") or "")
    except Exception as e:
        return None, None, "", f"Bot token validation failed: {e}"

    owner_user_id = widget.get("owner_user_id")
    if owner_user_id is not None:
        owner_user_id = int(owner_user_id)
    binding_id = dbm.bot_binding_add(
        conn,
        key,
        token,
        username,
        enabled=1,
        owner_user_id=owner_user_id,
    )
    binding = dbm.bot_binding_get(conn, binding_id) or {
        "id": binding_id,
        "key": key,
        "bot_token": token,
        "bot_username": username,
        "enabled": 1,
        "owner_user_id": owner_user_id,
    }
    await activate_customer_bot_binding(binding, probe, start_polling=True)
    return binding, probe, username, ""


@dp.message(Command("tokenadd"))
async def cmd_tokenadd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        await msg.reply("Please send /tokenadd in a private chat with this bot.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /tokenadd <key>")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return

    dbm.pending_action_set(
        conn,
        int(user["telegram_user_id"]),
        "await_token",
        key=key,
        ttl_seconds=300,
    )
    await msg.reply(f"Send the customer bot token for key `{key}` within 5 minutes.")


@dp.message(Command("welcome"))
async def cmd_welcome(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        await msg.reply("Please send /welcome in a private chat with this bot.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /welcome <key>")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return

    dbm.pending_action_set(
        conn,
        int(user["telegram_user_id"]),
        "await_welcome",
        key=key,
        ttl_seconds=300,
    )
    await msg.reply(f"Send the welcome text for key `{key}` within 5 minutes.")


async def handle_pending_action_message(msg: Message, bot: Bot) -> bool:
    if not is_main_bot(bot):
        return False
    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        return False
    if not getattr(msg, "from_user", None):
        return False

    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return True

    pending = dbm.pending_action_get(conn, int(user["telegram_user_id"]))
    if not pending:
        return False

    action = pending.get("action")
    text = (msg.text or "").strip()
    key = str(pending.get("key") or "")
    try:
        key = validate_key(key)
    except Exception:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("Pending action is invalid. Please run the command again.")
        return True

    if action == "await_welcome":
        if not text:
            dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
            await msg.reply("Welcome text is empty. Please run /welcome <key> again.")
            return True
        widget = require_owned_key(conn, user, key)
        if not widget:
            dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
            await msg.reply("Permission denied or key not found.")
            return True
        dbm.widget_set_welcome_text(conn, key, text)
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply(f"Welcome text updated for key: {key}")
        return True

    if action != "await_token":
        return False

    if not text:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("Bot token is empty. Please run /tokenadd <key> again.")
        return True

    with suppress(Exception):
        await msg.delete()
    binding, _, username, error = await _bind_customer_bot_token(conn, user, key, text)
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    if error:
        await msg.reply(error)
        return True

    await msg.reply(
        f"Customer bot bound\nkey: {key}\nbot: @{username or '-'}\n"
        f"binding_id: {binding['id']}\nPolling started."
    )
    return True


@dp.message(Command("groupbind"))
async def cmd_groupbind(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    if getattr(getattr(msg, "chat", None), "type", "") != "supergroup":
        await msg.reply("Please run /groupbind <key> in a supergroup.")
        return

    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /groupbind <key>")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return

    chat_id = int(msg.chat.id)
    ok = dbm.widget_set_forum_chat_id(conn, key, chat_id)
    if not ok:
        await msg.reply("Permission denied or key not found.")
        return
    await msg.reply(f"Group bound\nkey: {key}\nforum_chat_id: {chat_id}")


@dp.message(Command("myinfo"))
async def cmd_myinfo(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    rows = dbm.widget_list_by_owner(conn, int(user["telegram_user_id"]))
    lines = [
        "My account",
        f"id: {user['telegram_user_id']}",
        f"role: {_user_display_role(user)}",
        f"keys: {len(rows)}",
    ]
    if rows:
        lines.append("key overview:")
        for row in rows:
            lines.append(f"- {row['key']}: {row.get('display_name') or ''}")
    await msg.reply("\n".join(lines))


@dp.message(Command("keyadd"))
async def cmd_keyadd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("Usage: /keyadd <key> <display_name>")
        return

    key = parts[1].strip()
    display_name = parts[2].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    limit = key_limit_for_role(str(user.get("role") or ""))
    owner_user_id = int(user["telegram_user_id"])
    if limit is not None and dbm.widget_count_by_owner(conn, owner_user_id) >= limit:
        await msg.reply(f"Key limit reached for role: {_user_display_role(user)} (limit {limit})")
        return

    try:
        dbm.widget_add(
            conn,
            key,
            0,
            display_name,
            must_not_exist=True,
            owner_user_id=owner_user_id,
        )
    except ValueError as exc:
        if str(exc) == "KEY_EXISTS":
            await msg.reply(f"Key already exists: {key}")
            return
        raise
    await msg.reply(f"Key created: {key}\ndisplay_name: {display_name}")


@dp.message(Command("keyinfo"))
async def cmd_keyinfo(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /keyinfo <key>")
        return
    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return
    await msg.reply(_key_info_text(widget))


@dp.message(Command("keydel"))
async def cmd_keydel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: /keydel <key>")
        return
    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return
    for row in dbm.bot_binding_list(conn, key):
        await deactivate_customer_bot_binding(int(row["id"]))
    dbm.bot_binding_delete(conn, key)
    deleted = dbm.widget_del(conn, key)
    await msg.reply(f"Key deleted: {key}" if deleted else f"Key not found: {key}")


@dp.message(Command("id"))
async def cmd_id(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return

    chat = msg.chat
    is_forum = getattr(chat, "is_forum", False)
    await msg.reply(
        f"chat_id: {chat.id}\n"
        f"type: {chat.type}\n"
        f"is_forum: {is_forum}\n"
        f"thread_id: {msg.message_thread_id or '-'}"
    )


@dp.message(Command("kadd"))
async def cmd_kadd(msg: Message, bot: Bot):
    conn, user, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await msg.reply("用法：/kadd <key> <forum_chat_id> <显示名>\n例：/kadd yaoyao -1001234567890 客服瑶瑶")
        return

    _, key, forum_chat_id_s, display_name = parts

    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    try:
        forum_chat_id = int(forum_chat_id_s)
    except Exception:
        await msg.reply("❌ forum_chat_id 必须是数字（例如 -100xxxxxxxxxxxx）")
        return

    existing_widget = dbm.widget_get(conn, key)
    owner_user_id = (
        int(existing_widget["owner_user_id"])
        if existing_widget and existing_widget.get("owner_user_id") is not None
        else int(user["telegram_user_id"])
    )
    try:
        dbm.widget_add(
            conn,
            key,
            forum_chat_id,
            display_name,
            must_not_exist=False,
            owner_user_id=owner_user_id,
        )
        await msg.reply(f"✅ 已设置\nkey: {key}\nforum_chat_id: {forum_chat_id}\n显示名: {display_name}")
    except Exception as e:
        await msg.reply(f"❌ 设置失败：{e}")


@dp.message(Command("kdel"))
async def cmd_kdel(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/kdel <key>\n例：/kdel yaoyao")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    for row in dbm.bot_binding_list(conn, key):
        await deactivate_customer_bot_binding(int(row["id"]))
    dbm.bot_binding_delete(conn, key)
    n = dbm.widget_del(conn, key)
    await msg.reply(f"✅ 已删除：{key}" if n else f"⚠️ 未找到：{key}")


@dp.message(Command("kls"))
async def cmd_kls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Use /myinfo to list your keys, or /keyinfo <key> for one key.")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return
    await msg.reply(_key_info_text(widget))
    return
    if not msg.from_user or not is_admin(msg.from_user.id):
        return

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    rows = dbm.widget_list(conn, limit=200)

    if not rows:
        await msg.reply("（暂无配置）\n用 /kadd 添加：/kadd yaoyao -100xxx 客服瑶瑶")
        return

    lines = ["📌 当前 Widgets："]
    for r in rows:
        enabled = int(r.get("enabled", 1) or 0)
        st = "🟢在线" if enabled == 1 else "🔴离线"
        off = (r.get("offline_msg") or "").strip()
        if off:
            off = off.replace("\n", " ")
            if len(off) > 36:
                off = off[:36] + "…"
            off = f"｜{off}"
        lines.append(f"• {r['key']} -> {r['forum_chat_id']}（{r['display_name']}）{st}{off}")
    await msg.reply("\n".join(lines))


@dp.message(Command("koff"))
async def cmd_koff(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/koff <key> [离线提示]\n例：/koff yaoyao 瑶瑶已下班，请留言或联系@xxx")
        return

    key = parts[1].strip()
    custom = parts[2].strip() if len(parts) >= 3 else ""

    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    w = require_owned_key(conn, user, key)
    if not w:
        await msg.reply("Permission denied or key not found.")
        return

    display_name = w.get("display_name") or key
    msg_text = custom or f"{display_name}已下班，请留言，我们上班后会回复。"
    ok = dbm.widget_set_enabled(conn, key, 0, msg_text)
    await msg.reply(f"✅ 已下班：{key}\n提示：{msg_text}" if ok else f"❌ 操作失败：{key}")


@dp.message(Command("kon"))
async def cmd_kon(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/kon <key>\n例：/kon yaoyao")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    if not require_owned_key(conn, user, key):
        await msg.reply("Permission denied or key not found.")
        return
    ok = dbm.widget_set_enabled(conn, key, 1, None)
    await msg.reply(f"✅ 已上班：{key}" if ok else f"❌ 未找到：{key}")


@dp.message(Command("kmsg"))
async def cmd_kmsg(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("用法：/kmsg <key> <离线提示>\n例：/kmsg yaoyao 瑶瑶已下班，请联系@xxx")
        return

    key = parts[1].strip()
    text = parts[2].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    if not require_owned_key(conn, user, key):
        await msg.reply("Permission denied or key not found.")
        return
    ok = dbm.widget_set_offline_msg(conn, key, text)
    await msg.reply(f"✅ 已更新：{key}\n{text}" if ok else f"❌ 未找到：{key}")


@dp.message(Command("botadd"))
async def cmd_botadd(msg: Message, bot: Bot):
    conn, user, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=3)
    if len(parts) < 3:
        await msg.reply("用法：/botadd <key> <bot_token> [bot_username]")
        return
    _, key, token, *rest = parts
    username = rest[0].strip().lstrip("@") if rest else ""
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = dbm.widget_get(conn, key)
    if not widget:
        await msg.reply(f"❌ 未找到 key：{key}")
        return

    try:
        probe = Bot(token)
        me = await probe.get_me()
        username = username or (me.username or "")
    except Exception as e:
        await msg.reply(f"❌ 机器人 Token 验证失败：{e}")
        return

    owner_user_id = widget.get("owner_user_id")
    if owner_user_id is None:
        owner_user_id = int(user["telegram_user_id"])
    binding_id = dbm.bot_binding_add(conn, key, token, username, enabled=1, owner_user_id=int(owner_user_id))
    binding = dbm.bot_binding_get(conn, binding_id) or {
        "id": binding_id,
        "key": key,
        "bot_token": token,
        "bot_username": username,
        "enabled": 1,
        "owner_user_id": int(owner_user_id),
    }
    await activate_customer_bot_binding(binding, probe, start_polling=True)
    await msg.reply(
        f"✅ 已绑定客户机器人\nkey: {key}\nbot: @{username or '-'}\n"
        f"binding_id: {binding_id}\n提示：已开始轮询，不需要重启 tg_bot.py。"
    )


@dp.message(Command("botdel"))
async def cmd_botdel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/botdel <key> [bot_username]")
        return
    key = parts[1].strip()
    username = parts[2].strip().lstrip("@") if len(parts) >= 3 else ""
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return
    if not require_owned_key(conn, user, key):
        await msg.reply("Permission denied or key not found.")
        return
    rows = dbm.bot_binding_list(conn, key)
    if username:
        rows = [row for row in rows if (row.get("bot_username") or "") == username]
    for row in rows:
        await deactivate_customer_bot_binding(int(row["id"]))
    count = dbm.bot_binding_delete(conn, key, username)
    await msg.reply(f"✅ 已删除 {count} 个绑定" if count else "⚠️ 没有匹配的绑定")


@dp.message(Command("botls"))
async def cmd_botls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = _open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    parts = (msg.text or "").split(maxsplit=1)
    key = parts[1].strip() if len(parts) > 1 else ""
    if key:
        try:
            key = validate_key(key)
        except Exception as e:
            await msg.reply(explain_key_error(str(e)))
            return
        if not require_owned_key(conn, user, key):
            await msg.reply("Permission denied or key not found.")
            return
    elif not is_admin_user(user):
        await msg.reply("用法：/botls <key>")
        return
    rows = dbm.bot_binding_list(conn, key)
    if not rows:
        await msg.reply("（暂无客户机器人绑定）")
        return
    lines = ["🤖 客户机器人绑定："]
    for row in rows:
        status = "启用" if int(row.get("enabled") or 0) else "停用"
        lines.append(f"• {row['key']} -> @{row.get('bot_username') or '-'} #{row['id']} {status}")
    await msg.reply("\n".join(lines))


@dp.message(Command("qradd"))
async def cmd_qradd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3 or "|" not in parts[2]:
        await msg.reply("用法：/qradd <key> <标题>|<答案>")
        return
    key = parts[1].strip()
    title, answer = [x.strip() for x in parts[2].split("|", 1)]
    _, _, _, permission_error = _vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    if not title or not answer:
        await msg.reply("❌ 标题和答案不能为空")
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    if not dbm.widget_get(conn, key):
        await msg.reply(f"❌ 未找到 key：{key}")
        return
    current = dbm.quick_reply_list(conn, key, enabled_only=False)
    if len([x for x in current if int(x.get("enabled") or 0)]) >= 9:
        await msg.reply("❌ 每个 key 最多建议配置 9 个快速回复，请先删除不用的项")
        return
    reply_id = dbm.quick_reply_add(conn, key, title, answer, sort_order=len(current) + 1)
    await msg.reply(f"✅ 已添加快速回复 #{reply_id}\n{title}")


@dp.message(Command("qrls"))
async def cmd_qrls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/qrls <key>")
        return
    key = parts[1].strip()
    _, _, _, permission_error = _vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    rows = dbm.quick_reply_list(conn, key, enabled_only=False)
    if not rows:
        await msg.reply("（暂无快速回复）")
        return
    lines = [f"💬 {key} 快速回复："]
    for item in rows:
        status = "启用" if int(item.get("enabled") or 0) else "停用"
        lines.append(f"• #{item['id']} {item['title']}（{status}）")
    await msg.reply("\n".join(lines))


@dp.message(Command("qrdel"))
async def cmd_qrdel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("用法：/qrdel <key> <编号>")
        return
    key = parts[1].strip()
    try:
        reply_id = int(parts[2])
    except Exception:
        await msg.reply("❌ 编号必须是数字")
        return
    _, _, _, permission_error = _vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    count = dbm.quick_reply_delete(conn, key, reply_id)
    await msg.reply("✅ 已删除" if count else "⚠️ 没有找到对应快速回复")


@dp.message(Command("stats"))
async def cmd_stats(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/stats <key> [来源]")
        return
    key = parts[1].strip()
    source_code = parts[2].strip() if len(parts) >= 3 else ""
    _, _, _, permission_error = _vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    rows = dbm.stats_for_key(conn, key, source_code)
    if not rows:
        await msg.reply("（暂无统计）")
        return
    lines = [f"📊 {key} 来源统计："]
    for row in rows:
        lines.append(
            f"• {row['source_code']} / {row['channel']}: "
            f"点击 {row['clicks']}，会话 {row['sessions']}，有效 {row['valid']}，成交 {row['deal']}"
        )
    await msg.reply("\n".join(lines))


@dp.message(Command("statdel"))
async def cmd_statdel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/statdel <key> [来源]")
        return
    key = parts[1].strip()
    source_code = parts[2].strip() if len(parts) >= 3 else ""
    _, _, _, permission_error = _vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    count = dbm.stats_delete(conn, key, source_code)
    target = f"{key}/{source_code}" if source_code else key
    await msg.reply(f"✅ 已清理统计：{target}\n影响记录：{count}\n聊天记录和会话未删除。")


async def mark_current_session(msg: Message, mark: str) -> None:
    if not msg.message_thread_id or msg.chat.type != "supergroup":
        await msg.reply("❌ 此命令只能在客服会话话题内使用")
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    session_id = dbm.session_by_thread(conn, int(msg.chat.id), int(msg.message_thread_id))
    if not session_id:
        await msg.reply("❌ 未找到对应的客服会话")
        return
    marked_by = ""
    if msg.from_user:
        marked_by = (msg.from_user.full_name or msg.from_user.username or "").strip()
    ok = dbm.customer_mark_set(conn, session_id, mark, marked_by)
    if ok:
        await msg.reply("✅ 已标记有效客户" if mark == "valid" else "✅ 已标记成交客户")
    else:
        await msg.reply("❌ 标记失败")


@dp.message(Command("valid"))
async def cmd_valid(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    await mark_current_session(msg, "valid")


@dp.message(Command("deal"))
async def cmd_deal(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    await mark_current_session(msg, "deal")


@dp.callback_query()
async def handle_quick_reply_callback(call: CallbackQuery, bot: Bot):
    binding = binding_for_bot(bot)
    if not binding:
        return
    data = call.data or ""
    if not data.startswith("qr:"):
        return
    try:
        reply_id = int(data.split(":", 1)[1])
    except Exception:
        await call.answer("无效按钮", show_alert=False)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    reply = dbm.quick_reply_get(conn, reply_id)
    if not reply or reply.get("key") != binding["key"]:
        await call.answer("内容不存在", show_alert=False)
        return
    await call.message.answer(reply["answer"])
    await call.answer()


async def handle_customer_private_message(msg: Message, active_bot: Bot, binding: Dict[str, Any]) -> None:
    if msg.from_user and msg.from_user.is_bot:
        return
    if msg.chat.type not in {"private"}:
        return

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    key = binding["key"]
    widget = dbm.widget_get(conn, key)
    if not _widget_owner_enabled(conn, widget):
        await msg.answer("客服入口暂不可用。")
        return

    visitor_id = str(msg.from_user.id if msg.from_user else msg.chat.id)
    source_code = dbm.source_click_latest(conn, key, "telegram", visitor_id)
    session = dbm.session_find_customer(conn, int(binding["id"]), int(msg.chat.id))
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
    if not session:
        await msg.answer("创建客服会话失败，请稍后再试。")
        return

    thread_id = await ensure_support_thread(conn, session, widget)
    forum_chat_id = int(widget["forum_chat_id"])
    from_label = msg.from_user.full_name if msg.from_user else "Telegram 客户"

    if msg.text:
        text = msg.text.strip()
        if text.startswith("/"):
            await msg.answer("请直接发送咨询内容，或使用 /start 查看常见问题。")
            return
        dbm.event_add(conn, session["session_id"], role="user", kind="text", text=text)
        await send_support_text(forum_chat_id, thread_id, text, label=f"{from_label}（TG）")
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
        dbm.media_asset_upsert(conn, session["session_id"], file_id, kind, local_path, ttl_seconds=MEDIA_TTL_SECONDS)
        await send_support_media(forum_chat_id, thread_id, kind, local_path, caption=caption)
        await msg.answer("已转人工客服，请稍等。")
    except Exception as exc:
        await msg.answer(f"媒体转发失败，请改用文字描述。错误：{exc}")


# =============== /end 命令（结束会话） ===============

@dp.message(Command("end"))
async def cmd_end(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    if not msg.message_thread_id:
        await msg.reply("❌ 此命令只能在客服话题内使用")
        return
    if msg.chat.type != "supergroup":
        await msg.reply("❌ 此命令只能在超级群话题内使用")
        return

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)

    session_id = dbm.session_by_thread(conn, int(msg.chat.id), int(msg.message_thread_id))
    if not session_id:
        await msg.reply("❌ 未找到对应的客服会话")
        return

    topic_deleted = False
    topic_error = ""
    try:
        try:
            await bot.delete_forum_topic(chat_id=msg.chat.id, message_thread_id=msg.message_thread_id)
        except Exception:
            await bot.close_forum_topic(chat_id=msg.chat.id, message_thread_id=msg.message_thread_id)
        topic_deleted = True
    except Exception as e:
        topic_error = str(e)

    deleted_count = delete_session_record_and_media(conn, session_id, PUBLIC_ROOT)

    if topic_deleted:
        await msg.reply(
            f"✅ 会话已结束\n"
            f"• 已删除/关闭客服群话题\n"
            f"• 已删除数据库记录\n"
            f"• 已删除 {deleted_count} 个媒体文件"
        )
    else:
        await msg.reply(
            f"⚠️ 会话数据已删除，但删除/关闭话题失败：{topic_error}\n"
            f"• 已删除数据库记录\n"
            f"• 已删除 {deleted_count} 个媒体文件\n"
            f"请手动删除或关闭话题"
        )


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

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
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
        except Exception as e:
            print(f"下载媒体失败: {m['file_id']}, {e}")

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

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)

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
        except Exception as e:
            print(f"下载图片失败: {e}")
    elif msg.video:
        v = msg.video
        file_id = v.file_id
        kind = "video"
        try:
            local_path = await save_webchat_media(file_id, v.file_unique_id)
        except Exception as e:
            print(f"下载视频失败: {e}")
    elif msg.document:
        d = msg.document
        file_id = d.file_id
        kind = "document"
        try:
            local_path = await save_webchat_media(file_id, d.file_unique_id)
        except Exception as e:
            print(f"下载文档失败: {e}")

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


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("WEBCHAT_BOT_TOKEN not set")
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    for binding in dbm.bot_binding_list(conn, enabled_only=True):
        token = binding.get("bot_token") or ""
        if not token or token == BOT_TOKEN:
            continue
        try:
            customer_bot = Bot(token)
            me = await customer_bot.get_me()
            binding["bot_username"] = binding.get("bot_username") or (me.username or "")
            await activate_customer_bot_binding(binding, customer_bot, start_polling=True)
            print(f"Loaded customer bot @{binding.get('bot_username') or me.username or binding['id']} for key={binding['key']}")
        except Exception as exc:
            print(f"Load customer bot failed: key={binding.get('key')}, id={binding.get('id')}, error={exc}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
