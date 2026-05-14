from typing import Any, Dict, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _short_title(title: str, limit: int = 18) -> str:
    value = (title or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit - 1] + "..."


def widget_address_for_key(key: str) -> str:
    return f"/widget/{key}"


def chat_address_for_key(key: str) -> str:
    return f"/{key}"


def format_key_info_text(widget: Dict[str, Any], bindings: Optional[List[Dict[str, Any]]] = None) -> str:
    key = widget["key"]
    status = "🟢 在线" if int(widget.get("enabled") or 0) else "🔴 离线"
    welcome = (widget.get("welcome_text") or "").strip() or "（未设置）"
    offline_msg = (widget.get("offline_msg") or "").strip() or "（未设置）"
    bind_lines: List[str] = []
    if bindings:
        for b in bindings:
            uname = b.get("bot_username") or "-"
            bind_lines.append(f"  • @{uname}")
    elif bindings is not None:
        bind_lines.append("  （未绑定客户机器人）")
    lines = [
        f"key：{key}",
        f"显示名：{widget.get('display_name') or ''}",
        f"客服群 ID：{widget.get('forum_chat_id')}",
        f"状态：{status}",
        f"网页入口：{chat_address_for_key(key)}",
        f"挂件地址：{widget_address_for_key(key)}",
        "",
        f"📝 欢迎语：{welcome}",
        f"🛌 下班留言：{offline_msg}",
    ]
    if bind_lines:
        lines.append("🤖 已绑定客户机器人：")
        lines.extend(bind_lines)
    return "\n".join(lines)


def key_actions_keyboard(key: str, bindings: Optional[List[Dict[str, Any]]] = None) -> InlineKeyboardMarkup:
    """key 详情下的操作菜单。若已绑定客户机器人，则显示「解绑机器人」入口。"""
    has_binding = bool(bindings)
    rows: List[List[InlineKeyboardButton]] = []
    if has_binding:
        rows.append([InlineKeyboardButton(text="🔓 解绑机器人", callback_data=f"km:botdel:{key}")])
    else:
        rows.append([InlineKeyboardButton(text="🤖 绑定机器人", callback_data=f"km:bot:{key}")])
    rows.append([InlineKeyboardButton(text="👥 绑定客服群", callback_data=f"km:grp:{key}")])
    rows.append([InlineKeyboardButton(text="📝 欢迎语", callback_data=f"km:welc:{key}")])
    rows.append([InlineKeyboardButton(text="🛌 下班留言", callback_data=f"km:off:{key}")])
    rows.append([InlineKeyboardButton(text="🔁 自动回复", callback_data=f"km:qr:{key}")])
    rows.append([InlineKeyboardButton(text="⬅️ 返回 key 列表", callback_data="km:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def key_list_keyboard(rows, limit: int = 50) -> Optional[InlineKeyboardMarkup]:
    buttons = []
    for row in list(rows or [])[:limit]:
        key = row["key"]
        buttons.append([InlineKeyboardButton(text=f"管理 {key}", callback_data=f"km:open:{key}")])
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_kls_rows(target_user_id: int, rows) -> str:
    if not rows:
        return f"用户 {target_user_id} 暂无 key。\n可用 /keyadd <key> <显示名> 创建。"
    lines = [f"用户 {target_user_id} 的 key："]
    for row in rows:
        status = "🟢" if int(row.get("enabled") or 0) else "🔴"
        lines.append(f"{status} {row['key']}: {row.get('display_name') or ''}")
    lines.append("")
    lines.append("点下方按钮进入对应 key 的管理菜单。")
    return "\n".join(lines)


def quick_reply_management_text(key: str, rows) -> str:
    lines = [f"📝 {key} 自动回复管理"]
    if rows:
        for item in rows:
            status = "启用" if int(item.get("enabled") or 0) else "停用"
            title = (item.get("title") or "").strip()
            lines.append(f"• {title}（{status}）")
    else:
        lines.append("暂无自动回复。")
    lines.append("")
    lines.append("点条目可编辑/删除；点添加可新增。")
    return "\n".join(lines)


def quick_reply_management_keyboard(key: str, rows) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ 添加自动回复", callback_data=f"qrm:add:{key}")]
    ]
    for item in list(rows or [])[:20]:
        title = _short_title(str(item.get("title") or ""))
        buttons.append([
            InlineKeyboardButton(
                text=f"✏️ {title}",
                callback_data=f"qrm:open:{key}:{item['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="🔄 刷新", callback_data=f"qrm:refresh:{key}"),
        InlineKeyboardButton(text="⬅️ 返回", callback_data=f"qrm:back:{key}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def quick_reply_item_text(key: str, item: Dict[str, Any]) -> str:
    status = "启用" if int(item.get("enabled") or 0) else "停用"
    return (
        f"📝 {key} · 自动回复\n"
        f"标题：{item.get('title') or ''}\n"
        f"答案：{item.get('answer') or ''}\n"
        f"状态：{status}"
    )


def quick_reply_item_keyboard(key: str, reply_id: int, enabled: int) -> InlineKeyboardMarkup:
    toggle_label = "停用" if int(enabled) else "启用"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ 改标题", callback_data=f"qrm:editt:{key}:{reply_id}"),
            InlineKeyboardButton(text="✏️ 改答案", callback_data=f"qrm:edita:{key}:{reply_id}"),
        ],
        [
            InlineKeyboardButton(text=f"🔁 {toggle_label}", callback_data=f"qrm:toggle:{key}:{reply_id}"),
            InlineKeyboardButton(text="🗑 删除", callback_data=f"qrm:del:{key}:{reply_id}"),
        ],
        [InlineKeyboardButton(text="⬅️ 返回", callback_data=f"qrm:refresh:{key}")],
    ])
