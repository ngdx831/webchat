"""Importing this package triggers @dp.message decorator registration for every handler module.

Order matters: aiogram dispatches in registration order, so the catch-all
`@dp.message()` handler in `messages` must be imported LAST.
"""
from . import basic  # noqa: F401
from . import user_keys  # noqa: F401
from . import binding  # noqa: F401
from . import admin_users  # noqa: F401
from . import admin_entries  # noqa: F401
from . import customer_bots  # noqa: F401
from . import key_actions  # noqa: F401
from . import quick_replies  # noqa: F401
from . import stats  # noqa: F401
from . import session_cmds  # noqa: F401
from . import messages  # noqa: F401  # MUST be last — contains catch-all `@dp.message()`


def register_all(dispatcher=None) -> None:
    """No-op kept for symmetry with the architecture spec — handlers register themselves on import."""
    return None
