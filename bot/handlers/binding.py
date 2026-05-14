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
        await msg.reply("账号已禁用，请联系管理员。")
        return

    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        await msg.reply("请在主机器人私聊中发送 /tokenadd，避免 Token 泄露。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/tokenadd <key>")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("没有权限，或 key 不存在。")
        return

    dbm.pending_action_set(
        conn,
        int(user["telegram_user_id"]),
        "await_token",
        key=key,
        ttl_seconds=300,
    )
    await msg.reply(f"请在 5 分钟内发送 key `{key}` 对应的客户机器人 Token。")


@dp.message(Command("welcome"))
async def cmd_welcome(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return
    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        await msg.reply("请在主机器人私聊中发送 /welcome。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/welcome <key>")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("没有权限，或 key 不存在。")
        return

    dbm.pending_action_set(
        conn,
        int(user["telegram_user_id"]),
        "await_welcome",
        key=key,
        ttl_seconds=300,
    )
    await msg.reply(f"请在 5 分钟内发送 key `{key}` 的欢迎语。")


@dp.message(Command("groupbind"))
async def cmd_groupbind(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    if getattr(getattr(msg, "chat", None), "type", "") != "supergroup":
        await msg.reply("请在目标超级群里发送 /groupbind <key>。")
        return

    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/groupbind <key>")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("没有权限，或 key 不存在。")
        return

    chat_id = int(msg.chat.id)
    ok = dbm.widget_set_forum_chat_id(conn, key, chat_id)
    if not ok:
        await msg.reply("没有权限，或 key 不存在。")
        return
    await msg.reply(f"已绑定客服群\nkey：{key}\n客服群 ID：{chat_id}")
