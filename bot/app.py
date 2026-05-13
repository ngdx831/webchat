import asyncio

from aiogram import Bot

import db as dbm
from config import BOT_TOKEN, DB_PATH

from . import handlers  # noqa: F401  # importing registers handlers on dp
from .customer_bots import activate_customer_bot_binding, shutdown_customer_bots
from .runtime import bot, dp


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("WEBCHAT_BOT_TOKEN not set")
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    for binding in dbm.bot_binding_list(conn, enabled_only=True):
        token = binding.get("bot_token") or ""
        if not token or token == BOT_TOKEN:
            continue
        try:
            customer_bot = Bot(token)
            me = await customer_bot.get_me()
            binding["bot_username"] = binding.get("bot_username") or (me.username or "")
            await activate_customer_bot_binding(binding, customer_bot, start_polling=True)
            print(f"Loaded customer bot @{binding.get('bot_username') or me.username or binding['id']} for key={binding['key']}")
        except Exception as exc:
            print(f"Load customer bot failed: key={binding.get('key')}, id={binding.get('id')}, error={exc}")
    try:
        await dp.start_polling(bot)
    finally:
        await shutdown_customer_bots()


__all__ = ["main", "bot", "dp"]
