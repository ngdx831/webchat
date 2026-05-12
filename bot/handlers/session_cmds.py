from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

import db as dbm
from config import DB_PATH
from shared.session_cleanup import delete_session_record_and_media

from shared.errors import scrub_secrets

from ..auth import is_admin_user, open_user_context, require_owned_key
from ..customer_bots import is_main_bot
from ..media import PUBLIC_ROOT
from ..runtime import dp


def _resolve_session_owned(msg: Message):
    """返回 (conn, session_id, error_text)。error_text 非空时表示无权限或环境不对。"""
    if not msg.message_thread_id or msg.chat.type != "supergroup":
        return None, None, "❌ 此命令只能在客服会话话题内使用"

    conn, user = open_user_context(msg)
    session_id = dbm.session_by_thread(conn, int(msg.chat.id), int(msg.message_thread_id))
    if not session_id:
        return conn, None, "❌ 未找到对应的客服会话"

    session = dbm.session_get(conn, session_id)
    key = (session or {}).get("key") or ""
    # admin 始终放行;否则要求当前用户拥有该 key。
    if not is_admin_user(user) and not require_owned_key(conn, user, key):
        return conn, None, "❌ 你没有权限操作此会话"

    return conn, session_id, ""


async def mark_current_session(msg: Message, mark: str) -> None:
    conn, session_id, err = _resolve_session_owned(msg)
    if err:
        await msg.reply(err)
        return
    marked_by = ""
    if msg.from_user:
        marked_by = (msg.from_user.full_name or msg.from_user.username or "").strip()
    ok = dbm.customer_mark_set(conn, session_id, mark, marked_by)
    if ok:
        await msg.reply("✅ 已标记有效客户" if mark == "valid" else "✅ 已标记成交客户")
    else:
        await msg.reply("❌ 标记失败")


@dp.message(Command("valid"))
async def cmd_valid(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    await mark_current_session(msg, "valid")


@dp.message(Command("deal"))
async def cmd_deal(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    await mark_current_session(msg, "deal")


@dp.message(Command("end"))
async def cmd_end(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    if not msg.message_thread_id:
        await msg.reply("❌ 此命令只能在客服话题内使用")
        return
    if msg.chat.type != "supergroup":
        await msg.reply("❌ 此命令只能在超级群话题内使用")
        return

    conn, session_id, err = _resolve_session_owned(msg)
    if err:
        await msg.reply(err)
        return

    topic_deleted = False
    topic_error = ""
    try:
        try:
            await bot.delete_forum_topic(chat_id=msg.chat.id, message_thread_id=msg.message_thread_id)
        except Exception:
            await bot.close_forum_topic(chat_id=msg.chat.id, message_thread_id=msg.message_thread_id)
        topic_deleted = True
    except Exception as e:
        topic_error = scrub_secrets(str(e))

    deleted_count = delete_session_record_and_media(conn, session_id, PUBLIC_ROOT)

    if topic_deleted:
        await msg.reply(
            f"✅ 会话已结束\n"
            f"• 已删除/关闭客服群话题\n"
            f"• 已删除数据库记录\n"
            f"• 已删除 {deleted_count} 个媒体文件"
        )
    else:
        await msg.reply(
            f"⚠️ 会话数据已删除，但删除/关闭话题失败：{topic_error}\n"
            f"• 已删除数据库记录\n"
            f"• 已删除 {deleted_count} 个媒体文件\n"
            f"请手动删除或关闭话题"
        )
