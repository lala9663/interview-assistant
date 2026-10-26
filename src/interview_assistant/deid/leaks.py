"""Leak check: does any known identifying value survive de-identification?

A sample is a text plus its ground truth: every identifying value that appears in it. After
de-identification none of them may remain, in any spacing or separator variant. A residual scan
also flags anything still shaped like a phone number, e-mail or 주민번호 even if it is not in
the ground truth, letter-spaced or not. Optional `keep` phrases guard the other direction:
words that are not identifying must survive, so over-eager patterns do not garble what the LLM
reads.

The document check runs the same comparison on files: extract (PDF, DOCX, PPTX, HTML), then
de-identify every block including the file name and properties, then look for each
ground-truth value in every block. It also verifies the extraction itself: each value must be
found in the kind of block it was planted in (a header value in a header block), images must
have been dropped, and scanned files must be held as needing OCR rather than checked.

Both sides are compared after the same Unicode clean-up the extractors apply (NFC, no
zero-width characters, ASCII digits), so a value disguised by such characters still counts as
a leak. Used by scripts/check_leaks.py and the test suite.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.pool import StaticPool

from interview_assistant.crypto import FieldCipher
from interview_assistant.db import make_engine, make_session_factory
from interview_assistant.deid.config import DeidConfig, build_deidentifier
from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.detectors.contact import EMAIL, PHONE, RRN
from interview_assistant.deid.documents import DeidentifiedDocument, deidentify_document
from interview_assistant.deid.identity import open_identity, seal_identity
from interview_assistant.deid.store import SqlTokenStore
from interview_assistant.deid.text import parse_date, without_spaces
from interview_assistant.deid.types import DeidCategory, KnownIdentity
from interview_assistant.documents import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractionError,
    extract_document,
    normalize_text,
)
from interview_assistant.documents.base import ConverterMissing, EncryptedDocument
from interview_assistant.documents.types import ReadMethod
from interview_assistant.textmetrics import cer
from interview_assistant.models import Base, Candidate

Enroll = Callable[[str, KnownIdentity], tuple[str, KnownIdentity]]


@dataclass(frozen=True)
class ExpectedValue:
    category: DeidCategory
    value: str
    where: tuple[str, ...] = ()  # block kinds the value was placed in (document samples)


@dataclass(frozen=True)
class Sample:
    id: str
    kind: str
    text: str
    identity: KnownIdentity
    expected: tuple[ExpectedValue, ...]
    keep: tuple[str, ...] = ()


@dataclass
class SampleReport:
    sample_id: str
    kind: str
    output: str
    expected: int
    replaced: int
    leaks: list[ExpectedValue] = field(default_factory=list)
    residual: list[tuple[str, str]] = field(default_factory=list)  # (kind, surface)
    lost: list[str] = field(default_factory=list)  # `keep` phrases that were replaced
    not_in_source: list[str] = field(default_factory=list)  # fixture errors

    @property
    def ok(self) -> bool:
        return not (self.leaks or self.residual or self.lost or self.not_in_source)


def load_samples(path: Path) -> list[Sample]:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    samples = []
    for item in raw.get("samples", []):
        samples.append(
            Sample(
                id=str(item["id"]),
                kind=str(item.get("kind", "")),
                text=str(item["text"]),
                identity=KnownIdentity.from_dict(item.get("identity") or {}),
                expected=tuple(
                    ExpectedValue(DeidCategory(e["category"]), str(e["value"]))
                    for e in item.get("expected", [])
                ),
                keep=tuple(str(k) for k in item.get("keep", [])),
            )
        )
    return samples


def leak_pattern(expected: ExpectedValue) -> re.Pattern[str]:
    """Pattern for a value in any spacing / separator / case variant."""
    category, value = expected.category, normalize_text(expected.value)
    if category in (DeidCategory.phone, DeidCategory.rrn):
        digits = re.sub(r"[^\d*]", "", value)
        variants = {digits}
        if category is DeidCategory.phone and digits.startswith("82"):
            variants.add("0" + digits[2:])
        if category is DeidCategory.phone and digits.startswith("0"):
            variants.add("82" + digits[1:])
        sep = r"[\s.\-()+]{0,3}"
        return re.compile("|".join(sep.join(re.escape(c) for c in v) for v in variants))
    if category is DeidCategory.birthdate:
        iso = parse_date(value)
        if iso:
            y, m, d = iso.split("-")
            sep = r"\s*(?:[.\-/]|년|월)?\s*"
            return re.compile(
                rf"(?:{y}|{y[2:]}){sep}0?{int(m)}{sep}0?{int(d)}(?!\d)|{y}{m}{d}"
            )
    chars = [re.escape(c) for c in value if not c.isspace()]
    return re.compile(r"\s*".join(chars), re.IGNORECASE)


def find_leaks(output: str, expected: Sequence[ExpectedValue]) -> list[ExpectedValue]:
    output = normalize_text(output)
    leaks = [e for e in expected if leak_pattern(e).search(output)]
    # The local part of an e-mail address identifies a person on its own.
    for e in expected:
        if e.category is DeidCategory.email and e not in leaks:
            local = e.value.split("@", 1)[0]
            if len(local) >= 4 and local.lower() in output.lower():
                leaks.append(e)
    return leaks


def residual_scan(output: str) -> list[tuple[str, str]]:
    """Anything still shaped like a 주민번호, phone number or e-mail, also with every space
    removed ("0 1 0 - 1 2 3 4 - 5 6 7 8", "john @ example . com"). Stricter than the
    detectors, which only remove letter spacing: the check must not share their blind spots."""
    output = normalize_text(output)
    spaceless = without_spaces(output)
    found: list[tuple[str, str]] = []
    seen: list[tuple[int, int]] = []
    for kind, pattern in (("rrn", RRN), ("phone", PHONE), ("email", EMAIL)):
        spans = [m.span() for m in pattern.finditer(output)]
        spans += [
            spaceless.source_span(*m.span())
            for m in pattern.finditer(spaceless.text)
            if spaceless.dropped_inside(*m.span())
        ]
        for start, end in spans:
            if not any(start < e and s < end for s, e in seen):
                seen.append((start, end))
                found.append((kind, output[start:end]))
    return found


def check_sample(sample: Sample, deidentify: Callable[[Sample], tuple[str, int]]) -> SampleReport:
    output, replaced = deidentify(sample)
    source = normalize_text(sample.text)
    return SampleReport(
        sample_id=sample.id,
        kind=sample.kind,
        output=output,
        expected=len(sample.expected),
        replaced=replaced,
        leaks=find_leaks(output, sample.expected),
        residual=residual_scan(output),
        lost=[k for k in sample.keep if normalize_text(k) not in normalize_text(output)],
        not_in_source=[
            *(e.value for e in sample.expected if not leak_pattern(e).search(source)),
            *(k for k in sample.keep if normalize_text(k) not in source),
        ],
    )


@contextmanager
def real_path(config: DeidConfig) -> Iterator[tuple[Deidentifier, Enroll]]:
    """The production de-identification path on a throwaway in-memory database.

    Yields the de-identifier and `enroll(pseudonym, identity) -> (candidate_id, known)`, which
    seals the identity into Candidate.encrypted_identity and opens it again, as the app does.
    Tokens are persisted (encrypted) in deid_mappings. Throwaway key, no network.
    """
    engine = make_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    cipher = FieldCipher(FieldCipher.generate_key())
    try:
        with make_session_factory(engine)() as session:
            deid = build_deidentifier(
                config, SqlTokenStore(session, cipher, config.token_formats())
            )

            def enroll(pseudonym: str, identity: KnownIdentity) -> tuple[str, KnownIdentity]:
                candidate = Candidate(
                    pseudonym=f"LEAKCHECK-{pseudonym}",
                    encrypted_identity=seal_identity(cipher, identity),
                )
                session.add(candidate)
                session.flush()
                return candidate.id, open_identity(cipher, candidate.encrypted_identity or "")

            yield deid, enroll
            session.rollback()
    finally:
        engine.dispose()


def run_leak_check(samples: Sequence[Sample], config: DeidConfig) -> list[SampleReport]:
    """De-identify every sample through the real path (see `real_path`) and check it."""
    with real_path(config) as (deid, enroll):

        def deidentify(sample: Sample) -> tuple[str, int]:
            candidate_id, known = enroll(sample.id, sample.identity)
            result = deid.deidentify(sample.text, candidate_id=candidate_id, known=known)
            return result.text, len(result.replacements)

        return [check_sample(s, deidentify) for s in samples]


# --- documents -------------------------------------------------------------------------------

CHECKED, OCR_HOLD, ERROR = "checked", "ocr_hold", "error"
REFUSED = "refused"  # refused as the manifest expects (a password-protected file)
SKIPPED = "skipped"  # needs a converter this machine lacks (legacy .doc/.ppt without LibreOffice)


@dataclass(frozen=True)
class DocumentSample:
    id: str
    path: Path
    upload_name: str  # the file name as uploaded; extracted and de-identified like the content
    format: str
    scanned: bool  # some page has no usable text layer (scan, picture, garbled): it needs OCR
    identity: KnownIdentity
    expected: tuple[ExpectedValue, ...]
    keep: tuple[str, ...] = ()
    traps: tuple[str, ...] = ()
    images: int = 0  # images placed in the file; at least this many must be dropped
    ocr_pages: tuple[int, ...] = ()
    ocr_truth: str = ""  # the text drawn into the pictures OCR must read, for its error rate
    photos: int = 0  # ID photos placed: with OCR, at least this many must be dropped unread
    refused: str = ""  # "encrypted": the file must be refused, not read


@dataclass
class DocumentReport:
    sample: DocumentSample
    status: str  # CHECKED, OCR_HOLD (not read: nothing de-identified, nothing sent), ERROR, ...
    document: ExtractedDocument | None = None
    deidentified: DeidentifiedDocument | None = None
    error: str = ""
    leaks: list[tuple[ExpectedValue, str]] = field(default_factory=list)  # (value, block label)
    near: list[tuple[ExpectedValue, str, str]] = field(default_factory=list)  # (value, surface, label)
    residual: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, surface, label)
    lost: list[str] = field(default_factory=list)
    not_in_source: list[str] = field(default_factory=list)  # value not extracted at all
    missing: list[tuple[str, str]] = field(default_factory=list)  # (value, kind) absent there
    ocr_missed: list[str] = field(default_factory=list)  # in a picture, OCR did not read it
    problems: list[str] = field(default_factory=list)  # OCR classification, images, format
    cer: float | None = None  # OCR character error rate against `ocr_truth`

    @property
    def ok(self) -> bool:
        if self.status == ERROR or self.problems:
            return False
        if self.status in (OCR_HOLD, REFUSED, SKIPPED):
            return True
        return not (
            self.leaks or self.near or self.residual or self.lost or self.not_in_source or self.missing
        )

    @property
    def leaked_values(self) -> int:
        return len({e for e, _ in self.leaks} | {e for e, _, _ in self.near}) + len(self.residual)


def load_document_samples(path: Path) -> list[DocumentSample]:
    """Manifest entries; `file` is relative to the manifest's folder."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    samples = []
    for item in raw.get("samples", []):
        file = path.parent / str(item["file"])
        samples.append(
            DocumentSample(
                id=str(item["id"]),
                path=file,
                upload_name=str(item.get("upload_name") or file.name),
                format=str(item.get("format", "")),
                scanned=bool(item.get("scanned", False)),
                identity=KnownIdentity.from_dict(item.get("identity") or {}),
                expected=tuple(
                    ExpectedValue(
                        DeidCategory(e["category"]),
                        str(e["value"]),
                        tuple(str(w) for w in e.get("where", ())),
                    )
                    for e in item.get("expected", [])
                ),
                keep=tuple(str(k) for k in item.get("keep", [])),
                traps=tuple(str(t) for t in item.get("traps", [])),
                images=int(item.get("images", 0)),
                ocr_pages=tuple(int(n) for n in item.get("ocr_pages", ())),
                ocr_truth=str(item.get("ocr_truth") or ""),
                photos=int(item.get("photos", 0)),
                refused=str(item.get("refused") or ""),
            )
        )
    return samples


def check_document(
    sample: DocumentSample,
    deid: Deidentifier,
    enroll: Enroll,
    extractors: Mapping[str, DocumentExtractor] | None = None,
    reader: Any = None,
    tokens: re.Pattern[str] | None = None,
) -> DocumentReport:
    """Extract (through `reader`, documents.reading.DocumentReader, when given: OCR included),
    de-identify and check one sample."""
    data = sample.path.read_bytes()
    try:
        if reader is not None:
            document = reader.read(data, sample.upload_name)
        else:
            document = extract_document(data, sample.upload_name, extractors)
    except EncryptedDocument as exc:
        status = REFUSED if sample.refused == "encrypted" else ERROR
        return DocumentReport(sample, status, error=str(exc))
    except ConverterMissing as exc:
        status = SKIPPED if sample.format in ("doc", "ppt") else ERROR
        return DocumentReport(sample, status, error=str(exc))
    except ExtractionError as exc:
        return DocumentReport(sample, ERROR, error=str(exc))

    problems = []
    if sample.refused:
        problems.append(f"거부되어야 하는 파일이 읽힘 ({sample.refused})")
    if sample.format and document.format != sample.format:
        problems.append(f"형식 {document.format} (정답 {sample.format})")
    needing = [p.number for p in document.pages if p.needs_ocr or p.method is not ReadMethod.text]
    if bool(needing) != sample.scanned:
        got = "OCR 필요" if needing else "텍스트형"
        want = "OCR 필요" if sample.scanned else "텍스트형"
        problems.append(f"{got}로 분류됨 (정답 {want})")
    elif sample.ocr_pages and tuple(needing) != sample.ocr_pages:
        problems.append(f"OCR 필요 쪽 {needing} (정답 {list(sample.ocr_pages)})")
    if document.images_dropped < sample.images:
        problems.append(f"버린 이미지 {document.images_dropped}개 (넣은 이미지 {sample.images}개)")
    if document.reading is not None and sample.photos:
        photos = sum(1 for i in document.images if i.decision in ("photo", "small"))
        if photos < sample.photos:
            problems.append(f"증명사진으로 버린 그림 {photos}개 (넣은 증명사진 {sample.photos}개)")
    if document.needs_ocr:
        return DocumentReport(sample, OCR_HOLD, document=document, problems=problems)

    candidate_id, known = enroll(sample.id, sample.identity)
    deidentified = deidentify_document(deid, document, candidate_id=candidate_id, known=known)
    report = DocumentReport(
        sample, CHECKED, document=document, deidentified=deidentified, problems=problems
    )
    for block in deidentified.blocks:
        report.leaks.extend((e, block.label) for e in find_leaks(block.text, sample.expected))
        report.residual.extend((k, v, block.label) for k, v in residual_scan(block.text))
        if block.ocr:
            exact = {e for e, label in report.leaks if label == block.label}
            for e, surface in near_leaks(block.text, sample.expected, tokens):
                if e not in exact:
                    report.near.append((e, surface, block.label))
            for k, v in residual_scan(lookalike_digits(block.text)):
                if (k, v, block.label) not in report.residual:
                    report.residual.append((k, v, block.label))
    output = normalize_text(deidentified.text)
    sources = [(b.kind.value, normalize_text(b.text), b.ocr) for b in document.blocks]
    source = normalize_text(document.render())
    report.lost = [
        k for k in sample.keep if normalize_text(k) in source and normalize_text(k) not in output
    ]

    ocr_text = "\n".join(t for _, t, ocr in sources if ocr)
    for e in sample.expected:
        pattern = leak_pattern(e)
        if e.where and all(w == "image" for w in e.where):
            # Only in a picture: without OCR (none configured, picture OCR off) it is not read
            # at all, and OCR may misread it beyond recognition. Neither is a leak.
            if not ocr_text or not (pattern.search(ocr_text) or near_leaks(ocr_text, [e])):
                report.ocr_missed.append(e.value)
            continue
        if not any(pattern.search(text) for _, text, _ in sources):
            report.not_in_source.append(e.value)
            continue
        for kind in e.where:
            if kind != "image" and not any(pattern.search(t) for k, t, _ in sources if k == kind):
                report.missing.append((e.value, kind))
    if not document.ocr_used:
        report.not_in_source.extend(k for k in sample.keep if normalize_text(k) not in source)
    if sample.ocr_truth and ocr_text:
        report.cer = cer(sample.ocr_truth, ocr_text)
    return report


# Look-alike letters an OCR engine puts in place of digits. Stricter than documents/ocrfix.py on
# purpose: every token with three digits gets them all.
_DIGIT_LOOKALIKES = str.maketrans(
    {"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "!": "1", "i": "1",
     "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "b": "6", "G": "6", "g": "9", "q": "9"}
)  # fmt: skip
_DIGITISH = "0-9OoDQIl|!iZzSsBbGgq"
_DIGIT_RUN = re.compile(rf"[{_DIGITISH}][{_DIGITISH}\s().\-+]{{6,22}}[{_DIGITISH}]")


def lookalike_digits(text: str) -> str:
    def digits(m: re.Match[str]) -> str:
        token = m.group()
        return token.translate(_DIGIT_LOOKALIKES) if sum(c.isdigit() for c in token) >= 3 else token

    return re.sub(r"\S+", digits, text)


def near_leaks(
    output: str, expected: Sequence[ExpectedValue], tokens: re.Pattern[str] | None = None
) -> list[tuple[ExpectedValue, str]]:
    """Values that survive in OCR'd text with a misread character or two (approximate substring
    search, Sellers' algorithm). Hangul is compared jamo by jamo; look-alike Latin letters and
    digits count as equal. Tolerance: one edit for values up to 4 syllables or 11 characters,
    two beyond; a phone number or 주민번호: one digit. Values shorter than 3 characters only
    match exactly (find_leaks)."""
    text = normalize_text(output)
    if tokens is not None:
        text = tokens.sub("\x00", text)
    symbols, positions = _symbols(text)
    runs = [
        (m.group(), re.sub(r"\D", "", m.group().translate(_DIGIT_LOOKALIKES)))
        for m in _DIGIT_RUN.finditer(text)
    ]
    found: list[tuple[ExpectedValue, str]] = []
    for e in expected:
        if e.category in (DeidCategory.phone, DeidCategory.rrn):
            digits = re.sub(r"\D", "", normalize_text(e.value))
            for surface, run in runs:
                run = "0" + run[2:] if run.startswith("82") else run
                if _levenshtein(run, digits) <= 1 or digits in run:
                    found.append((e, surface))
                    break
            continue
        value = "".join(normalize_text(e.value).split())
        if len(value) < 3 or e.category is DeidCategory.birthdate:
            continue
        pattern, _ = _symbols(value)
        hangul = sum(1 for c in value if "가" <= c <= "힣")
        if hangul >= len(value) / 2:
            limit = 1 if hangul <= 4 else 2
        else:
            limit = 1 if len(value) < 12 else 2
        span = _approximate(pattern, symbols, limit)
        if span is not None:
            start, end = span
            found.append((e, text[positions[start] : positions[end - 1] + 1]))
    return found


_LATIN_LOOKALIKES = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s"})


def _symbols(text: str) -> tuple[list[str], list[int]]:
    """Comparable symbols and the text position each comes from: no spaces, lower case, look-
    alikes merged, each Hangul syllable as its three jamo."""
    symbols: list[str] = []
    positions: list[int] = []
    lowered = text.lower()
    i = 0
    while i < len(lowered):
        c = lowered[i]
        if lowered.startswith(("rn", "vv"), i):
            symbols.append("m" if c == "r" else "w")
            positions.append(i)
            i += 2
            continue
        if not c.isspace():
            if "가" <= c <= "힣":
                code = ord(c) - 0xAC00
                for part in (f"L{code // 588}", f"V{(code % 588) // 28}", f"T{code % 28}"):
                    symbols.append(part)
                    positions.append(i)
            else:
                symbols.append(c.translate(_LATIN_LOOKALIKES))
                positions.append(i)
        i += 1
    return symbols, positions


def _approximate(pattern: list[str], text: list[str], limit: int) -> tuple[int, int] | None:
    """(start, end) of the closest substring of `text` within `limit` edits of `pattern`."""
    m = len(pattern)
    if m == 0 or not text:
        return None
    column = list(range(m + 1))
    best: tuple[int, int] | None = None
    for j, t in enumerate(text, 1):
        diagonal, column[0] = column[0], 0
        for i in range(1, m + 1):
            current = min(column[i] + 1, column[i - 1] + 1, diagonal + (pattern[i - 1] != t))
            diagonal, column[i] = column[i], current
        if column[m] <= limit and (best is None or column[m] < best[0]):
            best = (column[m], j)
            if column[m] == 0:
                break
    if best is None:
        return None
    end = best[1]
    return max(0, end - m - limit), end


def _levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def run_document_leak_check(
    samples: Sequence[DocumentSample],
    config: DeidConfig,
    extractors: Mapping[str, DocumentExtractor] | None = None,
    reader: Any = None,
) -> list[DocumentReport]:
    """Extract (with OCR when `reader` is given), de-identify (real path) and check every file."""
    tokens = config.token_formats().pattern()
    with real_path(config) as (deid, enroll):
        return [check_document(s, deid, enroll, extractors, reader, tokens) for s in samples]


def mask(value: str) -> str:
    """'김도윤' -> '김**', '010-0123-4567' -> '01***********'. For reports on real data."""
    visible = 2 if len(value) > 6 else 1
    return value[:visible] + "*" * (len(value) - visible)
