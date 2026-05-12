import asyncio
import os
from contextlib import suppress
from datetime import datetime

from config import BOT_TOKEN, WEBCHAT_MEDIA_ROOT

from .telegram_api import (
    download_file_to,
    tg_get_file_path,
    tg_get_file_path_with_token,
)


def _public_root_from_media_root() -> str:
    try:
        return os.path.abspath(os.path.join(WEBCHAT_MEDIA_ROOT, os.pardir, os.pardir))
    except Exception:
        return "/www/wwwroot/kefu.ws"


PUBLIC_ROOT = _public_root_from_media_root()


def _try_chown_www(path: str) -> None:
    try:
        if os.geteuid() != 0:
            return
        import pwd, grp
        uid = pwd.getpwnam("www").pw_uid
        gid = grp.getgrnam("www").gr_gid
        os.chown(path, uid, gid)
    except Exception:
        pass


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o775)
    except Exception:
        pass
    _try_chown_www(path)


async def save_webchat_media(file_id: str, file_unique_id: str) -> str:
    """
    下载客服媒体文件到 WEBCHAT_MEDIA_ROOT/YYYYMM/xxx.ext
    返回 rel_path：webchat/media/YYYYMM/xxx.ext
    """
    file_path = await asyncio.to_thread(tg_get_file_path, file_id)
    _, ext = os.path.splitext(file_path)
    ext = ext or ".bin"

    ym = datetime.now().strftime("%Y%m")
    out_dir = os.path.join(WEBCHAT_MEDIA_ROOT, ym)
    ensure_dir(out_dir)

    fname = f"{file_unique_id}{ext}"
    abs_path = os.path.join(out_dir, fname)

    if not os.path.exists(abs_path):
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        await asyncio.to_thread(download_file_to, url, abs_path)
        try:
            os.chmod(abs_path, 0o664)
        except Exception:
            pass
        _try_chown_www(abs_path)

    rel_path = f"webchat/media/{ym}/{fname}"
    return rel_path


async def save_media_from_token(token: str, file_id: str, file_unique_id: str) -> str:
    file_path = await asyncio.to_thread(tg_get_file_path_with_token, token, file_id)
    _, ext = os.path.splitext(file_path)
    ext = ext or ".bin"
    ym = datetime.now().strftime("%Y%m")
    out_dir = os.path.join(WEBCHAT_MEDIA_ROOT, ym)
    ensure_dir(out_dir)
    fname = f"{file_unique_id}{ext}"
    abs_path = os.path.join(out_dir, fname)
    if not os.path.exists(abs_path):
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        await asyncio.to_thread(download_file_to, url, abs_path)
        with suppress(Exception):
            os.chmod(abs_path, 0o664)
        _try_chown_www(abs_path)
    return f"webchat/media/{ym}/{fname}"


def abs_public_path(rel_path: str) -> str:
    return os.path.join(PUBLIC_ROOT, (rel_path or "").lstrip("/\\"))
