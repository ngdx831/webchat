import time
from ipaddress import ip_address
from typing import Dict, List

from flask import request

from config import RATE_LIMIT_PER_60S


_rate_bucket: Dict[str, List[float]] = {}


def allow_rate(ip: str) -> bool:
    now = time.time()
    b = _rate_bucket.get(ip, [])
    b = [x for x in b if now - x < 60]
    if len(b) >= RATE_LIMIT_PER_60S:
        _rate_bucket[ip] = b
        return False
    b.append(now)
    _rate_bucket[ip] = b
    return True


def _is_internal_ip(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    try:
        parsed = ip_address(value)
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_private


def _internal_notify_client_ip() -> str:
    remote_addr = (request.remote_addr or "").strip()
    if _is_internal_ip(remote_addr):
        forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        if forwarded_for:
            return forwarded_for
        if real_ip:
            return real_ip
    return remote_addr


def internal_notify_allowed() -> bool:
    return _is_internal_ip(_internal_notify_client_ip())
