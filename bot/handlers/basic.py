import contextlib
from typing import Any, Dict

from aiogram import Bot
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import db as dbm
from config import DB_PATH

from ..command_catalog import (
    ADMIN_COMMANDS,
    SESSION_COMMANDS,
    USER_COMMANDS,
    VIP_COMMANDS,
    command_help_lines,
)
from ..auth import (
    is_admin_user,
    is_vip_or_admin,
    open_user_context,
    require_enabled_user,
    user_display_role,
    widget_owner_enabled,
    widget_owner_has_vip_features,
)
from ..customer_bots import binding_for_bot, is_main_bot
from ..runtime import dp
from ..validators import validate_source_code


@dp.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject, bot: Bot):
    binding = binding_for_bot(bot)
    if binding:
        await customer_cmd_start(msg, command, bot, binding)
        return

    conn, user = open_user_context(msg)
    if user and not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    if is_admin_user(user):
        await msg.reply(
            "✅ 后台机器人已启动\n\n"
            "请使用 /adminhelp 查看管理员命令。\n\n"
            "常用管理命令：\n"
            "/kls - 查看并管理客服入口 key\n"
            "/kadd - 管理员添加或更新 key\n"
            "/botadd - 直接绑定客户机器人 Token\n"
            "/qrls - 查看和管理自动回复\n\n"
            "客服会话命令：\n"
            + "\n".join(command_help_lines(SESSION_COMMANDS))
        )
    else:
        await msg.reply("这是网页客服系统的后台机器人，不提供普通聊天功能。")


async def customer_cmd_start(msg: Message, command: CommandObject, active_bot: Bot, binding: Dict[str, Any]) -> None:
    key = binding["key"]
    source_code = validate_source_code(command.args or "")
    visitor_id = str(msg.from_user.id if msg.from_user else msg.chat.id)
    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        widget = dbm.widget_get(conn, key)
        if not widget_owner_enabled(conn, widget):
            await active_bot.send_message(chat_id=msg.chat.id, text="客服入口暂不可用。")
            return
        if source_code:
            dbm.source_click_add(conn, key, source_code, "telegram", visitor_id)

        replies = dbm.quick_reply_list(conn, key) if widget_owner_has_vip_features(conn, widget) else []
        help_link = dbm.setting_get(conn, "help_link", "")
        welcome_text = (widget or {}).get("welcome_text") or "请选择常见问题，或直接发送消息联系人工客服。"
    keyboard = None
    if replies:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=item["title"], callback_data=f"qr:{item['id']}")]
                for item in replies[:9]
            ]
        )
    text_lines = [welcome_text]
    if help_link:
        text_lines.extend(["", f"帮助：{help_link}"])
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
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return
    admin_contact = dbm.setting_get(conn, "admin_contact", "请联系管理员。")
    lines = [
        "用户命令：",
        *command_help_lines(USER_COMMANDS),
        f"管理员联系方式：{admin_contact}",
    ]
    if is_vip_or_admin(user):
        lines.extend([
            "",
            "VIP/管理员命令：",
            *command_help_lines(VIP_COMMANDS),
        ])
    if is_admin_user(user):
        lines.extend(["", "管理员命令：/adminhelp - 查看管理员命令说明"])
    await msg.reply("\n".join(lines))


@dp.message(Command("adminhelp"))
async def cmd_adminhelp(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return
    if not is_admin_user(user):
        await msg.reply("没有权限。")
        return
    await msg.reply(
        "管理员命令：\n"
        + "\n".join(command_help_lines(ADMIN_COMMANDS))
        + "\n\n客服会话命令：\n"
        + "\n".join(command_help_lines(SESSION_COMMANDS))
    )


@dp.message(Command("helplink"))
async def cmd_helplink(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return
    if not is_admin_user(user):
        await msg.reply("没有权限。")
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.reply("用法：/helplink <URL>")
        return
    value = parts[1].strip()
    dbm.setting_set(conn, "help_link", value)
    await msg.reply(f"帮助链接已更新：{value}")


@dp.message(Command("admincontact"))
async def cmd_admincontact(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return
    if not is_admin_user(user):
        await msg.reply("没有权限。")
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.reply("用法：/admincontact <联系方式>")
        return
    value = parts[1].strip()
    dbm.setting_set(conn, "admin_contact", value)
    await msg.reply(f"管理员联系方式已更新：{value}")


@dp.message(Command("myinfo"))
async def cmd_myinfo(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return
    rows = dbm.widget_list_by_owner(conn, int(user["telegram_user_id"]))
    lines = [
        "我的账号",
        f"id: {user['telegram_user_id']}",
        f"角色：{user_display_role(user)}",
        f"key 数量：{len(rows)}",
    ]
    if rows:
        lines.append("key 概览：")
        for row in rows:
            lines.append(f"- {row['key']}: {row.get('display_name') or ''}")
    await msg.reply("\n".join(lines))


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
