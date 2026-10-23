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
    }
    handler = handlers.get(title or "")
    return handler(prompt, rng) if handler else None


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


def draft_competencies(prompt: str, rng: random.Random) -> dict[str, Any]:
    jd = tag(prompt, "jd") or ""
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

_FOLLOW_UPS: list[tuple[tuple[str, ...], str, str]] = [
    (
        ("문제",),
        "원인을 어떻게 좁혀 갔고, 다른 가설은 어떻게 배제했나요?",
        "원인 규명과 검증 과정을 확인합니다. 답변에는 결과 위주로 설명되어 있습니다.",
    ),
    (
        ("데이터", "분석"),
        "그 판단의 근거가 된 데이터는 무엇이었고, 충분하다고 본 이유는 무엇인가요?",
        "판단 근거 데이터의 출처와 충분성을 확인합니다.",
    ),
    (
        ("협업", "커뮤니케이션"),
        "그 과정에서 의견이 달랐던 사람과는 어떻게 합의했나요?",
        "이해관계자와의 조율 방식을 확인합니다.",
    ),
    (
        ("설계",),
        "그 구조를 정할 때 비교한 대안과 포기한 것은 무엇이었나요?",
        "설계 트레이드오프 인식을 확인합니다.",
    ),
    (
        ("운영", "장애"),
        "그 뒤로 같은 문제가 다시 생기지 않았다는 것은 어떻게 확인했나요?",
        "재발 방지 조치의 실효성을 확인합니다.",
    ),
    (
        ("품질", "코드"),
        "그 변경이 기존 동작을 깨지 않았다는 것은 어떻게 보장했나요?",
        "안전한 변경 방식과 테스트 전략을 확인합니다.",
    ),
    (
        ("이해", "장비", "공정"),
        "그 부분의 원리를 조금 더 구체적으로 설명해 주실 수 있나요?",
        "메커니즘 수준의 이해를 확인합니다.",
    ),
]
_DEFAULT_FOLLOW_UP = (
    "그 일에서 본인이 직접 한 부분과 판단 근거를 더 구체적으로 말씀해 주시겠어요?",
    "본인 기여와 판단 근거를 확인합니다.",
)


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

    blocks = []
    for i in range(3):
        competency = order[i % len(order)]
        grounding = picks[i % len(picks)]
        tail, rationale = next(
            ((q, r) for keys, q, r in _FOLLOW_UPS if any(k in competency for k in keys)),
            _DEFAULT_FOLLOW_UP,
        )
        question = f"“{_fragment(grounding)}”라고 하셨는데, {tail}"
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
