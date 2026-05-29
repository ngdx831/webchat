import logging
from threading import Lock
from typing import Any, Dict

import requests

import db as dbm
from config import BOT_TOKEN
from shared.errors import TelegramAPIError, scrub_secrets
from shared.session_presentation import format_session_header_html, make_topic_name


logger = logging.getLogger(__name__)
_session = requests.Session()
_session.headers.update({"User-Agent": "webchat/1.0"})


def tg_call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise TelegramAPIError(0, "BOT_TOKEN_NOT_CONFIGURED", method)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = _session.post(url, json=payload, timeout=(3, 10))
    except requests.RequestException as e:
        # 注意:不要直接把 e 转字符串放到外层(可能含 URL+token)。
        logger.warning("tg_call network error: method=%s err=%s", method, scrub_secrets(repr(e)))
        raise TelegramAPIError(0, "NETWORK_ERROR", method) from None

    status = r.status_code
    try:
        data = r.json()
    except ValueError:
        logger.warning("tg_call non-json response: method=%s status=%s", method, status)
        raise TelegramAPIError(status, "BAD_RESPONSE", method) from None

    if status >= 400 or not data.get("ok"):
        description = str(data.get("description") or "").strip() or f"HTTP_{status}"
        logger.warning("tg_call api error: method=%s status=%s desc=%s", method, status, scrub_secrets(description))
        raise TelegramAPIError(status, description, method)
    return data


def tg_create_topic(forum_chat_id: int, topic_name: str) -> int:
    data = tg_call("createForumTopic", {"chat_id": forum_chat_id, "name": topic_name})
    return int(data["result"]["message_thread_id"])


def tg_delete_topic(forum_chat_id: int, thread_id: int) -> None:
    """删除话题及其全部消息。

    `deleteForumTopic` 在 TG 端是原子操作，话题连同里面的全部消息一起消失，
    不再回退到 closeForumTopic（那只是关闭话题，消息会留在群里），
    这样满足"会话过期 → 客服群消息和话题一起删除"的语义。

    话题已被人工删除 / 不存在时，TG 会返回 "message thread not found" / "topic was deleted"
    等描述，我们当作幂等成功。其他错误（权限不足、网络）原样抛出，调用方记录日志。
    """
    payload = {"chat_id": int(forum_chat_id), "message_thread_id": int(thread_id)}
    try:
        tg_call("deleteForumTopic", payload)
    except TelegramAPIError as exc:
        desc = (exc.description or "").lower()
        if (
            "message thread not found" in desc
            or "topic_deleted" in desc
            or "topic was deleted" in desc
            or "thread not found" in desc
        ):
            return
        raise


def tg_send_message(forum_chat_id: int, thread_id: int, text: str) -> None:
    tg_call("sendMessage", {
        "chat_id": forum_chat_id,
        "message_thread_id": thread_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def tg_send_photo_file(forum_chat_id: int, thread_id: int, file_path: str, caption: str = "") -> None:
    if not BOT_TOKEN:
        raise TelegramAPIError(0, "BOT_TOKEN_NOT_CONFIGURED", "sendPhoto")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {"chat_id": forum_chat_id, "message_thread_id": thread_id}
    if caption:
        data["caption"] = caption
    try:
        with open(file_path, "rb") as f:
            r = _session.post(url, data=data, files={"photo": f}, timeout=(5, 30))
    except requests.RequestException as e:
        logger.warning("tg_send_photo_file network error: %s", scrub_secrets(repr(e)))
        raise TelegramAPIError(0, "NETWORK_ERROR", "sendPhoto") from None
    try:
        resp_data = r.json()
    except ValueError:
        raise TelegramAPIError(r.status_code, "BAD_RESPONSE", "sendPhoto") from None
    if r.status_code >= 400 or not resp_data.get("ok"):
        desc = str(resp_data.get("description") or "").strip() or f"HTTP_{r.status_code}"
        raise TelegramAPIError(r.status_code, desc, "sendPhoto")


def tg_send_document_file(forum_chat_id: int, thread_id: int, file_path: str, file_name: str = "", caption: str = "") -> None:
    if not BOT_TOKEN:
        raise TelegramAPIError(0, "BOT_TOKEN_NOT_CONFIGURED", "sendDocument")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    data = {"chat_id": forum_chat_id, "message_thread_id": thread_id}
    if caption:
        data["caption"] = caption
    try:
        fname = file_name or "file"
        with open(file_path, "rb") as f:
            r = _session.post(url, data=data, files={"document": (fname, f)}, timeout=(5, 30))
    except requests.RequestException as e:
        logger.warning("tg_send_document_file network error: %s", scrub_secrets(repr(e)))
        raise TelegramAPIError(0, "NETWORK_ERROR", "sendDocument") from None
    try:
        resp_data = r.json()
    except ValueError:
        raise TelegramAPIError(r.status_code, "BAD_RESPONSE", "sendDocument") from None
    if r.status_code >= 400 or not resp_data.get("ok"):
        desc = str(resp_data.get("description") or "").strip() or f"HTTP_{r.status_code}"
        raise TelegramAPIError(r.status_code, desc, "sendDocument")


def tg_get_file_url(file_id: str) -> str:
    if not BOT_TOKEN:
        raise TelegramAPIError(0, "BOT_TOKEN_NOT_CONFIGURED", "getFile")
    data = tg_call("getFile", {"file_id": file_id})
    file_path = data["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


def _send_session_header(
    forum_chat_id: int,
    thread_id: int,
    session_id: str,
    key: str,
    display_name: str,
    enabled: int,
    offline_msg: str,
    channel: str,
    source_code: str,
) -> None:
    header = format_session_header_html(
        session_id=session_id,
        key=key,
        display_name=display_name,
        enabled=enabled,
        offline_msg=offline_msg,
        channel=channel,
        source_code=source_code,
    )
    tg_send_message(forum_chat_id, int(thread_id), header)


_thread_locks: Dict[str, "Lock"] = {}
_thread_locks_guard = Lock()


def _session_thread_lock(session_id: str) -> "Lock":
    with _thread_locks_guard:
        lock = _thread_locks.get(session_id)
        if lock is None:
            lock = Lock()
            _thread_locks[session_id] = lock
        return lock


def ensure_thread(
    conn,
    session_id: str,
    forum_chat_id: int,
    key: str,
    display_name: str,
    enabled: int,
    offline_msg: str,
    channel: str = "web",
    source_code: str = "",
    force_new: bool = False,
) -> int:
    """确保 session 有可用 thread_id。

    force_new=True: 无论原 thread_id 是什么，都新建话题并覆盖（用于话题被手动删除/关闭的情况）。
    串行化:同一 session 同一时刻只有一个调用方在创建话题,避免重复 createForumTopic。
    """
    lock = _session_thread_lock(session_id)
    with lock:
        s = dbm.session_get(conn, session_id) or {}
        thread_id = s.get("thread_id")

        if (not force_new) and thread_id:
            return int(thread_id)

        topic_name = make_topic_name(display_name, key, source_code)
        thread_id = tg_create_topic(int(forum_chat_id), topic_name)
        try:
            dbm.session_set_thread(conn, session_id, int(thread_id))
        except Exception:
            # 半成功补偿:话题已建但 DB 没记下,主动删除避免泄漏空话题。
            try:
                tg_delete_topic(int(forum_chat_id), int(thread_id))
            except Exception:
                logger.exception("tg_delete_topic compensation failed")
            raise
        try:
            _send_session_header(
                int(forum_chat_id),
                int(thread_id),
                session_id,
                key,
                display_name,
                enabled,
                offline_msg,
                channel,
                source_code,
            )
        except TelegramAPIError:
            # header 发送失败不致命,留 log 即可,thread_id 仍然有效。
            logger.warning("session header send failed: session=%s", session_id)
        return int(thread_id)
