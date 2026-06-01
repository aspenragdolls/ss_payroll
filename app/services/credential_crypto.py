import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(get_settings().secret_key.encode()).digest()
    )
    return Fernet(key)


def encrypt_credential(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_credential(encrypted: str) -> str:
    return _fernet().decrypt(encrypted.encode()).decode()
