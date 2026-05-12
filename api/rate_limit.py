import hmac
import time
from ipaddress import ip_address, ip_network
from typing import Dict, List, Tuple

from flask import request

from config import RATE_LIMIT_PER_60S, RESOLVED_INTERNAL_TOKEN, TRUSTED_PROXIES


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


def _parse_networks(raw: str) -> Tuple:
    nets = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(nets)


_TRUSTED_NETWORKS = _parse_networks(TRUSTED_PROXIES)


def _is_trusted_remote(remote_addr: str) -> bool:
    try:
        addr = ip_address((remote_addr or "").strip())
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_NETWORKS)


def client_ip_for_rate_limit() -> str:
    """限流键:默认用 remote_addr;仅当来源在可信代理白名单时才采信 X-Real-IP。

    这样攻击者无法通过伪造 X-Real-IP 头绕过 IP 计数。
    """
    remote_addr = (request.remote_addr or "").strip()
    if remote_addr and _is_trusted_remote(remote_addr):
        forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        for candidate in (real_ip, forwarded_for):
            if candidate:
                try:
                    ip_address(candidate)
                except ValueError:
                    continue
                return candidate
    return remote_addr or "0.0.0.0"


def internal_notify_allowed() -> bool:
    """/internal/notify 鉴权:必须带正确的 Bearer Token。

    不再信任 X-Forwarded-For / X-Real-IP,这些头是 Nginx 透传的,
    任何外部攻击者都能伪造。
    """
    expected = RESOLVED_INTERNAL_TOKEN
    if not expected:
        return False
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return False
    provided = auth[7:].strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)
