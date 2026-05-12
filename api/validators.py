import re
from typing import Any, Dict, Optional

from flask import jsonify


KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
RESERVED_KEYS = {"api", "assets", "favicon.ico", "health", "internal", "robots.txt", "static", "webchat", "widget"}
SOURCE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def html_escape(s: str) -> str:
    s = s or ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def json_error(status: int, code: str, extra: Optional[Dict[str, Any]] = None):
    payload = {"ok": False, "error": code}
    if extra:
        payload.update(extra)
    return jsonify(payload), status


def validate_key_api(k: str) -> Optional[str]:
    k2 = (k or "").strip()
    if not k2:
        return None
    kl = k2.lower()
    if kl in RESERVED_KEYS or kl.startswith("api"):
        return None
    if not KEY_RE.fullmatch(k2):
        return None
    return k2


def validate_source_code(s: str) -> str:
    s2 = (s or "").strip()
    if not s2:
        return ""
    if not SOURCE_RE.fullmatch(s2):
        return ""
    return s2
