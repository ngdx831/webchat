from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

import db as dbm

from ..auth import (
    is_admin_user,
    open_user_context,
    require_enabled_user,
)
from ..customer_bots import deactivate_customer_bot_binding, is_main_bot
from ..runtime import dp
from ..validators import explain_key_error, validate_key


async def _admin_context_or_reply(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return None, None, False
    conn, user = open_user_context(msg)
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
