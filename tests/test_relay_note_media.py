import os
import unittest

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")
os.environ.setdefault("WEBCHAT_BOT_TOKEN", "123456:TEST_TOKEN")

import config

config.BOT_TOKEN = os.environ["WEBCHAT_BOT_TOKEN"]

from bot.customer_bots import CUSTOMER_BOTS_BY_BINDING_ID
from bot.relay import send_event_to_customer


class FakeCustomerBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(("message", kwargs))

    async def send_photo(self, **kwargs):
        self.calls.append(("photo", kwargs))

    async def send_video(self, **kwargs):
        self.calls.append(("video", kwargs))

    async def send_document(self, **kwargs):
        self.calls.append(("document", kwargs))


class RelayNoteMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        CUSTOMER_BOTS_BY_BINDING_ID.clear()

    async def test_note_event_for_telegram_customer_sends_text_and_media(self):
        fake = FakeCustomerBot()
        CUSTOMER_BOTS_BY_BINDING_ID[10] = fake
        session = {
            "session_id": "s1",
            "channel": "telegram",
            "bot_binding_id": 10,
            "customer_chat_id": 500,
        }
        event = {
            "kind": "note",
            "title": "Support note",
            "body": "See files",
            "media": [
                {"type": "photo", "local_path": "README.md"},
                {"type": "video", "local_path": "README.md"},
                {"type": "document", "local_path": "README.md"},
            ],
        }

        await send_event_to_customer(None, session, event)

        assert [name for name, _ in fake.calls] == ["message", "photo", "video", "document"]

    async def test_missing_note_media_is_reported_without_interrupting_remaining_items(self):
        fake = FakeCustomerBot()
        CUSTOMER_BOTS_BY_BINDING_ID[10] = fake
        session = {
            "session_id": "s1",
            "channel": "telegram",
            "bot_binding_id": 10,
            "customer_chat_id": 500,
        }
        event = {
            "kind": "note",
            "title": "Support note",
            "media": [
                {"type": "photo", "local_path": "missing-file.bin"},
                {"type": "document", "local_path": "README.md"},
            ],
        }

        await send_event_to_customer(None, session, event)

        assert [name for name, _ in fake.calls] == ["message", "message", "document"]
        assert "unavailable" in fake.calls[1][1]["text"].lower()


if __name__ == "__main__":
    unittest.main()
