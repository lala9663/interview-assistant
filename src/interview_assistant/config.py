"""Settings: environment variables (IA_* prefix) plus the providers YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSpec(BaseModel):
    """One `impl: ...` entry. Every key other than `impl` is passed to the implementation."""

    model_config = ConfigDict(extra="allow")

    impl: str

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


def _spec(impl: str, **options: Any) -> Any:
    return lambda: ProviderSpec(impl=impl, **options)


class DocumentsConfig(BaseModel):
    """Document reading (admin > 모델 설정 > 서류 읽기). A YAML without this section gets these
    defaults: no OCR engine that needs a download, the built-in readers, the automatic mode."""

    ocr: ProviderSpec = Field(default_factory=_spec("fake"))
    pdf: ProviderSpec = Field(default_factory=_spec("pdfplumber"))
    hwp: ProviderSpec = Field(default_factory=_spec("syhwp"))
    legacy: ProviderSpec = Field(default_factory=_spec("libreoffice"))
    reading: ProviderSpec = Field(default_factory=_spec("standard"))


class AudioConfig(BaseModel):
    """Microphone input (admin > 모델 설정 > 음성 입력). A YAML without this section gets these
    defaults (docs/audio-input.md): Silero VAD (bundled with faster-whisper), Smart Turn judging
    after 1 s of silence (silence of 2 s while its model file is not downloaded), no server-side
    noise suppression."""

    vad: ProviderSpec = Field(default_factory=_spec("silero"))
    turn: ProviderSpec = Field(
        default_factory=_spec("smart_turn", pause_ms=1000, threshold=0.8, max_silence_ms=3000)
    )
    denoise: ProviderSpec = Field(default_factory=_spec("off"))


class ProvidersConfig(BaseModel):
    llm: dict[str, ProviderSpec]  # roles: primary, screening
    stt: dict[str, ProviderSpec]  # roles: streaming, batch
    embedding: ProviderSpec
    diarization: ProviderSpec
    documents: DocumentsConfig = Field(default_factory=DocumentsConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)

    def by_role(self) -> dict[str, ProviderSpec]:
        """Flat role keys as the admin screen and the settings table name them: "llm.primary"."""
        roles = {f"llm.{k}": v for k, v in self.llm.items()}
        roles |= {f"stt.{k}": v for k, v in self.stt.items()}
        roles |= {f"document.{k}": getattr(self.documents, k) for k in DocumentsConfig.model_fields}
        roles |= {f"audio.{k}": getattr(self.audio, k) for k in AudioConfig.model_fields}
        return roles | {"embedding": self.embedding, "diarization": self.diarization}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./dev.db"
    providers_file: Path = Path("config/providers.yaml")
    deid_file: Path = Path("config/deid.yaml")
    # Fernet key for encrypted columns (candidate identity, de-identification reverse map).
    encryption_key: SecretStr | None = None
    # Raw zone on disk: uploaded application files and (step 11) recordings. Never served.
    uploads_dir: Path = Path("uploads")
    recordings_dir: Path = Path("recordings")
    # Local model weights (faster-whisper ...), downloaded from the admin screen. Git-ignored.
    weights_dir: Path = Path("weights")
    # Until SSO (Phase 1): employee number of the interviewer the API treats as signed in.
    # Empty: the first interviewer created.
    dev_interviewer: str | None = None
    # Pace of the simulated candidate in live interviews (1 = like the frontend mock, 0 = instant).
    demo_speed: float = 1.0
    # Recruiting-site intake (docs/site-intake-spec.md): the shared HMAC key the site signs every
    # request with. Empty: the site endpoints answer 503. `_previous` is accepted too while a key
    # is being rotated.
    site_secret: SecretStr | None = None
    site_secret_previous: SecretStr | None = None
    # How far a request's signed timestamp may be from the server clock, in seconds.
    site_clock_skew: int = 300
    # Background workers applying received events. 0: events wait in the queue (tests, maintenance).
    intake_workers: int = 4
    # Agent calls through the MCP server (docs/agent-integration.md). How a call proves who is
    # asking (api/agent_access.py `agent_identity`): "dev_token" until the agent platform's or
    # SSO's identity is known and added there. Its key (scripts/agent_token.py); empty: 503.
    agent_identity: Literal["dev_token"] = "dev_token"
    agent_token_secret: SecretStr | None = None


def load_providers(path: Path) -> ProvidersConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if "providers" not in raw:
        raise ValueError(f"{path}: top-level 'providers' key is missing")
    return ProvidersConfig.model_validate(raw["providers"])
