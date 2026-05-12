from typing import Any, Dict

from aiogram import Bot
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import db as dbm
from config import DB_PATH

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
    if not widget_owner_enabled(conn, widget):
        await active_bot.send_message(chat_id=msg.chat.id, text="客服入口暂不可用。")
        return
    if source_code:
        dbm.source_click_add(conn, key, source_code, "telegram", visitor_id)

    replies = dbm.quick_reply_list(conn, key) if widget_owner_has_vip_features(conn, widget) else []
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
    conn, user = open_user_context(msg)
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
    conn, user = open_user_context(msg)
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
    conn, user = open_user_context(msg)
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
    conn, user = open_user_context(msg)
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


@dp.message(Command("myinfo"))
async def cmd_myinfo(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return
    rows = dbm.widget_list_by_owner(conn, int(user["telegram_user_id"]))
    lines = [
        "My account",
        f"id: {user['telegram_user_id']}",
        f"role: {user_display_role(user)}",
        f"keys: {len(rows)}",
    ]
    if rows:
        lines.append("key overview:")
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
