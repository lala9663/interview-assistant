"""App-wide de-identification: config, dictionary and detectors are built once at startup; each
database session gets its own Deidentifier over a SqlTokenStore (tokens persist, encrypted).

    deid = DeidService.from_settings(settings)
    text = deid.deidentify(db, raw_text, candidate)   # tokens in place of identifiers

Every free text that reaches the API from a person (manual answers, typed questions, notes,
uploaded documents, speech) goes through here before it is stored where the API can read it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from interview_assistant.config import Settings
from interview_assistant.crypto import FieldCipher
from interview_assistant.deid.config import (
    DeidConfig,
    build_detectors,
    load_deid_config,
)
from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.identity import open_identity, seal_identity
from interview_assistant.deid.store import SqlTokenStore
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.models import Candidate


class DeidUnavailable(RuntimeError):
    """No encryption key: tokens and identities cannot be stored, so nothing is de-identified."""


class DeidService:
    def __init__(self, config: DeidConfig, cipher: FieldCipher | None) -> None:
        self.config = config
        self.cipher = cipher
        self.dictionary = config.load_dictionary()
        self.detectors = build_detectors(config, self.dictionary)
        self.formats = config.token_formats()

    @classmethod
    def from_settings(cls, settings: Settings) -> DeidService:
        key = settings.encryption_key
        cipher = FieldCipher(key.get_secret_value()) if key and key.get_secret_value() else None
        return cls(load_deid_config(settings.deid_file), cipher)

    def _cipher(self) -> FieldCipher:
        if self.cipher is None:
            raise DeidUnavailable(
                "IA_ENCRYPTION_KEY가 설정되지 않아 비식별화를 할 수 없습니다. .env에 키를 넣고 "
                "서버를 다시 시작하세요."
            )
        return self.cipher

    def deidentifier(self, db: Session) -> Deidentifier:
        store = SqlTokenStore(db, self._cipher(), self.formats)
        return Deidentifier(
            self.detectors, store, dictionary=self.dictionary, allow=self.config.allow
        )

    def identity(self, candidate: Candidate) -> KnownIdentity | None:
        if not candidate.encrypted_identity:
            return None
        return open_identity(self._cipher(), candidate.encrypted_identity)

    def seal(self, identity: KnownIdentity) -> str:
        return seal_identity(self._cipher(), identity)

    def deidentify(self, db: Session, text: str, candidate: Candidate) -> str:
        """Tokenised text for one candidate. New tokens are flushed; the caller commits."""
        return (
            self.deidentifier(db)
            .deidentify(text, candidate_id=candidate.id, known=self.identity(candidate))
            .text
        )
