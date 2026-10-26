"""De-identifying OCR text: misread identifiers and dropped spaces (deid/detectors/ocr.py), and
the leak check's own, independent near-miss search (deid/leaks.near_leaks)."""

from __future__ import annotations

import pytest

from interview_assistant.deid import InMemoryTokenStore, KnownIdentity
from interview_assistant.deid.config import build_deidentifier
from interview_assistant.deid.detectors.ocr import OcrTolerantDetector, jamo_distance
from interview_assistant.deid.documents import deidentify_document
from interview_assistant.deid.leaks import ExpectedValue, lookalike_digits, near_leaks
from interview_assistant.documents import BlockKind, ExtractedDocument, TextBlock
from interview_assistant.models import DeidCategory

KNOWN = KnownIdentity(
    name="설도현",
    aliases=("Dohyun Seol",),
    phones=("010-1381-0274",),
    emails=("dohyun.seol@example.net",),
    schools=("충북대학교",),
    companies=("누리소프트",),
    addresses=("충청북도 청주시 흥덕구 오송빛로 40",),
)


@pytest.fixture
def deid(deid_config):
    return build_deidentifier(deid_config, InMemoryTokenStore(deid_config.token_formats()))


def run(deid, text: str, *, ocr: bool = True) -> str:
    document = ExtractedDocument("x.pdf", "pdf", (TextBlock(BlockKind.body, "1쪽", text, ocr),))
    return deidentify_document(deid, document, candidate_id="c1", known=KNOWN).blocks[0].text


@pytest.mark.parametrize(
    "misread, gone",
    [
        ("저는설도헌입니다", "설도헌"),  # one jamo off, no space before the name
        ("[성장과정]저는설도현입니다", "설도현"),  # exact, but glued to the word before
        ("그 호기심이 광운대전자공학 진학으로", None),  # not the applicant's school: untouched
        ("학력: 중 북 대학교 생물정보학", "중 북 대학교"),  # Tesseract: syllables apart, first misread
        ("충북대전자공학 졸업", "충북대"),  # short form glued to the next word
        ("휴대전화: 010-1381-0279", "010-1381-0279"),  # one digit misread
        ("이메일: dohyun.seoI@example.net", "dohyun.seoI@example.net"),  # l read as I
        ("주소: 중청북도 청주시 흥덕구 오송빛로40", "중청북도"),
        ("영문 이름 Dohyon Seol", "Dohyon"),
    ],
)
def test_misread_identifiers_in_ocr_text_are_replaced(deid, misread, gone):
    out = run(deid, misread)
    if gone is None:
        assert out == misread
    else:
        assert gone not in out, out


def test_tolerance_applies_to_ocr_blocks_only(deid):
    assert "설도헌" in run(deid, "저는 설도헌입니다", ocr=False)
    assert "설도헌" not in run(deid, "저는 설도헌입니다", ocr=True)


def test_titled_third_parties_in_ocr_text(deid):
    assert "오태호" not in run(deid, "개를출시했습니다.오태호 팀 장 님 과 함께한")  # Tesseract
    assert "정민지" not in run(deid, "[협업]저는정민지실장님과 진행한")  # no boundary
    assert "정민지" not in run(deid, "함께한 정민지\n실장님이 소개해")  # title on the next line


def test_the_same_token_as_the_exact_value(deid):
    out = run(deid, "성명: 설도현 / 저는설도헌입니다")
    tokens = [t for t in out.split() if t.startswith("[")]
    assert len(set(t.split("]")[0] for t in tokens)) == 1, out


def test_jamo_distance():
    assert jamo_distance("설도현", "설도헌") == 1
    assert jamo_distance("충북대", "중북대") == 1
    assert jamo_distance("충북대", "충남대") == 3


def test_the_detector_needs_spans_and_identity():
    detector = OcrTolerantDetector([(0, 8)])
    assert list(detector.detect("저는설도헌입니다", None)) == []  # nothing known, no titles
    assert [d.value for d in detector.detect("저는설도헌입니다 설도헌", KNOWN)] == ["설도현"]  # span only


# --- the leak check's near search --------------------------------------------------------------


def E(category: str, value: str) -> ExpectedValue:
    return ExpectedValue(DeidCategory(category), value)


@pytest.mark.parametrize(
    "output, value, found",
    [
        ("저는설도헌입니다", E("candidate", "설도현"), "설도헌"),
        ("학력: 중 북 대학교", E("school", "충북대학교"), "중 북 대학교"),
        ("연락처 O1O-138l-0279", E("phone", "010-1381-0274"), "O1O-138l-0279"),
        ("메일 dohyun.seoI@exarnple.net", E("email", "dohyun.seol@example.net"), "dohyun.seoI@exarnple.net"),
    ],
)
def test_near_leaks_find_what_ocr_misread(output, value, found):
    hits = near_leaks(output, [value])
    assert hits and found in hits[0][1]


def test_near_leaks_skip_tokens_short_values_and_other_names(deid_config):
    tokens = deid_config.token_formats().pattern()
    assert near_leaks("[지원자]가 지원했습니다", [E("candidate", "지원자")], tokens) == []
    assert near_leaks("도현 님", [E("candidate", "도현")]) == []  # two syllables: exact only
    assert near_leaks("충남대학교 출신", [E("school", "충북대학교")]) == []  # three jamo apart


def test_lookalike_digits_for_the_residual_scan():
    assert lookalike_digits("전화 O1O-l234-5678 Office") == "전화 010-1234-5678 Office"
