from bot.command_catalog import MAIN_BOT_COMMANDS
from bot.key_management_ui import key_actions_keyboard, quick_reply_management_keyboard


def has_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_all_bot_command_descriptions_are_chinese():
    assert MAIN_BOT_COMMANDS
    for command in MAIN_BOT_COMMANDS:
        assert has_chinese(command.description), command


def test_key_actions_keyboard_exposes_requested_key_operations():
    markup = key_actions_keyboard("demo")

    assert button_texts(markup) == ["绑定机器人", "绑定客服群", "管理自动回复"]
    assert callback_data(markup) == ["km:bot:demo", "km:grp:demo", "km:qr:demo"]


def test_quick_reply_management_keyboard_exposes_button_management():
    markup = quick_reply_management_keyboard(
        "demo",
        [
            {"id": 7, "title": "价格", "enabled": 1},
        ],
    )

    texts = button_texts(markup)
    callbacks = callback_data(markup)
    assert "添加自动回复" in texts
    assert "删除 #7 价格" in texts
    assert "刷新" in texts
    assert "返回KEY操作" in texts
    assert "qrm:add:demo" in callbacks
    assert "qrm:del:demo:7" in callbacks
