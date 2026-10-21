"""Token assignment: the same value for the same candidate always gets the same token.

`SqlTokenStore` persists the mapping in `deid_mappings`, so tokens stay stable across sessions
and documents. It only ever encrypts; reading original values back is `reidentify.py`'s job.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from interview_assistant.crypto import FieldCipher
from interview_assistant.models.deid import DeidCategory, DeidMapping

_MAX_TOKEN_LENGTH = 50  # deid_mappings.token is String(50)


class TokenFormats:
    """Per-category token templates. `{n}` is the per-candidate, per-category sequence number.

    A template without `{n}` (e.g. "[지원자]") maps every value of that category to one token.
    """

    def __init__(self, templates: Mapping[DeidCategory | str, str]) -> None:
        parsed = {DeidCategory(k): v for k, v in templates.items()}
        missing = [c.value for c in DeidCategory if c not in parsed]
        if missing:
            raise ValueError(f"token format missing for: {', '.join(missing)}")
        for category, template in parsed.items():
            if not template.strip():
                raise ValueError(f"token format for {category.value} is empty")
            if len(self._render(template, 9999)) > _MAX_TOKEN_LENGTH:
                raise ValueError(f"token format for {category.value} is too long")
        rendered = [self._render(t, 1) for t in parsed.values()]
        if len(set(rendered)) != len(rendered):
            raise ValueError("token formats must differ between categories")
        self._templates = parsed

    @staticmethod
    def _render(template: str, seq: int) -> str:
        return template.replace("{n}", str(seq))

    def render(self, category: DeidCategory, seq: int) -> str:
        return self._render(self._templates[category], seq)

    def numbered(self, category: DeidCategory) -> bool:
        return "{n}" in self._templates[category]

    def pattern(self) -> re.Pattern[str]:
        """Matches any token these formats can produce."""
        alternatives = sorted(
            (re.escape(t).replace(re.escape("{n}"), r"\d+") for t in self._templates.values()),
            key=len,
            reverse=True,
        )
        return re.compile("|".join(alternatives))


class TokenStore(ABC):
    def __init__(self, formats: TokenFormats) -> None:
        self.formats = formats

    @abstractmethod
    def token_for(self, candidate_id: str, category: DeidCategory, value: str) -> str:
        """Token for a canonical value, creating the mapping on first sight."""


class InMemoryTokenStore(TokenStore):
    """Non-persistent store for tests and dry runs. Holds plaintext; never use with real data."""

    def __init__(self, formats: TokenFormats) -> None:
        super().__init__(formats)
        self._tokens: dict[tuple[str, DeidCategory, str], str] = {}
        self._counts: dict[tuple[str, DeidCategory], int] = {}

    def token_for(self, candidate_id: str, category: DeidCategory, value: str) -> str:
        key = (candidate_id, category, value)
        if key not in self._tokens:
            count = self._counts.get((candidate_id, category), 0)
            if not self.formats.numbered(category) and count:
                return self.formats.render(category, 1)
            self._counts[(candidate_id, category)] = count + 1
            self._tokens[key] = self.formats.render(category, count + 1)
        return self._tokens[key]


class SqlTokenStore(TokenStore):
    """Persistent store. Flushes new rows; the caller owns the transaction and commits."""

    def __init__(self, session: Session, cipher: FieldCipher, formats: TokenFormats) -> None:
        super().__init__(formats)
        self.session = session
        self.cipher = cipher

    def token_for(self, candidate_id: str, category: DeidCategory, value: str) -> str:
        value_hash = self.cipher.lookup_hash(candidate_id, category.value, value)
        existing = self.session.scalar(
            select(DeidMapping.token).where(
                DeidMapping.candidate_id == candidate_id,
                DeidMapping.category == category,
                DeidMapping.value_hash == value_hash,
            )
        )
        if existing is not None:
            return existing

        if not self.formats.numbered(category):
            shared = self.session.scalar(
                select(DeidMapping.token)
                .where(DeidMapping.candidate_id == candidate_id, DeidMapping.category == category)
                .limit(1)
            )
            if shared is not None:
                return shared

        last_seq = self.session.scalar(
            select(func.max(DeidMapping.seq)).where(
                DeidMapping.candidate_id == candidate_id, DeidMapping.category == category
            )
        )
        seq = (last_seq or 0) + 1
        token = self.formats.render(category, seq)
        self.session.add(
            DeidMapping(
                candidate_id=candidate_id,
                category=category,
                seq=seq,
                token=token,
                value_hash=value_hash,
                encrypted_value=self.cipher.encrypt(value),
            )
        )
        self.session.flush()
        return token
