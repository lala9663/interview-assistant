"""Error bodies in the FastAPI shape the frontend reads (`{"detail": ...}`), in Korean.

404 missing resource, 409 state conflict, 422 validation (`[{loc, msg, type}]`), 502 the AI
answered unusably or was refused by the guard, 503 de-identification is not configured.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.guard import IdentifierInPrompt
from interview_assistant.deid.service import DeidUnavailable


def _object_particle(word: str) -> str:
    last = word[-1] if word else ""
    if "가" <= last <= "힣":
        return "을" if (ord(last) - ord("가")) % 28 else "를"
    return "을(를)"


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what}{_object_particle(what)} 찾을 수 없습니다.")


def conflict(message: str) -> HTTPException:
    return HTTPException(409, message)


def ai_failed(message: str) -> HTTPException:
    return HTTPException(502, message)


def invalid(field: str, message: str) -> HTTPException:
    return HTTPException(422, [{"loc": ["body", field], "msg": message, "type": "value_error"}])


_MESSAGES = {
    "missing": "필수 항목입니다.",
    "string_type": "문자열이어야 합니다.",
    "int_type": "정수여야 합니다.",
    "int_parsing": "정수여야 합니다.",
    "int_from_float": "정수여야 합니다.",
    "bool_type": "참/거짓 값이어야 합니다.",
    "bool_parsing": "참/거짓 값이어야 합니다.",
    "list_type": "목록이어야 합니다.",
    "dict_type": "객체여야 합니다.",
    "model_type": "객체여야 합니다.",
    "enum": "허용되지 않는 값입니다.",
    "literal_error": "허용되지 않는 값입니다.",
    "datetime_type": "ISO 8601 시각이어야 합니다.",
    "datetime_parsing": "ISO 8601 시각이어야 합니다.",
    "datetime_from_date_parsing": "ISO 8601 시각이어야 합니다.",
    "timezone_aware": "시간대(UTC 오프셋)가 있는 시각이어야 합니다.",
    "string_too_long": "너무 깁니다.",
    "greater_than_equal": "값이 너무 작습니다.",
    "less_than_equal": "값이 너무 큽니다.",
    "json_invalid": "JSON 형식이 아닙니다.",
}


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = []
        for error in exc.errors():
            kind = str(error.get("type", "value_error"))
            message = _MESSAGES.get(kind, str(error.get("msg", "")))
            expected = (error.get("ctx") or {}).get("expected")
            if kind in ("enum", "literal_error") and expected:
                message = f"{message} ({expected})"
            detail.append({"loc": list(error.get("loc", ())), "msg": message, "type": kind})
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(DeidUnavailable)
    async def _no_deid(_: Request, exc: DeidUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(AiOutputInvalid)
    async def _bad_ai(_: Request, exc: AiOutputInvalid) -> JSONResponse:
        return JSONResponse({"detail": f"AI 응답을 쓸 수 없습니다: {exc}"}, status_code=502)

    @app.exception_handler(IdentifierInPrompt)
    async def _guarded(_: Request, exc: IdentifierInPrompt) -> JSONResponse:
        return JSONResponse(
            {"detail": "식별 정보가 남아 있어 AI 호출을 막았습니다. 관리자에게 알려 주세요."},
            status_code=502,
        )
