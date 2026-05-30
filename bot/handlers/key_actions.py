from typing import Optional

from aiogram import Bot, F
from aiogram.types import CallbackQuery

import db as dbm

from ..auth import (
    is_vip_or_admin,
    open_user_context_from_telegram_user,
    require_enabled_user,
    require_owned_key,
)
from ..customer_bots import deactivate_customer_bot_binding, is_main_bot
from ..key_management_ui import (
    format_key_info_text,
    format_kls_rows,
    key_actions_keyboard,
    key_list_keyboard,
    key_schedule_keyboard,
    quick_reply_item_keyboard,
    quick_reply_item_text,
    quick_reply_management_keyboard,
    quick_reply_management_text,
)
from ..runtime import dp
from ..validators import explain_key_error, validate_key


async def _answer_error(call: CallbackQuery, text: str) -> None:
    await call.answer(text, show_alert=True)


async def _replace_or_send(call: CallbackQuery, text: str, reply_markup=None) -> None:
    if not call.message:
        await call.answer("当前消息不可操作，请重新发送命令。", show_alert=True)
        return
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await call.message.answer(text, reply_markup=reply_markup)


def _chat_type(call: CallbackQuery) -> str:
    return str(getattr(getattr(call.message, "chat", None), "type", "") or "")


def _chat_id(call: CallbackQuery) -> Optional[int]:
    chat = getattr(call.message, "chat", None)
    if not chat:
        return None
    return int(chat.id)


def _callback_key_context(call: CallbackQuery, key: str):
    conn, user = open_user_context_from_telegram_user(call.from_user)
    if not require_enabled_user(user):
        return conn, user, None, "账号已禁用，请联系管理员。"
    try:
        key = validate_key(key)
    except Exception as exc:
        return conn, user, None, explain_key_error(str(exc))
    widget = require_owned_key(conn, user, key)
    if not widget:
        return conn, user, None, "没有权限，或 key 不存在。"
    return conn, user, widget, ""


def _callback_vip_key_context(call: CallbackQuery, key: str):
    conn, user, widget, error = _callback_key_context(call, key)
    if error:
        return conn, user, widget, error
    if not is_vip_or_admin(user):
        return conn, user, widget, "自动回复是 VIP/管理员功能，请联系管理员开通。"
    return conn, user, widget, ""


async def _show_key_actions(call: CallbackQuery, conn, key: str) -> None:
    widget = dbm.widget_get(conn, key)
    if not widget:
        await _answer_error(call, "key 不存在。")
        return
    bindings = dbm.bot_binding_list(conn, key)
    await _replace_or_send(
        call,
        format_key_info_text(widget, bindings),
        reply_markup=key_actions_keyboard(key, bindings),
    )


async def _show_quick_reply_menu(call: CallbackQuery, conn, key: str) -> None:
    rows = dbm.quick_reply_list(conn, key, enabled_only=False)
    await _replace_or_send(
        call,
        quick_reply_management_text(key, rows),
        reply_markup=quick_reply_management_keyboard(key, rows),
    )


async def _show_quick_reply_item(call: CallbackQuery, conn, key: str, reply_id: int) -> bool:
    item = dbm.quick_reply_get(conn, reply_id)
    if not item or item.get("key") != key:
        await _answer_error(call, "自动回复不存在或已被删除。")
        return False
    await _replace_or_send(
        call,
        quick_reply_item_text(key, item),
        reply_markup=quick_reply_item_keyboard(key, reply_id, int(item.get("enabled") or 0)),
    )
    return True


async def _show_kls_list(call: CallbackQuery, conn, user_id: int) -> None:
    rows = dbm.widget_list_by_owner(conn, user_id, limit=200)
    await _replace_or_send(
        call,
        format_kls_rows(user_id, rows),
        reply_markup=key_list_keyboard(rows),
    )


@dp.callback_query(F.data.startswith("km:"))
async def handle_key_management_callback(call: CallbackQuery, bot: Bot):
    if not is_main_bot(bot):
        return
    data = call.data or ""
    parts = data.split(":", 2)
    # km:back（无 key）
    if len(parts) == 2 and parts[1] == "back":
        conn, user = open_user_context_from_telegram_user(call.from_user)
        if not require_enabled_user(user):
            await _answer_error(call, "账号已禁用。")
            return
        await _show_kls_list(call, conn, int(user["telegram_user_id"]))
        await call.answer()
        return

    if len(parts) != 3:
        await _answer_error(call, "按钮数据无效，请重新发送命令。")
        return

    action, key = parts[1], parts[2]
    conn, user, widget, error = _callback_key_context(call, key)
    if error:
        await _answer_error(call, error)
        return

    if action == "open":
        await _show_key_actions(call, conn, widget["key"])
        await call.answer()
        return

    if action == "bot":
        if not call.message:
            await _answer_error(call, "当前消息不可操作。")
            return
        if _chat_type(call) != "private":
            await _answer_error(call, "请在主机器人私聊中点击「绑定机器人」，避免 Token 泄露。")
            return
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            "await_token",
            key=widget["key"],
            ttl_seconds=300,
        )
        await call.message.answer(f"请在 5 分钟内发送 key `{widget['key']}` 对应的客户机器人 Token。")
        await call.answer("已进入绑定机器人流程")
        return

    if action == "botdel":
        rows = dbm.bot_binding_list(conn, widget["key"])
        if not rows:
            await _show_key_actions(call, conn, widget["key"])
            await call.answer("没有可解绑的机器人")
            return
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        buttons = []
        for row in rows:
            uname = row.get("bot_username") or "-"
            buttons.append([InlineKeyboardButton(
                text=f"✅ 解绑 @{uname}",
                callback_data=f"botdel_c:{widget['key']}:{row['id']}",
            )])
        buttons.append([InlineKeyboardButton(text="❌ 取消", callback_data="botdel_x")])
        await _replace_or_send(
            call,
            f"确认要解绑 key `{widget['key']}` 的机器人吗？",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await call.answer()
        return

    if action == "grp":
        if not call.message:
            await _answer_error(call, "当前消息不可操作。")
            return
        if _chat_type(call) != "supergroup":
            await call.message.answer(
                "绑定客服群需要在目标超级群里操作：\n"
                f"1. 把主机器人拉进目标超级群；\n"
                f"2. 在群里发送 /groupbind {widget['key']}；\n"
                "3. 群需要开启话题功能。"
            )
            await call.answer()
            return
        chat_id = _chat_id(call)
        if chat_id is None:
            await _answer_error(call, "无法读取当前群 ID，请改用 /groupbind。")
            return
        dbm.widget_set_forum_chat_id(conn, widget["key"], chat_id)
        await _show_key_actions(call, conn, widget["key"])
        await call.answer("已绑定当前客服群")
        return

    if action == "welc":
        if not call.message or _chat_type(call) != "private":
            await _answer_error(call, "请在主机器人私聊中操作。")
            return
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            "await_welcome",
            key=widget["key"],
            ttl_seconds=300,
        )
        await call.message.answer(
            f"请在 5 分钟内发送 key `{widget['key']}` 的欢迎语。\n"
            "发送 - 表示清空欢迎语。"
        )
        await call.answer("已进入设置欢迎语流程")
        return

    if action == "off":
        if not call.message or _chat_type(call) != "private":
            await _answer_error(call, "请在主机器人私聊中操作。")
            return
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            "await_offline_msg",
            key=widget["key"],
            ttl_seconds=300,
        )
        await call.message.answer(
            f"请在 5 分钟内发送 key `{widget['key']}` 的下班留言。\n"
            "下班留言会在客户机器人 /start 和网页打开时，紧跟欢迎语之后显示。\n"
            "发送 - 表示清空。"
        )
        await call.answer("已进入设置下班留言流程")
        return

    if action == "tog":
        current = int(widget.get("enabled") or 0)
        new_val = 0 if current else 1
        dbm.widget_set_enabled(conn, widget["key"], new_val)
        await _show_key_actions(call, conn, widget["key"])
        await call.answer("已上班" if new_val else "已下班")
        return

    if action in ("sch", "sch_menu"):
        schedule = (widget.get("work_schedule") or "").strip()
        schedule_active = bool(int(widget.get("work_schedule_active") or 1))
        status_text = "⏰ <b>上班时间设置</b>\n"
        if schedule:
            auto_status = "🟢 自动切换已开启" if schedule_active else "🔴 自动切换已关闭"
            status_text += f"当前时间段：<code>{schedule}</code>\n{auto_status}"
        else:
            status_text += "当前未设置上班时间（不自动切换）"
        if call.message:
            await call.message.answer(status_text, parse_mode="HTML", reply_markup=key_schedule_keyboard(widget["key"], schedule_active))
        await call.answer()
        return

    if action == "sch_set":
        if not call.message or _chat_type(call) != "private":
            await _answer_error(call, "请在主机器人私聊中操作。")
            return
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            "await_work_schedule",
            key=widget["key"],
            ttl_seconds=300,
        )
        await call.message.answer(
            f"请在 5 分钟内发送 key `{widget['key']}` 的上班时间。\n"
            "格式示例：\n• 18:00-04:00 1-7（每天 18 点到次日 4 点）\n"
            "• 09:00-18:00 1-5（周一到周五）\n"
            "• 关闭（停止定时自动上下班）"
        )
        await call.answer("已进入设置上班时间流程")
        return

    if action == "sch_tog":
        current_active = bool(int(widget.get("work_schedule_active") or 1))
        new_active = not current_active
        dbm.widget_set_work_schedule_active(conn, widget["key"], new_active)
        widget["work_schedule_active"] = 1 if new_active else 0
        schedule = (widget.get("work_schedule") or "").strip()
        status_text = "⏰ <b>上班时间设置</b>\n"
        if schedule:
            auto_status = "🟢 自动切换已开启" if new_active else "🔴 自动切换已关闭"
            status_text += f"当前时间段：<code>{schedule}</code>\n{auto_status}"
        else:
            status_text += "当前未设置上班时间（不自动切换）"
        if call.message:
            await call.message.edit_text(status_text, parse_mode="HTML", reply_markup=key_schedule_keyboard(widget["key"], new_active))
        await call.answer("✅ 已" + ("开启" if new_active else "关闭") + "自动切换")
        return

    if action == "qr":
        conn, user, widget, error = _callback_vip_key_context(call, key)
        if error:
            await _answer_error(call, error)
            return
        await _show_quick_reply_menu(call, conn, widget["key"])
        await call.answer()
        return

    await _answer_error(call, "未知操作，请重新发送命令。")


@dp.callback_query(F.data.startswith("botdel_"))
async def handle_botdel_confirm_callback(call: CallbackQuery, bot: Bot):
    if not is_main_bot(bot):
        return
    data = call.data or ""
    await call.answer()

    if data == "botdel_x":
        if call.message:
            await call.message.edit_text("❌ 已取消解绑")
        return

    if data.startswith("botdel_c:"):
        parts = data[len("botdel_c:"):].split(":", 1)
        if len(parts) != 2:
            await call.message.edit_text("❌ 数据无效")
            return
        key_raw, binding_id_s = parts
        conn, user, widget, error = _callback_key_context(call, key_raw)
        if error:
            await call.message.edit_text(f"❌ {error}")
            return
        try:
            binding_id = int(binding_id_s)
        except Exception:
            await call.message.edit_text("❌ 数据无效")
            return
        await deactivate_customer_bot_binding(binding_id)
        dbm.bot_binding_delete_by_id(conn, binding_id)
        await _show_key_actions(call, conn, widget["key"])
        return

    if call.message:
        await call.message.edit_text("❌ 未知操作")


@dp.callback_query(F.data.startswith("qrm:"))
async def handle_quick_reply_management_callback(call: CallbackQuery, bot: Bot):
    if not is_main_bot(bot):
        return
    data = call.data or ""
    parts = data.split(":", 3)
    if len(parts) < 3:
        await _answer_error(call, "按钮数据无效，请重新发送命令。")
        return

    action = parts[1]
    key = parts[2]
    conn, user, widget, error = _callback_vip_key_context(call, key)
    if error:
        await _answer_error(call, error)
        return

    if action == "add":
        if not call.message or _chat_type(call) != "private":
            await _answer_error(call, "请在主机器人私聊中添加自动回复。")
            return
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            "await_quick_reply",
            key=widget["key"],
            ttl_seconds=300,
        )
        await call.message.answer(
            f"请在 5 分钟内发送 key `{widget['key']}` 的自动回复，格式：\n"
            "标题|答案"
        )
        await call.answer("已进入添加自动回复流程")
        return

    if action == "open":
        if len(parts) != 4:
            await _answer_error(call, "缺少自动回复编号。")
            return
        try:
            reply_id = int(parts[3])
        except Exception:
            await _answer_error(call, "自动回复编号无效。")
            return
        if await _show_quick_reply_item(call, conn, widget["key"], reply_id):
            await call.answer()
        return

    if action == "del":
        if len(parts) != 4:
            await _answer_error(call, "缺少自动回复编号。")
            return
        try:
            reply_id = int(parts[3])
        except Exception:
            await _answer_error(call, "自动回复编号无效。")
            return
        dbm.quick_reply_delete(conn, widget["key"], reply_id)
        await _show_quick_reply_menu(call, conn, widget["key"])
        await call.answer("已删除")
        return

    if action == "toggle":
        if len(parts) != 4:
            await _answer_error(call, "缺少自动回复编号。")
            return
        try:
            reply_id = int(parts[3])
        except Exception:
            await _answer_error(call, "自动回复编号无效。")
            return
        item = dbm.quick_reply_get(conn, reply_id)
        if not item or item.get("key") != widget["key"]:
            await _answer_error(call, "自动回复不存在。")
            return
        new_enabled = 0 if int(item.get("enabled") or 0) else 1
        dbm.quick_reply_set_enabled(conn, widget["key"], reply_id, new_enabled)
        if not await _show_quick_reply_item(call, conn, widget["key"], reply_id):
            return
        await call.answer("已启用" if new_enabled else "已停用")
        return

    if action in ("editt", "edita"):
        if len(parts) != 4:
            await _answer_error(call, "缺少自动回复编号。")
            return
        try:
            reply_id = int(parts[3])
        except Exception:
            await _answer_error(call, "自动回复编号无效。")
            return
        item = dbm.quick_reply_get(conn, reply_id)
        if not item or item.get("key") != widget["key"]:
            await _answer_error(call, "自动回复不存在。")
            return
        pending_action = "await_qr_title" if action == "editt" else "await_qr_answer"
        dbm.pending_action_set(
            conn,
            int(user["telegram_user_id"]),
            pending_action,
            key=widget["key"],
            payload=str(reply_id),
            ttl_seconds=300,
        )
        if not call.message:
            await _answer_error(call, "当前消息不可操作。")
            return
        prompt = "请在 5 分钟内发送新的"
        prompt += "标题。" if action == "editt" else "答案。"
        await call.message.answer(prompt)
        await call.answer()
        return

    if action == "refresh":
        await _show_quick_reply_menu(call, conn, widget["key"])
        await call.answer("已刷新")
        return

    if action == "back":
        await _show_key_actions(call, conn, widget["key"])
        await call.answer()
        return

    await _answer_error(call, "未知操作，请重新发送命令。")
