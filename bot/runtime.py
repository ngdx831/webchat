from typing import Optional

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN


_main_bot: Optional[Bot] = None
dp = Dispatcher()


def get_main_bot() -> Bot:
    global _main_bot
    if _main_bot is None:
        if not BOT_TOKEN:
            raise RuntimeError("WEBCHAT_BOT_TOKEN not set")
        _main_bot = Bot(BOT_TOKEN)
    return _main_bot
