"""Column encryption for identifying data (Fernet, key from IA_ENCRYPTION_KEY).

Fernet ciphertext is randomized, so it cannot be searched. `lookup_hash` gives a keyed,
deterministic HMAC of a value instead: it answers "have we seen this value before?" without
decrypting anything. The HMAC key is derived from the Fernet key, so there is one secret to
manage.

Generate a key:
    uv run python -c "from interview_assistant.crypto import FieldCipher as F; print(F.generate_key())"
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from interview_assistant.config import Settings

__all__ = ["FieldCipher", "InvalidToken", "MissingEncryptionKey"]

_LOOKUP_KEY_LABEL = b"interview-assistant/lookup-hash/v1"


class MissingEncryptionKey(RuntimeError):
    pass


class FieldCipher:
    def __init__(self, key: str | bytes) -> None:
        key_bytes = key.encode("ascii") if isinstance(key, str) else key
        self._fernet = Fernet(key_bytes)
        self._lookup_key = hmac.new(key_bytes, _LOOKUP_KEY_LABEL, hashlib.sha256).digest()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> FieldCipher:
        settings = settings or Settings()
        if settings.encryption_key is None:
            raise MissingEncryptionKey(
                "IA_ENCRYPTION_KEY is not set. Generate one with "
                "FieldCipher.generate_key() and put it in .env."
            )
        return cls(settings.encryption_key.get_secret_value())

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")

    def lookup_hash(self, *parts: str) -> str:
        message = "\x1f".join(parts).encode("utf-8")
        return hmac.new(self._lookup_key, message, hashlib.sha256).hexdigest()
