import contextlib

from aiogram import Bot, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import db as dbm
from config import DB_PATH

from ..auth import vip_key_context
from ..customer_bots import binding_for_bot, is_main_bot
from ..key_management_ui import quick_reply_management_keyboard, quick_reply_management_text
from ..runtime import dp


@dp.message(Command("qradd"))
async def cmd_qradd(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3 or "|" not in parts[2]:
        await msg.reply("用法：/qradd <key> <标题>|<答案>")
        return
    key = parts[1].strip()
    title, answer = [x.strip() for x in parts[2].split("|", 1)]
    from config import MAX_RICH_TEXT_LENGTH
    title = title[:120]
    answer = answer[: int(MAX_RICH_TEXT_LENGTH)]
    conn, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    if not title or not answer:
        await msg.reply("❌ 标题和答案不能为空")
        return
    if not dbm.widget_get(conn, key):
        await msg.reply(f"❌ 未找到 key：{key}")
        return
    current = dbm.quick_reply_list(conn, key, enabled_only=False)
    if len([x for x in current if int(x.get("enabled") or 0)]) >= 9:
        await msg.reply("❌ 每个 key 最多建议配置 9 个自动回复，请先删除不用的项")
        return
    reply_id = dbm.quick_reply_add(conn, key, title, answer, sort_order=len(current) + 1)
    rows = dbm.quick_reply_list(conn, key, enabled_only=False)
    await msg.reply(
        f"✅ 已添加自动回复 #{reply_id}\n{title}",
        reply_markup=quick_reply_management_keyboard(key, rows),
    )


@dp.message(Command("qrls"))
async def cmd_qrls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/qrls <key>")
        return
    key = parts[1].strip()
    conn, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    rows = dbm.quick_reply_list(conn, key, enabled_only=False)
    if not rows:
        await msg.reply(
            "暂无自动回复。",
            reply_markup=quick_reply_management_keyboard(key, rows),
        )
        return
    await msg.reply(
        quick_reply_management_text(key, rows),
        reply_markup=quick_reply_management_keyboard(key, rows),
    )


@dp.message(Command("qrdel"))
async def cmd_qrdel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("用法：/qrdel <key> <编号>")
        return
    key = parts[1].strip()
    try:
        reply_id = int(parts[2])
    except Exception:
        await msg.reply("❌ 编号必须是数字")
        return
    conn, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    count = dbm.quick_reply_delete(conn, key, reply_id)
    rows = dbm.quick_reply_list(conn, key, enabled_only=False)
    await msg.reply(
        "✅ 已删除" if count else "⚠️ 没有找到对应自动回复",
        reply_markup=quick_reply_management_keyboard(key, rows),
    )


@dp.callback_query(F.data.startswith("qr:"))
async def handle_quick_reply_callback(call: CallbackQuery, bot: Bot):
    binding = binding_for_bot(bot)
    if not binding:
        return
    data = call.data or ""
    if not data.startswith("qr:"):
        return
    try:
        reply_id = int(data.split(":", 1)[1])
    except Exception:
        await call.answer("无效按钮", show_alert=False)
        return
    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        reply = dbm.quick_reply_get(conn, reply_id)
    if not reply or reply.get("key") != binding["key"]:
        await call.answer("内容不存在", show_alert=False)
        return
    await call.message.answer(reply["answer"])
    await call.answer()
