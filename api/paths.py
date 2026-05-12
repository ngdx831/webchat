import os

from config import WEBCHAT_MEDIA_ROOT


def _public_root_from_media_root() -> str:
    """从 WEBCHAT_MEDIA_ROOT 推导站点静态根目录（例如 /www/wwwroot/kefu.ws）。"""
    try:
        return os.path.abspath(os.path.join(WEBCHAT_MEDIA_ROOT, os.pardir, os.pardir))
    except Exception:
        return "/www/wwwroot/kefu.ws"


PUBLIC_ROOT = _public_root_from_media_root()
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
