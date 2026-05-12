from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

import db as dbm

from ..auth import (
    open_user_context,
    require_enabled_user,
    require_owned_key,
)
from ..customer_bots import is_main_bot
from ..runtime import dp
from ..validators import explain_key_error, validate_key


@dp.message(Command("tokenadd"))
async def cmd_tokenadd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
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
    conn, user = open_user_context(msg)
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


@dp.message(Command("groupbind"))
async def cmd_groupbind(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    if getattr(getattr(msg, "chat", None), "type", "") != "supergroup":
        await msg.reply("Please run /groupbind <key> in a supergroup.")
        return

    conn, user = open_user_context(msg)
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
