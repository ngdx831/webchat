from aiogram import Bot
from aiogram.filters import Command
from aiogram.types import Message

import db as dbm

from ..auth import (
    is_admin_user,
    open_user_context,
    require_enabled_user,
    require_owned_key,
)
from ..customer_bots import is_main_bot
from ..key_management_ui import key_actions_keyboard, key_list_keyboard
from ..runtime import dp
from ..validators import explain_key_error, validate_key
from .admin_users import _admin_context_or_reply


def _resolve_kls_target_user_id(text: str, user) -> tuple[int | None, str]:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return int(user["telegram_user_id"]), ""
    if not is_admin_user(user):
        return None, "没有权限。普通用户请直接发送 /kls 查看自己的 key。"
    try:
        return int(parts[1].strip()), ""
    except Exception:
        return None, "用法：/kls [telegram_user_id]"


def _format_kls_rows(target_user_id: int, rows) -> str:
    if not rows:
        return f"用户 {target_user_id} 暂无 key。"
    lines = [f"用户 {target_user_id} 的 key："]
    for row in rows:
        status = "在线" if int(row.get("enabled") or 0) else "离线"
        lines.append(f"- {row['key']}: {row.get('display_name') or ''} {status}")
    return "\n".join(lines)


@dp.message(Command("kadd"))
async def cmd_kadd(msg: Message, bot: Bot):
    conn, user, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await msg.reply("用法：/kadd <key> <客服群ID> <显示名>")
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
        await msg.reply("客服群 ID 必须是数字，例如 -1001234567890。")
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
        await msg.reply(
            f"已配置 key：{key}\n客服群 ID：{forum_chat_id}\n显示名：{display_name}",
            reply_markup=key_actions_keyboard(key),
        )
    except Exception as e:
        await msg.reply(f"key 配置失败：{e}")


@dp.message(Command("kdel"))
async def cmd_kdel(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/kdel <key>")
        return

    try:
        key = validate_key(parts[1].strip())
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    from ..customer_bots import deactivate_customer_bot_binding

    for row in dbm.bot_binding_list(conn, key):
        await deactivate_customer_bot_binding(int(row["id"]))
    dbm.bot_binding_delete(conn, key)
    deleted = dbm.widget_del(conn, key)
    await msg.reply(f"已删除 key：{key}" if deleted else f"key 不存在：{key}")


@dp.message(Command("kls"))
async def cmd_kls(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    target_user_id, error = _resolve_kls_target_user_id(msg.text or "", user)
    if error:
        await msg.reply(error)
        return
    if target_user_id is None:
        await msg.reply("用法：/kls [telegram_user_id]")
        return
    if target_user_id != int(user["telegram_user_id"]) and not dbm.user_get(conn, target_user_id):
        await msg.reply(f"用户不存在：{target_user_id}")
        return
    rows = dbm.widget_list_by_owner(conn, target_user_id, limit=200)
    await msg.reply(_format_kls_rows(target_user_id, rows), reply_markup=key_list_keyboard(rows))


@dp.message(Command("koff"))
async def cmd_koff(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await msg.reply("用法：/koff <key> [离线提示]")
        return

    key = parts[1].strip()
    custom = parts[2].strip() if len(parts) >= 3 else ""
    try:
        key = validate_key(key)
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = require_owned_key(conn, user, key)
    if not widget:
        await msg.reply("没有权限，或 key 不存在。")
        return

    display_name = widget.get("display_name") or key
    msg_text = custom or f"{display_name} 当前离线，请先留言。"
    ok = dbm.widget_set_enabled(conn, key, 0, msg_text)
    await msg.reply(f"key 已离线：{key}\n提示：{msg_text}" if ok else f"key 不存在：{key}")


@dp.message(Command("kon"))
async def cmd_kon(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/kon <key>")
        return

    try:
        key = validate_key(parts[1].strip())
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    if not require_owned_key(conn, user, key):
        await msg.reply("没有权限，或 key 不存在。")
        return
    ok = dbm.widget_set_enabled(conn, key, 1, None)
    await msg.reply(f"key 已在线：{key}" if ok else f"key 不存在：{key}")


@dp.message(Command("kmsg"))
async def cmd_kmsg(msg: Message, bot: Bot):
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.reply("用法：/kmsg <key> <离线提示>")
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
        await msg.reply("没有权限，或 key 不存在。")
        return
    ok = dbm.widget_set_offline_msg(conn, key, text)
    await msg.reply(f"已更新离线提示：{key}\n{text}" if ok else f"key 不存在：{key}")
