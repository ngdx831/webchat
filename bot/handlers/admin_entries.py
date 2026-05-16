from typing import List

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
from ..key_management_ui import format_kls_rows, key_actions_keyboard, key_list_keyboard
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


def _format_admin_key_panel(widget, owner, bindings) -> str:
    key = widget["key"]
    status = "online" if int(widget.get("enabled") or 0) else "offline"
    owner_line = "-"
    if owner:
        username = owner.get("username") or "-"
        owner_line = (
            f"{widget.get('owner_user_id')} @{username} "
            f"{owner.get('role') or ''} enabled={int(owner.get('enabled') or 0)}"
        )
    lines = [
        f"管理 key：{key}",
        f"显示名：{widget.get('display_name') or ''}",
        f"负责人：{owner_line}",
        f"客服群：{widget.get('forum_chat_id')}",
        f"状态：{status}",
        f"离线提示：{widget.get('offline_msg') or '-'}",
        f"欢迎语：{widget.get('welcome_text') or '-'}",
    ]
    if bindings:
        bot_lines = []
        for row in bindings:
            bot_status = "enabled" if int(row.get("enabled") or 0) else "disabled"
            bot_lines.append(f"#{row['id']} @{row.get('bot_username') or '-'} {bot_status}")
        lines.append("客户机器人：" + "；".join(bot_lines))
    else:
        lines.append("客户机器人：-")
    lines.extend([
        "",
        "常用操作：",
        f"/kstatus {key}",
        f"/botls {key}",
        f"/qrls {key}",
        f"/stats {key}",
        f"/adminkeyinfo {key}",
        f"/adminkeydel {key}",
    ])
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
        bindings = dbm.bot_binding_list(conn, key)
        await msg.reply(
            f"已配置 key：{key}\n客服群 ID：{forum_chat_id}\n显示名：{display_name}",
            reply_markup=key_actions_keyboard(key, bindings),
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
    await msg.reply(format_kls_rows(target_user_id, rows), reply_markup=key_list_keyboard(rows))


@dp.message(Command("xxx"))
async def cmd_xxx(msg: Message, bot: Bot):
    conn, _, ok = await _admin_context_or_reply(msg, bot)
    if not ok:
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("用法：/xxx <key>")
        return
    try:
        key = validate_key(parts[1].strip())
    except Exception as e:
        await msg.reply(explain_key_error(str(e)))
        return

    widget = dbm.widget_get(conn, key)
    if not widget:
        await msg.reply(f"key 不存在：{key}")
        return
    owner = dbm.user_get(conn, int(widget["owner_user_id"])) if widget.get("owner_user_id") is not None else None
    bindings = dbm.bot_binding_list(conn, key)
    await msg.reply(
        _format_admin_key_panel(widget, owner, bindings),
        reply_markup=key_actions_keyboard(key, bindings),
    )


# ===== /kstatus: 统一上/下班 =====

def _toggle_widget(conn, widget) -> tuple[bool, str]:
    """切换单个 widget 的 enabled 状态，返回 (新状态_是否在线, 显示名)。"""
    key = widget["key"]
    display_name = widget.get("display_name") or key
    current = int(widget.get("enabled") or 0)
    new_enabled = 0 if current else 1
    if new_enabled == 0:
        offline_msg = (widget.get("offline_msg") or "").strip()
        dbm.widget_set_enabled(conn, key, 0, offline_msg)
    else:
        dbm.widget_set_enabled(conn, key, 1, None)
    return bool(new_enabled), display_name


def _format_kstatus_lines(results: List[tuple[str, str, bool]]) -> str:
    out = []
    for key, display_name, online in results:
        label = "已上班" if online else "已下班"
        prefix = "🟢" if online else "🔴"
        out.append(f"{prefix} {key}（{display_name}） {label}")
    return "\n".join(out)


@dp.message(Command("kstatus"))
async def cmd_kstatus(msg: Message, bot: Bot):
    """切换上/下班状态。

    - 带 key 参数：仅对该 key 切换；管理员也只能切自己拥有的 key。
    - 无参数：对当前用户名下全部 key 统一切换（按多数决：多数在线则全部下班，否则全部上班）。
    """
    if not is_main_bot(bot):
        return
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return

    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        key = parts[1].strip()
        try:
            key = validate_key(key)
        except Exception as e:
            await msg.reply(explain_key_error(str(e)))
            return
        widget = require_owned_key(conn, user, key)
        if not widget or widget.get("owner_user_id") != int(user["telegram_user_id"]):
            await msg.reply("没有权限，或 key 不存在。")
            return
        online, display_name = _toggle_widget(conn, widget)
        await msg.reply(_format_kstatus_lines([(key, display_name, online)]))
        return

    owner_id = int(user["telegram_user_id"])
    widgets = dbm.widget_list_by_owner(conn, owner_id, limit=500)
    if not widgets:
        await msg.reply("你名下还没有 key。可用 /keyadd <key> <显示名> 创建。")
        return

    online_count = sum(1 for w in widgets if int(w.get("enabled") or 0))
    target_online = online_count <= (len(widgets) - online_count)  # 多数在线则统一下班；否则统一上班
    results: List[tuple[str, str, bool]] = []
    for widget in widgets:
        full = dbm.widget_get(conn, widget["key"])
        if not full or full.get("owner_user_id") != owner_id:
            continue
        if bool(int(full.get("enabled") or 0)) == target_online:
            results.append((full["key"], full.get("display_name") or full["key"], target_online))
            continue
        if target_online:
            dbm.widget_set_enabled(conn, full["key"], 1, None)
        else:
            offline_msg = (full.get("offline_msg") or "").strip()
            dbm.widget_set_enabled(conn, full["key"], 0, offline_msg)
        results.append((full["key"], full.get("display_name") or full["key"], target_online))

    header = "✅ 已统一上班" if target_online else "🛌 已统一下班"
    await msg.reply(header + "\n" + _format_kstatus_lines(results))
