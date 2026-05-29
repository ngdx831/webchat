import re
from contextlib import suppress
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

import db as dbm
from config import MAX_RICH_TEXT_LENGTH

from .auth import (
    is_vip_or_admin,
    key_limit_for_role,
    open_user_context,
    require_enabled_user,
    require_owned_key,
    user_display_role,
)
from .customer_bots import activate_customer_bot_binding, is_main_bot
from .validators import explain_key_error, validate_key


def _clear_blank(text: str) -> str:
    """- 表示清空，否则原样裁剪。"""
    text = (text or "").strip()
    if text == "-":
        return ""
    return text


_SCHEDULE_RE = re.compile(r"^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})(\s+(.+))?$")


def _parse_work_schedule(text: str):
    """Returns (valid, normalized_schedule, error_msg)."""
    t = text.strip()
    if t in ("关闭", "disable", "off", "close"):
        return True, "", ""
    m = _SCHEDULE_RE.match(t)
    if not m:
        return False, "", "格式错误，请参考示例"
    start_s, end_s = m.group(1), m.group(2)
    days_s = (m.group(4) or "").strip()

    def _parse_time(s: str) -> str:
        h, mi = map(int, s.split(":"))
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            raise ValueError
        return f"{h:02d}:{mi:02d}"

    try:
        start_s = _parse_time(start_s)
        end_s = _parse_time(end_s)
    except (ValueError, IndexError):
        return False, "", "时间格式错误（HH:MM）"

    days_norm = ""
    if days_s:
        if "-" in days_s and "," not in days_s:
            parts = days_s.split("-")
            if len(parts) != 2:
                return False, "", "周几格式错误（如 1-5）"
            try:
                a, b = int(parts[0]), int(parts[1])
                if not (1 <= a <= 7 and 1 <= b <= 7 and a <= b):
                    raise ValueError
                days_norm = f"{a}-{b}"
            except ValueError:
                return False, "", "周几范围错误（1=周一，7=周日）"
        else:
            try:
                nums = [int(x.strip()) for x in days_s.replace("-", ",").split(",")]
                if not all(1 <= n <= 7 for n in nums):
                    raise ValueError
                days_norm = ",".join(str(n) for n in sorted(set(nums)))
            except ValueError:
                return False, "", "周几格式错误"

    schedule = f"{start_s}-{end_s}"
    if days_norm:
        schedule += f" {days_norm}"
    return True, schedule, ""


async def _bind_customer_bot_token(
    conn,
    user: Optional[Dict[str, Any]],
    key: str,
    token: str,
    bot_username: str = "",
):
    widget = require_owned_key(conn, user, key)
    if not widget:
        return None, None, "", "没有权限，或 key 不存在。"

    try:
        probe = Bot(token)
        me = await probe.get_me()
        username = bot_username or (getattr(me, "username", "") or "")
    except Exception:
        # 不要把原始异常文本回显给用户,它可能含 token 自身。
        return None, None, "", "机器人 Token 验证失败，请检查 token 格式。"

    owner_user_id = widget.get("owner_user_id")
    if owner_user_id is not None:
        owner_user_id = int(owner_user_id)
    binding_id = dbm.bot_binding_add(
        conn,
        key,
        token,
        username,
        enabled=1,
        owner_user_id=owner_user_id,
    )
    binding = dbm.bot_binding_get(conn, binding_id) or {
        "id": binding_id,
        "key": key,
        "bot_token": token,
        "bot_username": username,
        "enabled": 1,
        "owner_user_id": owner_user_id,
    }
    await activate_customer_bot_binding(binding, probe, start_polling=True)
    return binding, probe, username, ""


async def handle_pending_action_message(msg: Message, bot: Bot) -> bool:
    if not is_main_bot(bot):
        return False
    if getattr(getattr(msg, "chat", None), "type", "") != "private":
        return False
    if not getattr(msg, "from_user", None):
        return False

    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        await msg.reply("账号已禁用，请联系管理员。")
        return True

    pending = dbm.pending_action_get(conn, int(user["telegram_user_id"]))
    if not pending:
        return False

    action = pending.get("action")
    text = (msg.text or "").strip()
    raw_key = str(pending.get("key") or "")
    payload = str(pending.get("payload") or "")

    # await_keyadd 不强制 key 校验
    if action == "await_keyadd":
        return await _handle_await_keyadd(msg, conn, user, text)

    # 其它 action 都需要 key 合法
    try:
        key = validate_key(raw_key) if raw_key else ""
    except Exception:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("待处理操作已失效，请重新发送命令。")
        return True

    if action == "await_welcome":
        return await _handle_await_welcome(msg, conn, user, key, text)

    if action == "await_offline_msg":
        return await _handle_await_offline_msg(msg, conn, user, key, text)

    if action == "await_work_schedule":
        return await _handle_await_work_schedule(msg, conn, user, key, text)

    if action == "await_quick_reply":
        return await _handle_await_quick_reply(msg, conn, user, key, text)

    if action in ("await_qr_title", "await_qr_answer"):
        return await _handle_await_qr_edit(msg, conn, user, key, action, payload, text)

    if action == "await_token":
        return await _handle_await_token(msg, conn, user, key, text)

    return False


async def _handle_await_keyadd(msg: Message, conn, user, text: str) -> bool:
    if "|" not in text:
        await msg.reply("格式不正确，请按 <key>|<显示名> 重新发送。")
        return True
    key_raw, display_name = [x.strip() for x in text.split("|", 1)]
    if not key_raw or not display_name:
        await msg.reply("格式不正确，key 和显示名都不能为空。")
        return True
    try:
        key = validate_key(key_raw)
    except Exception as exc:
        await msg.reply(explain_key_error(str(exc)))
        return True
    limit = key_limit_for_role(str(user.get("role") or ""))
    owner_user_id = int(user["telegram_user_id"])
    if limit is not None and dbm.widget_count_by_owner(conn, owner_user_id) >= limit:
        dbm.pending_action_clear(conn, owner_user_id)
        await msg.reply(f"当前角色 {user_display_role(user)} 的 key 数量已达上限：{limit}")
        return True
    try:
        dbm.widget_add(
            conn,
            key,
            0,
            display_name[:120],
            must_not_exist=True,
            owner_user_id=owner_user_id,
        )
    except ValueError as exc:
        if str(exc) == "KEY_EXISTS":
            await msg.reply(f"key 已存在：{key}，请换一个或先 /keydel。")
            return True
        raise
    dbm.pending_action_clear(conn, owner_user_id)
    from .key_management_ui import key_actions_keyboard
    await msg.reply(
        f"✅ 已创建 key：{key}\n显示名：{display_name}\n\n"
        "下一步：使用「绑定客服群」和「绑定机器人」按钮完成配置。",
        reply_markup=key_actions_keyboard(key, dbm.bot_binding_list(conn, key)),
    )
    return True


async def _handle_await_welcome(msg: Message, conn, user, key: str, text: str) -> bool:
    widget = require_owned_key(conn, user, key)
    if not widget:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("没有权限，或 key 不存在。")
        return True
    value = _clear_blank(text)[: int(MAX_RICH_TEXT_LENGTH)]
    dbm.widget_set_welcome_text(conn, key, value)
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    await msg.reply(
        f"✅ 已更新 {key} 的欢迎语：\n{value or '（已清空）'}"
    )
    return True


async def _handle_await_offline_msg(msg: Message, conn, user, key: str, text: str) -> bool:
    widget = require_owned_key(conn, user, key)
    if not widget:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("没有权限，或 key 不存在。")
        return True
    value = _clear_blank(text)[: int(MAX_RICH_TEXT_LENGTH)]
    dbm.widget_set_offline_msg(conn, key, value)
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    await msg.reply(
        f"✅ 已更新 {key} 的下班留言：\n{value or '（已清空）'}"
    )
    return True


async def _handle_await_work_schedule(msg: Message, conn, user, key: str, text: str) -> bool:
    widget = require_owned_key(conn, user, key)
    if not widget:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("没有权限，或 key 不存在。")
        return True
    if not text:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("内容为空，已取消。请重新点击「设置上班时间」按钮。")
        return True
    valid, schedule, err = _parse_work_schedule(text)
    if not valid:
        await msg.reply(f"❌ {err}\n格式示例：\n• 09:00-18:00\n• 09:00-18:00 1-5\n• 关闭")
        return True
    dbm.widget_set_work_schedule(conn, key, schedule)
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    if schedule:
        await msg.reply(f"✅ 上班时间已设置：{schedule}（key={key}）")
    else:
        await msg.reply(f"✅ 定时上下班已关闭（key={key}）")
    return True


async def _handle_await_quick_reply(msg: Message, conn, user, key: str, text: str) -> bool:
    if not is_vip_or_admin(user):
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("自动回复是 VIP/管理员功能，请联系管理员开通。")
        return True
    if "|" not in text:
        await msg.reply("格式不正确，请发送：标题|答案")
        return True
    widget = require_owned_key(conn, user, key)
    if not widget:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("没有权限，或 key 不存在。")
        return True
    title, answer = [part.strip() for part in text.split("|", 1)]
    if not title or not answer:
        await msg.reply("标题和答案不能为空，请重新发送：标题|答案")
        return True
    current = dbm.quick_reply_list(conn, key, enabled_only=False)
    if len([item for item in current if int(item.get("enabled") or 0)]) >= 9:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("每个 key 最多建议配置 9 个自动回复，请先删除不用的项。")
        return True
    dbm.quick_reply_add(
        conn,
        key,
        title[:120],
        answer[: int(MAX_RICH_TEXT_LENGTH)],
        sort_order=len(current) + 1,
    )
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    await msg.reply(f"✅ 已添加自动回复：{title[:120]}")
    return True


async def _handle_await_qr_edit(msg, conn, user, key: str, action: str, payload: str, text: str) -> bool:
    if not is_vip_or_admin(user):
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("自动回复是 VIP/管理员功能，请联系管理员开通。")
        return True
    widget = require_owned_key(conn, user, key)
    if not widget:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("没有权限，或 key 不存在。")
        return True
    try:
        reply_id = int(payload)
    except Exception:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("待处理操作已失效，请重新发送命令。")
        return True
    if not text:
        await msg.reply("内容不能为空，请重新发送。")
        return True
    if action == "await_qr_title":
        dbm.quick_reply_set_title(conn, key, reply_id, text[:120])
        feedback = "✅ 已更新标题"
    else:
        dbm.quick_reply_set_answer(conn, key, reply_id, text[: int(MAX_RICH_TEXT_LENGTH)])
        feedback = "✅ 已更新答案"
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    await msg.reply(feedback)
    return True


async def _handle_await_token(msg: Message, conn, user, key: str, text: str) -> bool:
    if not text:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("机器人 Token 不能为空，请重新发送 /tokenadd <key>。")
        return True

    with suppress(Exception):
        await msg.delete()
    binding, _, username, error = await _bind_customer_bot_token(conn, user, key, text)
    dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
    if error:
        await msg.reply(error)
        return True

    await msg.reply(
        f"✅ 已绑定客户机器人\nkey：{key}\nbot：@{username or '-'}\n"
        f"绑定 ID：{binding['id']}\n已开始轮询。"
    )
    return True
