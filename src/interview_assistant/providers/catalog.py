"""What the admin screen can choose from: the AI roles, and per registered implementation where its
data goes, which roles it can serve, its models and options, and what this machine still lacks.

Requirement checks never touch the network or read secrets: they look for installed packages,
whether an environment variable or a credentials file exists (never its value), and whether model
weights are on disk. Credentials are never entered on the screen; they come from the server's
environment or Secret Manager, and an option may only name the environment variable.
"""

from __future__ import annotations

import enum
import importlib.util
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from interview_assistant.providers import registry
from interview_assistant.providers.programs import JAVA, LIBREOFFICE, TESSERACT, Program
from interview_assistant.providers.weights import (
    BGE_M3,
    PADDLEOCR,
    TESSDATA,
    WHISPER,
    WeightSet,
    is_complete,
)


class DataLocation(str, enum.Enum):
    local = "local"  # 이 PC(서버) 안
    server = "server"  # 관리자가 주소를 적은 사내 서버 (오픈소스 모델 서버)
    gcp = "gcp"  # 외부 클라우드 (Google Cloud): 회사 밖, 쓰지 않는 대안
    external = "external"  # 회사 밖 API

    @property
    def leaves_company(self) -> bool:
        """Sending data here needs the admin's confirmation (and a reason to apply)."""
        return self in (DataLocation.gcp, DataLocation.external)


@dataclass(frozen=True)
class Role:
    key: str  # "llm.primary"; also the settings table key
    kind: str  # registry kind: llm, stt, embedding, diarization, ocr, pdf_reader ...
    label: str
    description: str
    group: str = "ai"  # "ai" (AI 모델) or "documents" (서류 읽기): a heading on the screen


ROLES: tuple[Role, ...] = (
    Role("llm.primary", "llm", "LLM 주 모델", "역량 사전 초안, 꼬리질문, AI 채점"),
    Role("llm.screening", "llm", "LLM 선별용", "서류 구조화와 선별"),
    Role("stt.streaming", "stt", "STT 실시간", "면접 중 지원자 답변 전사"),
    Role("stt.batch", "stt", "STT 사후", "녹음 파일 전사 (10단계)"),
    Role("embedding", "embedding", "임베딩", "질문 은행 검색, 같은 질문 거르기, 비슷한 역량 사전·평점 기준 찾기"),
    Role("diarization", "diarization", "화자분리", "대면 면접 화자 구분 (10단계)"),
    Role("document.reading", "reading", "읽기 방식", "텍스트 층과 OCR 중 무엇으로 읽을지, 문서 속 그림", "documents"),
    Role("document.ocr", "ocr", "OCR 엔진", "스캔본·사진·그림 속 글자 읽기", "documents"),
    Role("document.pdf", "pdf_reader", "PDF 텍스트 추출", "PDF의 텍스트 층 읽기", "documents"),
    Role("document.hwp", "hwp_reader", "HWP·HWPX 읽기", "한글 문서 (HWP 5.x, HWPX)", "documents"),
    Role("document.legacy", "office_converter", "구형 오피스 변환", ".doc·.ppt를 .docx·.pptx로 바꿔 읽기", "documents"),
)
ROLE_BY_KEY: dict[str, Role] = {r.key: r for r in ROLES}

FieldType = Literal["string", "text", "integer", "number", "boolean", "select"]


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    note: str = ""
    size_bytes: int | None = None  # weights to download for this choice
    recommended_for: tuple[str, ...] = ()  # role keys


@dataclass(frozen=True)
class OptionField:
    key: str
    label: str
    type: FieldType
    default: Any = None
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = 100
    choices: tuple[Choice, ...] = ()
    roles: tuple[str, ...] = ()  # shown for these roles only (empty: every role)
    fixed: bool = False  # shown, not editable
    optional: bool = False  # a string that may be left empty

    def applies_to(self, role: str) -> bool:
        return not self.roles or role in self.roles


@dataclass(frozen=True)
class Requirement:
    key: str
    label: str
    ok: bool
    detail: str
    fix: str | None = None


@dataclass(frozen=True)
class ImplInfo:
    kind: str
    impl: str
    label: str
    description: str
    data_location: DataLocation
    data_note: str
    license: str
    roles: tuple[str, ...]
    options: tuple[OptionField, ...] = ()
    packages: tuple[tuple[str, str], ...] = ()  # (import name, how to install)
    env: tuple[str, ...] = ()  # environment variables that must exist
    gcp_credentials: bool = False
    weights: Mapping[str, WeightSet] = field(default_factory=dict)  # "model" option value -> files
    role_defaults: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    role_notes: Mapping[str, str] = field(default_factory=dict)
    programs: tuple[Program, ...] = ()  # system programs that must be installed (Tesseract ...)
    # Checks the options together after each field's own check (raises SpecError).
    check: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    # Environment variables the options name (an API key's variable): they must exist.
    option_env: Callable[[Mapping[str, Any]], list[str]] | None = None

    def field(self, key: str) -> OptionField | None:
        return next((f for f in self.options if f.key == key), None)

    def defaults(self, role: str) -> dict[str, Any]:
        values = {f.key: f.default for f in self.options if f.applies_to(role)}
        return values | dict(self.role_defaults.get(role, {}))


# --- the catalog ------------------------------------------------------------------------------

_SPEED = OptionField(
    "speed",
    "지연 흉내 속도",
    "number",
    1.0,
    "1이면 데모 속도, 0이면 지연 없이 바로 답합니다.",
    minimum=0,
    maximum=5,
)
_KO = OptionField("language", "언어", "string", "ko-KR", "한국어로 고정합니다.", fixed=True)
_BATCH_DIARIZATION = OptionField(
    "diarization",
    "화자 구분",
    "boolean",
    False,
    "사후 전사에서 화자 라벨을 붙입니다.",
    roles=("stt.batch",),
)
_GCP_PACKAGES = (("anthropic", "uv sync --extra gcp"),)
_GCP_NOTE = (
    "회사 밖 Google Cloud로 데이터를 보냅니다. GCP는 쓰지 않기로 해서(2026-10-28) 비교용으로만 남긴 "
    "대안입니다."
)
_LIVE_AUDIO_NOTE = (
    "실시간 면접의 음성 입력(마이크·WebRTC)은 다음 단계에서 붙습니다. 그 전까지 진행 중 면접 "
    "화면은 가상 지원자 대본(텍스트)을 보내므로, fake가 아닌 STT로 바꾸면 새로 시작하는 면접의 "
    "전사가 꺼지고 수기 답변 입력으로 바뀝니다. 지금 진행 중인 면접은 시작할 때의 STT를 계속 씁니다."
)

_WHISPER_MODELS = (
    Choice(
        "small",
        "small",
        "가장 가볍고 빠릅니다. 한국어 글자를 자주 틀립니다(노트북 측정 CER 13%).",
        WHISPER["small"].size_bytes,
    ),
    Choice(
        "medium",
        "medium",
        "실시간 권장(정확도 기준, 측정 CER 1%). 노트북 CPU에서 발화 끝부터 확정까지 8~12초 걸립니다.",
        WHISPER["medium"].size_bytes,
        ("stt.streaming",),
    ),
    Choice(
        "large-v3",
        "large-v3",
        "사후 권장. 가장 정확합니다(측정 CER 0%). 노트북 CPU에서 30초 녹음에 약 36초, 메모리 3.3GB.",
        WHISPER["large-v3"].size_bytes,
        ("stt.batch",),
    ),
    Choice(
        "large-v3-turbo",
        "large-v3-turbo",
        "large-v3의 디코더를 줄인 모델. 정확도는 large-v3에 가깝고(CER 0.4%), 인코더가 커서 CPU에서는 medium보다 느립니다.",
        WHISPER["large-v3-turbo"].size_bytes,
    ),
)

def _retrieval_options(sparse: float, duplicate: float, minimum: float) -> tuple[OptionField, ...]:
    """Retrieval settings on the score scale of one embedding model."""
    return (
        OptionField(
            "sparse_weight",
            "단어 일치 가중치",
            "number",
            sparse,
            "검색 점수 = 의미 유사도 + 이 값 × 단어 일치 점수. 전문 용어·약어(FDC, RF, CVD)가 그대로 맞는 "
            "질문을 끌어올립니다. 0이면 의미만 봅니다.",
            minimum=0,
            maximum=1,
        ),
        OptionField(
            "duplicate_threshold",
            "같은 질문으로 볼 유사도",
            "number",
            duplicate,
            "꼬리질문 후보가 이 면접이나 이전 차수에서 이미 한 질문과 의미 유사도가 이 값 이상이면 뺍니다. "
            "낮출수록 더 많이 거릅니다.",
            minimum=0.5,
            maximum=1,
        ),
        OptionField(
            "min_score",
            "질문 은행 제안 최소 점수",
            "number",
            minimum,
            "답변과의 검색 점수가 이보다 낮은 질문 은행 질문은 제안하지 않습니다.",
            minimum=0,
            maximum=2,
        ),
    )


_LOCAL_FILES = "서류와 그림은 이 PC 밖으로 나가지 않습니다."
_NO_LLM_IMAGES = "그림은 OCR로 글자만 읽고 버립니다. LLM에는 그림을 보내지 않습니다."


def _document_impls() -> tuple[ImplInfo, ...]:
    """서류 읽기: OCR engines, the readers per format, the converter and the reading mode."""
    paddle_models = (
        Choice(
            "ppocrv5-mobile",
            "PP-OCRv5 mobile + 한국어 인식",
            "권장. 이 노트북 CPU에서 A4 한 쪽 2~7초, 메모리 최대 약 1.6GB.",
            PADDLEOCR["ppocrv5-mobile"].size_bytes,
            ("document.ocr",),
        ),
        Choice(
            "ppocrv5-server",
            "PP-OCRv5 server + 한국어 인식",
            "검출 모델이 큽니다. 이 노트북 CPU에서 한 쪽 30초 이상, 메모리 약 2.9GB. GPU 서버용.",
            PADDLEOCR["ppocrv5-server"].size_bytes,
        ),
    )
    tessdata = (
        Choice("best", "tessdata_best (kor+eng)", "정확도 우선 LSTM 모델.", TESSDATA["best"].size_bytes),
        Choice("fast", "tessdata_fast (kor+eng)", "빠르고 작은 모델. 한국어 정확도는 더 낮습니다.", TESSDATA["fast"].size_bytes),
    )
    return (
        ImplInfo(
            "reading",
            "standard",
            "읽기 방식",
            "페이지(슬라이드)마다 텍스트 층을 쓸지 OCR로 읽을지 정합니다. 깨진 텍스트 층은 보내지 않습니다.",
            DataLocation.local,
            "설정입니다. 데이터를 보내지 않습니다.",
            "프로젝트 코드",
            ("document.reading",),
            options=(
                OptionField(
                    "mode",
                    "읽기 방식",
                    "select",
                    "auto",
                    "자동: 텍스트 층이 있으면 텍스트, 없거나 깨졌으면 OCR. 항상 OCR: PDF 쪽과 그림을 모두 OCR "
                    "(문서 속성·숨은 텍스트·링크는 그대로 읽음). 텍스트만: OCR 없이, 텍스트 층 없는 쪽이 있으면 보류.",
                    choices=(
                        Choice("auto", "자동 (텍스트 우선, 없거나 깨지면 OCR)", recommended_for=("document.reading",)),
                        Choice("always_ocr", "항상 OCR"),
                        Choice("text_only", "텍스트만 (OCR 안 함)"),
                    ),
                ),
                OptionField(
                    "embedded_images",
                    "문서 속 그림 OCR",
                    "boolean",
                    True,
                    "DOCX·PPTX·HWP·PDF 안의 그림(자격증 사본, 캡처 화면)을 OCR로 읽습니다. 증명사진으로 보이는 "
                    "그림은 이 설정과 관계없이 읽지 않고 버립니다.",
                ),
                OptionField(
                    "sensitivity",
                    "깨짐 판정 민감도",
                    "select",
                    "medium",
                    "텍스트 층이 깨졌다고(글꼴 매핑 문제로 'ÀÌ·Â¼­'처럼 나옴) 볼 기준. 깨진 쪽은 OCR로 다시 읽습니다.",
                    choices=(
                        Choice("low", "낮음 (의심 글자 30% 이상)"),
                        Choice("medium", "보통 (15% 이상 또는 3글자 연속)", recommended_for=("document.reading",)),
                        Choice("high", "높음 (5% 이상 또는 2글자 연속)"),
                    ),
                ),
                OptionField("dpi", "OCR 해상도 (dpi)", "integer", 200, "PDF 쪽을 그림으로 바꿀 해상도.", 100, 400),
                OptionField(
                    "low_confidence",
                    "OCR 신뢰도 경고 기준",
                    "number",
                    0.8,
                    "OCR 평균 신뢰도가 이보다 낮은 쪽은 검토 리포트에 경고로 남깁니다 (0~1).",
                    minimum=0,
                    maximum=1,
                ),
            ),
        ),
        ImplInfo(
            "ocr",
            "fake",
            "Fake OCR",
            "글자를 읽지 않고 자리 표시 한 줄만 돌려줍니다. 화면과 흐름 확인용입니다.",
            DataLocation.local,
            "외부 호출이 없습니다.",
            "프로젝트 코드",
            ("document.ocr",),
        ),
        ImplInfo(
            "ocr",
            "paddleocr",
            "PaddleOCR (로컬, PP-OCRv5 한국어)",
            "이 PC의 CPU에서 PP-OCRv5로 읽습니다. 무료, 오프라인. 한국어·영문·숫자.",
            DataLocation.local,
            f"{_LOCAL_FILES} 모델 파일만 Hugging Face에서 한 번 내려받습니다. {_NO_LLM_IMAGES}",
            "Apache-2.0 (PaddleOCR, PaddlePaddle, PP-OCRv5 모델)",
            ("document.ocr",),
            options=(
                OptionField("model", "모델", "select", "ppocrv5-mobile", choices=paddle_models),
                OptionField(
                    "textline_orientation",
                    "줄 방향 보정",
                    "boolean",
                    False,
                    "뒤집힌 줄을 바로 세웁니다. 바로 선 스캔에서 멀쩡한 줄을 뒤집어 망치는 일이 있어 기본은 끔.",
                ),
                OptionField(
                    "doc_orientation",
                    "쪽 방향 보정",
                    "boolean",
                    False,
                    "90°·180° 돌아간 사진을 바로 세웁니다. 옆으로 찍은 휴대폰 사진이 많으면 켭니다.",
                ),
                OptionField("max_side", "그림 긴 변 제한 (px)", "integer", 2400, "큰 사진은 줄여서 읽습니다.", 1200, 4000),
                OptionField("cpu_threads", "CPU 스레드", "integer", 0, "0이면 자동 (코어 수 - 4).", 0, 32),
            ),
            packages=(("paddleocr", "uv sync --extra ocr"), ("paddle", "uv sync --extra ocr")),
            weights=PADDLEOCR,
        ),
        ImplInfo(
            "ocr",
            "tesseract",
            "Tesseract (로컬, 비교용)",
            "이 PC의 Tesseract 5로 읽습니다. 가볍고 빠르지만 한국어는 음절을 띄어 읽는 등 PaddleOCR보다 부정확합니다.",
            DataLocation.local,
            f"{_LOCAL_FILES} 언어 데이터만 GitHub에서 한 번 내려받습니다. {_NO_LLM_IMAGES}",
            "Apache-2.0 (Tesseract, tessdata)",
            ("document.ocr",),
            options=(
                OptionField("model", "언어 데이터", "select", "best", choices=tessdata),
                OptionField("psm", "페이지 분할 방식 (psm)", "integer", 3, "3 자동, 4 한 단, 6 한 덩어리 글.", 3, 13),
            ),
            weights=TESSDATA,
            programs=(TESSERACT,),
        ),
        ImplInfo(
            "ocr",
            "google_document_ai",
            "Google Document AI (외부 클라우드)",
            "Google Cloud의 Document AI OCR. 구현 전이며 비교 대상입니다. 처리 위치는 프로세서의 리전(us·eu)입니다.",
            DataLocation.gcp,
            "서류 그림(이름·연락처가 그대로 보이는 원본 쪽)을 회사 밖 Google Cloud의 Document AI로 보냅니다.",
            "상용 (GCP 과금)",
            ("document.ocr",),
            options=(
                OptionField("processor_id", "프로세서 ID", "string", "ocr-processor", "Document AI OCR 프로세서."),
                OptionField("location", "위치", "string", "us", "프로세서 리전 (us 또는 eu)."),
            ),
            packages=(("google.cloud.documentai", "uv sync --extra gcp"),),
            env=("GOOGLE_CLOUD_PROJECT", "DOCUMENT_AI_PROCESSOR_ID"),
            gcp_credentials=True,
        ),
        ImplInfo(
            "ocr",
            "clova_ocr",
            "Naver CLOVA OCR (외부)",
            "네이버 클라우드의 CLOVA OCR. 구현 전이며 비교 대상입니다.",
            DataLocation.external,
            "서류 그림(이름·연락처가 그대로 보이는 원본 쪽)을 회사 밖 네이버 클라우드로 보냅니다.",
            "상용 (네이버 클라우드 과금)",
            ("document.ocr",),
            env=("CLOVA_OCR_INVOKE_URL", "CLOVA_OCR_SECRET"),
        ),
        ImplInfo(
            "pdf_reader",
            "pdfplumber",
            "pdfplumber",
            "본문·표·숨은 텍스트·주석·링크·속성을 읽고 자간을 되돌립니다. 텍스트 층 없는 쪽과 깨진 쪽을 가려냅니다.",
            DataLocation.local,
            _LOCAL_FILES,
            "MIT (pdfplumber, pdfminer.six), Apache-2.0/BSD-3 (pypdfium2)",
            ("document.pdf",),
            options=(
                OptionField(
                    "min_text_chars",
                    "텍스트 층 최소 글자 수",
                    "integer",
                    30,
                    "한 쪽의 글자가 이보다 적고 그림이 쪽 대부분을 덮으면 텍스트 층이 없는 쪽(스캔)으로 봅니다.",
                    5,
                    500,
                ),
            ),
            packages=(("pdfplumber", "uv sync"),),
        ),
        ImplInfo(
            "hwp_reader",
            "syhwp",
            "syhwp + OWPML (파이썬)",
            "HWP 5.x는 syhwp(MIT)로 열고 머리글·각주·숨은 설명을 나눠 읽습니다. HWPX는 자체 OWPML 읽기. "
            "문서 정보·미리보기 텍스트·흰 글씨(HWPX)까지 읽고, 암호 걸린 문서는 거부합니다.",
            DataLocation.local,
            _LOCAL_FILES,
            "MIT (syhwp), BSD (olefile)",
            ("document.hwp",),
            packages=(("syhwp", "uv sync"), ("olefile", "uv sync")),
        ),
        ImplInfo(
            "hwp_reader",
            "hwplib",
            "hwplib (Java)",
            "neolord0의 hwplib·hwpxlib(Apache-2.0)으로 읽는 대안 경로. 구현 전입니다. 실제 한글 샘플에서 syhwp가 "
            "부족하면 검토합니다.",
            DataLocation.local,
            _LOCAL_FILES,
            "Apache-2.0 (hwplib, hwpxlib)",
            ("document.hwp",),
            programs=(JAVA,),
        ),
        ImplInfo(
            "office_converter",
            "libreoffice",
            "LibreOffice (헤드리스)",
            "구형 .doc·.ppt를 .docx·.pptx로 바꾼 뒤 같은 방식으로 읽습니다. 매번 임시 프로필로 돌리고 매크로는 실행하지 않습니다.",
            DataLocation.local,
            _LOCAL_FILES,
            "MPL-2.0 (LibreOffice, 별도 프로그램으로 실행)",
            ("document.legacy",),
            options=(OptionField("timeout", "변환 제한 시간 (초)", "integer", 120, minimum=30, maximum=600),),
            programs=(LIBREOFFICE,),
        ),
    )


_SERVER_OPTIONS = (
    OptionField(
        "base_url",
        "서버 주소",
        "string",
        "",
        "모델 서버의 OpenAI 형식 API 주소를 /v1까지 적습니다. 예: vLLM http://10.0.0.5:8000/v1, "
        "Ollama http://10.0.0.5:11434/v1. openai.com 주소는 받지 않습니다.",
        max_length=300,
    ),
    OptionField(
        "model",
        "모델 이름",
        "string",
        "",
        "서버에 올린 이름 그대로 적습니다. vLLM은 --served-model-name(없으면 Hugging Face 경로, 예: "
        "Qwen/Qwen3-8B), Ollama는 qwen3:8b처럼 태그까지.",
        max_length=200,
    ),
    OptionField(
        "api_key_env",
        "API 키 환경변수 이름",
        "string",
        "",
        "서버가 키를 요구하면 키가 든 환경변수의 이름을 적습니다(예: IA_LLM_API_KEY). 키 값은 여기에 "
        "적지 않고 서버 환경에만 둡니다. 비우면 키 없이 부릅니다.",
        optional=True,
    ),
    OptionField(
        "timeout",
        "타임아웃 (초)",
        "number",
        120,
        "요청 하나를 기다리는 최대 시간. 스트리밍은 토큰 사이 간격에 적용합니다. GPU 없는 서버라면 늘립니다.",
        minimum=5,
        maximum=600,
    ),
    OptionField(
        "max_tokens",
        "최대 출력 토큰",
        "integer",
        4096,
        "요청마다 앱이 정한 값과 이 값 중 작은 쪽을 씁니다. 서버의 컨텍스트 길이(vLLM --max-model-len, "
        "Ollama num_ctx)에서 입력 길이를 뺀 것보다 작아야 합니다.",
        minimum=256,
        maximum=32768,
    ),
    OptionField(
        "temperature",
        "온도",
        "number",
        0.3,
        "낮을수록 같은 입력에 같은 답을 냅니다. AI 채점은 한 답변을 세 번 채점해 중앙값을 쓰므로 0보다 "
        "조금 큰 값을 권합니다.",
        minimum=0,
        maximum=2,
    ),
    OptionField(
        "structured_output",
        "구조화 출력 방식",
        "select",
        "json_schema",
        "채점·선별처럼 JSON으로 받는 작업에서 서버에 형식을 어떻게 요구할지. 스키마는 어느 방식이든 "
        "프롬프트에도 넣습니다.",
        choices=(
            Choice(
                "json_schema",
                "JSON 스키마 강제",
                "vLLM·SGLang·Ollama가 스키마에 맞는 JSON만 만듭니다.",
                recommended_for=("llm.primary", "llm.screening"),
            ),
            Choice("json_object", "JSON만 강제", "스키마 강제를 못 하는 서버·게이트웨이용."),
            Choice("prompt", "프롬프트로만 요청", "서버가 response_format을 거부할 때."),
        ),
    ),
    OptionField(
        "headers",
        "추가 헤더 (사내 게이트웨이용)",
        "text",
        "",
        "한 줄에 '이름: 값' 하나. 키·토큰은 값 대신 ${환경변수}로 적습니다 "
        "(예: X-Gateway-Key: ${IA_GATEWAY_KEY}). 값은 서버 환경에서 읽고 저장하지 않습니다.",
        max_length=1000,
    ),
    OptionField(
        "extra_body",
        "추가 요청 필드 (JSON)",
        "text",
        "",
        "서버별 옵션을 요청에 더합니다. 예: vLLM에서 Qwen3의 추론 끄기 "
        '{"chat_template_kwargs": {"enable_thinking": false}}. model·messages·tools 같은 필드는 '
        "넣을 수 없습니다.",
        max_length=2000,
    ),
)


def _check_server_options(values: dict[str, Any]) -> dict[str, Any]:
    from interview_assistant.providers.llm.open_model_server import OptionError, check_options

    try:
        return check_options(values)
    except OptionError as exc:
        raise SpecError(exc.field, str(exc)) from exc


def _server_env(options: Mapping[str, Any]) -> list[str]:
    from interview_assistant.providers.llm.open_model_server import header_env_names

    names = [str(options.get("api_key_env") or "").strip()]
    return [n for n in (*names, *header_env_names(str(options.get("headers") or ""))) if n]


CATALOG: tuple[ImplInfo, ...] = (
    ImplInfo(
        "llm",
        "fake",
        "Fake LLM",
        "자격증명 없이 도는 규칙 기반 응답. 화면과 흐름 확인용이며 내용의 품질은 없습니다.",
        DataLocation.local,
        "외부 호출이 없습니다.",
        "프로젝트 코드",
        ("llm.primary", "llm.screening"),
        options=(
            OptionField(
                "model",
                "모델 이름 (표시용)",
                "string",
                "fake-llm",
                "결과와 감사 로그에 남는 이름입니다.",
            ),
            _SPEED,
        ),
        role_defaults={"llm.screening": {"model": "fake-llm-screening"}},
    ),
    ImplInfo(
        "llm",
        "open_model_server",
        "오픈소스 모델 서버 (vLLM·Ollama 등)",
        "사내에 설치한 오픈 웨이트 모델 서버(vLLM, Ollama, SGLang 등)를 부릅니다. 이런 서버가 주는 "
        "OpenAI 형식 API(/v1/chat/completions)를 쓰지만 OpenAI 서비스로는 보내지 않습니다(openai.com "
        "주소는 거부). 도구 호출은 쓰지 않습니다.",
        DataLocation.server,
        "비식별 텍스트만 관리자가 적은 사내 서버 주소로 보냅니다. 회사 밖 주소를 적으면 안 됩니다. "
        "프롬프트와 응답은 저장하지 않고, 감사 로그에는 호출 기록만 남습니다.",
        "모델마다 다름 (docs/reference/llm.md)",
        ("llm.primary", "llm.screening"),
        options=_SERVER_OPTIONS,
        packages=(("httpx2", "uv sync"),),
        check=_check_server_options,
        option_env=_server_env,
    ),
    ImplInfo(
        "llm",
        "anthropic_vertex",
        "Claude (Vertex AI)",
        "Google Cloud의 Vertex AI로 Claude를 부릅니다. GCP를 쓰지 않기로 해서 구현하지 않은 대안입니다.",
        DataLocation.gcp,
        _GCP_NOTE,
        "상용 (GCP 과금)",
        ("llm.primary", "llm.screening"),
        options=(
            OptionField(
                "model",
                "모델",
                "select",
                "claude-opus-5-5",
                choices=(
                    Choice(
                        "claude-opus-5-5",
                        "Claude Opus 5.5",
                        "주 모델 권장",
                        recommended_for=("llm.primary",),
                    ),
                    Choice("claude-sonnet-5-5", "Claude Sonnet 5.5", "속도와 성능의 균형"),
                    Choice(
                        "claude-haiku-5-5",
                        "Claude Haiku 5.5",
                        "선별용 권장 (대량·저비용)",
                        recommended_for=("llm.screening",),
                    ),
                    Choice("claude-fable-5-1", "Claude Fable 5.1", "가장 높은 성능, 가장 비쌈"),
                ),
            ),
            OptionField(
                "region", "리전", "string", "global", "Vertex AI 엔드포인트 리전 (global 권장)."
            ),
        ),
        packages=_GCP_PACKAGES,
        env=("GOOGLE_CLOUD_PROJECT",),
        gcp_credentials=True,
        role_defaults={"llm.screening": {"model": "claude-haiku-5-5"}},
    ),
    ImplInfo(
        "stt",
        "fake",
        "Fake STT",
        "가상 지원자 대본(텍스트)을 받아 적습니다. 실제 음성은 알아듣지 않고 길이만 알려 줍니다.",
        DataLocation.local,
        "외부 호출이 없습니다.",
        "프로젝트 코드",
        ("stt.streaming", "stt.batch"),
        options=(_KO, _SPEED, _BATCH_DIARIZATION),
        role_defaults={"stt.batch": {"diarization": True}},
    ),
    ImplInfo(
        "stt",
        "faster_whisper",
        "Whisper (로컬, faster-whisper)",
        "OpenAI Whisper를 이 PC의 CPU에서 돌립니다(int8). 무료, 오프라인, 한국어 고정.",
        DataLocation.local,
        "음성은 이 PC 밖으로 나가지 않습니다. 모델 파일만 Hugging Face에서 한 번 내려받습니다.",
        "MIT (faster-whisper, Whisper 가중치)",
        ("stt.streaming", "stt.batch"),
        options=(
            OptionField("model", "모델 크기", "select", "medium", choices=_WHISPER_MODELS),
            _KO,
            OptionField(
                "initial_prompt",
                "기술 용어 힌트",
                "text",
                "",
                "면접에 자주 나오는 용어·약어·고유명사를 적으면 그 표기로 받아 적을 확률이 높아집니다. "
                "예: 반도체 공정, CMP, 식각, 수율, SPC, Kubernetes. 너무 길면 오히려 엉뚱한 말을 "
                "지어낼 수 있으니 짧게 씁니다.",
                max_length=500,
            ),
            OptionField(
                "beam_size",
                "빔 크기",
                "integer",
                5,
                "클수록 조금 더 정확하고 느립니다. 실시간은 1~2.",
                1,
                5,
            ),
            OptionField(
                "vad_min_silence_ms",
                "발화 끝 판정 침묵 (ms)",
                "integer",
                500,
                "이만큼 조용하면 한 발화가 끝난 것으로 보고 확정 전사를 냅니다.",
                200,
                2000,
            ),
            OptionField(
                "cpu_threads", "CPU 스레드", "integer", 0, "0이면 자동 (코어 수 - 4).", 0, 32
            ),
        ),
        packages=(("faster_whisper", "uv sync --extra whisper"),),
        weights=WHISPER,
        role_defaults={
            "stt.streaming": {"model": "medium", "beam_size": 1},
            "stt.batch": {"model": "large-v3", "beam_size": 5},
        },
        role_notes={
            "stt.streaming": _LIVE_AUDIO_NOTE,
            "stt.batch": "화자 구분은 하지 않습니다 (화자분리 역할이 따로 맡습니다).",
        },
    ),
    ImplInfo(
        "stt",
        "google_stt_v2",
        "Google Speech-to-Text v2",
        "Google Cloud의 Speech-to-Text v2 (Chirp). 구현 전이며 비교 대상입니다.",
        DataLocation.gcp,
        _GCP_NOTE,
        "상용 (GCP 과금)",
        ("stt.streaming", "stt.batch"),
        options=(
            OptionField(
                "model",
                "모델",
                "select",
                "chirp_3",
                choices=(
                    Choice("chirp_3", "Chirp 3"),
                    Choice("chirp_2", "Chirp 2"),
                    Choice("long", "long"),
                ),
            ),
            _KO,
            _BATCH_DIARIZATION,
        ),
        packages=(("google.cloud.speech", "uv sync --extra gcp"),),
        env=("GOOGLE_CLOUD_PROJECT",),
        gcp_credentials=True,
        role_defaults={"stt.batch": {"diarization": True}},
        role_notes={"stt.streaming": _LIVE_AUDIO_NOTE},
    ),
    ImplInfo(
        "embedding",
        "fake",
        "Fake 임베딩",
        "단어와 두 글자 조각을 해시해 만든 벡터. 같은 단어를 쓴 문장끼리만 가깝고 뜻은 모릅니다. 흐름 확인용입니다.",
        DataLocation.local,
        "외부 호출이 없습니다.",
        "프로젝트 코드",
        ("embedding",),
        options=(
            OptionField("dimensions", "차원", "integer", 256, minimum=2, maximum=4096),
            *_retrieval_options(0.3, 0.8, 0.15),
        ),
    ),
    ImplInfo(
        "embedding",
        "bge_m3",
        "BGE-M3 (로컬)",
        "BAAI의 다국어 임베딩 모델을 이 PC의 CPU에서 돌립니다(ONNX Runtime). 의미 벡터(1024차원)와 단어 일치 "
        "가중치를 함께 내어, 뜻이 비슷한 질문과 전문 용어·약어가 맞는 질문을 같이 찾습니다. 무료, 오프라인.",
        DataLocation.local,
        "질문·답변 텍스트는 이 PC 밖으로 나가지 않습니다. 모델 파일만 Hugging Face에서 한 번 내려받습니다.",
        "MIT (BGE-M3 모델, ONNX Runtime), Apache-2.0 (tokenizers)",
        ("embedding",),
        options=(
            OptionField(
                "model",
                "모델",
                "select",
                "bge-m3",
                choices=(
                    Choice(
                        "bge-m3",
                        "BGE-M3 (fp32 ONNX)",
                        "한국어 포함 100여 개 언어, 최대 8,192토큰. 밀집 1024차원 + 희소(단어 일치). "
                        "메모리 약 2.5GB.",
                        BGE_M3["bge-m3"].size_bytes,
                        ("embedding",),
                    ),
                ),
            ),
            OptionField(
                "max_length",
                "최대 길이 (토큰)",
                "integer",
                512,
                "이보다 긴 텍스트는 잘라서 임베딩합니다. 면접 답변 하나는 보통 300토큰 안쪽이고, 길수록 느려집니다.",
                64,
                8192,
            ),
            OptionField(
                "cpu_threads", "CPU 스레드", "integer", 0, "0이면 자동 (코어 수의 절반, 최대 6).", 0, 32
            ),
            *_retrieval_options(0.3, 0.85, 0.55),
        ),
        packages=(
            ("onnxruntime", "uv sync --extra embedding"),
            ("tokenizers", "uv sync --extra embedding"),
        ),
        weights=BGE_M3,
    ),
    ImplInfo(
        "embedding",
        "vertex_embedding",
        "Vertex AI 임베딩",
        "Google Cloud의 Vertex AI 텍스트 임베딩. 구현 전이며 비교 대상입니다.",
        DataLocation.gcp,
        _GCP_NOTE,
        "상용 (GCP 과금)",
        ("embedding",),
        options=(
            OptionField(
                "model",
                "모델",
                "select",
                "gemini-embedding-001",
                choices=(
                    Choice("gemini-embedding-001", "gemini-embedding-001"),
                    Choice("text-multilingual-embedding-002", "text-multilingual-embedding-002"),
                ),
            ),
            OptionField("dimensions", "차원", "integer", 768, minimum=128, maximum=3072),
        ),
        env=("GOOGLE_CLOUD_PROJECT",),
        gcp_credentials=True,
    ),
    ImplInfo(
        "diarization",
        "fake",
        "Fake 화자분리",
        "고정된 화자 구간 두 개를 돌려줍니다.",
        DataLocation.local,
        "외부 호출이 없습니다.",
        "프로젝트 코드",
        ("diarization",),
    ),
    ImplInfo(
        "diarization",
        "google_stt_v2",
        "Google Speech-to-Text v2 화자분리",
        "Google Cloud의 Speech-to-Text v2 화자 구분. 구현 전이며 비교 대상입니다.",
        DataLocation.gcp,
        _GCP_NOTE,
        "상용 (GCP 과금)",
        ("diarization",),
        packages=(("google.cloud.speech", "uv sync --extra gcp"),),
        env=("GOOGLE_CLOUD_PROJECT",),
        gcp_credentials=True,
    ),
    *_document_impls(),
)

# Implementations registered only at run time (tests) are looked up here as well.
_EXTRA: dict[tuple[str, str], ImplInfo] = {}


def register(info: ImplInfo) -> None:
    _EXTRA[(info.kind, info.impl)] = info


def unregister(info: ImplInfo) -> None:
    _EXTRA.pop((info.kind, info.impl), None)


def all_impls() -> list[ImplInfo]:
    return [*CATALOG, *_EXTRA.values()]


def impl_info(kind: str, impl: str) -> ImplInfo | None:
    return next((i for i in all_impls() if i.kind == kind and i.impl == impl), None)


def bare(kind: str, impl: str) -> ImplInfo:
    """What the screen shows for a registered impl the catalog does not describe (or a stored
    spec whose impl was removed)."""
    return ImplInfo(
        kind,
        impl,
        impl,
        "카탈로그에 설명이 없는 구현입니다.",
        DataLocation.external,
        "데이터가 어디로 가는지 확인되지 않았습니다.",
        "알 수 없음",
        tuple(r.key for r in ROLES if r.kind == kind),
    )


# --- requirements -----------------------------------------------------------------------------


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # a missing parent package raises
        return False


def _gcp_credentials_present() -> tuple[bool, str]:
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_file and Path(key_file).is_file():
        return True, "서비스 계정 키 파일이 있습니다."
    config = Path(os.environ.get("APPDATA", "")) if os.name == "nt" else Path.home() / ".config"
    if (config / "gcloud" / "application_default_credentials.json").is_file():
        return True, "gcloud 기본 자격증명(ADC)이 있습니다."
    return False, "자격증명이 없습니다."


def requirements(
    info: ImplInfo, options: Mapping[str, Any], *, weights_dir: Path
) -> list[Requirement]:
    """What `info` needs on this machine to run with `options`. No network, no secret values."""
    found: list[Requirement] = []
    path = registry.import_path(info.kind, info.impl)
    implemented = path is not None and _has_module(path.split(":")[0])
    found.append(
        Requirement(
            "implemented",
            "구현",
            implemented,
            "구현되어 있습니다." if implemented else "아직 구현되지 않았습니다.",
            None
            if implemented
            else "이 provider의 구현 단계(구현 순서 문서)를 마친 뒤 쓸 수 있습니다.",
        )
    )
    for module, install in info.packages:
        ok = _has_module(module)
        found.append(
            Requirement(
                f"package:{module}",
                f"패키지 {module}",
                ok,
                "설치되어 있습니다." if ok else "설치되어 있지 않습니다.",
                None if ok else f"서버에서 `{install}` 실행 후 서버를 다시 띄웁니다.",
            )
        )
    named = info.option_env(options) if info.option_env else []
    for name in dict.fromkeys([*info.env, *named]):
        ok = bool(os.environ.get(name))
        found.append(
            Requirement(
                f"env:{name}",
                f"환경변수 {name}",
                ok,
                "설정되어 있습니다." if ok else "설정되어 있지 않습니다.",
                None
                if ok
                else "서버를 띄우는 환경(또는 Secret Manager)에 설정합니다. 화면에서는 입력받지 않습니다.",
            )
        )
    if info.gcp_credentials:
        ok, detail = _gcp_credentials_present()
        found.append(
            Requirement(
                "gcp_credentials",
                "GCP 자격증명",
                ok,
                detail,
                None
                if ok
                else "서비스 계정 키(GOOGLE_APPLICATION_CREDENTIALS)나 Secret Manager로 서버에만 둡니다. "
                "화면에서는 입력받지 않습니다.",
            )
        )
    for program in info.programs:
        path = program.find()
        version = program.version() if path else None
        found.append(
            Requirement(
                program.key,
                program.label,
                path is not None,
                (version or "설치되어 있습니다.") if path else "설치되어 있지 않습니다.",
                None if path else program.install,
            )
        )
    weights = info.weights.get(str(options.get("model", "")))
    if weights is not None:
        ok = is_complete(weights, weights_dir)
        found.append(
            Requirement(
                f"weights:{weights.key}",
                f"모델 파일 {options.get('model')}",
                ok,
                "내려받았습니다."
                if ok
                else f"아직 내려받지 않았습니다 ({_size(weights.size_bytes)}).",
                None if ok else "모델 크기 옆의 다운로드 버튼으로 받습니다.",
            )
        )
    return found


def _size(n: int) -> str:
    return f"{n / 1e9:.1f}GB" if n >= 1e9 else f"{n / 1e6:.0f}MB"


# --- option validation ------------------------------------------------------------------------


class SpecError(ValueError):
    def __init__(self, field_key: str, message: str) -> None:
        super().__init__(message)
        self.field = field_key
        self.message = message


def validate_options(info: ImplInfo, role: str, options: Mapping[str, Any]) -> dict[str, Any]:
    """Options from the admin screen, checked against the schema and completed with defaults.
    Unknown keys are refused: nothing but declared options reaches a provider's constructor."""
    fields = {f.key: f for f in info.options if f.applies_to(role)}
    unknown = sorted(set(options) - set(fields))
    if unknown:
        raise SpecError(unknown[0], f"알 수 없는 옵션입니다: {', '.join(unknown)}")
    values = info.defaults(role)
    for key, f in fields.items():
        if key not in options:
            continue
        value = options[key]
        if f.fixed:
            if value != values.get(key):
                raise SpecError(key, f"{f.label}은(는) 바꿀 수 없습니다.")
            continue
        values[key] = _check(f, value)
    return info.check(values) if info.check else values


def _check(f: OptionField, value: Any) -> Any:
    if f.type == "boolean":
        if not isinstance(value, bool):
            raise SpecError(f.key, f"{f.label}: 참/거짓 값이어야 합니다.")
        return value
    if f.type in ("integer", "number"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecError(f.key, f"{f.label}: 숫자여야 합니다.")
        if f.type == "integer":
            if int(value) != value:
                raise SpecError(f.key, f"{f.label}: 정수여야 합니다.")
            value = int(value)
        if f.minimum is not None and value < f.minimum:
            raise SpecError(f.key, f"{f.label}: {f.minimum:g} 이상이어야 합니다.")
        if f.maximum is not None and value > f.maximum:
            raise SpecError(f.key, f"{f.label}: {f.maximum:g} 이하여야 합니다.")
        return value
    if not isinstance(value, str):
        raise SpecError(f.key, f"{f.label}: 문자열이어야 합니다.")
    if f.type == "select":
        if value not in {c.value for c in f.choices}:
            raise SpecError(f.key, f"{f.label}: 고를 수 있는 값이 아닙니다.")
        return value
    value = value.strip()
    if len(value) > f.max_length:
        raise SpecError(f.key, f"{f.label}: {f.max_length}자 이하로 적어 주세요.")
    if f.type == "string" and not value and not f.optional:
        raise SpecError(f.key, f"{f.label}: 비워 둘 수 없습니다.")
    return value
