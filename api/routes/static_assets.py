from flask import Blueprint, send_from_directory

from ..paths import PUBLIC_DIR


bp = Blueprint("static_assets", __name__)


@bp.get("/chat.css")
def chat_css():
    return send_from_directory(PUBLIC_DIR, "chat.css", mimetype="text/css")


@bp.get("/chat.js")
def chat_js():
    return send_from_directory(PUBLIC_DIR, "chat.js", mimetype="application/javascript")
