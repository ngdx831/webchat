import logging
from typing import Dict

import requests

from config import BOT_TOKEN
from shared.errors import TelegramAPIError, scrub_secrets


logger = logging.getLogger(__name__)


def _do_call(token: str, method: str, payload: Dict) -> Dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        logger.warning("tg http error: method=%s err=%s", method, scrub_secrets(repr(e)))
        raise TelegramAPIError(0, "NETWORK_ERROR", method) from None

    status = r.status_code
    try:
        data = r.json()
    except ValueError:
        raise TelegramAPIError(status, "BAD_RESPONSE", method) from None

    if status >= 400 or not data.get("ok"):
        description = str(data.get("description") or "").strip() or f"HTTP_{status}"
        logger.warning("tg api error: method=%s status=%s desc=%s", method, status, scrub_secrets(description))
        raise TelegramAPIError(status, description, method)
    return data


def tg_http_call(method: str, payload: Dict) -> Dict:
    return _do_call(BOT_TOKEN, method, payload)


def tg_http_call_with_token(token: str, method: str, payload: Dict) -> Dict:
    return _do_call(token, method, payload)


def tg_get_file_path(file_id: str) -> str:
    data = tg_http_call("getFile", {"file_id": file_id})
    return data["result"]["file_path"]


def tg_get_file_path_with_token(token: str, file_id: str) -> str:
    data = tg_http_call_with_token(token, "getFile", {"file_id": file_id})
    return data["result"]["file_path"]


def download_file_to(path_url: str, dest_path: str) -> None:
    with requests.get(path_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
