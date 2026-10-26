"""Request signing between the recruiting site and this system (docs/site-intake-spec.md 4장).

    string_to_sign = f"{timestamp}\\n{METHOD}\\n{path}\\n{sha256_hex(body)}"
    X-Intake-Timestamp: 1793000000                      (unix seconds)
    X-Intake-Signature: v1=<hex HMAC-SHA256(secret, string_to_sign)>

The timestamp bounds a replay to the allowed clock skew; within that window the event_id makes a
replayed request idempotent. Method and path are signed so a captured request cannot be replayed
against another endpoint, and the body hash covers every byte of a multipart upload. During a
key change the server accepts the current and the previous secret, and a sender may send one
`v1=` value per key, comma separated.

Both sides use this module: the API to verify, the fake recruiting site (scripts/) to sign.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterable, Mapping

TIMESTAMP_HEADER = "X-Intake-Timestamp"
SIGNATURE_HEADER = "X-Intake-Signature"
VERSION = "v1"


class SignatureError(Exception):
    """`code`: missing_signature, invalid_signature or stale_timestamp. The message is safe to
    return; it never echoes what was sent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def string_to_sign(timestamp: str, method: str, path: str, body: bytes) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return f"{timestamp}\n{method.upper()}\n{path}\n{digest}".encode()


def sign(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), string_to_sign(timestamp, method, path, body), hashlib.sha256)
    return f"{VERSION}={mac.hexdigest()}"


def signed_headers(
    secret: str, method: str, path: str, body: bytes, *, now: float | None = None
) -> dict[str, str]:
    timestamp = str(int(time.time() if now is None else now))
    return {
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: sign(secret, timestamp, method, path, body),
    }


def verify(
    secrets: Iterable[str],
    headers: Mapping[str, str],
    method: str,
    path: str,
    body: bytes,
    *,
    skew: int = 300,
    now: float | None = None,
) -> None:
    """Raises SignatureError unless one of `secrets` signed this exact request recently."""
    timestamp = headers.get(TIMESTAMP_HEADER) or headers.get(TIMESTAMP_HEADER.lower())
    signature = headers.get(SIGNATURE_HEADER) or headers.get(SIGNATURE_HEADER.lower())
    if not timestamp or not signature:
        raise SignatureError("missing_signature", "서명 헤더가 없습니다.")
    if not timestamp.isdigit():
        raise SignatureError("invalid_signature", "서명 시각 형식이 맞지 않습니다 (유닉스 초).")
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > skew:
        raise SignatureError(
            "stale_timestamp", f"서명 시각이 서버 시각과 {skew}초 넘게 차이 납니다. 새로 서명해 보내세요."
        )
    offered = [
        part.strip()[len(VERSION) + 1 :]
        for part in signature.split(",")
        if part.strip().startswith(f"{VERSION}=")
    ]
    for secret in secrets:
        expected = sign(secret, timestamp, method, path, body)[len(VERSION) + 1 :]
        if any(hmac.compare_digest(expected, value) for value in offered):
            return
    raise SignatureError("invalid_signature", "서명이 맞지 않습니다.")
