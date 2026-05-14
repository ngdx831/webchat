import contextlib
from typing import Any, Dict

from aiogram import Bot, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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
    open_user_context_from_telegram_user,
    require_enabled_user,
    user_display_role,
    widget_owner_enabled,
    widget_owner_has_vip_features,
)
from ..customer_bots import binding_for_bot, is_main_bot
from ..key_management_ui import (
    format_kls_rows,
    key_list_keyboard,
)
from ..runtime import dp
from ..validators import validate_source_code


def _start_inline_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="➕ 创建 key", callback_data="start:keyadd"),
            InlineKeyboardButton(text="🗂 管理 key", callback_data="start:kls"),
        ],
        [InlineKeyboardButton(text="❓ 帮助", callback_data="start:help")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 管理员命令", callback_data="start:adminhelp")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _main_start_text(user, help_link: str, is_admin: bool) -> str:
    role = user_display_role(user) if user else "normal"
    lines = [
        "👋 欢迎使用网页客服系统后台机器人。",
        f"你的角色：{role}",
        "",
        "常用命令：",
        "  /keyadd <key> <显示名> - 创建客服入口",
        "  /kls - 查看并管理你的 key",
        "  /kstatus - 切换上/下班状态",
        "  /help - 查看完整命令列表",
    ]
    if is_admin:
        lines += [
            "  /adminhelp - 管理员命令",
        ]
    if help_link:
        lines += ["", f"📎 帮助文档：{help_link}"]
    return "\n".join(lines)


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

    is_admin = is_admin_user(user)
    help_link = dbm.setting_get(conn, "help_link", "")
    await msg.reply(
        _main_start_text(user, help_link, is_admin),
        reply_markup=_start_inline_keyboard(is_admin),
    )


async def customer_cmd_start(msg: Message, command: CommandObject, active_bot: Bot, binding: Dict[str, Any]) -> None:
    """客户机器人 /start：只显示该 key 的欢迎语 + 快捷回复按钮。

    要求（来自需求 #13）：暂时不显示其他消息（不展示 help_link / 提示行）。
    离线时按 #10 的语义：先欢迎语，再下班留言。
    """
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

        replies = (
            dbm.quick_reply_list(conn, key)
            if widget_owner_has_vip_features(conn, widget)
            else []
        )
        welcome_text = (widget or {}).get("welcome_text") or ""
        offline_msg = (widget or {}).get("offline_msg") or ""
        enabled = int((widget or {}).get("enabled") or 0)
        display_name = (widget or {}).get("display_name") or key

    keyboard = None
    if replies:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=item["title"], callback_data=f"qr:{item['id']}")]
                for item in replies[:9]
            ]
        )

    text_parts = []
    if welcome_text:
        text_parts.append(welcome_text)
    else:
        text_parts.append(display_name)
    if enabled == 0 and offline_msg:
        text_parts.append(offline_msg)

    await active_bot.send_message(
        chat_id=msg.chat.id,
        text="\n\n".join(text_parts),
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
    await msg.reply(_help_text(conn, user))


def _help_text(conn, user) -> str:
    lines = [
        "用户命令：",
        *command_help_lines(USER_COMMANDS),
    ]
    if is_vip_or_admin(user):
        lines += ["", "VIP/管理员命令：", *command_help_lines(VIP_COMMANDS)]
    if is_admin_user(user):
        lines += ["", "管理员命令：/adminhelp - 查看管理员命令说明"]
    help_link = dbm.setting_get(conn, "help_link", "")
    if help_link:
        lines += ["", f"📎 帮助文档：{help_link}"]
    return "\n".join(lines)


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
    await msg.reply(_adminhelp_text())


def _adminhelp_text() -> str:
    return (
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


# ===== /start 内联按钮回调 =====

@dp.callback_query(F.data.startswith("start:"))
async def handle_start_callback(call: CallbackQuery, bot: Bot):
    if not is_main_bot(bot):
        return
    action = (call.data or "").split(":", 1)[1] if call.data else ""
    conn, user = open_user_context_from_telegram_user(call.from_user)
    if not require_enabled_user(user):
        await call.answer("账号已禁用，请联系管理员。", show_alert=True)
        return

    if action == "keyadd":
        if not call.message or getattr(getattr(call.message, "chat", None), "type", "") != "private":
            await call.answer("请在主机器人私聊中操作。", show_alert=True)
            return
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            "await_keyadd",
            key="",
            ttl_seconds=300,
        )
        await call.message.answer(
            "请在 5 分钟内按格式发送：\n"
            "<key>|<显示名>\n\n"
            "示例：mystore|我的小店"
        )
        await call.answer("已进入创建 key 流程")
        return

    if action == "kls":
        rows = dbm.widget_list_by_owner(conn, int(user["telegram_user_id"]), limit=200)
        target_user_id = int(user["telegram_user_id"])
        if not call.message:
            await call.answer("当前消息不可操作。", show_alert=True)
            return
        await call.message.answer(
            format_kls_rows(target_user_id, rows),
            reply_markup=key_list_keyboard(rows),
        )
        await call.answer()
        return

    if action == "help":
        if not call.message:
            await call.answer("当前消息不可操作。", show_alert=True)
            return
        await call.message.answer(_help_text(conn, user))
        await call.answer()
        return

    if action == "adminhelp":
        if not is_admin_user(user):
            await call.answer("没有权限。", show_alert=True)
            return
        if not call.message:
            await call.answer("当前消息不可操作。", show_alert=True)
            return
        await call.message.answer(_adminhelp_text())
        await call.answer()
        return

    await call.answer("未知操作", show_alert=False)
