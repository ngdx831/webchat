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


def format_key_info_text(widget) -> str:
    key = widget["key"]
    status = "在线" if int(widget.get("enabled") or 0) else "离线"
    return (
        f"key：{key}\n"
        f"显示名：{widget.get('display_name') or ''}\n"
        f"客服群 ID：{widget.get('forum_chat_id')}\n"
        f"状态：{status}\n"
        f"网页入口：{chat_address_for_key(key)}\n"
        f"挂件地址：{widget_address_for_key(key)}"
    )


def key_actions_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="绑定机器人", callback_data=f"km:bot:{key}")],
            [InlineKeyboardButton(text="绑定客服群", callback_data=f"km:grp:{key}")],
            [InlineKeyboardButton(text="管理自动回复", callback_data=f"km:qr:{key}")],
        ]
    )


def key_list_keyboard(rows, limit: int = 50) -> InlineKeyboardMarkup | None:
    buttons = []
    for row in list(rows or [])[:limit]:
        key = row["key"]
        buttons.append([InlineKeyboardButton(text=f"管理 {key}", callback_data=f"km:open:{key}")])
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def quick_reply_management_text(key: str, rows) -> str:
    lines = [f"{key} 自动回复管理"]
    if rows:
        for item in rows:
            status = "启用" if int(item.get("enabled") or 0) else "停用"
            lines.append(f"#{item['id']} {item['title']}（{status}）")
    else:
        lines.append("暂无自动回复。")
    lines.append("")
    lines.append("可使用下方按钮添加、删除或刷新。")
    return "\n".join(lines)


def quick_reply_management_keyboard(key: str, rows) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="添加自动回复", callback_data=f"qrm:add:{key}")]]
    for item in list(rows or [])[:20]:
        title = _short_title(str(item.get("title") or ""))
        buttons.append([
            InlineKeyboardButton(
                text=f"删除 #{item['id']} {title}",
                callback_data=f"qrm:del:{key}:{item['id']}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="刷新", callback_data=f"qrm:refresh:{key}"),
        InlineKeyboardButton(text="返回KEY操作", callback_data=f"qrm:back:{key}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
