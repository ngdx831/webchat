from contextlib import suppress

from aiogram import Bot, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db as dbm

from ..auth import (
    is_admin_user,
    open_user_context,
    open_user_context_from_callback,
    require_enabled_user,
    require_owned_key,
)
from ..customer_bots import (
    activate_customer_bot_binding,
    deactivate_customer_bot_binding,
    is_main_bot,
)
from ..runtime import dp
from ..validators import explain_key_error, validate_key


@dp.message(Command("botadd"))
async def cmd_botadd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
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

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("没有权限，或 key 不存在。")
        return

    probe = Bot(token)
    try:
        me = await probe.get_me()
        username = username or (me.username or "")
    except Exception:
        # 不回显原始异常,token 可能在异常文本里。
        with suppress(Exception):
            await probe.session.close()
        await msg.reply("❌ 机器人 Token 验证失败,请检查 token 格式或网络。")
        return

    owner_user_id = widget.get("owner_user_id") or int(user["telegram_user_id"])
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
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
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
        await msg.reply("没有权限，或 key 不存在。")
        return
    rows = dbm.bot_binding_list(conn, key)
    if username:
        rows = [row for row in rows if (row.get("bot_username") or "") == username]
    if not rows:
        await msg.reply("⚠️ 没有匹配的绑定")
        return

    buttons = []
    for row in rows:
        uname = row.get("bot_username") or "-"
        bid = int(row["id"])
        status = "启用" if int(row.get("enabled") or 0) else "停用"
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ 解绑 @{uname}（#{bid} {status}）",
            callback_data=f"botdel_c:{key}:{bid}",
        )])
    if len(rows) > 1:
        buttons.append([InlineKeyboardButton(text="🗑️ 解绑全部", callback_data=f"botdel_all:{key}")])
    buttons.append([InlineKeyboardButton(text="❌ 取消", callback_data="botdel_x")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    target = f" @{username}" if username else ""
    await msg.reply(f"确认解绑 key={key}{target} 的客户机器人？", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("botdel_"))
async def cb_botdel(callback: CallbackQuery, bot: Bot):
    if not is_main_bot(bot):
        return
    data = callback.data or ""
    await callback.answer()

    if data == "botdel_x":
        await callback.message.edit_text("❌ 已取消解绑")
        return

    conn, user = open_user_context_from_callback(callback)
    if not require_enabled_user(user):
        await callback.message.edit_text("Account disabled.")
        return

    if data.startswith("botdel_all:"):
        key = data[len("botdel_all:"):]
        try:
            key = validate_key(key)
        except Exception:
            await callback.message.edit_text("❌ 无效 key")
            return
        if not require_owned_key(conn, user, key):
            await callback.message.edit_text("❌ 权限不足")
            return
        rows = dbm.bot_binding_list(conn, key)
        for row in rows:
            await deactivate_customer_bot_binding(int(row["id"]))
        count = dbm.bot_binding_delete(conn, key)
        await callback.message.edit_text(f"✅ 已解绑 {count} 个客户机器人（key={key}）")
        return

    if data.startswith("botdel_c:"):
        parts = data[len("botdel_c:"):].split(":", 1)
        if len(parts) != 2:
            await callback.message.edit_text("❌ 无效操作")
            return
        key, bid_str = parts
        try:
            key = validate_key(key)
            bid = int(bid_str)
        except Exception:
            await callback.message.edit_text("❌ 无效参数")
            return
        if not require_owned_key(conn, user, key):
            await callback.message.edit_text("❌ 权限不足")
            return
        await deactivate_customer_bot_binding(bid)
        count = dbm.bot_binding_delete_by_id(conn, bid)
        await callback.message.edit_text(
            f"✅ 已解绑 binding #{bid}（key={key}）" if count else f"⚠️ 未找到 binding #{bid}"
        )
        return

    await callback.message.edit_text("❌ 未知操作")


@dp.message(Command("botls"))
async def cmd_botls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
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
            await msg.reply("没有权限，或 key 不存在。")
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
