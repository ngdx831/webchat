# /www/wwwroot/webchat/config.py
import logging
import os


logger = logging.getLogger(__name__)

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 运行时数据默认放在项目内 data/ 目录；生产环境可通过环境变量覆盖。
DATA_DIR = os.path.join(BASE_DIR, "data")

# ===================== 1) Telegram 配置 =====================

# 主 Bot Token 只从环境变量读取，不要把真实 Token 写入代码仓库。
BOT_TOKEN = os.getenv("WEBCHAT_BOT_TOKEN", "").strip()

# 客户侧 Bot Token 落盘加密密钥。必须是 Fernet.generate_key() 生成的
# 32 字节 URL-safe base64 字符串。
WEBCHAT_TOKEN_KEY = os.getenv("WEBCHAT_TOKEN_KEY", "").strip()
if not WEBCHAT_TOKEN_KEY:
    raise RuntimeError(
        "WEBCHAT_TOKEN_KEY is required. Generate one with: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

# 默认管理员 Telegram 用户 ID；生产环境建议用 WEBCHAT_ADMIN_IDS 覆盖。
_DEFAULT_ADMIN_IDS = {
    1316912879,
    8257830578,
    8154319235,
}


def _parse_admin_ids(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return set(_DEFAULT_ADMIN_IDS)
    ids = set()
    invalid = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError:
            invalid.append(value)
    if invalid:
        logger.warning("Invalid WEBCHAT_ADMIN_IDS entries ignored: %s", ",".join(invalid))
    return ids


ADMIN_IDS = _parse_admin_ids(os.getenv("WEBCHAT_ADMIN_IDS", ""))

# ===================== 2) 数据库路径 =====================

# 客服系统数据库（会话/事件）。可通过 WEBCHAT_DB_PATH 覆盖。
DB_PATH = os.getenv("WEBCHAT_DB_PATH", "").strip() or os.path.join(DATA_DIR, "webchat.db")

# ===================== 3) 清理策略 =====================

# 客服会话过期时间（秒）
# 会话创建超过约 2 个月，或最后一次对话超过约 2 个月，会自动删除。
SESSION_TTL_SECONDS = 60 * 24 * 60 * 60
SESSION_IDLE_TTL_SECONDS = 60 * 24 * 60 * 60
MEDIA_TTL_SECONDS = 3 * 24 * 60 * 60

# 兼容旧配置名：事件跟随会话删除，不再单独提前清理。
EVENT_TTL_SECONDS = SESSION_TTL_SECONDS

# 展示给客户的等待提示。
CUSTOMER_WAITING_HINT = "客服可能正在处理其他咨询，回复不及时请稍等几分钟，我们会尽快回复您。"

# ===================== 4) API 服务监听 =====================

# 只给 Nginx 反代用，保持 127.0.0.1 更安全
API_HOST = "127.0.0.1"
API_PORT = 5055

# ===================== 5) 简单限流 =====================

# 同一个 IP 每 60 秒最多发多少次消息到客服
RATE_LIMIT_PER_60S = 24

# 可信代理 CIDR 列表（逗号分隔）。只有来自这些代理的请求才会读取 X-Real-IP /
# X-Forwarded-For;默认仅信任本机回环。
TRUSTED_PROXIES = os.getenv("WEBCHAT_TRUSTED_PROXIES", "127.0.0.0/8").strip()

# ===================== 5b) 内部接口鉴权 =====================

# /internal/notify 必须带的 Bearer Token;Bot 进程与 API 进程共享同一个值。
# 未设置时,启动会自动生成一个临时 token(写入 data/.internal_token),
# 防止裸启动也能被攻击者利用;生产请务必显式设置 WEBCHAT_INTERNAL_TOKEN。
INTERNAL_NOTIFY_TOKEN = os.getenv("WEBCHAT_INTERNAL_TOKEN", "").strip()

# ===================== 5c) 输入上限 =====================

# 单条客户消息最大字符数(防止单条 GB 级文本拖垮后端)
MAX_TEXT_LENGTH = 3500

# 单次 HTTP 请求体最大字节数(Flask 全局 MAX_CONTENT_LENGTH)
MAX_REQUEST_BYTES = 64 * 1024

# 欢迎语 / 离线语 / 快捷回复等富文本字段的最大字符数
MAX_RICH_TEXT_LENGTH = 4000

# ===================== 6) 客服系统媒体文件落盘目录 =====================

# 默认落在项目根目录 media/；项目目录变化时会跟随 BASE_DIR。
WEBCHAT_MEDIA_ROOT = os.path.abspath(os.getenv("WEBCHAT_MEDIA_ROOT", "").strip() or os.path.join(BASE_DIR, "media"))


def _resolved_internal_token() -> str:
    if INTERNAL_NOTIFY_TOKEN:
        return INTERNAL_NOTIFY_TOKEN
    import secrets
    token_path = os.path.join(DATA_DIR, ".internal_token")
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            existing = (f.read() or "").strip()
            if existing:
                return existing
    except FileNotFoundError:
        pass
    except OSError:
        return secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(token)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return token


# 真正生效的内部通知 token,API 进程与 Bot 进程通过 import 都会拿到同一个值。
RESOLVED_INTERNAL_TOKEN = _resolved_internal_token()
