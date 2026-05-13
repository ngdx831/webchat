import sqlite3
from typing import Any, Dict, List, Optional

from .connection import _utc_now_ts


USER_ROLE_NORMAL = "normal"
USER_ROLE_VIP = "vip"
USER_ROLE_ADMIN = "admin"
USER_ROLES = {USER_ROLE_NORMAL, USER_ROLE_VIP, USER_ROLE_ADMIN}


def _validate_user_role(role: str) -> str:
    role = role or USER_ROLE_NORMAL
    if role not in USER_ROLES:
        raise ValueError("INVALID_USER_ROLE")
    return role


def user_get(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_user_id=? LIMIT 1",
        (int(telegram_user_id),),
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["enabled"] = int(out.get("enabled") or 0)
    return out


def user_upsert_from_telegram(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    username: str,
    display_name: str,
    default_role: str = USER_ROLE_NORMAL,
) -> Dict[str, Any]:
    default_role = _validate_user_role(default_role)
    telegram_user_id = int(telegram_user_id)
    now = _utc_now_ts()
    existing = user_get(conn, telegram_user_id)
    role = default_role
    if existing:
        role = USER_ROLE_ADMIN if default_role == USER_ROLE_ADMIN else existing["role"]

    conn.execute(
        """
        INSERT INTO users(
            telegram_user_id, username, display_name, role, enabled,
            vip_until, created_ts, updated_ts
        )
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            username=excluded.username,
            display_name=excluded.display_name,
            role=excluded.role,
            updated_ts=excluded.updated_ts
        """,
        (
            telegram_user_id,
            username or "",
            display_name or "",
            role,
            1,
            existing["vip_until"] if existing else "",
            existing["created_ts"] if existing else now,
            now,
        ),
    )
    conn.commit()
    user = user_get(conn, telegram_user_id)
    if user is None:
        raise RuntimeError("USER_UPSERT_FAILED")
    return user


def user_set_role(conn: sqlite3.Connection, telegram_user_id: int, role: str) -> Optional[Dict[str, Any]]:
    role = _validate_user_role(role)
    conn.execute(
        "UPDATE users SET role=?, updated_ts=? WHERE telegram_user_id=?",
        (role, _utc_now_ts(), int(telegram_user_id)),
    )
    conn.commit()
    return user_get(conn, telegram_user_id)


def user_set_enabled(conn: sqlite3.Connection, telegram_user_id: int, enabled: bool) -> Optional[Dict[str, Any]]:
    conn.execute(
        "UPDATE users SET enabled=?, updated_ts=? WHERE telegram_user_id=?",
        (1 if enabled else 0, _utc_now_ts(), int(telegram_user_id)),
    )
    conn.commit()
    return user_get(conn, telegram_user_id)


def user_list(
    conn: sqlite3.Connection,
    role: str = "",
    enabled_only: bool = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    where = []
    args: List[Any] = []
    if role:
        where.append("role=?")
        args.append(_validate_user_role(role))
    if enabled_only:
        where.append("enabled=1")
    sql = "SELECT * FROM users"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY telegram_user_id ASC LIMIT ?"
    args.append(int(limit))
    out = [dict(r) for r in conn.execute(sql, args).fetchall()]
    for row in out:
        row["enabled"] = int(row.get("enabled") or 0)
    return out
