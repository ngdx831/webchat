from bot.command_catalog import MAIN_BOT_COMMANDS
from bot.key_management_ui import (
    key_actions_keyboard,
    quick_reply_item_keyboard,
    quick_reply_management_keyboard,
)


def has_chinese(text):
    return any("一" <= ch <= "鿿" for ch in text)


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_all_bot_command_descriptions_are_chinese():
    assert MAIN_BOT_COMMANDS
    for command in MAIN_BOT_COMMANDS:
        assert has_chinese(command.description), command


def test_key_actions_keyboard_when_no_binding_shows_bind_and_management_buttons():
    markup = key_actions_keyboard("demo", bindings=None)

    callbacks = callback_data(markup)
    assert "km:bot:demo" in callbacks  # 未绑定时显示「绑定机器人」
    assert "km:botdel:demo" not in callbacks
    assert "km:grp:demo" in callbacks
    assert "km:welc:demo" in callbacks  # 欢迎语
    assert "km:off:demo" in callbacks  # 下班留言
    assert "km:qr:demo" in callbacks
    assert "km:back" in callbacks  # 返回 key 列表


def test_key_actions_keyboard_when_binding_exists_shows_unbind():
    markup = key_actions_keyboard("demo", bindings=[{"id": 1, "bot_username": "demo_bot"}])

    callbacks = callback_data(markup)
    assert "km:botdel:demo" in callbacks
    assert "km:bot:demo" not in callbacks


def test_quick_reply_management_keyboard_uses_edit_open_not_direct_delete():
    markup = quick_reply_management_keyboard(
        "demo",
        [
            {"id": 7, "title": "价格", "enabled": 1},
        ],
    )

    texts = button_texts(markup)
    callbacks = callback_data(markup)
    assert any("添加" in t for t in texts)
    # 列表里不再出现 #ID 序号
    assert all("#" not in t for t in texts)
    # 列表按钮点击进入编辑视图，而非直接删除
    assert "qrm:open:demo:7" in callbacks
    assert "qrm:del:demo:7" not in callbacks
    assert "qrm:refresh:demo" in callbacks


def test_quick_reply_item_keyboard_offers_edit_toggle_delete_back():
    markup = quick_reply_item_keyboard("demo", 9, enabled=1)

    callbacks = callback_data(markup)
    assert "qrm:editt:demo:9" in callbacks
    assert "qrm:edita:demo:9" in callbacks
    assert "qrm:toggle:demo:9" in callbacks
    assert "qrm:del:demo:9" in callbacks
    assert "qrm:refresh:demo" in callbacks
