"""Each detector on its own: what it must catch, and ordinary text it must leave alone."""

import pytest

from interview_assistant.deid import DeidCategory, KnownIdentity
from interview_assistant.deid.detectors import (
    DictionaryDetector,
    Entity,
    KnownIdentityDetector,
    NERDetector,
    TermDictionary,
    contact_detector,
    organization_detector,
    titled_person_detector,
)


def spans(detector, text, known=None):
    return [(text[d.start : d.end], d.category, d.value) for d in detector.detect(text, known)]


def surfaces(detector, text, known=None):
    return [s for s, _, _ in spans(detector, text, known)]


@pytest.mark.parametrize(
    "text, phone",
    [
        ("연락처 010-0123-4567입니다", "010-0123-4567"),
        ("010.0123.4567로 주세요", "010.0123.4567"),
        ("번호는 010 0123 4567", "010 0123 4567"),
        ("01001234567", "01001234567"),
        ("+82 10-0123-4567", "+82 10-0123-4567"),
        ("+82-10-0123-4567로", "+82-10-0123-4567"),
        ("집 전화 02-123-4567", "02-123-4567"),
        ("042-012-3456입니다", "042-012-3456"),
    ],
)
def test_phone_formats(text, phone):
    found = [s for s, c, _ in spans(contact_detector(), text) if c is DeidCategory.phone]
    assert found == [phone]


def test_email_rrn_and_masked_rrn():
    text = "메일 Doyoon.Kim@example.com으로, 주민번호 950314-1******, 9503141234560"
    found = {(s, c) for s, c, _ in spans(contact_detector(), text)}
    assert ("Doyoon.Kim@example.com", DeidCategory.email) in found
    assert ("950314-1******", DeidCategory.rrn) in found
    assert ("9503141234560", DeidCategory.rrn) in found


@pytest.mark.parametrize(
    "text",
    [
        "생년월일은 1995년 3월 14일입니다",
        "생년월일: 1995.03.14",
        "1995-03-14에 태어났습니다",
        "95년 3월 14일생입니다",
        "DOB 1995/03/14",
    ],
)
def test_birthdate_needs_birth_context(text):
    found = [c for _, c, _ in spans(contact_detector(), text)]
    assert found == [DeidCategory.birthdate]


@pytest.mark.parametrize(
    "text",
    [
        "2019년 3월 2일에 입사했습니다",
        "2023.11.01부터 프로젝트를 맡았습니다",
        "3월 14일 생산 라인 점검",
        "버전 2.4.1을 배포했고 응답 시간이 120ms 줄었습니다",
        "매출 1,200억, 2018-2021 재직",
    ],
)
def test_ordinary_dates_and_numbers_are_left_alone(text):
    assert spans(contact_detector(), text) == []


@pytest.mark.parametrize(
    "text, address",
    [
        ("서울특별시 마포구 솔바람길 27에 삽니다", "서울특별시 마포구 솔바람길 27"),
        ("경기도 수원시 영통구에 살고 있습니다", "경기도 수원시 영통구"),
        (
            "대전광역시 유성구 별빛누리길 42 한울아파트 103동 502호에",
            "대전광역시 유성구 별빛누리길 42 한울아파트 103동 502호",
        ),
        ("성남시 분당구 솔내음로 95에 살고", "성남시 분당구 솔내음로 95"),
        ("강남구 역삼동 123-45 거주", "강남구 역삼동 123-45"),
        ("서울 강남구에서 자랐습니다", "서울 강남구"),
    ],
)
def test_addresses(text, address):
    found = [s for s, c, _ in spans(contact_detector(), text) if c is DeidCategory.address]
    assert address in found


@pytest.mark.parametrize(
    "text",
    [
        "서울에서 자랐고 부산 출신입니다",
        "연구 활동 3건과 친구 행동 분석",
        "당시 동시 접속자가 많았습니다",
        "서울 연구소와 협업",
    ],
)
def test_non_addresses(text):
    assert [s for s, c, _ in spans(contact_detector(), text) if c is DeidCategory.address] == []


@pytest.fixture
def dictionary():
    return TermDictionary(
        {
            DeidCategory.school: [("서울대학교", "서울대", "SNU"), ("광주과학기술원", "지스트", "GIST")],
            DeidCategory.company: [
                ("카카오", "Kakao"),
                ("KT", "케이티"),
                ("LG전자", "LG Electronics"),
                ("비바리퍼블리카", "토스"),
            ],
        }
    )


def test_dictionary_maps_aliases_to_canonical(dictionary):
    text = "서울대 졸업, SNU 동문, 서울대학교 대학원, Kakao와 카카오에서 일했습니다"
    found = spans(DictionaryDetector(dictionary), text)
    assert [(s, v) for s, _, v in found if v == "서울대학교"] == [
        ("서울대", "서울대학교"),
        ("SNU", "서울대학교"),
        ("서울대학교", "서울대학교"),
    ]
    assert {s for s, _, v in found if v == "카카오"} == {"Kakao", "카카오"}


def test_dictionary_boundaries(dictionary):
    detector = DictionaryDetector(dictionary)
    # Acronyms are case-sensitive and must stand alone; Hangul terms allow only particles after.
    assert surfaces(detector, "the gist of it, KTX를 타고, SKT 근무") == []
    assert surfaces(detector, "카카오톡으로 연락, 업무를 토스하다") == []
    assert surfaces(detector, "GIST 출신, KT에서, 토스에서, LG 전자") == ["GIST", "KT", "토스", "LG 전자"]


def test_dictionary_rejects_conflicting_alias():
    with pytest.raises(ValueError, match="already maps"):
        TermDictionary({DeidCategory.school: [("가대학교", "가대"), ("나대학교", "가대")]})


def test_dictionary_files_load(deid_config):
    dictionary = deid_config.load_dictionary()
    assert dictionary.canonical(DeidCategory.school, "카이스트") == "한국과학기술원"
    assert dictionary.canonical(DeidCategory.company, "현대차") == "현대자동차"
    assert len(dictionary) > 100


@pytest.mark.parametrize(
    "text, expected",
    [
        ("한빛대학교에서 공부했고", ("한빛대학교", DeidCategory.school)),
        ("새솔여자고등학교 졸업", ("새솔여자고등학교", DeidCategory.school)),
        ("(주)누리소프트에서 일했습니다", ("(주)누리소프트", DeidCategory.company)),
        ("㈜푸름데이터와 협업", ("㈜푸름데이터", DeidCategory.company)),
        ("누리소프트(주) 개발팀", ("누리소프트(주)", DeidCategory.company)),
        ("하늘시스템즈 주식회사와", ("하늘시스템즈 주식회사", DeidCategory.company)),
        ("다온테크로 이직", ("다온테크", DeidCategory.company)),
    ],
)
def test_organization_patterns(text, expected):
    found = {(s, c) for s, c, _ in spans(organization_detector(), text)}
    assert expected in found


@pytest.mark.parametrize(
    "text",
    [
        "소프트웨어 개발을 했습니다",
        "일반대학원과 전문대학원을 비교했습니다",
        "에듀테크와 핀테크 분야",
        "광전자 효과를 연구",
        "채용공고를 보고 지원했습니다",
        "관리시스템을 개발했습니다",
    ],
)
def test_organization_patterns_skip_generic_words(text):
    assert spans(organization_detector(), text) == []


def test_trailing_corporate_marker_does_not_eat_previous_word():
    text = "졸업하고 (주)누리소프트에서, 고객사였던 ㈜푸름데이터와"
    found = surfaces(organization_detector(), text)
    assert {"(주)누리소프트", "㈜푸름데이터"} <= set(found)
    assert not any("졸업하고" in s or "고객사였던" in s or "에서" in s for s in found)


def test_titled_person_and_follow_up_mentions():
    text = "남궁민수 사원과 이서준 팀장님, 오태호 CTO님, 최유진씨. 나중에 민수 씨가 맡았고 이서준이 도왔다."
    found = spans(titled_person_detector(), text)
    assert {(s, v) for s, _, v in found} == {
        ("남궁민수", "남궁민수"),
        ("이서준", "이서준"),
        ("오태호", "오태호"),
        ("최유진", "최유진"),
        ("민수", "남궁민수"),
    }
    assert sum(1 for s, _, _ in found if s == "이서준") == 3  # titled + "이서준이" via follow-up


@pytest.mark.parametrize(
    "text",
    [
        "마케팅 팀장님과 회의",
        "고객사 대표님께 보고",
        "이번에 팀장님이 바뀌었습니다",
        "기획팀 팀장님",
        "서비스 PM으로 일했습니다",
        "모든 선배님들",
        "고객사 프로젝트",
        "인프라 엔지니어로 일했습니다",
        "반도체 엔지니어 직무",
        "연구소 연구원으로",
    ],
)
def test_titled_person_skips_common_words(text):
    assert spans(titled_person_detector(), text) == []


@pytest.fixture
def known():
    return KnownIdentity(
        name="김도윤",
        aliases=("Do-yoon Kim",),
        phones=("010-0123-4567",),
        emails=("doyoon.kim@example.com",),
        birthdate="1995-03-14",
        addresses=("서울특별시 마포구 솔바람길 27, 101동 1203호",),
        schools=("한빛대학교", "새솔여자고등학교"),
        companies=("(주)누리소프트",),
    )


@pytest.mark.parametrize(
    "text, surface, category",
    [
        ("저는 김 도윤입니다", "김 도윤", DeidCategory.candidate),
        ("도윤이라고 불러주세요", "도윤", DeidCategory.candidate),
        ("Doyoon Kim입니다", "Doyoon Kim", DeidCategory.candidate),
        ("동료들은 Do-yoon이라고", "Do-yoon", DeidCategory.candidate),
        ("+82 10 0123 4567", "+82 10 0123 4567", DeidCategory.phone),
        ("DOYOON.KIM@EXAMPLE.COM", "DOYOON.KIM@EXAMPLE.COM", DeidCategory.email),
        ("95.3.14에 입사", "95.3.14", DeidCategory.birthdate),
        ("19950314", "19950314", DeidCategory.birthdate),
        ("101동 1203호", "101동 1203호", DeidCategory.address),
        ("한빛대 출신", "한빛대", DeidCategory.school),
        ("새솔여고에서", "새솔여고", DeidCategory.school),
        ("누리소프트에서", "누리소프트", DeidCategory.company),
        # Shapes that come out of files: letter-spaced PDF text, bracketed area code, values a
        # narrow table cell wrapped mid-word.
        ("0 1 0 . 0 1 2 3 . 4 5 6 7", "0 1 0 . 0 1 2 3 . 4 5 6 7", DeidCategory.phone),
        ("(010) 0123-4567", "(010) 0123-4567", DeidCategory.phone),
        ("doyoon.kim@exa mple.com", "doyoon.kim@exa mple.com", DeidCategory.email),
        ("한빛대\n학교 졸업", "한빛대\n학교", DeidCategory.school),
        ("솔바\n람길 27", "솔바\n람길 27", DeidCategory.address),
    ],
)
def test_known_identity_variants(known, text, surface, category):
    found = {(s, c) for s, c, _ in spans(KnownIdentityDetector(), text, known)}
    assert (surface, category) in found


def test_known_identity_address_split_across_cells(known):
    """Each piece of the known address is found on its own and maps to the same value."""
    found = spans(KnownIdentityDetector(), "주소 | 서울특별시 마포구 | 솔바람길 27 | 101동 1203호", known)
    address = "서울특별시 마포구 솔바람길 27, 101동 1203호"
    assert {(s, v) for s, c, v in found if c is DeidCategory.address} == {
        ("서울특별시 마포구", address),
        ("솔바람길 27", address),
        ("101동 1203호", address),
    }


def test_known_identity_values_are_canonical(known):
    found = spans(KnownIdentityDetector(), "도윤, 1995년 3월 14일, 한빛대", known)
    assert {v for _, _, v in found} == {"김도윤", "1995-03-14", "한빛대학교"}


def test_known_identity_ignores_other_dates(known):
    assert spans(KnownIdentityDetector(), "1996년 3월 14일", known) == []


def test_known_identity_without_identity_finds_nothing():
    assert spans(KnownIdentityDetector(), "김도윤 010-0123-4567") == []


class FakeRecognizer:
    def recognize(self, text):
        start = text.index("박서준")
        return [Entity(start, start + 3, "PS"), Entity(0, 2, "LC"), Entity(5, 99, "PS")]


def test_ner_adapter_maps_labels_and_drops_bad_spans():
    text = "서울에서 박서준과 일했다"
    found = spans(NERDetector(FakeRecognizer()), text)
    assert found == [("박서준", DeidCategory.person, "박서준")]
    opt_in = NERDetector(FakeRecognizer(), labels={"LC": DeidCategory.address})
    assert surfaces(opt_in, text) == ["서울"]
