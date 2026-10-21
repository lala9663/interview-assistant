"""Candidate.encrypted_identity <-> KnownIdentity. Raw zone only."""

from __future__ import annotations

import json

from interview_assistant.crypto import FieldCipher
from interview_assistant.deid.types import KnownIdentity


def seal_identity(cipher: FieldCipher, identity: KnownIdentity) -> str:
    return cipher.encrypt(json.dumps(identity.to_dict(), ensure_ascii=False))


def open_identity(cipher: FieldCipher, sealed: str) -> KnownIdentity:
    return KnownIdentity.from_dict(json.loads(cipher.decrypt(sealed)))
