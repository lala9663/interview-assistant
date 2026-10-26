"""What the admin screen can choose from: the AI roles, and per registered implementation where its
data goes, which roles it can serve, its models and options, and what this machine still lacks.

Requirement checks never touch the network or read secrets: they look for installed packages,
whether an environment variable or a credentials file exists (never its value), and whether model
weights are on disk. Credentials are never entered on the screen; they come from the server's
environment or Secret Manager.
"""

from __future__ import annotations

import enum
import importlib.util
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from interview_assistant.providers import registry
from interview_assistant.providers.weights import WHISPER, WeightSet, is_complete


class DataLocation(str, enum.Enum):
    local = "local"  # 이 PC(서버) 안
    gcp = "gcp"  # 사내 GCP 프로젝트
    external = "external"  # 회사 밖 API


@dataclass(frozen=True)
class Role:
    key: str  # "llm.primary"; also the settings table key
    kind: str  # registry kind: llm, stt, embedding, diarization
    label: str
    description: str


ROLES: tuple[Role, ...] = (
    Role("llm.primary", "llm", "LLM 주 모델", "역량 사전 초안, 꼬리질문, AI 채점"),
    Role("llm.screening", "llm", "LLM 선별용", "서류 구조화와 선별"),
    Role("stt.streaming", "stt", "STT 실시간", "면접 중 지원자 답변 전사"),
    Role("stt.batch", "stt", "STT 사후", "녹음 파일 전사 (10단계)"),
    Role("embedding", "embedding", "임베딩", "검색·유사도 (후순위)"),
    Role("diarization", "diarization", "화자분리", "대면 면접 화자 구분 (10단계)"),
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
_GCP_NOTE = "사내 GCP 프로젝트 안에서 처리합니다. 회사 밖 API로는 보내지 않습니다."
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
        "anthropic_vertex",
        "Claude (Vertex AI)",
        "사내 GCP 프로젝트의 Vertex AI로 Claude를 부릅니다. 3단계에서 구현합니다.",
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
        "사내 GCP 프로젝트의 Speech-to-Text v2 (Chirp). 10·11단계에서 구현합니다.",
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
        "텍스트 해시로 만든 단위 벡터. 차원과 흐름 확인용입니다.",
        DataLocation.local,
        "외부 호출이 없습니다.",
        "프로젝트 코드",
        ("embedding",),
        options=(OptionField("dimensions", "차원", "integer", 8, minimum=2, maximum=4096),),
    ),
    ImplInfo(
        "embedding",
        "vertex_embedding",
        "Vertex AI 임베딩",
        "사내 GCP 프로젝트의 Vertex AI 텍스트 임베딩. 후순위로 구현합니다.",
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
        "사내 GCP 프로젝트의 Speech-to-Text v2 화자 구분. 10단계에서 구현합니다.",
        DataLocation.gcp,
        _GCP_NOTE,
        "상용 (GCP 과금)",
        ("diarization",),
        packages=(("google.cloud.speech", "uv sync --extra gcp"),),
        env=("GOOGLE_CLOUD_PROJECT",),
        gcp_credentials=True,
    ),
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
    for name in info.env:
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
    return values


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
    if f.type == "string" and not value:
        raise SpecError(f.key, f"{f.label}: 비워 둘 수 없습니다.")
    return value
