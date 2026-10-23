"""Letter-spaced values ("0 1 0 - 1 2 3 4 - 5 6 7 8", "누 리 대 학 교"): the spaceless copy, what
it lets the detectors catch without an application form, what it must leave alone, and the
leak checker seeing through the same spacing. No LLM, no network."""

import pytest

from interview_assistant.deid import InMemoryTokenStore, KnownIdentity, build_deidentifier
from interview_assistant.deid.detectors import KnownIdentityDetector, contact_detector
from interview_assistant.deid.leaks import ExpectedValue, find_leaks, residual_scan
from interview_assistant.deid.text import without_letter_spacing, without_spaces
from interview_assistant.models import DeidCategory


@pytest.fixture
def deid(deid_config):
    return build_deidentifier(deid_config, InMemoryTokenStore(deid_config.token_formats()))


def run(deid, text, known=None):
    return deid.deidentify(text, candidate_id="c1", known=known).text


@pytest.mark.parametrize(
    "text, copy",
    [
        ("0 1 0 - 1 2 3 4 - 5 6 7 8", "010-1234-5678"),
        ("j o h n @ e x a m p l e . c o m", "john@example.com"),
        ("메일 john @ example . com 으로", "메일 john@example.com 으로"),
        ("Email john @example.com now", "Email john@example.com now"),
        ("누 리 대 학 교 를 졸업", "누리대학교를 졸업"),
        ("권  하  린", "권하린"),
        # The narrowest spacing is letter spacing; wider gaps stay word breaks.
        ("누 리 대 학 교   졸 업", "누리대학교   졸업"),
        # Ordinary words keep their spaces, single-letter words between them included.
        ("저는 그 대학교에 다녔고 있는 대학교 근처", "저는 그 대학교에 다녔고 있는 대학교 근처"),
        ("가 나\n다 라", "가나\n다라"),  # never across a line break
    ],
)
def test_without_letter_spacing(text, copy):
    assert without_letter_spacing(text).text == copy


def test_spaceless_copy_maps_back_to_the_original():
    text = "연락처 0 1 0 - 1 2 3 4 - 5 6 7 8 입니다"
    copy = without_letter_spacing(text)
    start = copy.text.index("010")
    span = copy.source_span(start, start + len("010-1234-5678"))
    assert text[span[0] : span[1]] == "0 1 0 - 1 2 3 4 - 5 6 7 8"
    assert copy.dropped_inside(start, start + 3)
    word = copy.text.index("연락처")
    assert not copy.dropped_inside(word, word + 3)
    assert without_spaces("a b\tc\nd  e").text == "abc\nde"


@pytest.mark.parametrize(
    "text, expected",
    [
        # Not on any application form: only the shape gives them away.
        ("연락처 0 1 0 - 1 2 3 4 - 5 6 7 8 입니다", "연락처 [전화-1] 입니다"),
        ("메일 john @ example . com 으로", "메일 [이메일-1] 으로"),
        ("메일 j o h n @ e x a m p l e . c o m 으로", "메일 [이메일-1] 으로"),
        ("Email john @ example . com now", "Email [이메일-1] now"),
        ("주민번호 9 5 0 3 1 4 - 1 2 3 4 5 6 7", "주민번호 [주민번호-1]"),
        ("집 0 2 - 1 2 3 - 4 5 6 7", "집 [전화-1]"),
        ("연락처 010 - 1234 - 5678", "연락처 [전화-1]"),
        ("누 리 대 학 교 를 졸업했습니다", "[학교-1] 를 졸업했습니다"),
        ("새 봄 테 크 에서 일했습니다", "[회사-1] 에서 일했습니다"),
        ("( 주 ) 푸 름 데 이 터 에서 근무", "[회사-1] 에서 근무"),
    ],
)
def test_letter_spaced_values_without_known_identity(deid, text, expected):
    assert run(deid, text) == expected


def test_spaced_and_plain_spellings_share_a_token(deid):
    text = "누 리 대 학 교 와 누리대학교, j o h n @ e x a m p l e . c o m 과 john@example.com"
    assert run(deid, text) == "[학교-1] 와 [학교-1], [이메일-1] 과 [이메일-1]"


def test_known_name_with_any_spacing():
    known = KnownIdentity(name="권하린")
    for text in ("권  하  린", "권 하 린", "권\t하\t린", "권하린"):
        found = KnownIdentityDetector().detect(text, known)
        assert [(text[d.start : d.end], d.value) for d in found] == [(text, "권하린")], text


@pytest.mark.parametrize(
    "text",
    [
        "2 0 1 9 . 0 3 입사",
        "1 2 3 4 단계로 나눴습니다",
        "버전 2 . 4 . 1 배포",
        "1 . 2 . 3 . 4 순서",
        "점수 4 . 5 / 5 . 0",
        "2 0 1 9 - 2 0 2 1 재직",
        "0 . 2 3 초 단축",
        "기간 2 0 1 6 . 0 3 ~ 2 0 2 0 . 0 2",
        "이 력 서",
        "자 기 소 개 서",
        "학 력 사 항",
        "최 종 학 력 | 대 학 교 졸 업",
        "저는 그 대학교에 다녔고, 있는 대학교 근처에 살았습니다",
        "에 듀 테 크 분야",
        "소 프 트 웨 어 개발",
        "전 자 공 학 전공",
        "응 용 소 프 트 웨 어",
        "그 외 다 른 일",
    ],
)
def test_ordinary_spaced_text_is_left_alone(deid, text):
    assert run(deid, text) == text


def test_ordinary_words_next_to_spaced_values_survive(deid):
    text = "추천인 연락처: 0 1 0 - 1 8 2 6 - 4 0 9 7 / s j . y o o n @ e x a m p l e . n e t 로 부탁드립니다"
    assert run(deid, text) == "추천인 연락처: [전화-1] / [이메일-1] 로 부탁드립니다"


def test_names_are_not_looked_for_in_the_spaceless_copy():
    """Names need word boundaries; they are matched on the original text only."""
    detections = list(contact_detector().detect("담 당 자 정 민 지"))
    assert detections == []


@pytest.mark.parametrize(
    "output, kind",
    [
        ("연락처 0 1 0 - 1 2 3 4 - 5 6 7 8", "phone"),
        ("연락처 010 - 1234 - 5678", "phone"),
        ("메일 john @ example . com", "email"),
        ("메일 j o h n @ e x a m p l e . c o m", "email"),
        ("번호 9 5 0 3 1 4 - 1 2 3 4 5 6 7", "rrn"),
    ],
)
def test_residual_scan_sees_through_spacing(output, kind):
    found = residual_scan(output)
    assert [k for k, _ in found] == [kind]
    assert found[0][1] in output and " " in found[0][1]


def test_residual_scan_reports_each_value_once_and_ignores_ordinary_numbers():
    assert residual_scan("연락처 010 1234 5678") == [("phone", "010 1234 5678")]
    assert residual_scan("[전화-1] · [이메일-2], 2 0 1 9 . 0 3, 1 2 3 4, 버전 2 . 4 . 1") == []


def test_leak_patterns_see_through_letter_spacing():
    for category, value, output in [
        (DeidCategory.phone, "010-1234-5678", "0 1 0 - 1 2 3 4 - 5 6 7 8"),
        (DeidCategory.email, "john@example.com", "j o h n @ e x a m p l e . c o m"),
        (DeidCategory.school, "누리대학교", "누 리 대 학 교"),
        (DeidCategory.candidate, "권하린", "권  하  린"),
    ]:
        assert find_leaks(output, [ExpectedValue(category, value)]), value
