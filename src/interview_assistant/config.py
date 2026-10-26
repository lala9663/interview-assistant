"""Settings: environment variables (IA_* prefix) plus the providers YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSpec(BaseModel):
    """One `impl: ...` entry. Every key other than `impl` is passed to the implementation."""

    model_config = ConfigDict(extra="allow")

    impl: str

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class ProvidersConfig(BaseModel):
    llm: dict[str, ProviderSpec]  # roles: primary, screening
    stt: dict[str, ProviderSpec]  # roles: streaming, batch
    embedding: ProviderSpec
    diarization: ProviderSpec

    def by_role(self) -> dict[str, ProviderSpec]:
        """Flat role keys as the admin screen and the settings table name them: "llm.primary"."""
        roles = {f"llm.{k}": v for k, v in self.llm.items()}
        roles |= {f"stt.{k}": v for k, v in self.stt.items()}
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


def load_providers(path: Path) -> ProvidersConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if "providers" not in raw:
        raise ValueError(f"{path}: top-level 'providers' key is missing")
    return ProvidersConfig.model_validate(raw["providers"])
