"""Which provider serves each AI role right now, and switching it without a restart.

A `ProviderSet` is an immutable snapshot of every role (AI models and 서류 읽기) at one config
revision, with its own AI gateway. `ModelManager.active` is the set new work uses; replacing it is a single reference
assignment, so a request or background task that already holds a set keeps it to the end.
Interview sessions pin the revision they started with (`InterviewSession.ai_config_revision`) and
get their set back from `for_revision`, rebuilt from the history when needed (after a restart):
live transcription, follow-ups and the AI scoring after the interview all use it. Provider
instances are shared between sets by spec, so the same Whisper weights load once, and instances
that neither the active set nor a live session uses are dropped (`evict`).

Changing a role: the spec is checked against the catalog, this machine must meet its requirements,
a provider sending data out of the company (an outside API, Google Cloud) needs an explicit
confirmation, and the new provider is built and warmed up (weights loaded) before anything is written. Only then is the
change recorded (history + active row) and the new set swapped in.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import AiGateway
from interview_assistant.ai_models import store
from interview_assistant.config import ProviderSpec, Settings, load_providers
from interview_assistant.documents.reading import DocumentReader
from interview_assistant.models import (
    AiModelChange,
    AiScoringStatus,
    InterviewSession,
    ModelChangeKind,
    SessionStatus,
)
from interview_assistant.providers import catalog, registry
from interview_assistant.providers.base import (
    DiarizationProvider,
    EmbeddingProvider,
    LLMProvider,
    ProviderUnavailable,
    STTProvider,
)
from interview_assistant.providers.catalog import ImplInfo, Requirement, Role
from interview_assistant.providers.weights import DownloadManager

log = logging.getLogger(__name__)


@dataclass
class Providers:
    llm: dict[str, LLMProvider]
    stt: dict[str, STTProvider]
    embedding: EmbeddingProvider
    diarization: DiarizationProvider


class Unavailable:
    """Stands in for a provider that could not be built, so the rest of the app keeps running;
    every call says what is wrong. Live transcription sees `accepts` empty and goes manual."""

    accepts: frozenset[str] = frozenset()
    language = "ko-KR"
    dimensions = 0

    def __init__(self, role: Role, impl: str, reason: str) -> None:
        self.role = role
        self.model = f"{impl} (사용 불가)"
        self.reason = reason

    def _fail(self) -> ProviderUnavailable:
        return ProviderUnavailable(
            f"{self.role.label} 모델을 쓸 수 없습니다: {self.reason} 관리자 > 모델 설정에서 확인하세요."
        )

    async def warm_up(self) -> None:
        return None

    async def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()
        yield  # an async generator, like the real thing

    async def transcribe(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    async def embed(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    async def encode(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    @property
    def index_key(self) -> str:
        return self.model

    async def diarize(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    # 서류 읽기: an unusable reader refuses the files it would read; an unusable OCR engine
    # leaves pages unread (held), which the intake reports as such.
    def recognize(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    def extract(self, *args: Any, **kwargs: Any) -> Any:
        raise self._fail()

    def convert(self, *args: Any, **kwargs: Any) -> Any:
        from interview_assistant.documents.base import ConverterMissing

        raise ConverterMissing(str(self._fail()))


@dataclass(frozen=True)
class ProviderSet:
    revision: int
    specs: Mapping[str, ProviderSpec]
    by_role: Mapping[str, Any]
    providers: Providers
    ai: AiGateway
    errors: Mapping[str, str] = field(default_factory=dict)
    keys: frozenset[str] = frozenset()

    def get(self, role: str) -> Any:
        return self.by_role[role]

    @property
    def reader(self) -> DocumentReader:
        """Reads uploaded documents with this snapshot's 서류 읽기 settings. Take it once at the
        start of a piece of work: the work then finishes with these settings even if an admin
        changes them meanwhile, and its result records this revision."""
        return reader_for(self.by_role, self.revision)


def reader_for(by_role: Mapping[str, Any], revision: int | None) -> DocumentReader:
    from interview_assistant.documents.reading import ReadingPolicy

    policy = getattr(by_role.get("document.reading"), "policy", None) or ReadingPolicy()
    extractors: dict[str, Any] = {}
    if "document.pdf" in by_role:
        extractors["pdf"] = by_role["document.pdf"]
    if "document.hwp" in by_role:
        extractors["hwp"] = extractors["hwpx"] = by_role["document.hwp"]
    return DocumentReader(
        policy=policy,
        ocr=by_role.get("document.ocr"),
        extractors=extractors,
        converter=by_role.get("document.legacy"),
        revision=revision,
    )


@dataclass(frozen=True)
class Prepared:
    """A spec checked against the catalog for one role, with what this machine still lacks."""

    role: Role
    info: ImplInfo
    spec: ProviderSpec
    requirements: list[Requirement]

    @property
    def unmet(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.ok]

    @property
    def external(self) -> bool:
        return self.info.data_location.leaves_company


class ChangeRefused(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def describe(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if text.endswith((".", "다")) else f"{text}."


def _key(kind: str, spec: ProviderSpec) -> str:
    return f"{kind}:" + json.dumps(store.spec_json(spec), sort_keys=True, ensure_ascii=False)


class ModelManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        preset: Providers | None = None,
        downloads: DownloadManager | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.downloads = downloads or DownloadManager(settings.weights_dir)
        self.persistent = True  # false when the settings tables are missing (unmigrated DB)
        self._preset = preset
        self._instances: dict[str, Any] = {}
        self._tested: tuple[str, Any] | None = None  # the last provider built for a test
        self._sets: dict[int, ProviderSet] = {}
        self._active: ProviderSet | None = None
        self._lock = asyncio.Lock()
        # Called with the role key after a change is swapped in (retrieval rebuilds its index).
        self.listeners: list[Callable[[str], None]] = []

    @property
    def active(self) -> ProviderSet:
        if self._active is None:
            raise RuntimeError("ModelManager.start() has not run")
        return self._active

    @property
    def context(self) -> dict[str, Any]:
        return {"weights_dir": self.settings.weights_dir}

    # --- startup ----------------------------------------------------------------------------

    def start(self) -> None:
        defaults = load_providers(self.settings.providers_file).by_role()
        try:
            with self.session_factory() as db:
                revision, specs = store.load_or_seed(db, defaults)
                # Interviews running from before pinning existed keep the config they find now.
                db.execute(
                    update(InterviewSession)
                    .where(
                        InterviewSession.ai_config_revision.is_(None),
                        or_(
                            InterviewSession.status == SessionStatus.in_progress,
                            InterviewSession.ai_scoring_status == AiScoringStatus.running,
                        ),
                    )
                    .values(ai_config_revision=revision)
                )
                db.commit()
        except SQLAlchemyError:
            log.warning(
                "AI model settings tables are missing (run `alembic upgrade head`): "
                "using %s, changes cannot be saved",
                self.settings.providers_file,
            )
            self.persistent = False
            revision, specs = 0, dict(defaults)
        if self._preset is not None:
            for role in catalog.ROLES:
                given = self._preset_instance(role)
                if given is not None and role.key in specs:
                    self._instances[_key(role.kind, specs[role.key])] = given
        self._active = self._build_set(revision, specs)

    def _preset_instance(self, role: Role) -> Any:
        p = self._preset
        assert p is not None
        slot = role.key.split(".", 1)[-1]
        return {
            "llm": p.llm.get(slot),
            "stt": p.stt.get(slot),
            "embedding": p.embedding,
            "diarization": p.diarization,
        }.get(role.kind)  # document roles have no presets: built from their specs

    async def warm_up_active(self) -> None:
        """Load the active providers' weights in the background after startup."""
        for role, provider in self.active.by_role.items():
            try:
                await provider.warm_up()
            except Exception:
                log.exception("could not warm up %s", role)

    # --- sets -------------------------------------------------------------------------------

    def _instance(self, kind: str, spec: ProviderSpec) -> Any:
        key = _key(kind, spec)
        if key in self._instances:
            return self._instances[key]
        if self._tested is not None and self._tested[0] == key:
            return self._tested[1]
        return registry.resolve(kind, spec, self.context)

    def _build_set(self, revision: int, specs: Mapping[str, ProviderSpec]) -> ProviderSet:
        by_role: dict[str, Any] = {}
        errors: dict[str, str] = {}
        keys: set[str] = set()
        for role in catalog.ROLES:
            spec = specs.get(role.key)
            if spec is None:
                errors[role.key] = "설정이 없습니다."
                by_role[role.key] = Unavailable(role, "-", errors[role.key])
                continue
            key = _key(role.kind, spec)
            try:
                provider = self._instance(role.kind, spec)
            except Exception as exc:  # unknown impl, missing package, bad options ...
                errors[role.key] = self._why(role, spec, exc)
                by_role[role.key] = Unavailable(role, spec.impl, errors[role.key])
                continue
            self._instances[key] = provider
            keys.add(key)
            by_role[role.key] = provider
        providers = Providers(
            llm={"primary": by_role["llm.primary"], "screening": by_role["llm.screening"]},
            stt={"streaming": by_role["stt.streaming"], "batch": by_role["stt.batch"]},
            embedding=by_role["embedding"],
            diarization=by_role["diarization"],
        )
        return ProviderSet(
            revision,
            dict(specs),
            by_role,
            providers,
            AiGateway(providers.llm),
            errors,
            frozenset(keys),
        )

    def _why(self, role: Role, spec: ProviderSpec, exc: Exception) -> str:
        """Why a stored spec cannot be built, in the requirement terms the admin screen uses."""
        info = catalog.impl_info(role.kind, spec.impl)
        if info is not None:
            unmet = [
                r.label
                for r in catalog.requirements(
                    info, spec.options, weights_dir=self.settings.weights_dir
                )
                if not r.ok
            ]
            if unmet:
                return f"요구 조건 미충족 ({', '.join(unmet)})."
        return describe(exc)

    def for_revision(self, revision: int | None) -> ProviderSet:
        """The set a session pinned at `revision` uses; the active set for unpinned sessions."""
        active = self.active
        if revision is None or revision == active.revision or not self.persistent:
            return active
        if revision in self._sets:
            return self._sets[revision]
        with self.session_factory() as db:
            specs = store.specs_at(db, revision)
        if not specs:
            return active
        found = self._build_set(revision, specs)
        self._sets[revision] = found
        return found

    def for_session(self, session: InterviewSession) -> ProviderSet:
        return self.for_revision(session.ai_config_revision)

    def live_revisions(self) -> dict[int, int]:
        """Revisions still in use: sessions in progress or being scored -> how many."""
        try:
            with self.session_factory() as db:
                rows = db.scalars(
                    select(InterviewSession.ai_config_revision).where(
                        InterviewSession.ai_config_revision.is_not(None),
                        or_(
                            InterviewSession.status == SessionStatus.in_progress,
                            InterviewSession.ai_scoring_status == AiScoringStatus.running,
                        ),
                    )
                ).all()
        except SQLAlchemyError:
            return {}
        counts: dict[int, int] = {}
        for rev in rows:
            counts[rev] = counts.get(rev, 0) + 1
        return counts

    def evict(self) -> None:
        """Forget sets no live session uses and the provider instances only they held."""
        keep = {self.active.revision, *self.live_revisions()}
        for rev in [r for r in self._sets if r not in keep]:
            del self._sets[rev]
        used = set(self.active.keys).union(*(s.keys for s in self._sets.values()))
        for key in [k for k in self._instances if k not in used]:
            del self._instances[key]

    # --- checks, tests, changes -------------------------------------------------------------

    def prepare(
        self, role_key: str, impl: str, options: Mapping[str, Any], *, stored: bool = False
    ) -> Prepared:
        """Check a spec for a role. New specs from the screen are validated strictly; `stored`
        specs (rollback targets, YAML seeds) are taken as they were saved."""
        role = catalog.ROLE_BY_KEY.get(role_key)
        if role is None:
            raise catalog.SpecError("role", "알 수 없는 역할입니다.")
        info = catalog.impl_info(role.kind, impl)
        if info is None:
            if not registry.is_registered(role.kind, impl):
                raise catalog.SpecError("impl", "등록되지 않은 provider입니다.")
            info = catalog.bare(role.kind, impl)
        if role.key not in info.roles:
            raise catalog.SpecError(
                "impl", f"{info.label}은(는) {role.label} 역할에 쓸 수 없습니다."
            )
        values = dict(options) if stored else catalog.validate_options(info, role.key, options)
        spec = ProviderSpec(impl=impl, **values)
        reqs = catalog.requirements(info, values, weights_dir=self.settings.weights_dir)
        return Prepared(role, info, spec, reqs)

    async def provider_for(self, prepared: Prepared) -> Any:
        """Build and warm up the provider of a checked spec (for a test or a change). The result
        is kept as the last tested provider, so applying it right after reuses loaded weights."""
        if prepared.unmet:
            raise ChangeRefused(
                "요구 조건을 충족하지 않습니다: " + ", ".join(r.label for r in prepared.unmet)
            )
        key = _key(prepared.role.kind, prepared.spec)
        try:
            provider = self._instance(prepared.role.kind, prepared.spec)
            await provider.warm_up()
        except Exception as exc:
            raise ChangeRefused(f"모델을 불러오지 못했습니다: {describe(exc)}", 502) from exc
        if key not in self._instances:
            self._tested = (key, provider)
        return provider

    async def change(
        self,
        prepared: Prepared,
        *,
        kind: ModelChangeKind,
        actor_id: str | None,
        reason: str,
        confirm_external: bool,
        reverts_change_id: str | None = None,
        also: Callable[[Session, AiModelChange], None] | None = None,
    ) -> tuple[ProviderSet, AiModelChange]:
        """Swap in `prepared` for its role. `also` adds rows (the audit log) to the transaction
        that records the change."""
        async with self._lock:
            old = self.active
            if store.same(old.specs.get(prepared.role.key), prepared.spec):
                raise ChangeRefused("지금 쓰는 설정과 같습니다.")
            if prepared.external and not confirm_external:
                raise ChangeRefused(
                    "회사 밖으로 데이터를 보내는 provider입니다. 경고를 확인하고 사유를 적어야 적용됩니다."
                )
            if not reason.strip():
                raise catalog.SpecError("reason", "변경 사유를 적어 주세요.")
            if not self.persistent:
                raise ChangeRefused(
                    "모델 설정 테이블이 없어 저장할 수 없습니다 (alembic upgrade head).", 503
                )
            provider = await self.provider_for(prepared)
            with self.session_factory() as db:
                change = store.record(
                    db,
                    prepared.role.key,
                    kind,
                    old.specs.get(prepared.role.key),
                    prepared.spec,
                    actor_id=actor_id,
                    reason=reason.strip(),
                    reverts_change_id=reverts_change_id,
                    details={
                        "model": str(getattr(provider, "model", "") or prepared.spec.impl),
                        "data_location": prepared.info.data_location.value,
                        "confirmed_external": prepared.external and confirm_external,
                    },
                    also=also,
                )
            new = self._build_set(change.revision, {**old.specs, prepared.role.key: prepared.spec})
            self._sets[old.revision] = old
            self._active = new
            if self._tested is not None and self._tested[0] in self._instances:
                self._tested = None
            self.evict()
        for listener in self.listeners:
            try:
                listener(prepared.role.key)
            except Exception:
                log.exception("model change listener failed")
        return new, change
