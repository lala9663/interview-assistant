"""Shape-based fallback for schools and companies that are not in the dictionary.

"한빛대학교", "새솔고등학교", "(주)누리소프트", "다온테크" are caught by their suffix or corporate
marker. Generic phrases ("일반대학원", "에듀테크") are excluded by a stop list.
"""

from __future__ import annotations

import re

from interview_assistant.deid.detectors.base import PatternRule, RegexDetector
from interview_assistant.deid.text import HANGUL as H
from interview_assistant.deid.text import LEFT, RIGHT_HANGUL
from interview_assistant.deid.types import DeidCategory

_SCHOOL_SUFFIX = "여자고등학교|여자중학교|여자대학교|고등학교|중학교|초등학교|대학교|대학원|과학고|외고|여고|여중"
_SCHOOL_STOP = (
    "일반 전문 특수 지방 해외 국내 명문 사립 국립 공립 인근 다른 같은 해당 모교 본교 각 여러 "
    "상위권 하위권 사이버 대학 교육 공과 의과 법학전문 경영전문 외국어 과학 예술 체육 국제 자율형사립"
).split()

_COMPANY_SUFFIX = (
    "테크놀로지|테크|소프트|시스템즈|랩스|네트웍스|코리아|파트너스|컴퍼니|증권|중공업|제약|전자|건설|"
    "게임즈|엔터테인먼트|모빌리티|로보틱스|솔루션즈|인더스트리"
)
_COMPANY_STOP = (
    "에듀 애드 헬스 푸드 프롭 리걸 클린 그린 인슈어 레그 하이 딥 퀀트 핀 바이오 기후 보안 국내 해외 "
    "대형 중소 중견 대기업 글로벌 전통 반도체 가전 종합 임베디드 국내외 대표 주요 경쟁 협력 다국적 외국계"
).split()
_CORP = r"\(주\)|㈜|주식회사"
_PARTICLE = "에서|에게|에|의|은|는|이|가|을|를|과|와|으로|로|도|만"

SCHOOL = re.compile(
    rf"{LEFT}(?!(?:{'|'.join(_SCHOOL_STOP)})(?:{_SCHOOL_SUFFIX}))"
    rf"[{H}]{{2,10}}?(?:{_SCHOOL_SUFFIX}){RIGHT_HANGUL}"
)
COMPANY_MARKER_BEFORE = re.compile(rf"(?:{_CORP})\s*[{H}A-Za-z0-9&]{{1,20}}")
# A trailing marker must be glued to the name ("누리소프트(주)") or, for 주식회사, end the mention
# ("누리소프트 주식회사와"). Otherwise "졸업하고 (주)누리소프트" would take "졸업하고" as the name.
COMPANY_MARKER_AFTER = re.compile(
    rf"{LEFT}[{H}A-Za-z0-9&]{{2,20}}(?:\(주\)|㈜|\s?주식회사(?=$|[^\s{H}A-Za-z0-9]|{_PARTICLE}))"
)
COMPANY_SUFFIX = re.compile(
    rf"{LEFT}(?!(?:{'|'.join(_COMPANY_STOP)})(?:{_COMPANY_SUFFIX}))"
    rf"[{H}A-Za-z]{{2,10}}?(?:{_COMPANY_SUFFIX}){RIGHT_HANGUL}"
)


def organization_detector() -> RegexDetector:
    return RegexDetector(
        "pattern",
        priority=3,
        rules=[
            PatternRule(DeidCategory.school, SCHOOL),
            PatternRule(DeidCategory.company, COMPANY_MARKER_BEFORE, strip_particle=True),
            PatternRule(DeidCategory.company, COMPANY_MARKER_AFTER),
            PatternRule(DeidCategory.company, COMPANY_SUFFIX),
        ],
    )
