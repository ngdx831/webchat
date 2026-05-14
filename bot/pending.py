from contextlib import suppress
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

import db as dbm
from config import MAX_RICH_TEXT_LENGTH

from .auth import is_vip_or_admin, open_user_context, require_enabled_user, require_owned_key
from .customer_bots import activate_customer_bot_binding, is_main_bot
from .validators import validate_key


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
    key = str(pending.get("key") or "")
    try:
        key = validate_key(key)
    except Exception:
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply("待处理操作已失效，请重新发送命令。")
        return True

    if action == "await_welcome":
        if not text:
            dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
            await msg.reply("欢迎语不能为空，请重新发送 /welcome <key>。")
            return True
        widget = require_owned_key(conn, user, key)
        if not widget:
            dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
            await msg.reply("没有权限，或 key 不存在。")
            return True
        dbm.widget_set_welcome_text(conn, key, text[: int(MAX_RICH_TEXT_LENGTH)])
        dbm.pending_action_clear(conn, int(user["telegram_user_id"]))
        await msg.reply(f"已更新 key 欢迎语：{key}")
        return True

    if action == "await_quick_reply":
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
        await msg.reply(f"已添加自动回复：{title[:120]}")
        return True

    if action != "await_token":
        return False

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
        f"已绑定客户机器人\nkey：{key}\nbot：@{username or '-'}\n"
        f"绑定 ID：{binding['id']}\n已开始轮询。"
    )
    return True
