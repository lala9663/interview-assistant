"""Stopgap for third-party names until a Korean NER model is plugged in (see ner.py).

Catches a surname + two-syllable given name directly followed by a title or honorific:
"이서준 팀장님", "박하은 교수님", "최유진씨". Once a name is found that way, later mentions in the
same text of the full name or the given name alone ("민수 씨가") get the same token. Names that
never appear with a title are not caught. Only the name is replaced, so "[인물-1] 팀장님" keeps
the role for the LLM.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from interview_assistant.deid.detectors.base import PatternRule, RegexDetector
from interview_assistant.deid.text import HANGUL as H
from interview_assistant.deid.text import LEFT, RIGHT_HANGUL, RIGHT_LATIN
from interview_assistant.deid.types import DeidCategory, Detection, KnownIdentity

_SINGLE_SURNAMES = (
    "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공"
    "현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경"
)
_DOUBLE_SURNAMES = "남궁|황보|제갈|선우|독고|사공|서문"
_TITLES_HANGUL = (
    "선배|후배|동기|교수|박사|팀장|파트장|그룹장|실장|본부장|센터장|부장|차장|과장|대리|주임|사원|선임|책임|"
    "수석|매니저|프로|리더|대표|이사|상무|전무|사장|원장|선생|강사|멘토|멘티|연구원|엔지니어|개발자|"
    "디자이너|면접관|님|씨"
)
_TITLES_LATIN = "PM|PL|PO|CTO|CEO|CFO"

TITLED_NAME = re.compile(
    rf"{LEFT}(?P<name>(?:{_DOUBLE_SURNAMES})[{H}]{{2}}|[{_SINGLE_SURNAMES}][{H}]{{2}})"
    rf"(?=\s?(?:(?:{_TITLES_HANGUL}){RIGHT_HANGUL}|(?:{_TITLES_LATIN}){RIGHT_LATIN}))"
)

# Three-syllable words that start with a surname character and often precede a title.
_NOT_NAMES = frozenset(
    "마케팅 모바일 백엔드 서비스 연구원 전직장 주니어 한국인 고객사 경쟁사 협력사 기획팀 인사팀 전략팀 "
    "정규직 계약직 신입생 재학생 졸업생 대학원 지원자 면접관 담당자 관리자 책임자 선임자 후임자 전임자 "
    # Job-field words seen before 엔지니어/개발자 in resumes ("인프라 엔지니어", "반도체 엔지니어").
    "인프라 반도체 연구소 전기차 제조업 하이브리드 공정팀 임베디".split()
)
# Given names never end in these (조사, or organisation words like 팀/사/부).
_NOT_NAME_ENDINGS = frozenset("에의는을를로와과께들팀사부실처청단")


def _looks_like_name(text: str, m: re.Match[str]) -> bool:
    name = m.group("name")
    return name not in _NOT_NAMES and name[-1] not in _NOT_NAME_ENDINGS


class TitledPersonDetector(RegexDetector):
    def __init__(self) -> None:
        super().__init__(
            "titled_person",
            priority=4,
            rules=[
                PatternRule(DeidCategory.person, TITLED_NAME, group="name", accept=_looks_like_name)
            ],
        )

    def detect(self, text: str, known: KnownIdentity | None = None) -> Iterator[Detection]:
        names: set[str] = set()
        for d in super().detect(text, known):
            names.add(d.value)
            yield d
        for name in names:
            given = name[-2:]
            for pattern in (LEFT + name, LEFT + given + RIGHT_HANGUL):
                for m in re.finditer(pattern, text):
                    yield Detection(
                        m.start(), m.end(), DeidCategory.person, name, self.name, self.priority
                    )


def titled_person_detector() -> TitledPersonDetector:
    return TitledPersonDetector()
