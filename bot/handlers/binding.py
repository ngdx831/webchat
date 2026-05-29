from aiogram import Bot, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db as dbm

from ..auth import (
    open_user_context,
    open_user_context_from_callback,
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
    await msg.reply(f"✅ 客服群绑定成功\nkey: {key}\n客服群 ID: {chat_id}")


@dp.message(Command("groupunbind"))
async def cmd_groupunbind(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    if getattr(getattr(msg, "chat", None), "type", "") != "supergroup":
        await msg.reply("请在超级群内执行 /groupunbind <key>")
        return

    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/groupunbind <key>")
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

    current_fid = widget.get("forum_chat_id") or 0
    if not current_fid:
        await msg.reply(f"⚠️ key={key} 当前未绑定任何客服群")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ 确认解绑", callback_data=f"gu_c:{key}"),
        InlineKeyboardButton(text="❌ 取消", callback_data="gu_x"),
    ]])
    await msg.reply(
        f"确认解绑客服群？\nkey: {key}\n当前 forum_chat_id: {current_fid}",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data.startswith("gu_"))
async def cb_groupunbind(callback: CallbackQuery, bot: Bot):
    if not is_main_bot(bot):
        return
    data = callback.data or ""
    await callback.answer()

    if data == "gu_x":
        await callback.message.edit_text("❌ 已取消解绑")
        return

    if data.startswith("gu_c:"):
        key = data[len("gu_c:"):]
        conn, user = open_user_context_from_callback(callback)
        if not require_enabled_user(user):
            await callback.message.edit_text("账号已禁用，请联系管理员。")
            return
        try:
            key = validate_key(key)
        except Exception:
            await callback.message.edit_text("❌ 无效 key")
            return
        widget = require_owned_key(conn, user, key)
        if not widget:
            await callback.message.edit_text("❌ 权限不足")
            return
        dbm.widget_set_forum_chat_id(conn, key, 0)
        await callback.message.edit_text(f"✅ 客服群已解绑（key={key}）")
        return

    await callback.message.edit_text("❌ 未知操作")
