import traceback

from flask import Flask

from config import API_HOST, API_PORT, BOT_TOKEN

from .routes import ALL_BLUEPRINTS
from .validators import json_error


def create_app() -> Flask:
    app = Flask(__name__)
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(Exception)
    def _handle_any_error(e: Exception):
        print(f"ERROR: {e}")
        traceback.print_exc()
        return json_error(500, "INTERNAL_ERROR", {"detail": str(e)})

    return app


def main() -> None:
    if not BOT_TOKEN:
        print("WARNING: WEBCHAT_BOT_TOKEN not set")
    app = create_app()
    print(f"Starting API server on {API_HOST}:{API_PORT}")
    app.run(host=API_HOST, port=API_PORT, threaded=True)


__all__ = ["create_app", "main"]
