from contextlib import suppress
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

import db as dbm

from .auth import open_user_context, require_enabled_user, require_owned_key
from .customer_bots import activate_customer_bot_binding, is_main_bot
from .validators import validate_key


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


async def handle_pending_action_message(msg: Message, bot: Bot) -> bool:
    if not is_main_bot(bot):
        return False
    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        return False
    if not getattr(msg, "from_user", None):
        return False

    conn, user = open_user_context(msg)
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
