"""共享错误类型与脱敏工具,集中处理 Telegram Bot Token 等敏感值。"""
import re


_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def scrub_secrets(text: str) -> str:
    """从任意字符串中去掉形如 'bot<digits>:<secret>' 的 Telegram token。"""
    if not text:
        return ""
    return _BOT_TOKEN_RE.sub("bot***", str(text))


class TelegramAPIError(Exception):
    """统一封装 Telegram Bot API 调用错误。

    永远不在 __str__ 中暴露完整 URL 或 token,只携带 HTTP 状态与描述。
    """

    def __init__(self, status: int = 0, description: str = "", method: str = ""):
        self.status = int(status or 0)
        self.description = scrub_secrets(description or "")
        self.method = method or ""
        super().__init__(self.description or "TELEGRAM_API_ERROR")

    def __str__(self) -> str:
        if self.status:
            return f"TG_API_ERROR[{self.status}]: {self.description}"
        return f"TG_API_ERROR: {self.description}" if self.description else "TG_API_ERROR"
