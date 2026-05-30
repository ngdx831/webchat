from typing import Any, Dict

from aiogram import Bot, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db as dbm

from ..auth import (
    is_admin_user,
    key_limit_for_role,
    open_user_context,
    open_user_context_from_callback,
    require_enabled_user,
    require_owned_key,
    user_display_role,
)
from ..customer_bots import deactivate_customer_bot_binding, is_main_bot
from ..key_management_ui import format_key_info_text, key_actions_keyboard
from ..runtime import dp
from ..validators import explain_key_error, validate_key


@dp.message(Command("keyadd"))
async def cmd_keyadd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("用法：/keyadd <key> <显示名>")
        return

    key = parts[1].strip()
    display_name = parts[2].strip()[:120]
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    limit = key_limit_for_role(str(user.get("role") or ""))
    owner_user_id = int(user["telegram_user_id"])
    if limit is not None and dbm.widget_count_by_owner(conn, owner_user_id) >= limit:
        await msg.reply(f"当前角色 {user_display_role(user)} 的 key 数量已达上限：{limit}")
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
            await msg.reply(f"key 已存在：{key}")
            return
        raise
    bindings = dbm.bot_binding_list(conn, key)
    await msg.reply(
        f"已创建 key：{key}\n显示名：{display_name}",
        reply_markup=key_actions_keyboard(key, bindings),
    )


@dp.message(Command("keyinfo"))
async def cmd_keyinfo(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/keyinfo <key>")
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
    widget["work_schedule"] = dbm.widget_get_work_schedule(conn, key)
    bindings = dbm.bot_binding_list(conn, key)
    await msg.reply(
        format_key_info_text(widget, bindings),
        reply_markup=key_actions_keyboard(key, bindings),
    )


@dp.message(Command("keydel"))
async def cmd_keydel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/keydel <key>")
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
    for row in dbm.bot_binding_list(conn, key):
        await deactivate_customer_bot_binding(int(row["id"]))
    dbm.bot_binding_delete(conn, key)
    deleted = dbm.widget_del(conn, key)
    await msg.reply(f"已删除 key：{key}" if deleted else f"key 不存在：{key}")
