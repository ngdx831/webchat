"""Thin entrypoint for the Telegram bot. Business logic lives in `bot/`."""
import asyncio

from bot.app import main


if __name__ == "__main__":
    asyncio.run(main())
