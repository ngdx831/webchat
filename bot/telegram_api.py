from typing import Dict

import requests

from config import BOT_TOKEN


def tg_http_call(method: str, payload: Dict) -> Dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"TG_API_ERROR:{data}")
    return data


def tg_http_call_with_token(token: str, method: str, payload: Dict) -> Dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"TG_API_ERROR:{data}")
    return data


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
