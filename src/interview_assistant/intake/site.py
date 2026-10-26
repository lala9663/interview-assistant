"""The recruiting site's event, as docs/site-intake-spec.md fixes it, and the checks at the door.

What the site may send is fixed here. Three kinds of content are told apart before anything is
stored:

- items we decided never to receive (photo, 주민등록번호, family, body, birthplace, marital status,
  assets, religion, politics, health, gender): the whole event is refused (`forbidden_field`) and
  only the field paths are recorded
- fields outside the spec: dropped, their paths recorded (`dropped_fields`), the rest applied
- required fields missing or malformed: refused (`missing_field` / `invalid_field`), paths only

Messages and recorded paths never carry a value.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from interview_assistant.deid.types import KnownIdentity
from interview_assistant.intake.forms import FormFields
from interview_assistant.intake.service import ApplicationInput, Attachment
from interview_assistant.models import ApplicationChannel

EVENT_TYPES = {
    "application.submitted": "submitted",
    "application.updated": "updated",
    "application.withdrawn": "withdrawn",
}
ATTACHMENT_KINDS = ("resume", "portfolio", "certificate", "other")
MAX_ATTACHMENTS = 5

Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SiteModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Applicant(SiteModel):
    applicant_no: Key  # 지원자 번호: hashed on arrival, never stored or shown
    name: Text100
    other_names: list[Text100] = Field(default_factory=list, max_length=3)  # 영문·한자 표기
    phones: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)]] = Field(
        default_factory=list, max_length=3
    )
    emails: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]] = Field(
        default_factory=list, max_length=3
    )
    birthdate: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class Consent(SiteModel):
    terms_version: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    agreed_at: AwareDatetime


class AttachmentMeta(SiteModel):
    part: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]  # multipart field name
    kind: Literal["resume", "portfolio", "certificate", "other"] = "resume"
    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SiteEvent(SiteModel):
    event_id: Key
    event_type: Literal["application.submitted", "application.updated", "application.withdrawn"]
    occurred_at: AwareDatetime
    revision: int = Field(ge=1, le=1_000_000)
    posting_no: Key
    application_no: Key
    applicant: Applicant | None = Field(default=None, validate_default=True)
    consent: Consent | None = Field(default=None, validate_default=True)
    form: FormFields | None = None
    attachments: list[AttachmentMeta] = Field(default_factory=list, max_length=MAX_ATTACHMENTS)

    @field_validator("applicant", "consent")
    @classmethod
    def _required_unless_withdrawn(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None and info.data.get("event_type") != "application.withdrawn":
            raise PydanticCustomError("missing", "제출·수정 이벤트에는 필수입니다.")
        return value

    @model_validator(mode="after")
    def _distinct_parts(self) -> SiteEvent:
        parts = [a.part for a in self.attachments]
        if len(set(parts)) != len(parts):
            raise ValueError("attachments의 part 이름이 겹칩니다.")
        return self

    @property
    def kind(self) -> str:
        return EVENT_TYPES[self.event_type]

    def envelope(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            include={"event_id", "event_type", "occurred_at", "revision", "posting_no", "application_no"},
        )


# --- items never received -------------------------------------------------------------------

# Canonical item -> (label, legal or policy basis, key spellings after normalisation).
FORBIDDEN: dict[str, tuple[str, str, frozenset[str]]] = {
    "photo": (
        "사진",
        "평가에 쓰지 않음 (블라인드 채용)",
        frozenset("photo photos photourl photograph picture profilephoto profileimage idphoto portrait 사진 증명사진".split()),
    ),
    "resident_registration_number": (
        "주민등록번호",
        "개인정보 보호법 제24조의2",
        frozenset("rrn residentno residentnumber residentregistrationnumber residentid jumin juminno juminbunho ssn nationalid 주민등록번호 주민번호".split()),
    ),
    "family": (
        "가족 관계·가족의 학력·직업·재산",
        "채용절차법 제4조의3",
        frozenset("family familymembers familyrelation familyrelations parents father mother spouse siblings 가족 가족관계 가족사항".split()),
    ),
    "physical": (
        "키·체중·용모 등 신체 조건",
        "채용절차법 제4조의3",
        frozenset("height weight bodysize appearance bloodtype 키 체중 신장 신체 혈액형".split()),
    ),
    "birthplace": (
        "출신 지역·본적",
        "채용절차법 제4조의3",
        frozenset("birthplace hometown placeoforigin origin domicile registereddomicile 본적 출신지 출신지역 출생지".split()),
    ),
    "marital_status": (
        "혼인 여부",
        "채용절차법 제4조의3",
        frozenset("maritalstatus married marriage 혼인 혼인여부 결혼여부".split()),
    ),
    "assets": ("재산", "채용절차법 제4조의3", frozenset("assets property wealth income 재산".split())),
    "religion": ("종교", "개인정보 보호법 제23조 (민감정보)", frozenset("religion 종교".split())),
    "political": (
        "정치 성향·정당",
        "개인정보 보호법 제23조 (민감정보)",
        frozenset("political politicalparty politicalview 정당 정치성향".split()),
    ),
    "health": (
        "건강·장애",
        "개인정보 보호법 제23조 (민감정보)",
        frozenset("health medical disability disabilitystatus 건강 장애 병력".split()),
    ),
    "gender": ("성별", "평가에 쓰지 않음 (편향 방지)", frozenset("gender sex 성별".split())),
}
_KEY_TO_ITEM = {spelling: item for item, (_, _, spellings) in FORBIDDEN.items() for spelling in spellings}
_PHOTO_KINDS = frozenset({"photo", "idphoto", "picture", "사진", "증명사진"})


def _norm(key: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", key)).lower()


def forbidden_items(raw: Any, path: str = "") -> list[tuple[str, str]]:
    """(path, item) for every key the spec refuses, at any depth; an attachment whose kind is a
    photo counts as a photo. Values are never looked at except that kind."""
    found: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            here = f"{path}.{key}" if path else str(key)
            item = _KEY_TO_ITEM.get(_norm(str(key)))
            if item is not None:
                found.append((here, item))
                continue
            if key == "kind" and path.startswith("attachments[") and isinstance(value, str):
                if _norm(value) in _PHOTO_KINDS:
                    found.append((here, "photo"))
                    continue
            found += forbidden_items(value, here)
    elif isinstance(raw, list):
        for i, value in enumerate(raw):
            found += forbidden_items(value, f"{path}[{i}]")
    return found


def forbidden_message(found: list[tuple[str, str]]) -> str:
    items = list(dict.fromkeys(item for _, item in found))
    labels = ", ".join(FORBIDDEN[item][0] for item in items)
    return f"받지 않는 항목이 들어 있어 지원서를 받지 않았습니다: {labels}. 이 항목을 빼고 새 event_id로 다시 보내 주세요."


# --- fields outside the spec ----------------------------------------------------------------


def drop_unknown(model: BaseModel, path: str = "") -> list[str]:
    """Remove every key the spec does not define, in place, and return their paths."""
    dropped = []
    extra = model.__pydantic_extra__ or {}
    for key in list(extra):
        dropped.append(f"{path}.{key}" if path else key)
    if extra:
        model.__pydantic_extra__ = {}
    for name in type(model).model_fields:
        value = getattr(model, name)
        here = f"{path}.{name}" if path else name
        if isinstance(value, BaseModel):
            dropped += drop_unknown(value, here)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, BaseModel):
                    dropped += drop_unknown(item, f"{here}[{i}]")
    return dropped


# --- validation errors ----------------------------------------------------------------------


def _loc(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def validation_failure(exc: ValidationError) -> tuple[str, str, list[str]]:
    """(code, message, field paths) for a SiteEvent that does not validate. No values."""
    missing, invalid = [], []
    for error in exc.errors():
        loc = _loc(tuple(error.get("loc", ())))
        if error.get("type") == "missing":
            missing.append(loc)
        else:
            invalid.append(loc or "event")
    if missing:
        return "missing_field", f"필수 항목이 없습니다: {', '.join(missing)}", missing + invalid
    return "invalid_field", f"형식이 맞지 않는 항목이 있습니다: {', '.join(invalid)}", invalid


# --- fingerprint and conversion -------------------------------------------------------------


def fingerprint(raw: Any, parts: dict[str, bytes]) -> str:
    """Same content, same fingerprint, whatever the key order or multipart boundary."""
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8"))
    for name in sorted(parts):
        digest.update(f"\n{name}:{hashlib.sha256(parts[name]).hexdigest()}".encode())
    return digest.hexdigest()


def known_identity(event: SiteEvent) -> KnownIdentity:
    """What the form says about the person, for de-identification only. Schools and companies
    come from the 학력·경력 칸, so they are masked wherever else they appear."""
    applicant = event.applicant
    assert applicant is not None
    form = event.form or FormFields()
    return KnownIdentity(
        name=applicant.name,
        aliases=tuple(applicant.other_names),
        phones=tuple(applicant.phones),
        emails=tuple(applicant.emails),
        birthdate=applicant.birthdate,
        addresses=(applicant.address,) if applicant.address else (),
        schools=tuple(dict.fromkeys(e.school for e in form.education)),
        companies=tuple(dict.fromkeys(c.company for c in form.career)),
    )


def application_input(event: SiteEvent, files: dict[str, bytes]) -> ApplicationInput:
    assert event.applicant is not None
    return ApplicationInput(
        channel=ApplicationChannel.site,
        identity=known_identity(event),
        posting_no=event.posting_no,
        applicant_no=event.applicant.applicant_no,
        application_no=event.application_no,
        fields=event.form,
        attachments=tuple(
            Attachment(filename=a.filename, data=files[a.part], kind=a.kind) for a in event.attachments
        ),
        revision=event.revision,
    )
