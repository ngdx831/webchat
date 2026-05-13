import os

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")
os.environ.setdefault("WEBCHAT_BOT_TOKEN", "123456:TEST_TOKEN")

import config

config.BOT_TOKEN = os.environ["WEBCHAT_BOT_TOKEN"]

import db as dbm
from bot.handlers.admin_entries import _format_kls_rows, _resolve_kls_target_user_id


def test_kls_without_argument_targets_current_user():
    user = {"telegram_user_id": 100, "role": dbm.USER_ROLE_NORMAL}

    target, error = _resolve_kls_target_user_id("/kls", user)

    assert target == 100
    assert error == ""


def test_kls_normal_user_cannot_query_other_account():
    user = {"telegram_user_id": 100, "role": dbm.USER_ROLE_NORMAL}

    target, error = _resolve_kls_target_user_id("/kls 200", user)

    assert target is None
    assert "Permission denied" in error


def test_kls_admin_can_query_target_account():
    user = {"telegram_user_id": 100, "role": dbm.USER_ROLE_ADMIN}

    target, error = _resolve_kls_target_user_id("/kls 200", user)

    assert target == 200
    assert error == ""


def test_kls_admin_argument_must_be_numeric():
    user = {"telegram_user_id": 100, "role": dbm.USER_ROLE_ADMIN}

    target, error = _resolve_kls_target_user_id("/kls abc", user)

    assert target is None
    assert "Usage" in error


def test_kls_formats_all_keys_for_target_user():
    rows = [
        {"key": "a", "display_name": "A", "enabled": 1},
        {"key": "b", "display_name": "B", "enabled": 0},
    ]

    text = _format_kls_rows(200, rows)

    assert "Keys for user 200:" in text
    assert "- a: A online" in text
    assert "- b: B offline" in text
