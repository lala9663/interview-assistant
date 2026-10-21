"""Pluggable detectors. Each one finds spans; the de-identifier merges them and assigns tokens."""

from interview_assistant.deid.detectors.base import Detector, PatternRule, RegexDetector
from interview_assistant.deid.detectors.contact import contact_detector
from interview_assistant.deid.detectors.dictionary import DictionaryDetector, TermDictionary
from interview_assistant.deid.detectors.known import KnownIdentityDetector
from interview_assistant.deid.detectors.ner import Entity, EntityRecognizer, NERDetector
from interview_assistant.deid.detectors.organization import organization_detector
from interview_assistant.deid.detectors.person import titled_person_detector

__all__ = [
    "Detector",
    "DictionaryDetector",
    "Entity",
    "EntityRecognizer",
    "KnownIdentityDetector",
    "NERDetector",
    "PatternRule",
    "RegexDetector",
    "TermDictionary",
    "contact_detector",
    "organization_detector",
    "titled_person_detector",
]
