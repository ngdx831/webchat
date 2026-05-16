import re
import secrets
import string


def html_escape(value: str) -> str:
    value = value or ""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def random_topic_code(length: int = 6) -> str:
    alphabet = string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(1, int(length))))


def make_topic_name(
    display_name: str,
    key: str,
    source_code: str = "",
    *,
    random_code: str | None = None,
    max_length: int = 80,
) -> str:
    name = _compact(display_name) or _compact(key) or "客户"
    code = _compact(random_code or random_topic_code(6))
    source = _compact(source_code)
    suffix_parts = [code]
    if source:
        suffix_parts.append(source)
    suffix = "-".join(suffix_parts)
    full = f"{name}-{suffix}"
    if len(full) <= max_length:
        return full

    room = max_length - len(suffix) - 1
    if room <= 0:
        return full[:max_length]
    return f"{name[:room].rstrip()}-{suffix}"[:max_length]


def channel_status_label(channel: str, enabled: int) -> str:
    side = "机器人侧" if (channel or "").lower() == "telegram" else "网页"
    status = "离线留言" if int(enabled or 0) == 0 else "在线咨询"
    return f"{side}{status}"


def entry_label_html(display_name: str, key: str) -> str:
    display = _compact(display_name) or _compact(key) or "客服入口"
    key_value = _compact(key)
    if key_value and key_value != display:
        return f"<b>{html_escape(display)}</b>（<code>{html_escape(key_value)}</code>）"
    return f"<b>{html_escape(display)}</b>"


def format_session_header_html(
    *,
    session_id: str,
    key: str,
    display_name: str,
    enabled: int,
    offline_msg: str,
    channel: str,
    source_code: str = "",
) -> str:
    lines = [
        "🔔 <b>新咨询</b>",
        f"入口：{entry_label_html(display_name, key)}",
        f"状态：<b>{html_escape(channel_status_label(channel, enabled))}</b>",
    ]
    if int(enabled or 0) == 0 and offline_msg:
        lines.append(f"离线提示：{html_escape(offline_msg)}")
    if source_code:
        lines.append(f"统计来源：<code>{html_escape(source_code)}</code>")
    lines.extend([
        f"会话：<code>{html_escape(session_id)}</code>",
        "——",
    ])
    return "\n".join(lines)
