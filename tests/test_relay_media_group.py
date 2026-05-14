"""客服 note 转发到 Telegram 用户：多媒体走 send_media_group 整组上传，

- 不依赖 forward，因此用户不会看到「转发自」来源；
- 一组媒体作为一条 album 出现在用户聊天里，而不是被拆成 N 条单图。
"""
import asyncio
import os
import sys
import types

# 桩掉 aiohttp 防止真实网络。
sys.modules.setdefault("aiohttp", types.SimpleNamespace(ClientTimeout=lambda total: None))

from bot import relay  # noqa: E402


class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))

    async def send_photo(self, **kwargs):
        self.calls.append(("send_photo", kwargs))

    async def send_video(self, **kwargs):
        self.calls.append(("send_video", kwargs))

    async def send_document(self, **kwargs):
        self.calls.append(("send_document", kwargs))

    async def send_media_group(self, **kwargs):
        self.calls.append(("send_media_group", kwargs))


def _make_local_files(tmpdir, count, prefix="p"):
    out = []
    for i in range(count):
        path = os.path.join(tmpdir, f"{prefix}{i}.bin")
        with open(path, "wb") as f:
            f.write(b"fake")
        out.append(path)
    return out


def test_note_with_multiple_media_sends_one_media_group(tmp_path, monkeypatch):
    files = _make_local_files(str(tmp_path), 3, "p")
    monkeypatch.setattr(relay, "abs_public_path", lambda rel: rel)

    bot = FakeBot()
    event = {
        "kind": "note",
        "title": "笔记标题",
        "body": "说明文字",
        "media": [
            {"type": "photo", "local_path": files[0]},
            {"type": "photo", "local_path": files[1]},
            {"type": "video", "local_path": files[2]},
        ],
    }

    session = {"channel": "telegram", "bot_binding_id": 1, "customer_chat_id": 12345}

    # 注入 customer bot 实例。
    relay.CUSTOMER_BOTS_BY_BINDING_ID[1] = bot
    try:
        asyncio.run(relay.send_event_to_customer(None, session, event))
    finally:
        relay.CUSTOMER_BOTS_BY_BINDING_ID.pop(1, None)

    methods = [c[0] for c in bot.calls]
    assert methods == ["send_media_group"]  # 一次性组发，不被拆
    args = bot.calls[0][1]
    assert args["chat_id"] == 12345
    media = args["media"]
    assert len(media) == 3
    # caption 只挂第一项上
    assert media[0].caption == "笔记标题\n说明文字"
    assert media[1].caption is None
    assert media[2].caption is None


def test_note_with_single_media_does_not_call_media_group(tmp_path, monkeypatch):
    files = _make_local_files(str(tmp_path), 1, "single")
    monkeypatch.setattr(relay, "abs_public_path", lambda rel: rel)

    bot = FakeBot()
    event = {
        "kind": "note",
        "title": "只有一张图",
        "body": "",
        "media": [{"type": "photo", "local_path": files[0]}],
    }
    session = {"channel": "telegram", "bot_binding_id": 2, "customer_chat_id": 99}

    relay.CUSTOMER_BOTS_BY_BINDING_ID[2] = bot
    try:
        asyncio.run(relay.send_event_to_customer(None, session, event))
    finally:
        relay.CUSTOMER_BOTS_BY_BINDING_ID.pop(2, None)

    methods = [c[0] for c in bot.calls]
    assert methods == ["send_photo"]
    assert bot.calls[0][1]["caption"] == "只有一张图"


def test_note_text_only_falls_back_to_send_message(monkeypatch):
    monkeypatch.setattr(relay, "abs_public_path", lambda rel: rel)

    bot = FakeBot()
    event = {"kind": "note", "title": "纯文本", "body": "", "media": []}
    session = {"channel": "telegram", "bot_binding_id": 3, "customer_chat_id": 77}

    relay.CUSTOMER_BOTS_BY_BINDING_ID[3] = bot
    try:
        asyncio.run(relay.send_event_to_customer(None, session, event))
    finally:
        relay.CUSTOMER_BOTS_BY_BINDING_ID.pop(3, None)

    methods = [c[0] for c in bot.calls]
    assert methods == ["send_message"]
