"""Questions an interviewer must not ask (채용 면접 금지 질문), checked by rules.

The categories follow the Korean rules on fair hiring: 채용절차의 공정화에 관한 법률 제4조의3
(출신 지역, 혼인 여부, 재산, 직계 존비속과 형제자매의 학력·직업·재산, 용모·키·체중 같은 신체 조건을
직무와 무관하게 요구하거나 수집하지 않는다), 남녀고용평등법 제7조 (혼인·임신·출산을 이유로 한 차별,
직무와 무관한 신체 조건·미혼 조건), and the grounds of discrimination in 국가인권위원회법 제2조 제3호
(종교, 나이, 출신 지역·국가·민족, 용모, 혼인·가족 형태, 임신·출산, 정치적 의견, 병력, 성적 지향,
학력 ...). Blind hiring guidance adds the school name. docs/question-bank.md lists them with examples.

Rules are word patterns with context, so ordinary job talk stays clean ("가족 같은 팀 분위기",
"장비 키 값", "서비스 장애 대응"): a match is a warning for a person to read, not a verdict. A question
with warnings can still be approved, but only with an explicit confirmation that the audit log
keeps. The optional AI check (prompts.QUESTION_CHECK_*) can add warnings the rules miss; it sees the
question only, never candidate data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    category: str  # stable key
    label: str  # shown on the screen
    basis: str  # where the prohibition comes from
    patterns: tuple[str, ...]
    example: str


_FAMILY = r"(부모|부모님|아버지|어머니|아버님|어머님|아빠|엄마|형제|자매|남매|형님|오빠|언니|누나|남동생|여동생|배우자|남편|아내|자녀|아들|딸|가족)"

RULES: tuple[Rule, ...] = (
    Rule(
        "family",
        "가족 사항",
        "채용절차법 제4조의3 (직계 존비속·형제자매의 학력·직업·재산)",
        (
            # a family member and their job, schooling or wealth in the same sentence
            _FAMILY + r"[^.?!\n]{0,20}?(직업|직장|학력|학교|재산|회사|직위|무슨\s*일|어떤\s*일|뭐\s*하|하시는\s*일|일하시)",
            r"가족\s*(관계|구성|사항|형태|상황|중에|분들)",
            r"(아버지|어머니|부모님)\s*(는|은|께서는)?\s*(뭐|무엇|어디)",
            r"(형제|자매|남매)\s*(관계|가\s*(몇|있)|는\s*몇)",
            r"(외동|장남|장녀|막내|몇\s*남\s*몇\s*녀)",
            r"(한부모|편부|편모|이혼\s*가정)",
        ),
        "부모님은 어떤 일을 하시나요?",
    ),
    Rule(
        "origin",
        "출신 지역·국가·민족",
        "채용절차법 제4조의3, 국가인권위원회법 제2조",
        (
            r"(고향|본적|출신\s*(지역|지|도|국가|나라|민족)|어디\s*출신|어느\s*지역\s*(사람|출신)|본관)",
            r"(사투리|억양)\s*(이|가|을|를)?\s*(있|쓰|들리)",
            r"(국적|민족|인종|피부색)",
        ),
        "고향이 어디세요?",
    ),
    Rule(
        "marriage",
        "혼인·연애",
        "채용절차법 제4조의3, 남녀고용평등법 제7조",
        (
            r"(결혼|혼인|기혼|미혼|이혼|재혼|사실혼|약혼|배우자|(?<!장)애인|연애|남자\s*친구|여자\s*친구|남친|여친)",
        ),
        "결혼 계획이 있으신가요?",
    ),
    Rule(
        "pregnancy",
        "임신·출산·육아 계획",
        "남녀고용평등법 제7조, 국가인권위원회법 제2조",
        (
            r"(임신|출산|산후|아이를\s*(낳|가질)|자녀\s*(계획|를\s*가질|가\s*있|는\s*몇)|아이\s*계획|육아\s*(휴직|때문)|아이가\s*(있|몇))",
        ),
        "출산 계획이 있다면 업무에 지장이 없을까요?",
    ),
    Rule(
        "religion",
        "종교",
        "국가인권위원회법 제2조",
        (r"(종교|신앙|교회|성당|사찰|절에\s*다|기독교|불교|천주교|이슬람|무교)",),
        "종교가 있으신가요?",
    ),
    Rule(
        "appearance",
        "외모·신체 조건",
        "채용절차법 제4조의3, 남녀고용평등법 제7조",
        (
            r"(외모|용모|생김새|얼굴|인상이|키가|키는|키\s*몇|신장|몸무게|체중|체격|살을\s*빼|뚱뚱|날씬|문신)",
        ),
        "키와 몸무게가 어떻게 되시나요?",
    ),
    Rule(
        "age",
        "나이",
        "국가인권위원회법 제2조 (직무와 무관한 나이)",
        (r"(나이|몇\s*살|연세|연령|몇\s*년생|출생\s*연도|무슨\s*띠|띠가)",),
        "올해 나이가 어떻게 되시나요?",
    ),
    Rule(
        "wealth",
        "재산·경제 사정",
        "채용절차법 제4조의3",
        (r"(재산|자가|전세|월세|집이\s*있|부채|빚이|대출이\s*있|연봉이\s*(부모|배우자)|생활\s*형편|경제\s*사정)",),
        "사시는 집은 자가인가요?",
    ),
    Rule(
        "politics",
        "정치 성향·사상",
        "국가인권위원회법 제2조",
        (r"(정치\s*성향|지지\s*(하는\s*)?정당|정당\s*(가입|활동)|투표|진보|보수\s*(성향|정당)|노조\s*(가입|활동))",),
        "지지하는 정당이 있나요?",
    ),
    Rule(
        "health",
        "건강·병력·장애",
        "국가인권위원회법 제2조, 장애인차별금지법 (직무와 무관한 건강 정보)",
        (
            r"(병력|지병|질병|투병|수술\s*(받|한)|건강\s*(상태|문제)|정신과|우울증|복용\s*(하는|중인)\s*약)",
            r"(장애인|장애\s*(여부|등급|판정)|장애(가|를)\s*(있으신|있으세요|있나요|가지고))",
        ),
        "앓고 있는 지병이 있나요?",
    ),
    Rule(
        "orientation",
        "성별 고정관념·성적 지향",
        "남녀고용평등법 제7조, 국가인권위원회법 제2조",
        (
            r"(성적\s*지향|동성애|성\s*정체성)",
            r"(여자|여성|남자|남성)(라서|이라서|이니까|인데)\s*",
            r"(여자|여성)\s*(가|이|로서)?\s*(야근|출장|체력|버틸)",
        ),
        "여자라서 야근이 힘들지 않겠어요?",
    ),
    Rule(
        "school",
        "출신 학교 (블라인드)",
        "블라인드 채용 지침 (출신 학교·학벌로 판단하지 않음)",
        (r"(출신\s*(학교|대학|고교|고등학교)|어느\s*(학교|대학)\s*(나오|나왔|졸업|출신|다니)|학벌|명문대|지방대)",),
        "어느 대학 나오셨어요?",
    ),
)

RULE_BY_CATEGORY = {r.category: r for r in RULES}

# Ordinary job talk that contains a flagged word: removed before matching.
_SAFE = (
    r"가족\s*같은",
    r"팀\s*분위기",
    r"(장비|설정|키|API|암호화|기본|외래|고유)\s*키",
    r"키\s*(값|를\s*(돌|바꾸|관리)|관리|회전|발급)",
    r"(나이테|나이브)",
    r"(종교적\s*신념처럼|신앙처럼)",
    r"(얼굴|안면)\s*인식",
    r"(투표|다수결)로\s*(정|결정)",
    r"(성장|진보)\s*(했|하는|과정)",
    r"보수적(으로|인)",
    r"경제\s*(성|적|효과)",
    r"(데이터|모델|코드)\s*건강",
    r"건강\s*(검진\s*결과를\s*제외|한\s*코드)",
)


@dataclass(frozen=True)
class Flag:
    category: str
    label: str
    basis: str
    matched: str
    source: str = "rule"  # "rule" or "ai"
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "label": self.label,
            "basis": self.basis,
            "matched": self.matched,
            "source": self.source,
            "note": self.note,
        }


def check(*texts: str) -> list[Flag]:
    """Warnings for a question (and its follow-up examples): one per category, first match."""
    found: dict[str, Flag] = {}
    for text in texts:
        clean = text or ""
        for safe in _SAFE:
            clean = re.sub(safe, lambda m: " " * len(m.group(0)), clean)
        for rule in RULES:
            if rule.category in found:
                continue
            for pattern in rule.patterns:
                m = re.search(pattern, clean)
                if m:
                    found[rule.category] = Flag(rule.category, rule.label, rule.basis, m.group(0).strip())
                    break
    return [found[r.category] for r in RULES if r.category in found]
