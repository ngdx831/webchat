from typing import Any, Dict, Optional

from aiogram.types import Message

import db as dbm
from config import ADMIN_IDS, DB_PATH


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def current_user_from_message(conn, msg: Message) -> Optional[Dict[str, Any]]:
    if not getattr(msg, "from_user", None):
        return None
    tg_user = msg.from_user
    user_id = int(tg_user.id)
    default_role = dbm.USER_ROLE_ADMIN if is_admin(user_id) else dbm.USER_ROLE_NORMAL
    username = getattr(tg_user, "username", "") or ""
    display_name = getattr(tg_user, "full_name", "") or username
    return dbm.user_upsert_from_telegram(
        conn,
        user_id,
        username,
        display_name,
        default_role=default_role,
    )


def is_vip_or_admin(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    return user.get("role") in {dbm.USER_ROLE_VIP, dbm.USER_ROLE_ADMIN}


def is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    if not user:
        return False
    return user.get("role") == dbm.USER_ROLE_ADMIN


def require_enabled_user(user: Optional[Dict[str, Any]]) -> bool:
    return bool(user and int(user.get("enabled") or 0) == 1)


def require_owned_key(conn, user: Optional[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    if not require_enabled_user(user):
        return None
    if is_admin_user(user):
        return dbm.widget_get(conn, key)
    return dbm.widget_get_owned(conn, key, int(user["telegram_user_id"]))


def key_limit_for_role(role: str) -> Optional[int]:
    if role == dbm.USER_ROLE_ADMIN:
        return None
    if role == dbm.USER_ROLE_VIP:
        return 5
    return 1


def user_display_role(user: Dict[str, Any]) -> str:
    return str(user.get("role") or dbm.USER_ROLE_NORMAL)


def widget_owner_has_vip_features(conn, widget: Optional[Dict[str, Any]]) -> bool:
    if not widget or widget.get("owner_user_id") is None:
        return False
    owner = dbm.user_get(conn, int(widget["owner_user_id"]))
    return bool(require_enabled_user(owner) and is_vip_or_admin(owner))


def widget_owner_enabled(conn, widget: Optional[Dict[str, Any]]) -> bool:
    if not widget or widget.get("owner_user_id") is None:
        return False
    owner = dbm.user_get(conn, int(widget["owner_user_id"]))
    return require_enabled_user(owner)


def open_user_context(msg: Message):
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    user = current_user_from_message(conn, msg)
    return conn, user


def vip_key_context(msg: Message, key: str):
    conn, user = open_user_context(msg)
    if not require_enabled_user(user):
        return conn, user, None, "Account disabled. Please contact admin."
    if not is_vip_or_admin(user):
        return conn, user, None, "VIP feature required. Please contact admin."
    widget = require_owned_key(conn, user, key)
    if not widget:
        return conn, user, None, "Permission denied or key not found."
    return conn, user, widget, ""
