from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

import db as dbm
from config import DB_PATH

from ..auth import vip_key_context
from ..customer_bots import is_main_bot
from ..runtime import dp


@dp.message(Command("stats"))
async def cmd_stats(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/stats <key> [来源]")
        return
    key = parts[1].strip()
    source_code = parts[2].strip() if len(parts) >= 3 else ""
    conn, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    rows = dbm.stats_for_key(conn, key, source_code)
    if not rows:
        await msg.reply("（暂无统计）")
        return
    lines = [f"📊 {key} 来源统计："]
    for row in rows:
        lines.append(
            f"• {row['source_code']} / {row['channel']}: "
            f"点击 {row['clicks']}，会话 {row['sessions']}，有效 {row['valid']}，成交 {row['deal']}"
        )
    await msg.reply("\n".join(lines))


@dp.message(Command("statdel"))
async def cmd_statdel(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/statdel <key> [来源]")
        return
    key = parts[1].strip()
    source_code = parts[2].strip() if len(parts) >= 3 else ""
    conn, _, _, permission_error = vip_key_context(msg, key)
    if permission_error:
        await msg.reply(permission_error)
        return
    count = dbm.stats_delete(conn, key, source_code)
    target = f"{key}/{source_code}" if source_code else key
    await msg.reply(f"✅ 已清理统计：{target}\n影响记录：{count}\n聊天记录和会话未删除。")
