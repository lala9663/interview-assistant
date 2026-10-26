"""Garbled text layers: the criteria in documents/quality.py, fixed by examples."""

import pytest

from interview_assistant.documents.quality import assess

RESUME = (
    "이력서 성명 권하린 (Harin Kwon) 생년월일 1996.04.17 휴대전화 010-0211-3344 "
    "이메일 harin.kwon@example.com 주소 서울특별시 마포구 솔바람길 27 "
    "[지원 동기] 백엔드 개발 직무에 지원한 권하린입니다. 큰 시스템이 실패 없이 돌아가게 만드는 일에 흥미를 느꼈습니다."
)


def mojibake(text: str) -> str:
    """Korean as a legacy font's broken ToUnicode map shows it: CP949 bytes read as Latin-1."""
    return "".join(
        c.encode("cp949").decode("latin-1") if "가" <= c <= "힣" else c for c in text
    )


@pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
def test_clean_korean_and_english_pass_at_every_sensitivity(sensitivity):
    assert not assess(RESUME).garbled(sensitivity)
    english = "Senior engineer at José's team, 5 years of C++ and Python; GPA 4.0/4.5 · TOEIC 950 ©2026"
    assert not assess(english).garbled(sensitivity)
    assert not assess("學歷 權夏潾 漢字 이름과 α, β 계수 · ㅇ 항목").garbled(sensitivity)


@pytest.mark.parametrize("sensitivity", ["low", "medium", "high"])
def test_whole_page_mojibake_is_garbled_at_every_sensitivity(sensitivity):
    quality = assess(mojibake(RESUME))
    assert quality.ratio > 0.5
    assert quality.garbled(sensitivity)


def test_one_broken_name_is_caught_by_the_run_rule_not_the_share():
    text = RESUME.replace("권하린입니다", mojibake("권하린") + "입니다")
    quality = assess(text)
    assert quality.ratio < 0.05  # six odd characters in a long page
    assert quality.longest_run == 6
    assert not quality.garbled("low")
    assert quality.garbled("medium")
    assert quality.garbled("high")


def test_unmapped_glyphs_private_use_and_replacement_characters_count():
    assert assess("(cid:12)(cid:40)(cid:7) 이력서").longest_run == 3
    assert assess(" 성명").suspicious == 2
    assert assess("성��명").garbled("medium") is False  # a run of two: only high
    assert assess("성��명").garbled("high")


def test_latin1_signs_are_fine_alone_but_not_in_a_row():
    assert assess("학력·경력 ±0.5 30°C ©2026").suspicious == 0
    assert assess(mojibake("가")) == assess("°¡")  # 가 = B0 A1: two "allowed" signs
    assert assess("°¡").longest_run == 2


def test_spaces_end_a_run_and_are_not_counted():
    quality = assess("é é é é")
    assert (quality.chars, quality.suspicious, quality.longest_run) == (4, 4, 1)


def test_short_text_needs_a_run_not_a_share():
    assert not assess("Ç 가").garbled("high")  # 50% of two characters is not evidence
    assert assess("ÇÑ").garbled("high")
