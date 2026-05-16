from flask import Blueprint, send_from_directory

from ..paths import PUBLIC_DIR


bp = Blueprint("static_assets", __name__)


@bp.get("/chat.css")
def chat_css():
    return send_from_directory(PUBLIC_DIR, "chat.css", mimetype="text/css")


@bp.get("/chat.js")
def chat_js():
    return send_from_directory(PUBLIC_DIR, "chat.js", mimetype="application/javascript")


@bp.get("/sw.js")
def service_worker():
    # 必须由根路径提供,这样 Service Worker 才能控制整个站点(/<key> 子路径)。
    # Service-Worker-Allowed 头允许更宽的作用域,避免被 /chat.js 等子路径限制。
    resp = send_from_directory(PUBLIC_DIR, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp
