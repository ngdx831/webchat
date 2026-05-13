import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from config import API_HOST, API_PORT, BOT_TOKEN, MAX_REQUEST_BYTES
from shared.errors import scrub_secrets

from .db_helpers import close_db_conn
from .routes import ALL_BLUEPRINTS
from .validators import json_error


logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = int(MAX_REQUEST_BYTES)
    app.teardown_appcontext(close_db_conn)

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(404)
    def _handle_404(_e):
        return json_error(404, "NOT_FOUND")

    @app.errorhandler(405)
    def _handle_405(_e):
        return json_error(405, "METHOD_NOT_ALLOWED")

    @app.errorhandler(413)
    def _handle_413(_e):
        return json_error(413, "REQUEST_TOO_LARGE")

    @app.errorhandler(HTTPException)
    def _handle_http(e: HTTPException):
        return json_error(e.code or 500, (e.name or "HTTP_ERROR").upper().replace(" ", "_"))

    @app.errorhandler(Exception)
    def _handle_any_error(e: Exception):
        # 真异常细节只进日志(已脱敏);响应只给上层调用方稳定的 error code。
        logger.exception("unhandled error: %s", scrub_secrets(repr(e)))
        return json_error(500, "INTERNAL_ERROR")

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        logger.warning("WEBCHAT_BOT_TOKEN not set")
    app = create_app()
    logger.info("Starting API server on %s:%s", API_HOST, API_PORT)
    app.run(host=API_HOST, port=API_PORT, threaded=True)


__all__ = ["create_app", "main"]
