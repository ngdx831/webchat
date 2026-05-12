from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import db as dbm
from config import DB_PATH

from ..auth import vip_key_context
from ..customer_bots import binding_for_bot, is_main_bot
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
    _, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    if not title or not answer:
        await msg.reply("❌ 标题和答案不能为空")
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    if not dbm.widget_get(conn, key):
        await msg.reply(f"❌ 未找到 key：{key}")
        return
    current = dbm.quick_reply_list(conn, key, enabled_only=False)
    if len([x for x in current if int(x.get("enabled") or 0)]) >= 9:
        await msg.reply("❌ 每个 key 最多建议配置 9 个快速回复，请先删除不用的项")
        return
    reply_id = dbm.quick_reply_add(conn, key, title, answer, sort_order=len(current) + 1)
    await msg.reply(f"✅ 已添加快速回复 #{reply_id}\n{title}")


@dp.message(Command("qrls"))
async def cmd_qrls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/qrls <key>")
        return
    key = parts[1].strip()
    _, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    rows = dbm.quick_reply_list(conn, key, enabled_only=False)
    if not rows:
        await msg.reply("（暂无快速回复）")
        return
    lines = [f"💬 {key} 快速回复："]
    for item in rows:
        status = "启用" if int(item.get("enabled") or 0) else "停用"
        lines.append(f"• #{item['id']} {item['title']}（{status}）")
    await msg.reply("\n".join(lines))


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
    _, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    count = dbm.quick_reply_delete(conn, key, reply_id)
    await msg.reply("✅ 已删除" if count else "⚠️ 没有找到对应快速回复")


@dp.callback_query()
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
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    reply = dbm.quick_reply_get(conn, reply_id)
    if not reply or reply.get("key") != binding["key"]:
        await call.answer("内容不存在", show_alert=False)
        return
    await call.message.answer(reply["answer"])
    await call.answer()
