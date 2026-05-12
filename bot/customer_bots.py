import asyncio
from contextlib import suppress
from typing import Any, Dict, Optional

from aiogram import Bot

from config import BOT_TOKEN

from .runtime import dp


CUSTOMER_BOTS_BY_TOKEN: Dict[str, Dict[str, Any]] = {}
CUSTOMER_BOTS_BY_BINDING_ID: Dict[int, Bot] = {}
CUSTOMER_BOT_POLLING_TASKS: Dict[int, "asyncio.Task[Any]"] = {}


def _bot_token(active_bot: Optional[Bot]) -> str:
    return str(getattr(active_bot, "token", "") or "")


def is_main_bot(active_bot: Optional[Bot]) -> bool:
    return _bot_token(active_bot) == BOT_TOKEN


def binding_for_bot(active_bot: Optional[Bot]) -> Optional[Dict[str, Any]]:
    return CUSTOMER_BOTS_BY_TOKEN.get(_bot_token(active_bot))


def _register_customer_bot_binding(binding: Dict[str, Any], customer_bot: Bot) -> int:
    binding_id = int(binding["id"])
    token = _bot_token(customer_bot) or str(binding.get("bot_token") or "")
    binding["bot_token"] = token
    CUSTOMER_BOTS_BY_TOKEN[token] = binding
    CUSTOMER_BOTS_BY_BINDING_ID[binding_id] = customer_bot
    return binding_id


async def _run_customer_bot_polling(binding_id: int, customer_bot: Bot) -> None:
    try:
        await dp._polling(
            bot=customer_bot,
            polling_timeout=10,
            handle_as_tasks=True,
            allowed_updates=dp.resolve_used_update_types(),
            dispatcher=dp,
            bots=(customer_bot,),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"Customer bot polling stopped: binding_id={binding_id}, error={exc}")
    finally:
        task = asyncio.current_task()
        if CUSTOMER_BOT_POLLING_TASKS.get(binding_id) is task:
            CUSTOMER_BOT_POLLING_TASKS.pop(binding_id, None)


async def activate_customer_bot_binding(
    binding: Dict[str, Any],
    customer_bot: Bot,
    start_polling: bool = True,
) -> bool:
    """Register a customer-side bot and optionally start polling it immediately."""
    binding_id = int(binding["id"])
    existing_bot = CUSTOMER_BOTS_BY_BINDING_ID.get(binding_id)
    if existing_bot is not None and existing_bot is not customer_bot:
        await deactivate_customer_bot_binding(binding_id)

    _register_customer_bot_binding(binding, customer_bot)

    if not start_polling:
        return False

    task = CUSTOMER_BOT_POLLING_TASKS.get(binding_id)
    if task and not task.done():
        return False

    CUSTOMER_BOT_POLLING_TASKS[binding_id] = asyncio.create_task(
        _run_customer_bot_polling(binding_id, customer_bot),
        name=f"customer-bot-polling-{binding_id}",
    )
    return True


async def deactivate_customer_bot_binding(binding_id: int) -> None:
    binding_id = int(binding_id)
    task = CUSTOMER_BOT_POLLING_TASKS.pop(binding_id, None)
    if task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    customer_bot = CUSTOMER_BOTS_BY_BINDING_ID.pop(binding_id, None)
    if customer_bot:
        CUSTOMER_BOTS_BY_TOKEN.pop(_bot_token(customer_bot), None)
        with suppress(Exception):
            await customer_bot.session.close()


async def shutdown_customer_bots(*args: Any, **kwargs: Any) -> None:
    for binding_id in list(CUSTOMER_BOT_POLLING_TASKS):
        await deactivate_customer_bot_binding(binding_id)


with suppress(Exception):
    dp.shutdown.register(shutdown_customer_bots)
