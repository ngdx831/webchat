# /www/wwwroot/webchat/config.py
import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 运行时数据默认放在项目内 data/ 目录；生产环境可通过环境变量覆盖。
DATA_DIR = os.path.join(BASE_DIR, "data")

# ===================== 1) Telegram 配置 =====================

# 主 Bot Token 只从环境变量读取，不要把真实 Token 写入代码仓库。
BOT_TOKEN = os.getenv("WEBCHAT_BOT_TOKEN", "").strip()

# 修改这里：多个管理员 Telegram 用户 ID
ADMIN_IDS = {
    1316912879,
    8257830578,
    8154319235,
}

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

# ===================== 6) 客服系统媒体文件落盘目录 =====================

# 默认落在项目内 data/media；生产可通过 WEBCHAT_MEDIA_ROOT 指向 Nginx 托管目录，
# 例如：export WEBCHAT_MEDIA_ROOT=/www/wwwroot/kefu.ws/webchat/media
WEBCHAT_MEDIA_ROOT = os.getenv("WEBCHAT_MEDIA_ROOT", "").strip() or os.path.join(DATA_DIR, "media")
