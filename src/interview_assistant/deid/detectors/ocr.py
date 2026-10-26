"""The applicant's own identifiers in OCR text, despite misread characters.

OCR gets single characters wrong: "설도현" comes out "설도헌", "충북대학교" as "중북대학교", a digit
of a phone number as another digit. Exact matching then misses the value and it reaches the LLM
nearly intact. This detector runs only on the OCR'd parts of a document (`spans`), where such
errors are expected, and only for values the application form already gives (KnownIdentity):

- names and other Hangul values (aliases, schools and their short forms, companies, address
  heads) of three syllables or more, with no word boundary required: OCR drops spaces
  ("저는설도현입니다", "광운대전자공학"), which the exact detectors' boundaries then miss. Same
  number of syllables (spaces between them allowed: Tesseract splits syllables), at most one
  jamo different for up to four syllables, two beyond (zero is a match too). The first syllable
  may be the misread one ("충북대학교" read as "중 북 대학교"); the cost is that another person's
  name one jamo away from the applicant's is replaced too, in OCR text only
- phone numbers: the same digits with at most one digit different, missing or extra
  (documents/ocrfix.py has already turned look-alike letters into digits)
- e-mail addresses and romanised names: at most one character different (two from 12
  characters), comparing look-alikes (0/o, 1/l/i, rn/m) as equal
- the given name alone with its syllables apart ("'하 준 님'", Tesseract)
- third-party names before a title (the titled-person rule) without a word boundary and with
  letter spacing removed: "저는정민지실장님과", "오태호 팀 장 님" (Tesseract), also before a
  title OCR cut short ("윤채아 / 석님" for 수석님: one or two syllables, then 님), then every
  later mention of such a name in the OCR text

It replaces with the same token as the exact value would get.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from interview_assistant.deid.detectors.base import Detector
from interview_assistant.deid.detectors.person import (
    _DOUBLE_SURNAMES,
    _SINGLE_SURNAMES,
    TITLED_NAME,
    _looks_like_name,
)
from interview_assistant.deid.text import HANGUL, LEFT, normalize, without_letter_spacing
from interview_assistant.deid.types import DeidCategory, Detection, KnownIdentity

_HANGUL = re.compile(r"[가-힣](?:\s?[가-힣])*")
_DIGIT_RUN = re.compile(r"(?:\+?\d)[\d\s().\-]{7,20}\d")
_WORD = re.compile(r"[A-Za-z0-9._%+\-@]+(?:\s?[@.]\s?[A-Za-z0-9._%+\-]+)*")
_TITLED_ANYWHERE = re.compile(TITLED_NAME.pattern.removeprefix(LEFT))
_NAME = rf"(?P<name>(?:{_DOUBLE_SURNAMES})[{HANGUL}]{{2}}|[{_SINGLE_SURNAMES}][{HANGUL}]{{2}})"
_CUT_TITLE = re.compile(_NAME + rf"(?=\s?[{HANGUL}]{{1,2}}님)")
_LOOKALIKE = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s"})


class OcrTolerantDetector(Detector):
    name = "ocr_tolerant"
    priority = 1

    def __init__(self, spans: Sequence[tuple[int, int]]) -> None:
        self.spans = tuple(spans)

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterator[Detection]:
        for start, end in self.spans:
            for s, e, name in _titled_names(text[start:end]):
                yield Detection(start + s, start + e, DeidCategory.person, name, self.name, 4)
        if known is None:
            return
        hangul = _hangul_values(known)
        phones = [normalize(DeidCategory.phone, p) for p in known.phones]
        latin = [(DeidCategory.email, e.strip(), normalize(DeidCategory.email, e)) for e in known.emails]
        for alias in (a for a in known.aliases if a.isascii()):  # "Dohyun Seol": each long part
            latin += [(DeidCategory.candidate, part, known.name or alias) for part in alias.split() if len(part) >= 5]
        for start, end in self.spans:
            segment = text[start:end]
            for s, e, category, value in (
                *_near_hangul(segment, hangul),
                *_spaced_given(segment, known),
                *_near_phones(segment, phones),
                *_near_latin(segment, latin),
            ):
                yield Detection(start + s, start + e, category, value, self.name, self.priority)


def _titled_names(segment: str) -> Iterator[tuple[int, int, str]]:
    copy = without_letter_spacing(segment)
    names: set[str] = set()
    for pattern in (_TITLED_ANYWHERE, _CUT_TITLE):
        for m in pattern.finditer(copy.text):
            if _looks_like_name(copy.text, m):
                names.add(m.group("name"))
    for name in names:
        for m in re.finditer(name, copy.text):
            start, end = copy.source_span(*m.span())
            yield start, end, name


def _spaced_given(segment: str, known: KnownIdentity) -> Iterator[tuple[int, int, DeidCategory, str]]:
    name = "".join((known.name or "").split())
    if not known.include_given_name or not re.fullmatch(rf"[{HANGUL}]{{3,5}}", name):
        return
    given = name[2:] if len(name) >= 4 else name[1:]
    if len(given) != 2:
        return
    for m in re.finditer(rf"(?<![{HANGUL}]){given[0]}\s{given[1]}", segment):
        yield m.start(), m.end(), DeidCategory.candidate, known.name or name


# --- Hangul: compare jamo -----------------------------------------------------------------------


def jamo(syllable: str) -> tuple[int, int, int]:
    code = ord(syllable) - 0xAC00
    return code // 588, (code % 588) // 28, code % 28


def jamo_distance(a: str, b: str) -> int:
    """Differing jamo between two Hangul strings of the same length (substitutions only)."""
    return sum(x != y for sa, sb in zip(a, b, strict=True) for x, y in zip(jamo(sa), jamo(sb), strict=True))


def _hangul_values(known: KnownIdentity) -> list[tuple[DeidCategory, str, str]]:
    """(category, Hangul surface without spaces, canonical value)."""
    out: list[tuple[DeidCategory, str, str]] = []

    def add(category: DeidCategory, surface: str, value: str) -> None:
        compact = "".join(surface.split())
        if len(compact) >= 3 and re.fullmatch(r"[가-힣]+", compact):
            out.append((category, compact, value))

    if known.name:
        add(DeidCategory.candidate, known.name, known.name)
        for alias in known.aliases:
            add(DeidCategory.candidate, alias, known.name)
    for school in known.schools:
        add(DeidCategory.school, school, school)
        for suffix, short in (("대학교", "대"), ("고등학교", "고"), ("중학교", "중")):
            if school.endswith(suffix):
                add(DeidCategory.school, school[: -len(suffix)] + short, school)
    for company in known.companies:
        bare = re.sub(r"\(주\)|㈜|주식회사", "", company)
        add(DeidCategory.company, bare, company)
    for address in known.addresses:
        head = address.split(",")[0]
        for piece in re.findall(r"[가-힣]{2,}(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구|로|길)", head):
            add(DeidCategory.address, piece, address)
    return out


def _near_hangul(segment: str, values: list[tuple[DeidCategory, str, str]]) -> Iterator[tuple[int, int, DeidCategory, str]]:
    for m in _HANGUL.finditer(segment):
        positions = [m.start() + i for i, c in enumerate(m.group()) if not c.isspace()]
        syllables = "".join(segment[p] for p in positions)
        for category, surface, value in values:
            n = len(surface)
            limit = 1 if n <= 4 else 2
            for i in range(len(syllables) - n + 1):
                window = syllables[i : i + n]
                if window == surface or jamo_distance(window, surface) <= limit:
                    yield positions[i], positions[i + n - 1] + 1, category, value


# --- digits and Latin ---------------------------------------------------------------------------


def _edit_distance(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _near_phones(segment: str, phones: list[str]) -> Iterator[tuple[int, int, DeidCategory, str]]:
    if not phones:
        return
    for m in _DIGIT_RUN.finditer(segment):
        digits = re.sub(r"\D", "", m.group())
        if digits.startswith("82"):
            digits = "0" + digits[2:]
        for phone in phones:
            if digits != phone and _edit_distance(digits, phone, 1) <= 1:
                yield m.start(), m.end(), DeidCategory.phone, phone


def _skeleton(text: str) -> str:
    return text.lower().replace("rn", "m").replace("vv", "w").translate(_LOOKALIKE)


def _near_latin(
    segment: str, values: list[tuple[DeidCategory, str, str]]
) -> Iterator[tuple[int, int, DeidCategory, str]]:
    if not values:
        return
    for m in _WORD.finditer(segment):
        word = "".join(m.group().split())
        for category, surface, value in values:
            target = "".join(surface.split())
            if len(target) < 5 or word.lower() == target.lower():
                continue
            limit = 1 if len(target) < 12 else 2
            if _edit_distance(_skeleton(word), _skeleton(target), limit) <= limit:
                yield m.start(), m.end(), category, value
