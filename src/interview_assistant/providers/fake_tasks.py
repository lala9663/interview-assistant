"""Offline answers to the app's own prompts, used by FakeLLM.

Each function reads the tagged inputs of `interview_assistant.ai.prompts` and builds schema-valid
output with plain rules (keyword lists, regexes, sentence picking), so every AI flow runs end to
end without a model or a network. This is not a model: the output is plausible in shape only and
says nothing about what a real model would answer.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterator
from datetime import date
from typing import Any


def tag(prompt: str, name: str) -> str | None:
    m = re.search(rf"<{name}>\n?(.*?)\n?</{name}>", prompt, re.S)
    return m.group(1).strip() if m else None


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def respond(title: str | None, prompt: str, rng: random.Random) -> dict[str, Any] | None:
    """Structured output for a schema title, or None when the prompt is not one of ours."""
    handlers = {
        "CompetencyDraft": draft_competencies,
        "CandidateProfile": extract_profile,
        "ScreeningAssessment": assess_screening,
        "AnswerScores": score_answer,
        "PresetDraft": draft_presets,
        "CarryoverQuestions": carryover_questions,
        "CheckPointDraft": check_points,
        "ConnectionTest": connection_test,
    }
    handler = handlers.get(title or "")
    return handler(prompt, rng) if handler else None


def connection_test(prompt: str, rng: random.Random) -> dict[str, Any]:
    numbers = [int(n) for n in re.findall(r"-?\d+", tag(prompt, "numbers") or "")]
    return {"echo": tag(prompt, "echo") or "", "sum": sum(numbers)}


# --- 역량 사전 ------------------------------------------------------------------------------


def _bars(*levels: str) -> dict[str, str]:
    return {str(i + 1): text for i, text in enumerate(levels)}


_LIBRARY: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        ("공정", "수율", "불량", "원인", "개선"),
        {
            "name": "문제 해결",
            "description": "문제의 원인을 가설로 세우고 실험과 데이터로 검증해 해결한다.",
            "bars": _bars(
                "문제를 현상 수준으로만 설명하고 원인 가설이 없다.",
                "원인 가설을 제시하지만 검증 방법이 모호하다.",
                "복수 가설을 세우고 실험이나 데이터로 하나 이상 검증해 개선했다.",
                "가설 우선순위를 근거로 정하고 체계적으로 검증해 재발 방지까지 연결했다.",
                "근본 원인을 메커니즘 수준에서 규명하고 표준화해 다른 조직에 확산했다.",
            ),
        },
    ),
    (
        ("데이터", "분석", "SPC", "통계", "Python", "SQL"),
        {
            "name": "데이터 기반 분석",
            "description": "데이터를 다루고 통계적 근거로 판단한다.",
            "bars": _bars(
                "데이터 근거 없이 경험으로만 판단한다.",
                "평균·추세 같은 기초 통계로 현상을 설명한다.",
                "상관·비교 분석으로 이상 구간을 찾고 결론을 낸다.",
                "모델링으로 핵심 인자를 정량화해 의사결정에 썼다.",
                "분석 체계를 자동화·표준화해 팀의 판단 속도와 정확도를 높였다.",
            ),
        },
    ),
    (
        ("설계", "아키텍처", "분산", "트래픽", "API", "게이트웨이"),
        {
            "name": "시스템 설계",
            "description": "요구사항에 맞는 구조를 고르고 트레이드오프를 설명한다.",
            "bars": _bars(
                "주어진 구조를 그대로 구현하는 데 그친다.",
                "익숙한 패턴을 적용하지만 대안 비교가 없다.",
                "요구사항에 맞춰 2개 이상 대안을 비교해 구조를 정했다.",
                "확장성·비용·운영 부담까지 정량적으로 비교해 설계를 이끌었다.",
                "조직 표준이 되는 아키텍처와 진화 경로를 설계했다.",
            ),
        },
    ),
    (
        ("장애", "운영", "SLO", "관측성", "모니터링"),
        {
            "name": "운영·장애 대응",
            "description": "관측성을 갖추고 장애를 빠르게 복구하며 재발을 막는다.",
            "bars": _bars(
                "장애 대응 경험이 거의 없다.",
                "정해진 절차에 따라 장애를 처리한다.",
                "지표로 원인을 좁혀 복구하고 회고를 작성했다.",
                "SLO·알림 체계를 정비해 탐지와 복구 시간을 줄였다.",
                "장애 예방 체계를 조직에 정착시켰다.",
            ),
        },
    ),
    (
        ("코드", "테스트", "리뷰", "품질"),
        {
            "name": "코드 품질",
            "description": "읽기 쉽고 테스트 가능한 코드를 쓰고 리뷰 문화에 기여한다.",
            "bars": _bars(
                "동작하는 코드에 만족하고 테스트가 없다.",
                "기본적인 테스트와 리뷰를 따른다.",
                "테스트 전략을 세우고 리팩터링으로 구조를 개선했다.",
                "공통 도구나 규칙으로 팀의 코드 품질을 끌어올렸다.",
                "품질 지표와 문화를 만들어 조직의 결함률을 낮췄다.",
            ),
        },
    ),
    (
        ("사용자", "사용성", "리서치", "UX"),
        {
            "name": "사용자 리서치",
            "description": "사용자 문제를 근거로 정의하고 검증 방법을 설계한다.",
            "bars": _bars(
                "가정만으로 문제를 정의한다.",
                "기존 리서치 결과를 참고한다.",
                "인터뷰·테스트를 직접 설계해 문제를 검증했다.",
                "정성·정량 근거를 결합해 우선순위를 정했다.",
                "리서치 체계를 만들어 팀 의사결정에 정착시켰다.",
            ),
        },
    ),
    (
        ("인터랙션", "프로토타입", "흐름", "디자인 시스템"),
        {
            "name": "인터랙션 설계",
            "description": "흐름과 상태를 빠짐없이 설계하고 프로토타입으로 검증한다.",
            "bars": _bars(
                "주요 화면만 그린다.",
                "기본 흐름과 주요 상태를 설계한다.",
                "예외·빈 상태까지 설계하고 프로토타입으로 검증했다.",
                "복잡한 흐름을 단순화해 측정 가능한 개선을 만들었다.",
                "인터랙션 원칙을 정의해 여러 서비스에 적용했다.",
            ),
        },
    ),
    (
        ("학습", "머신러닝", "신기술", "ML"),
        {
            "name": "학습 민첩성",
            "description": "새로운 기술과 도구를 빠르게 익혀 업무에 적용한다.",
            "bars": _bars(
                "익숙한 방식만 고수한다.",
                "지시받은 범위에서 새 도구를 익힌다.",
                "스스로 필요한 기술을 찾아 익히고 업무에 적용했다.",
                "새 기술을 적용해 측정 가능한 개선을 만들었다.",
                "학습한 기술을 팀에 전파해 일하는 방식을 바꿨다.",
            ),
        },
    ),
]

_COLLABORATION = {
    "name": "협업과 커뮤니케이션",
    "description": "유관 부서와 이해관계를 조율하고 결과를 명확히 전달한다.",
    "bars": _bars(
        "담당 범위 밖 협업 경험이 거의 없다.",
        "요청받은 범위에서 정보를 공유한다.",
        "유관 부서와 목표를 맞추고 이견을 조정한 경험이 있다.",
        "이견이 있는 상황에서 근거로 합의를 이끌어냈다.",
        "조직 간 협업 구조를 새로 만들어 반복 문제를 줄였다.",
    ),
}

_INITIATIVE = {
    "name": "주도성",
    "description": "맡은 범위를 넘어서는 문제를 스스로 정의하고 끝까지 해결한다.",
    "bars": _bars(
        "지시받은 일만 수행한다.",
        "문제를 발견하면 보고한다.",
        "문제를 스스로 정의하고 해결안을 실행했다.",
        "여러 팀에 걸친 문제를 주도해 해결했다.",
        "조직의 우선순위를 바꾸는 개선을 주도했다.",
    ),
}


_ORG_FIT = {
    "name": "조직 적합과 성장 의지",
    "description": "조직의 일하는 방식과 가치에 맞춰 일하고, 스스로 성장 목표를 세워 실행한다.",
    "bars": _bars(
        "지원 동기와 성장 목표가 막연하다.",
        "회사와 직무에 대한 기대를 일반론으로 설명한다.",
        "경험에 근거해 지원 동기와 성장 계획을 구체적으로 설명한다.",
        "조직의 우선순위와 자신의 강점을 연결해 기여 방식을 제시한다.",
        "장기적 기여 계획을 실행 근거와 함께 제시하고 주변의 성장까지 이끈다.",
    ),
}


def draft_competencies(prompt: str, rng: random.Random) -> dict[str, Any]:
    jd = tag(prompt, "jd") or ""
    earlier = tag(prompt, "earlier_round_competencies") or "없음"
    raw_current = tag(prompt, "current_competencies") or ""
    try:
        current = json.loads(raw_current) if raw_current.startswith("[") else []
    except json.JSONDecodeError:
        current = []
    if current:
        names = {c["name"] for c in current}
        extra = next(
            (c for c in [_INITIATIVE, *(item for _, item in _LIBRARY)] if c["name"] not in names),
            None,
        )
        return {"competencies": [*current, *([extra] if extra else [])]}

    if earlier != "없음":
        # A later round (임원 면접 ...): what the earlier rounds did not look at, plus fit.
        seen = set(earlier.split("\n"))
        picked = [c for c in (_INITIATIVE, _ORG_FIT, _COLLABORATION) if c["name"] not in seen]
        return {"competencies": picked or [_INITIATIVE, _ORG_FIT]}

    scored = [(sum(jd.count(k) for k in keys), item) for keys, item in _LIBRARY]
    picked = [item for hits, item in sorted(scored, key=lambda x: -x[0]) if hits > 0][:4]
    for fallback in (_LIBRARY[0][1], _INITIATIVE):
        if len(picked) >= 2:
            break
        if fallback not in picked:
            picked.append(fallback)
    return {"competencies": [*picked, _COLLABORATION]}


# --- 서류 구조화 ----------------------------------------------------------------------------

SKILLS = (
    "Python Java Go Kotlin TypeScript JavaScript Node.js React Vue Spring FastAPI Django "
    "Kubernetes Docker Kafka Redis PostgreSQL MySQL SQL AWS GCP Terraform gRPC vLLM Triton "
    "PyTorch TensorFlow scikit-learn pandas Prometheus Grafana OpenTelemetry Spotfire JMP Tableau "
    "Excel Figma CVD ALD SPC DOE FDC MES C++ ROS MATLAB Simulink"
).split() + [
    "식각",
    "증착",
    "포토",
    "수율",
    "가상 계측",
    "이상 탐지",
    "머신러닝",
    "통계",
    "사용성 테스트",
    "디자인 시스템",
    "프로토타이핑",
    "자율주행",
    "회로 설계",
    "임베디드",
    "요구사항 분석",
    "데이터 분석",
    "배포",
]

_ROLE = re.compile(
    r"([가-힣A-Za-z]{0,10}\s?(?:엔지니어|개발자|연구원|매니저|디자이너|분석가|리드|책임|선임))"
)
_PERIOD = re.compile(
    r"((?:19|20)\d{2})[.\-/]\s?(\d{1,2})\s*[–~\-]\s*(?:((?:19|20)\d{2})[.\-/]\s?(\d{1,2})|(현재|재직\s?중))"
)
_YEARS = re.compile(r"(?:경력|경험)\s*(\d{1,2})\s*년|(\d{1,2})\s*년\s*(?:차|경력)")
_COMPANY = re.compile(r"\[회사-\d+\]")
_SCHOOL = re.compile(r"\[학교-\d+\]")
_DEGREE = re.compile(r"박사|석사|학사")
_MAJOR = re.compile(r"([가-힣]{1,8}(?:공학|과학|학과|물리학|화학|통계학|경영학|디자인))")
_CERT = re.compile(r"([가-힣]{2,10}(?:산업기사|기사|기능사)|TOEIC\s?\d{3}|OPIc\s?[A-Z]{1,2}\d?)")


def skills_in(text: str) -> list[str]:
    found = []
    for skill in SKILLS:
        if re.search(rf"(?<![A-Za-z]){re.escape(skill)}(?![A-Za-z])", text, re.I):
            found.append(skill)
    return found


def _months(m: re.Match[str]) -> int:
    start = int(m.group(1)) * 12 + int(m.group(2))
    if m.group(5):
        today = date.today()
        end = today.year * 12 + today.month
    else:
        end = int(m.group(3)) * 12 + int(m.group(4))
    return max(0, end - start)


def extract_profile(prompt: str, rng: random.Random) -> dict[str, Any]:
    text = tag(prompt, "document") or ""
    # Block labels of the rendered document ("[본문]", "[표 1]") are not content; tokens have "-n".
    lines = [
        ln.strip(" -•·\t")
        for ln in text.splitlines()
        if ln.strip() and not re.fullmatch(r"\[[^\]\-]+\]", ln.strip())
    ]

    stated = [int(a or b) for a, b in _YEARS.findall(text)]
    work = "\n".join(ln for ln in lines if _COMPANY.search(ln))
    months = sum(_months(m) for m in _PERIOD.finditer(work))
    years = max(stated) if stated else round(months / 12)

    experience = []
    for i, line in enumerate(lines):
        company = _COMPANY.search(line)
        if not company or any(e["company"] == company.group() for e in experience):
            continue
        window = " ".join(lines[i : i + 2])
        role = _ROLE.search(window)
        period = _PERIOD.search(window)
        highlights = [
            ln for ln in lines[i + 1 : i + 4] if not _COMPANY.search(ln) and not _SCHOOL.search(ln)
        ][:2]
        experience.append(
            {
                "company": company.group(),
                "role": role.group(1).strip() if role else "",
                "period": period.group(0) if period else "",
                "highlights": highlights,
            }
        )

    education = []
    for line in lines:
        school = _SCHOOL.search(line)
        if not school or any(e["school"] == school.group() for e in education):
            continue
        degree = _DEGREE.search(line)
        major = next((m for m in _MAJOR.findall(line) if "대학" not in m), "")
        education.append(
            {"school": school.group(), "degree": degree.group() if degree else "", "major": major}
        )

    projects = []
    for i, line in enumerate(lines):
        if "프로젝트" in line and len(line) > 6 and len(projects) < 3:
            detail = lines[i + 1] if i + 1 < len(lines) else ""
            projects.append(
                {"name": line[:40], "description": detail[:120], "tech": skills_in(line + detail)}
            )

    skills = skills_in(text)
    role = next((e["role"] for e in experience if e["role"]), "")
    head = f"{role} {years}년".strip() if years else (role or "경력 정보 없음")
    summary = f"{head}. 주요 기술: {', '.join(skills[:4])}." if skills else f"{head}."
    return {
        "summary": summary,
        "years_experience": years,
        "skills": skills,
        "experience": experience[:4],
        "education": education[:2],
        "projects": projects,
        "certifications": sorted(set(_CERT.findall(text)))[:4],
    }


# --- 서류 선별 ------------------------------------------------------------------------------

_REQUIRED_YEARS = re.compile(r"(\d{1,2})\s*년\s*이상")


def assess_screening(prompt: str, rng: random.Random) -> dict[str, Any]:
    jd = tag(prompt, "jd") or ""
    try:
        profile = json.loads(tag(prompt, "candidate_profile") or "{}")
    except json.JSONDecodeError:
        profile = {}
    years = float(profile.get("years_experience") or 0)
    required = max((int(n) for n in _REQUIRED_YEARS.findall(jd)), default=0)
    wanted = skills_in(jd)
    have = {s.lower() for s in profile.get("skills") or []}
    matched = [s for s in wanted if s.lower() in have]
    missing = [s for s in wanted if s.lower() not in have]

    years_part = 1.0 if required == 0 else min(1.0, years / required)
    skill_part = len(matched) / len(wanted) if wanted else 0.5
    fit = round(25 + 40 * years_part + 35 * skill_part + rng.uniform(-4, 4))
    fit = max(0, min(100, fit))

    strengths, concerns = [], []
    if required and years >= required:
        strengths.append(f"경력 {years:g}년, 필수 요건({required}년 이상) 충족")
    elif required:
        concerns.append(f"경력 {years:g}년으로 필수 요건({required}년 이상)에 못 미침")
    if matched:
        strengths.append(f"JD 핵심 기술 경험: {', '.join(matched[:4])}")
    if missing:
        concerns.append(f"JD에 있는 {', '.join(missing[:3])} 경험이 서류에 드러나지 않음")
    if not profile.get("experience"):
        concerns.append("경력 사항을 서류에서 구조화하지 못함, 원문 확인 필요")

    if fit >= 75:
        recommendation, summary = "passed", "필수 요건과 핵심 기술이 JD와 대부분 맞습니다."
    elif fit >= 55:
        recommendation, summary = (
            "hold",
            "요건 일부는 맞지만 근거가 부족한 항목이 있어 확인이 필요합니다.",
        )
    else:
        recommendation, summary = "rejected", "필수 요건이나 핵심 기술 근거가 JD와 거리가 있습니다."
    return {
        "fit_score": fit,
        "summary": summary,
        "strengths": strengths or ["서류에서 JD와 맞는 근거를 찾지 못함"],
        "concerns": concerns,
        "recommendation": recommendation,
    }


# --- 평점 ---------------------------------------------------------------------------------

_SIGNALS = ("검증", "확인", "비교", "데이터", "원인", "합의", "개선", "측정", "기준", "설계")


def competency_names(prompt: str) -> list[str]:
    block = tag(prompt, "competencies") or ""
    return [m.group(1).strip() for m in re.finditer(r"^- ([^:\n]+):", block, re.M)]


def _pick_competency(prompt: str) -> str | None:
    names = competency_names(prompt)
    target = (tag(prompt, "target_competency") or "").strip()
    if target in names:
        return target
    answer = tag(prompt, "answer") or ""
    for name in names:
        if any(part in answer for part in re.split(r"[\s·과와]+", name) if len(part) >= 2):
            return name
    return names[0] if names else None


def evidence_sentence(answer: str, rng: random.Random) -> str:
    parts = sentences(answer)
    with_numbers = [s for s in parts if re.search(r"\d", s)]
    pool = with_numbers or parts or [answer]
    return rng.choice(pool)


def score_answer(prompt: str, rng: random.Random) -> dict[str, Any]:
    answer = tag(prompt, "answer") or ""
    competency = _pick_competency(prompt)
    if not answer.strip() or competency is None:
        return {"scores": []}
    score = 2 + bool(re.search(r"\d", answer)) + (len(answer) > 150)
    score += any(word in answer for word in _SIGNALS)
    score += rng.choice((-1, 0, 0, 0, 1))
    return {
        "scores": [
            {
                "competency": competency,
                "score": max(1, min(5, score)),
                "evidence": evidence_sentence(answer, rng),
                "confidence": round(0.55 + rng.random() * 0.35, 2),
            }
        ]
    }


# --- 꼬리질문 (stream) -------------------------------------------------------------------

# (competency keywords, what the question is about (matched against earlier rounds' questions),
#  question, rationale, deeper question for when an earlier round already asked it)
_FOLLOW_UPS: list[tuple[tuple[str, ...], tuple[str, ...], str, str, str]] = [
    (
        ("문제",),
        ("원인", "가설"),
        "원인을 어떻게 좁혀 갔고, 다른 가설은 어떻게 배제했나요?",
        "원인 규명과 검증 과정을 확인합니다. 답변에는 결과 위주로 설명되어 있습니다.",
        "같은 방법이 통하지 않았던 사례가 있다면, 그때는 판단을 어떻게 바꾸셨나요?",
    ),
    (
        ("데이터", "분석"),
        ("근거", "데이터"),
        "그 판단의 근거가 된 데이터는 무엇이었고, 충분하다고 본 이유는 무엇인가요?",
        "판단 근거 데이터의 출처와 충분성을 확인합니다.",
        "데이터가 부족한 상황에서 결정해야 했다면 무엇을 기준으로 삼으셨나요?",
    ),
    (
        ("협업", "커뮤니케이션"),
        ("합의", "의견", "갈렸"),
        "그 과정에서 의견이 달랐던 사람과는 어떻게 합의했나요?",
        "이해관계자와의 조율 방식을 확인합니다.",
        "합의한 뒤에도 결과가 기대와 달랐을 때 관계와 일정은 어떻게 다시 맞추셨나요?",
    ),
    (
        ("설계",),
        ("대안", "구조"),
        "그 구조를 정할 때 비교한 대안과 포기한 것은 무엇이었나요?",
        "설계 트레이드오프 인식을 확인합니다.",
        "그 결정을 지금 다시 한다면 무엇을 바꾸고, 그 이유는 무엇인가요?",
    ),
    (
        ("운영", "장애"),
        ("재발", "다시"),
        "그 뒤로 같은 문제가 다시 생기지 않았다는 것은 어떻게 확인했나요?",
        "재발 방지 조치의 실효성을 확인합니다.",
        "그 조치를 다른 팀이나 서비스로 넓힐 때 무엇이 걸림돌이었나요?",
    ),
    (
        ("품질", "코드"),
        ("보장", "테스트"),
        "그 변경이 기존 동작을 깨지 않았다는 것은 어떻게 보장했나요?",
        "안전한 변경 방식과 테스트 전략을 확인합니다.",
        "팀 전체의 품질 기준을 바꾸려 할 때 어떤 반대가 있었고 어떻게 설득하셨나요?",
    ),
    (
        ("이해", "장비", "공정"),
        ("원리", "변수"),
        "그 부분의 원리를 조금 더 구체적으로 설명해 주실 수 있나요?",
        "메커니즘 수준의 이해를 확인합니다.",
        "그 원리가 다른 공정이나 조건에서는 어떻게 달라지는지 설명해 주시겠어요?",
    ),
    (
        ("주도", "리더", "책임"),
        ("주도", "책임"),
        "그 일을 맡게 된 계기와, 본인이 먼저 나서서 바꾼 것은 무엇이었나요?",
        "스스로 문제를 정의하고 끝까지 책임진 정도를 확인합니다.",
        "성과가 나지 않았을 때 그 책임을 어떻게 지고 다음 결정을 내리셨나요?",
    ),
    (
        ("조직", "성장", "적합"),
        ("동기", "성장"),
        "그 경험이 지원하신 직무에서 어떻게 이어질 것이라고 보시나요?",
        "경험과 지원 동기, 성장 계획의 연결을 확인합니다.",
        "입사 후 첫해에 스스로 세운 목표를 이루지 못한다면 무엇부터 바꾸시겠어요?",
    ),
]
_DEFAULT_FOLLOW_UP = (
    "그 일에서 본인이 직접 한 부분과 판단 근거를 더 구체적으로 말씀해 주시겠어요?",
    "본인 기여와 판단 근거를 확인합니다.",
)


def _earlier_rounds(text: str | None) -> list[tuple[str, str, str]]:
    """(round label, question, answer) of an `<earlier_rounds>` block (prompts.earlier_rounds_text)."""
    if not text or text == "없음":
        return []
    found = []
    for block in re.split(r"\n\n(?=\[)", text):
        m = re.match(r"\[([^\]]+)\] Q: (.*?)\nA: (.*)", block, re.S)
        if m:
            found.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return found


def _asked_before(about: tuple[str, ...], questions: list[str]) -> bool:
    return any(word in q for q in questions for word in about)


def _fragment(sentence: str, words: int = 5) -> str:
    parts = sentence.rstrip(".?! ").split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def follow_up_text(prompt: str, rng: random.Random) -> str | None:
    """Tagged suggestions for a follow-up request, or None when the prompt is not one."""
    request = tag(prompt, "follow_up_request")
    if request is None:
        return None
    answer = tag(request, "answer") or ""
    names = competency_names(request) or ["역량"]
    target = (tag(request, "target_competency") or "").strip()
    order = ([target] if target in names else []) + [n for n in names if n != target]
    picks = [s.rstrip(".?!") for s in sentences(answer)]
    picks.sort(key=lambda s: (not re.search(r"\d", s), -len(s)))
    if not picks:
        return ""

    earlier = _earlier_rounds(tag(request, "earlier_rounds"))
    earlier_questions = [q for _, q, _ in earlier]
    blocks = []
    for i in range(3):
        competency = order[i % len(order)]
        grounding = picks[i % len(picks)]
        tail, rationale = _DEFAULT_FOLLOW_UP
        for keys, about, q, r, deeper in _FOLLOW_UPS:
            if any(k in competency for k in keys):
                tail, rationale = q, r
                if _asked_before(about, earlier_questions):
                    label = earlier[-1][0]
                    tail = deeper
                    rationale = (
                        f"{label}에서 '{about[0]}'은(는) 이미 물었으므로 반복하지 않고 한 단계 더 "
                        "깊이 확인합니다."
                    )
                break
        question = f"“{_fragment(grounding)}”라고 하셨는데, {tail}"
        if i == 0 and earlier:
            label, _, before = earlier[-1]
            echo = sentences(before)
            if echo:
                question = (
                    f"{label}에서는 “{_fragment(echo[0])}”라고 하셨는데, 이번에 말씀하신 "
                    f"“{_fragment(grounding)}”와는 어떻게 이어지나요?"
                )
                rationale = (
                    f"{label} 답변과 이어 보며 일관성과 깊이를 확인합니다. {label}에서 물은 "
                    "질문은 반복하지 않습니다."
                )
        blocks.append(
            "<suggestion>"
            f"<competency>{competency}</competency>"
            f"<question>{question}</question>"
            f"<rationale>{rationale}</rationale>"
            f"<grounding>{grounding}</grounding>"
            "</suggestion>"
        )
    return "\n".join(blocks)


def chunks(text: str, rng: random.Random) -> Iterator[str]:
    """Token-sized pieces (2-4 characters), the way a streaming model delivers text."""
    i = 0
    while i < len(text):
        step = rng.randint(2, 4)
        yield text[i : i + step]
        i += step


# --- 사전 질문 초안 (차수별) --------------------------------------------------------------------

# (competency keywords, questions, deeper questions for a later round)
_PRESETS: list[tuple[tuple[str, ...], tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]] = [
    (
        ("문제",),
        (
            ("가장 어려웠던 문제를 하나 골라, 원인을 어떻게 좁혀 갔는지 설명해 주세요.", "가설 수립과 검증"),
            ("해결책이 기대만큼 효과가 없었던 경험과 그 뒤의 대응을 말씀해 주세요.", "실패 대응과 재검증"),
        ),
        (
            ("같은 문제가 다른 조건에서 다시 생긴다면 무엇부터 다르게 하시겠어요?", "학습과 일반화"),
            ("해결 방법을 팀의 표준으로 만든 경험이 있나요? 무엇이 어려웠나요?", "확산과 표준화"),
        ),
    ),
    (
        ("데이터", "분석"),
        (
            ("데이터로 판단을 바꾼 사례를 하나 설명해 주세요. 어떤 데이터를 어떤 순서로 보셨나요?", "분석 절차"),
            ("분석 결과가 현장의 직감과 달랐던 경험과 그때의 결론을 말씀해 주세요.", "데이터 근거 설득"),
        ),
        (
            ("데이터가 불완전한 상황에서 결정해야 했던 경험과 그 기준을 말씀해 주세요.", "불확실성 아래 판단"),
            ("분석 체계를 다른 사람도 쓸 수 있게 만든 경험이 있나요?", "분석의 확산"),
        ),
    ),
    (
        ("협업", "커뮤니케이션", "영향"),
        (
            ("유관 부서와 의견이 갈렸던 사례와 합의에 이른 과정을 말씀해 주세요.", "이견 조율"),
            ("외부 협력사와 일하며 어려웠던 점과 해결 방법은 무엇이었나요?", "외부 협업"),
        ),
        (
            ("권한이 없는 상대를 설득해 일정을 바꾼 경험을 말씀해 주세요.", "영향력"),
            ("협업이 실패했던 경험에서 본인이 바꾼 일하는 방식은 무엇인가요?", "회고와 변화"),
        ),
    ),
    (
        ("주도", "리더", "책임"),
        (
            ("맡은 범위를 넘어 스스로 문제를 정의하고 끝까지 해결한 경험을 말씀해 주세요.", "주도성"),
            ("팀의 우선순위를 바꾸자고 제안한 경험과 결과를 말씀해 주세요.", "변화 주도"),
        ),
        (
            ("결정이 틀렸다고 드러났을 때 책임을 어떻게 지셨나요?", "책임감"),
            ("후배나 동료의 성장을 이끈 구체적 사례를 말씀해 주세요.", "사람의 성장"),
        ),
    ),
    (
        ("조직", "성장", "적합"),
        (
            ("이 직무를 고른 이유와, 지난 경력과 어떻게 이어지는지 말씀해 주세요.", "지원 동기"),
            ("앞으로 3년 동안 이루고 싶은 성장 목표와 그 근거는 무엇인가요?", "성장 계획"),
        ),
        (
            ("조직의 방향과 본인의 판단이 달랐던 경험과 그때의 선택을 말씀해 주세요.", "가치 판단"),
            ("입사 후 첫해에 회사에 기여할 방법을 구체적으로 말씀해 주세요.", "기여 방식"),
        ),
    ),
]
_DEFAULT_PRESETS = (
    ("이 역량이 드러난 최근 경험을 하나 골라 상황, 행동, 결과 순으로 설명해 주세요.", "행동 사례"),
    ("그 경험에서 다시 한다면 무엇을 바꾸시겠어요?", "회고"),
)


def _lines(block: str | None) -> list[str]:
    if not block or block == "없음":
        return []
    return [ln.strip()[2:].strip() for ln in block.splitlines() if ln.strip().startswith("- ")]


def draft_presets(prompt: str, rng: random.Random) -> dict[str, Any]:
    names = competency_names(prompt)
    earlier = _lines(tag(prompt, "earlier_round_questions"))
    existing = set(_lines(tag(prompt, "existing_questions")))
    questions = []
    for name in names:
        base, deeper = next(
            ((b, d) for keys, b, d in _PRESETS if any(k in name for k in keys)),
            (_DEFAULT_PRESETS, _DEFAULT_PRESETS),
        )
        # A later round digs deeper than what earlier rounds asked.
        pool = [*deeper, *base] if earlier else [*base, *deeper]
        picked = [(q, i) for q, i in pool if q not in existing and q not in earlier][:2]
        questions += [{"competency": name, "question": q, "intent": i} for q, i in picked]
    return {"questions": questions}


# --- 이어 질문 ---------------------------------------------------------------------------------

_QA_BLOCK = re.compile(r'<qa ref="([^"]+)" round="([^"]+)">\nQ: (.*?)\nA: (.*?)\n</qa>', re.S)


def _specificity(answer: str) -> int:
    """Rough evidence weight of an answer: numbers and signal words."""
    return len(re.findall(r"\d", answer)) + sum(word in answer for word in _SIGNALS)


def carryover_questions(prompt: str, rng: random.Random) -> dict[str, Any]:
    names = competency_names(prompt) or ["역량"]
    blocks = [m.groups() for m in _QA_BLOCK.finditer(tag(prompt, "earlier_rounds") or "")]
    if not blocks:
        return {"questions": []}
    # The thinnest earlier answers first: that is where the earlier round left most to check.
    ordered = sorted(blocks, key=lambda b: _specificity(b[3]))[:3]
    questions = []
    for i, (ref, label, question, answer) in enumerate(ordered):
        parts = sentences(answer) or [answer]
        grounding = min(parts, key=_specificity).rstrip(".")
        competency = names[i % len(names)]
        topic = _fragment(question, 4)
        questions.append(
            {
                "competency": competency,
                "question": (
                    f"{label}에서 “{_fragment(grounding)}”라고 하셨습니다. 그 일에서 본인이 내린 "
                    "가장 어려운 판단은 무엇이었고, 결과에 대해 어떤 책임을 지셨나요?"
                ),
                "intent": f"{label} 답변 심화",
                "based_on": ref,
                "grounding": grounding,
                "rationale": (
                    f"{label}에서 '{topic}'은(는) 이미 물었고 답변이 결과 위주였습니다. 같은 "
                    f"질문을 반복하지 않고 {competency} 관점에서 판단과 책임을 더 깊이 확인합니다."
                ),
            }
        )
    return {"questions": questions}


# --- 확인이 필요한 점 ---------------------------------------------------------------------------

_INTERVIEW_QA = re.compile(r'<qa seq="(\d+)">\nQ: (.*?)\nA: (.*?)\n</qa>', re.S)


def check_points(prompt: str, rng: random.Random) -> dict[str, Any]:
    names = competency_names(prompt)
    blocks = [m.groups() for m in _INTERVIEW_QA.finditer(tag(prompt, "interview") or "")]
    answered = [(int(n), q, a) for n, q, a in blocks if a.strip()]
    points = []
    for seq, question, answer in sorted(answered, key=lambda b: _specificity(b[2]))[:2]:
        parts = sentences(answer) or [answer]
        evidence = min(parts, key=_specificity)
        competency = next(
            (n for n in names if any(p in question + answer for p in re.split(r"[\s·과와]+", n) if len(p) >= 2)),
            names[0] if names else "",
        )
        points.append(
            {
                "competency": competency,
                "point": (
                    f"{competency}: 이 답변은 근거가 적어 본인이 직접 한 판단과 결과를 다음 "
                    "차수에서 구체적으로 확인할 필요가 있습니다."
                ),
                "evidence": evidence,
                "qa_seq": seq,
            }
        )
    return {"points": points}
