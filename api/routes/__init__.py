from .health import bp as health_bp
from .widget import bp as widget_bp
from .messages import bp as messages_bp
from .stream import bp as stream_bp
from .media import bp as media_bp
from .internal import bp as internal_bp
from .static_assets import bp as static_assets_bp
from .upload import bp as upload_bp


ALL_BLUEPRINTS = (
    health_bp,
    static_assets_bp,
    widget_bp,
    messages_bp,
    stream_bp,
    media_bp,
    internal_bp,
    upload_bp,
)
