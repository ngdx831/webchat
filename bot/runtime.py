from typing import Optional

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from .db_lifecycle import register_db_cleanup_middleware


_main_bot: Optional[Bot] = None
dp = Dispatcher()
register_db_cleanup_middleware(dp)


def get_main_bot() -> Bot:
    global _main_bot
    if _main_bot is None:
        if not BOT_TOKEN:
            raise RuntimeError("WEBCHAT_BOT_TOKEN not set")
        _main_bot = Bot(BOT_TOKEN)
    return _main_bot
