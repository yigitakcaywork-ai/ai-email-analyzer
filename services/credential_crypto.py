import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    secret = os.getenv("FLASK_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("FLASK_SECRET_KEY .env dosyasında bulunamadı.")

    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    return _get_fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        return _get_fernet().decrypt(text.encode("utf-8")).decode("utf-8")
    except InvalidToken as error:
        raise RuntimeError(
            "Gmail bağlantı bilgileri çözülemedi. Gmail hesabını yeniden bağlayın."
        ) from error
