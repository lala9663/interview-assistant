"""Loads config/deid.yaml and wires detectors, dictionary and token formats together."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.detectors import (
    Detector,
    DictionaryDetector,
    EntityRecognizer,
    KnownIdentityDetector,
    NERDetector,
    TermDictionary,
    contact_detector,
    organization_detector,
    titled_person_detector,
)
from interview_assistant.deid.store import TokenFormats, TokenStore
from interview_assistant.models.deid import DeidCategory

DEFAULT_DETECTORS = ["known_identity", "regex", "dictionary", "pattern", "titled_person"]


class DeidConfig(BaseModel):
    tokens: dict[DeidCategory, str]
    dictionaries: dict[DeidCategory, list[Path]] = Field(default_factory=dict)
    detectors: list[str] = Field(default_factory=lambda: list(DEFAULT_DETECTORS))
    allow: list[str] = Field(default_factory=list)

    def token_formats(self) -> TokenFormats:
        return TokenFormats(self.tokens)

    def load_dictionary(self) -> TermDictionary:
        return TermDictionary.load(self.dictionaries)


def load_deid_config(path: Path) -> DeidConfig:
    """Dictionary paths in the file are relative to the file itself."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if "deid" not in raw:
        raise ValueError(f"{path}: top-level 'deid' key is missing")
    config = DeidConfig.model_validate(raw["deid"])
    base = path.parent
    config.dictionaries = {
        category: [p if p.is_absolute() else base / p for p in paths]
        for category, paths in config.dictionaries.items()
    }
    return config


def build_detectors(
    config: DeidConfig,
    dictionary: TermDictionary,
    recognizer: EntityRecognizer | None = None,
) -> list[Detector]:
    factories: dict[str, Callable[[], Detector]] = {
        "known_identity": KnownIdentityDetector,
        "regex": contact_detector,
        "dictionary": lambda: DictionaryDetector(dictionary),
        "pattern": organization_detector,
        "titled_person": titled_person_detector,
    }
    detectors: list[Detector] = []
    for name in config.detectors:
        if name == "ner":
            if recognizer is None:
                raise ValueError("detector 'ner' is configured but no recognizer was given")
            detectors.append(NERDetector(recognizer))
        elif name in factories:
            detectors.append(factories[name]())
        else:
            known = ", ".join([*factories, "ner"])
            raise ValueError(f"unknown detector '{name}' (known: {known})")
    return detectors


def build_deidentifier(
    config: DeidConfig,
    store: TokenStore,
    *,
    recognizer: EntityRecognizer | None = None,
) -> Deidentifier:
    dictionary = config.load_dictionary()
    return Deidentifier(
        build_detectors(config, dictionary, recognizer),
        store,
        dictionary=dictionary,
        allow=config.allow,
    )
