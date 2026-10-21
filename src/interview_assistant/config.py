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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./dev.db"
    providers_file: Path = Path("config/providers.yaml")
    deid_file: Path = Path("config/deid.yaml")
    # Fernet key for encrypted columns (candidate identity, de-identification reverse map).
    encryption_key: SecretStr | None = None


def load_providers(path: Path) -> ProvidersConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if "providers" not in raw:
        raise ValueError(f"{path}: top-level 'providers' key is missing")
    return ProvidersConfig.model_validate(raw["providers"])
