import asyncio
import logging
from contextlib import suppress
from typing import Any, Dict, Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart

from config import BOT_TOKEN


logger = logging.getLogger(__name__)

CUSTOMER_BOTS_BY_TOKEN: Dict[str, Dict[str, Any]] = {}
CUSTOMER_BOTS_BY_BINDING_ID: Dict[int, Bot] = {}
CUSTOMER_BOT_POLLING_TASKS: Dict[int, "asyncio.Task[Any]"] = {}
CUSTOMER_BOT_DISPATCHERS: Dict[int, Dispatcher] = {}


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


def _create_customer_dispatcher() -> Dispatcher:
    customer_dp = Dispatcher()

    from .handlers.basic import cmd_start
    from .handlers.messages import handle_forum_topic_reply
    from .handlers.quick_replies import handle_quick_reply_callback

    customer_dp.message.register(cmd_start, CommandStart())
    customer_dp.callback_query.register(handle_quick_reply_callback)
    customer_dp.message.register(handle_forum_topic_reply)
    return customer_dp


async def _run_customer_bot_polling(binding_id: int, customer_bot: Bot, customer_dp: Dispatcher) -> None:
    try:
        await customer_dp.start_polling(
            customer_bot,
            polling_timeout=10,
            allowed_updates=customer_dp.resolve_used_update_types(),
            handle_signals=False,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("customer bot polling stopped: binding_id=%s error=%s", binding_id, exc)
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

    customer_dp = CUSTOMER_BOT_DISPATCHERS.get(binding_id)
    if customer_dp is None:
        customer_dp = _create_customer_dispatcher()
        CUSTOMER_BOT_DISPATCHERS[binding_id] = customer_dp

    CUSTOMER_BOT_POLLING_TASKS[binding_id] = asyncio.create_task(
        _run_customer_bot_polling(binding_id, customer_bot, customer_dp),
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
    CUSTOMER_BOT_DISPATCHERS.pop(binding_id, None)
    if customer_bot:
        CUSTOMER_BOTS_BY_TOKEN.pop(_bot_token(customer_bot), None)
        with suppress(Exception):
            await customer_bot.session.close()


async def shutdown_customer_bots(*args: Any, **kwargs: Any) -> None:
    for binding_id in list(CUSTOMER_BOT_POLLING_TASKS):
        await deactivate_customer_bot_binding(binding_id)
