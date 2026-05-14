"""/kstatus 切换逻辑：

- 无参数时按多数决统一切换；
- 带 key 时仅切换单个；
- 任何切换都不影响非自有 key。
"""
import contextlib
import uuid
from pathlib import Path

import db as dbm
from bot.handlers.admin_entries import _toggle_widget


def _db_path():
    root = Path("data") / "test_dbs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"kstatus_{uuid.uuid4().hex}.db"


def _seed(conn, owner_id, keys, enabled_map=None):
    enabled_map = enabled_map or {}
    dbm.user_upsert_from_telegram(conn, owner_id, "u", "U", default_role=dbm.USER_ROLE_VIP)
    for key in keys:
        dbm.widget_add(conn, key, -100, key, owner_user_id=owner_id)
        if enabled_map.get(key, 1) == 0:
            dbm.widget_set_enabled(conn, key, 0, "")


def test_toggle_widget_flips_enabled():
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed(conn, 1, ["a"], {"a": 1})
        widget = dbm.widget_get(conn, "a")
        online, _ = _toggle_widget(conn, widget)
        assert online is False
        assert int(dbm.widget_get(conn, "a")["enabled"]) == 0
        # 第二次切回在线
        online, _ = _toggle_widget(conn, dbm.widget_get(conn, "a"))
        assert online is True
        assert int(dbm.widget_get(conn, "a")["enabled"]) == 1


def test_kstatus_majority_rule_3online_1offline_means_all_offline():
    """3 在线 + 1 离线 → 多数在线 → 统一下班。

    这里直接测算 target_online 决策与最终 enabled 值，不走命令分发。
    """
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed(conn, 1, ["a", "b", "c", "d"], {"a": 1, "b": 1, "c": 1, "d": 0})

        widgets = dbm.widget_list_by_owner(conn, 1, limit=500)
        online_count = sum(1 for w in widgets if int(w.get("enabled") or 0))
        target_online = online_count <= (len(widgets) - online_count)
        assert target_online is False  # 多数在线 → 统一下班

        for w in widgets:
            if target_online:
                dbm.widget_set_enabled(conn, w["key"], 1, None)
            else:
                dbm.widget_set_enabled(conn, w["key"], 0, "")

        for key in ["a", "b", "c", "d"]:
            assert int(dbm.widget_get(conn, key)["enabled"]) == 0


def test_kstatus_majority_rule_1online_3offline_means_all_online():
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed(conn, 1, ["a", "b", "c", "d"], {"a": 1, "b": 0, "c": 0, "d": 0})

        widgets = dbm.widget_list_by_owner(conn, 1, limit=500)
        online_count = sum(1 for w in widgets if int(w.get("enabled") or 0))
        target_online = online_count <= (len(widgets) - online_count)
        assert target_online is True  # 多数离线 → 统一上班

        for w in widgets:
            if target_online:
                dbm.widget_set_enabled(conn, w["key"], 1, None)
            else:
                dbm.widget_set_enabled(conn, w["key"], 0, "")

        for key in ["a", "b", "c", "d"]:
            assert int(dbm.widget_get(conn, key)["enabled"]) == 1


def test_kstatus_does_not_touch_other_users_keys():
    """A 用户 /kstatus 不应影响 B 用户的 key。"""
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed(conn, 1, ["a1", "a2"], {"a1": 1, "a2": 1})
        _seed(conn, 2, ["b1"], {"b1": 1})

        # 模拟 user 1 全部切下班
        widgets = dbm.widget_list_by_owner(conn, 1, limit=500)
        for w in widgets:
            dbm.widget_set_enabled(conn, w["key"], 0, "")

        assert int(dbm.widget_get(conn, "a1")["enabled"]) == 0
        assert int(dbm.widget_get(conn, "a2")["enabled"]) == 0
        # user 2 未受影响
        assert int(dbm.widget_get(conn, "b1")["enabled"]) == 1
