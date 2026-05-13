from config import WEBCHAT_TOKEN_KEY

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - exercised when dependency is not installed.
    Fernet = None
    InvalidToken = Exception


_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    if Fernet is None:
        raise RuntimeError("cryptography is required for WEBCHAT_TOKEN_KEY encryption")
    _fernet = Fernet(WEBCHAT_TOKEN_KEY.encode("utf-8"))
    return _fernet


def encrypt_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        raise ValueError("EMPTY_TOKEN")
    return _get_fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        raise ValueError("EMPTY_TOKEN")
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("INVALID_TOKEN_CIPHERTEXT") from exc
