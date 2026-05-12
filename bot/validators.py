import re


KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
SOURCE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
RESERVED_KEYS = {"api", "assets", "favicon.ico", "health", "internal", "robots.txt", "static", "webchat", "widget"}


def validate_key(k: str) -> str:
    k2 = (k or "").strip()
    if not k2:
        raise ValueError("BAD_KEY_EMPTY")
    kl = k2.lower()
    if kl in RESERVED_KEYS or kl.startswith("api"):
        raise ValueError("BAD_KEY_RESERVED")
    if not KEY_RE.fullmatch(k2):
        raise ValueError("BAD_KEY_FORMAT")
    return k2


def explain_key_error(code: str) -> str:
    if code == "BAD_KEY_EMPTY":
        return "❌ key 不能为空"
    if code == "BAD_KEY_RESERVED":
        return "❌ key 禁止使用（保留字，或以 api 开头）"
    if code == "BAD_KEY_FORMAT":
        return "❌ key 格式不合法：仅允许英文/数字/_/-，长度 1~32，且必须英文/数字开头"
    return f"❌ 参数错误：{code}"


def validate_source_code(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return value if SOURCE_RE.fullmatch(value) else ""


def html_escape(s: str) -> str:
    s = s or ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))
