import os


os.environ.setdefault("WEBCHAT_TOKEN_KEY", "dGVzdF90ZXN0X3Rlc3RfdGVzdF90ZXN0X3Rlc3RfdGVzdF8=")

from bot.handlers.admin_entries import _format_admin_key_panel


def test_admin_key_panel_lists_key_state_and_commands():
    widget = {
        "key": "ktv",
        "display_name": "KTV客服",
        "owner_user_id": 10001,
        "forum_chat_id": -100123,
        "enabled": 1,
        "offline_msg": "",
        "welcome_text": "欢迎",
    }
    owner = {"role": "vip", "enabled": 1, "username": "owner"}
    bindings = [{"id": 7, "bot_username": "kc_bot", "enabled": 1}]

    text = _format_admin_key_panel(widget, owner, bindings)

    assert "管理 key：ktv" in text
    assert "显示名：KTV客服" in text
    assert "负责人：10001 @owner vip enabled=1" in text
    assert "客户机器人：#7 @kc_bot enabled" in text
    assert "/kstatus ktv" in text
    assert "/adminkeydel ktv" in text
