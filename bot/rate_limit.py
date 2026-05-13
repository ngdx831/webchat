"""主 Bot 对 Telegram 的全局发包限速。

Telegram 文档给 Bot 设的全局上限大约是 30 msg/s,超出后会返回
TelegramRetryAfter。这里在客户端侧做 token bucket,把主 Bot 的发包速率
压在 25/s,留出余量,避免高峰期撞限速、整段会话卡顿。

只覆盖主 Bot(forum 话题、客服回复给客户的入口);客户侧 Bot 各自有自己
的限额,不在这里统一计入。
"""
import asyncio
import logging
import time
from typing import Awaitable, Callable, TypeVar

from aiogram.exceptions import TelegramRetryAfter


logger = logging.getLogger(__name__)
T = TypeVar("T")


class AsyncTokenBucket:
    def __init__(self, rate: float, burst: int):
        self.rate = float(rate)
        self.capacity = int(burst)
        self.tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    float(self.capacity),
                    self.tokens + (now - self._last) * self.rate,
                )
                self._last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
            await asyncio.sleep(max(wait, 0.005))


# 25/s 的速率 + 25 的突发桶容量,留 Telegram 30/s 上限约 17% 余量。
main_bot_bucket = AsyncTokenBucket(rate=25.0, burst=25)


async def safe_main_bot_call(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """获取一个 token 再调用主 Bot API。撞到 flood control 时按 Telegram 返回
    的 retry_after 等待并重试一次。"""
    await main_bot_bucket.acquire()
    try:
        return await coro_factory()
    except TelegramRetryAfter as exc:
        wait = float(getattr(exc, "retry_after", 1) or 1) + 0.5
        logger.warning("main bot hit Telegram flood control, sleeping %.1fs", wait)
        await asyncio.sleep(wait)
        await main_bot_bucket.acquire()
        return await coro_factory()
