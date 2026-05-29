"""Thin entrypoint for the Telegram bot. Business logic lives in `bot/`."""
import asyncio
import contextlib
import logging

from aiogram import Bot

import db as dbm
from config import BOT_TOKEN, DB_PATH, WORK_SCHEDULE_TZ

from . import handlers  # noqa: F401  # importing registers handlers on dp
from .command_catalog import setup_main_bot_commands
from .customer_bots import activate_customer_bot_binding, shutdown_customer_bots
from .runtime import dp, get_main_bot


logger = logging.getLogger(__name__)


def _get_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(WORK_SCHEDULE_TZ)
    except Exception:
        import datetime
        return datetime.timezone.utc


def _parse_schedule_for_check(schedule: str):
    """
    Returns (start_minutes, end_minutes, days_set) or None if invalid/empty.
    start/end in minutes-from-midnight; days_set is set of ISO weekday ints (1-7), empty = all days.
    """
    s = (schedule or "").strip()
    if not s:
        return None
    parts = s.split(None, 1)
    time_part = parts[0]
    days_part = parts[1] if len(parts) > 1 else ""
    times = time_part.split("-")
    if len(times) != 2:
        return None
    try:
        sh, sm = map(int, times[0].split(":"))
        eh, em = map(int, times[1].split(":"))
    except Exception:
        return None
    start_min = sh * 60 + sm
    end_min = eh * 60 + em

    days: set = set()
    if days_part:
        if "-" in days_part and "," not in days_part:
            p = days_part.split("-")
            if len(p) == 2:
                try:
                    a, b = int(p[0]), int(p[1])
                    days = set(range(a, b + 1))
                except Exception:
                    return None
        else:
            try:
                days = {int(x) for x in days_part.replace("-", ",").split(",") if x.strip()}
            except Exception:
                return None
    return start_min, end_min, days


def _should_be_online(schedule: str, tz) -> bool | None:
    """Return True/False or None if no schedule."""
    parsed = _parse_schedule_for_check(schedule)
    if parsed is None:
        return None
    start_min, end_min, days = parsed
    import datetime
    now = datetime.datetime.now(tz)
    iso_day = now.isoweekday()  # 1=Mon, 7=Sun
    if days and iso_day not in days:
        return False
    cur_min = now.hour * 60 + now.minute
    if start_min < end_min:
        return start_min <= cur_min < end_min
    # overnight schedule (e.g. 22:00-06:00)
    return cur_min >= start_min or cur_min < end_min


async def _work_schedule_loop() -> None:
    tz = _get_tz()
    while True:
        await asyncio.sleep(60)
        try:
            _apply_work_schedules(tz)
        except Exception:
            logger.exception("work_schedule_loop error")


def _apply_work_schedules(tz) -> None:
    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        for widget in dbm.widget_list(conn):
            schedule = dbm.widget_get_work_schedule(conn, widget["key"])
            if not schedule:
                continue
            should_online = _should_be_online(schedule, tz)
            if should_online is None:
                continue
            current = int(widget.get("enabled") or 0)
            want = 1 if should_online else 0
            if current != want:
                offline_msg = widget.get("offline_msg") or ""
                dbm.widget_set_enabled(conn, widget["key"], want, offline_msg if want == 0 else None)
                logger.info(
                    "work_schedule: key=%s -> %s (schedule=%s)",
                    widget["key"], "online" if want else "offline", schedule,
                )


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("WEBCHAT_BOT_TOKEN not set")
    main_bot = get_main_bot()
    try:
        await setup_main_bot_commands(main_bot)
    except Exception as exc:
        print(f"设置中文命令说明失败：{exc}")
    with contextlib.closing(dbm.get_conn(DB_PATH)) as conn:
        dbm.init_db(conn)
        for binding in dbm.bot_binding_list(conn, enabled_only=True):
            token = binding.get("bot_token") or ""
            if not token or token == BOT_TOKEN:
                continue
            customer_bot = Bot(token)
            try:
                me = await customer_bot.get_me()
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await customer_bot.session.close()
                print(f"Load customer bot failed: key={binding.get('key')}, id={binding.get('id')}, error={exc}")
                continue
            binding["bot_username"] = binding.get("bot_username") or (me.username or "")
            await activate_customer_bot_binding(binding, customer_bot, start_polling=True)
            print(f"Loaded customer bot @{binding.get('bot_username') or me.username or binding['id']} for key={binding['key']}")

    asyncio.create_task(_work_schedule_loop())
    try:
        await dp.start_polling(main_bot)
    finally:
        await shutdown_customer_bots()


__all__ = ["main", "dp"]
