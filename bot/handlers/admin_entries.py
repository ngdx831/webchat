from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

import db as dbm
from config import DB_PATH

from ..auth import (
    open_user_context,
    require_enabled_user,
    require_owned_key,
)
from ..customer_bots import is_main_bot
from ..runtime import dp
from ..validators import explain_key_error, validate_key
from .admin_users import _admin_context_or_reply
from .user_keys import _key_info_text


@dp.message(Command("kadd"))
async def cmd_kadd(msg: Message, bot: Bot):
    conn, user, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await msg.reply("用法：/kadd <key> <forum_chat_id> <显示名>\n例：/kadd yaoyao -1001234567890 客服瑶瑶")
        return

    _, key, forum_chat_id_s, display_name = parts

    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    try:
        forum_chat_id = int(forum_chat_id_s)
    except Exception:
        await msg.reply("❌ forum_chat_id 必须是数字（例如 -100xxxxxxxxxxxx）")
        return

    existing_widget = dbm.widget_get(conn, key)
    owner_user_id = (
        int(existing_widget["owner_user_id"])
        if existing_widget and existing_widget.get("owner_user_id") is not None
        else int(user["telegram_user_id"])
    )
    try:
        dbm.widget_add(
            conn,
            key,
            forum_chat_id,
            display_name,
            must_not_exist=False,
            owner_user_id=owner_user_id,
        )
        await msg.reply(f"✅ 已设置\nkey: {key}\nforum_chat_id: {forum_chat_id}\n显示名: {display_name}")
    except Exception as e:
        await msg.reply(f"❌ 设置失败：{e}")


@dp.message(Command("kdel"))
async def cmd_kdel(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/kdel <key>\n例：/kdel yaoyao")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    from ..customer_bots import deactivate_customer_bot_binding
    for row in dbm.bot_binding_list(conn, key):
        await deactivate_customer_bot_binding(int(row["id"]))
    dbm.bot_binding_delete(conn, key)
    n = dbm.widget_del(conn, key)
    await msg.reply(f"✅ 已删除：{key}" if n else f"⚠️ 未找到：{key}")


@dp.message(Command("kls"))
async def cmd_kls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Use /myinfo to list your keys, or /keyinfo <key> for one key.")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("Permission denied or key not found.")
        return
    await msg.reply(_key_info_text(widget))
    return
    # 旧管理员路径（保留与原实现一致的不可达代码）
    if not msg.from_user:
        return

    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    rows = dbm.widget_list(conn, limit=200)

    if not rows:
        await msg.reply("（暂无配置）\n用 /kadd 添加：/kadd yaoyao -100xxx 客服瑶瑶")
        return

    lines = ["📌 当前 Widgets："]
    for r in rows:
        enabled = int(r.get("enabled", 1) or 0)
        st = "🟢在线" if enabled == 1 else "🔴离线"
        off = (r.get("offline_msg") or "").strip()
        if off:
            off = off.replace("\n", " ")
            if len(off) > 36:
                off = off[:36] + "…"
            off = f"｜{off}"
        lines.append(f"• {r['key']} -> {r['forum_chat_id']}（{r['display_name']}）{st}{off}")
    await msg.reply("\n".join(lines))


@dp.message(Command("koff"))
async def cmd_koff(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/koff <key> [离线提示]\n例：/koff yaoyao 瑶瑶已下班，请留言或联系@xxx")
        return

    key = parts[1].strip()
    custom = parts[2].strip() if len(parts) >= 3 else ""

    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    w = require_owned_key(conn, user, key)
    if not w:
        await msg.reply("Permission denied or key not found.")
        return

    display_name = w.get("display_name") or key
    msg_text = custom or f"{display_name}已下班，请留言，我们上班后会回复。"
    ok = dbm.widget_set_enabled(conn, key, 0, msg_text)
    await msg.reply(f"✅ 已下班：{key}\n提示：{msg_text}" if ok else f"❌ 操作失败：{key}")


@dp.message(Command("kon"))
async def cmd_kon(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/kon <key>\n例：/kon yaoyao")
        return

    key = parts[1].strip()
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    if not require_owned_key(conn, user, key):
        await msg.reply("Permission denied or key not found.")
        return
    ok = dbm.widget_set_enabled(conn, key, 1, None)
    await msg.reply(f"✅ 已上班：{key}" if ok else f"❌ 未找到：{key}")


@dp.message(Command("kmsg"))
async def cmd_kmsg(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("Account disabled. Please contact admin.")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("用法：/kmsg <key> <离线提示>\n例：/kmsg yaoyao 瑶瑶已下班，请联系@xxx")
        return

    key = parts[1].strip()
    from config import MAX_RICH_TEXT_LENGTH
    text = parts[2].strip()[: int(MAX_RICH_TEXT_LENGTH)]
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    if not require_owned_key(conn, user, key):
        await msg.reply("Permission denied or key not found.")
        return
    ok = dbm.widget_set_offline_msg(conn, key, text)
    await msg.reply(f"✅ 已更新：{key}\n{text}" if ok else f"❌ 未找到：{key}")
