"""Microphone audio for the live interview (docs/audio-input.md, docs/api-contract.md 3.3).

The browser sends 16 kHz mono 16-bit PCM: over a WebSocket (`/sessions/{id}/audio`), or, where a
proxy or DLP blocks WebSockets, as HTTP chunks (`POST /sessions/{id}/audio/chunks`). Both run as
the signed-in interviewer (the same dependency as every other route; agent tokens may not open
them) and feed the same `MicrophoneSource`, which the live hub then transcribes.

Refusals carry a short code (live/codes.py) the screen shows: no consent (`NO-CONSENT`, the
microphone stays off and answers are typed), not in progress, another connection already sending,
wrong format. Missing models do not refuse the connection: with consent the audio is still
recorded, and the code (`VAD-MISSING`, `STT-MISSING` ...) comes with the transcript status.

Audio goes to memory and the raw zone only: the session's WAV when the candidate consented
(live/recording.py). The diagnostic sample (`source=sample`) is transcribed like a microphone but
never recorded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from interview_assistant.ai_models.manager import Unavailable
from interview_assistant.api import schemas as s
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import conflict, not_found
from interview_assistant.api.routes.sessions import get_session, record_question
from interview_assistant.live import codes
from interview_assistant.live.microphone import CANDIDATE, MicrophoneSource
from interview_assistant.live.recording import WavRecorder
from interview_assistant.models import Interviewer, InterviewSession, QuestionSource, SessionStatus
from interview_assistant.models.base import new_id
from interview_assistant.providers.audio import SAMPLES_DIR, uri_to_path
from interview_assistant.providers.base import (
    PCM16_16K,
    SAMPLE_RATE,
    DenoiseProvider,
    TurnProvider,
    VADProvider,
)
from interview_assistant.providers.turn.silence import SilenceTurn
from interview_assistant.runtime import Runtime

log = logging.getLogger(__name__)
router = APIRouter(tags=["audio"])

FALLBACK_SILENCE_MS = 2000  # end of answer while the configured detector cannot run
STALE_S = 10  # a connection that sent nothing for this long may be taken over
SOURCES = ("microphone", "sample")
MAX_CHUNK = SAMPLE_RATE * 2 * 5  # one HTTP chunk: at most 5 s of audio

# Bundled sample audio the browser can play into the pipeline instead of a microphone (preview,
# automated tests, diagnosing a blocked microphone). Public data only: see samples/NOTICE.md.
SAMPLES = {
    "answer-pauses": (
        "가상 답변 (생각하는 멈춤 포함)",
        "FLEURS 한국어 낭독 두 문장. 첫 문장 안에 1.5초, 두 문장 사이에 1.9초 멈춥니다.",
        "보고서는 행정부의 현재 이라크 정책에 대해 거의 모든 측면에서 매우 비판적이며 즉각적인 방향 변경을 "
        "촉구합니다. 파리 사람들은 자기중심적이고, 무례하고, 오만하다는 평판이 있습니다.",
    ),
    "ko-fleurs-1894": (
        "한국어 낭독 한 문장",
        "FLEURS 한국어 낭독 11.5초. STT 연결 테스트와 같은 샘플입니다.",
        "커리는 약용 식물과 향신료를 기본으로 하여 고기나 채소를 곁들이는 요리입니다.",
    ),
}


class AudioRefused(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _refusal(exc: AudioRefused) -> HTTPException:
    return HTTPException(exc.status, {**codes.describe(exc.code)})


def _recorder(db: Session, found: InterviewSession) -> WavRecorder:
    """The session's WAV in the raw zone (older sessions were given a .webm name before audio
    existed: it becomes .wav)."""
    assert found.recording_uri is not None
    path = uri_to_path(found.recording_uri)
    if path.suffix != ".wav":
        path = path.with_suffix(".wav")
        found.recording_uri = path.resolve().as_uri()
        db.commit()
    return WavRecorder(path)


async def _ready(provider: Any, kind: type) -> Any | None:
    """The role's provider loaded, or None when it cannot run here."""
    if isinstance(provider, Unavailable) or not isinstance(provider, kind):
        return None
    try:
        await provider.warm_up()
    except Exception:
        log.exception("audio provider %s could not load", type(provider).__name__)
        return None
    return provider


async def open_microphone(
    runtime: Runtime, db: Session, me: Any, session_id: str, *, transport: str, stream_id: str, source: str
) -> MicrophoneSource:
    found = db.get(InterviewSession, session_id)
    if found is None or found.status is not SessionStatus.in_progress:
        raise AudioRefused(codes.NOT_LIVE, 409)
    if found.recording_uri is None:
        raise AudioRefused(codes.NO_CONSENT, 403)
    hub = runtime.hub
    mic = hub.microphone(session_id)
    if mic is not None and mic.connected and mic.stream_id != stream_id:
        if time.monotonic() - mic.last_seen < STALE_S:
            raise AudioRefused(codes.MIC_TAKEN, 409)
        mic.detach()
    if mic is None or mic.closed:
        pinned = runtime.pinned(found)
        notices: list[str] = []
        vad = await _ready(pinned.get("audio.vad"), VADProvider)
        if vad is None:
            notices.append(codes.VAD_MISSING)
        turn = await _ready(pinned.get("audio.turn"), TurnProvider)
        if turn is None:
            turn = SilenceTurn(silence_ms=FALLBACK_SILENCE_MS)
            notices.append(codes.TURN_MISSING)
        denoise = await _ready(pinned.get("audio.denoise"), DenoiseProvider)
        stt = pinned.get("stt.streaming")
        if not getattr(stt, "accepts", ()):
            notices.append(codes.STT_MISSING)
        elif PCM16_16K not in stt.accepts:
            notices.append(codes.STT_FORMAT)
        mic = MicrophoneSource(vad=vad, turn=turn, denoise=denoise, notices=tuple(notices))
        await hub.attach_microphone(session_id, mic)
    mic.recorder = _recorder(db, found) if source == "microphone" else None
    mic.attach(transport, stream_id)
    hub.microphone_attached(session_id)
    audit(
        db,
        me,
        "audio.connected",
        "interview_session",
        session_id,
        transport=transport,
        source=source,
        recorded=mic.recorder is not None,
        notices=mic.notices,
    )
    db.commit()
    return mic


async def _feed(mic: MicrophoneSource, data: bytes) -> None:
    try:
        await mic.feed(data)
    except OSError:
        log.exception("could not write the recording")
        mic.recorder = None
        if codes.REC_FAILED not in mic.notices:
            mic.notices.append(codes.REC_FAILED)
            mic.on_change()
        await mic.feed(data)


def _closed(db: Session, me_id: str, session_id: str, mic: MicrophoneSource, transport: str, started: float) -> None:
    audit(
        db,
        db.get(Interviewer, me_id),
        "audio.disconnected",
        "interview_session",
        session_id,
        transport=transport,
        seconds=round(time.monotonic() - started, 1),
        received_s=round(mic.received_ms / 1000, 1),
    )
    db.commit()


@router.websocket("/sessions/{session_id}/audio")
async def audio_socket(websocket: WebSocket, session_id: str, db: Db, me: Me, runtime: RuntimeDep) -> None:
    """Text frames: `{"type": "start", "format": "pcm16", "sample_rate": 16000, "source":
    "microphone" | "sample", "constraints": {...}}` first, then binary PCM frames. The server
    answers `ready` (with notices), `state` when speech starts or stops, and `error` before
    closing (close code 4000 + HTTP status, reason = the code)."""
    await websocket.accept()

    async def refuse(code: str, status: int) -> None:
        await websocket.send_json({"type": "error", **codes.describe(code)})
        await websocket.close(code=4000 + status, reason=code)

    try:
        start = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
    except (TimeoutError, ValueError, WebSocketDisconnect, KeyError):
        await refuse(codes.AUDIO_FORMAT, 400)
        return
    source = start.get("source", "microphone")
    if (
        start.get("type") != "start"
        or start.get("format") != "pcm16"
        or start.get("sample_rate") != SAMPLE_RATE
        or source not in SOURCES
    ):
        await refuse(codes.AUDIO_FORMAT, 400)
        return
    stream_id = new_id()
    try:
        mic = await open_microphone(
            runtime, db, me, session_id, transport="websocket", stream_id=stream_id, source=source
        )
    except AudioRefused as exc:
        await refuse(exc.code, exc.status)
        return
    me_id = me.id
    audit(db, me, "audio.constraints", "interview_session", session_id, **_constraints(start))
    db.commit()
    db.close()  # no database session held while the socket is open
    started = time.monotonic()
    await websocket.send_json({"type": "ready", "stream_id": stream_id, "role": mic.role, "notices": mic.notices})
    speaking = mic.speaking
    try:
        while not mic.closed and mic.stream_id == stream_id:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data:
                await _feed(mic, data)
            elif message.get("text") and json.loads(message["text"]).get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            if mic.speaking != speaking:
                speaking = mic.speaking
                await websocket.send_json({"type": "state", "speaking": speaking, "role": mic.role})
        if mic.closed:
            await refuse(codes.NOT_LIVE, 409)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if mic.stream_id == stream_id:
            mic.detach()
        with runtime.session_factory() as fresh:
            _closed(fresh, me_id, session_id, mic, "websocket", started)


def _constraints(start: dict[str, Any]) -> dict[str, Any]:
    """What the browser asked for and got (AEC, NS, AGC, sample rate), for diagnosis."""
    raw = start.get("constraints") or {}
    keys = ("echoCancellation", "noiseSuppression", "autoGainControl", "sampleRate", "channelCount")
    return {k: raw.get(k) for k in keys if isinstance(raw.get(k), (bool, int, float))}


@router.post("/sessions/{session_id}/audio/chunks", response_model=s.AudioChunkResult)
async def audio_chunk(
    session_id: str,
    request: Request,
    db: Db,
    me: Me,
    runtime: RuntimeDep,
    stream: str = Query(min_length=8, max_length=64),
    seq: int = Query(ge=0),
    source: str = Query("microphone"),
) -> s.AudioChunkResult:
    """The fallback for a blocked WebSocket: PCM (`application/octet-stream`, at most 5 s) in
    order (`seq` from 0 per `stream`). A chunk that comes again is ignored."""
    if request.headers.get("x-audio-format", "pcm16;rate=16000") != "pcm16;rate=16000" or source not in SOURCES:
        raise _refusal(AudioRefused(codes.AUDIO_FORMAT, 415))
    data = await request.body()
    if len(data) > MAX_CHUNK:
        raise _refusal(AudioRefused(codes.AUDIO_FORMAT, 413))
    mic = runtime.hub.microphone(session_id)
    if mic is None or not mic.connected or mic.stream_id != stream:
        try:
            mic = await open_microphone(runtime, db, me, session_id, transport="http", stream_id=stream, source=source)
        except AudioRefused as exc:
            raise _refusal(exc) from exc
    if seq > mic.last_seq:
        mic.last_seq = seq
        await _feed(mic, data)
    return s.AudioChunkResult(speaking=mic.speaking, role=mic.role, notices=mic.notices)


@router.delete("/sessions/{session_id}/audio/chunks", status_code=204)
def audio_stop(session_id: str, db: Db, me: Me, runtime: RuntimeDep, stream: str = Query(max_length=64)) -> None:
    mic = runtime.hub.microphone(session_id)
    if mic is not None and mic.stream_id == stream:
        mic.detach()
        _closed(db, me.id, session_id, mic, "http", time.monotonic())


@router.post("/sessions/{session_id}/live/role", response_model=s.MicRoleResult)
async def switch_role(
    session_id: str, body: s.MicRoleRequest, db: Db, me: Me, runtime: RuntimeDep
) -> s.MicRoleResult:
    """질문 중 / 답변 듣는 중 for one microphone in a face-to-face interview. Back to the
    candidate, a question the interviewer asked aloud meanwhile becomes the next question."""
    found = get_session(db, session_id)
    if found.status is not SessionStatus.in_progress:
        raise conflict("진행 중인 면접에서만 바꿀 수 있습니다.")
    if runtime.hub.microphone(session_id) is None:
        raise conflict("마이크가 연결되어 있지 않습니다.")
    spoken = await runtime.hub.set_role(session_id, body.role)
    db.expire_all()
    qa = None
    if body.role == CANDIDATE:
        question = " ".join(text.strip() for _, text in spoken).strip()
        if question:
            qa = record_question(db, runtime, found, question, QuestionSource.interviewer)
            audit(db, me, "qa.created", "interview_session", found.id, question_source="interviewer", spoken=True)
    audit(db, me, "audio.role", "interview_session", found.id, role=body.role)
    db.commit()
    if qa is not None:
        result = s.QAItem.model_validate(qa)
        runtime.hub.publish(session_id, "qa.created", result.model_dump(mode="json"))
        runtime.hub.listen(session_id, qa.id, announce=False)
    elif body.role == CANDIDATE:
        runtime.hub.resume(session_id)
    return s.MicRoleResult(role=body.role, qa_item=s.QAItem.model_validate(qa) if qa else None)


@router.get("/live/audio-samples", response_model=list[s.AudioSample])
def audio_samples(me: Me) -> list[s.AudioSample]:
    found = []
    for name, (label, note, text) in SAMPLES.items():
        path = SAMPLES_DIR / f"{name}.wav"
        if path.is_file():
            seconds = (path.stat().st_size - 44) / 2 / SAMPLE_RATE
            found.append(s.AudioSample(name=name, label=label, seconds=round(seconds, 1), text=text, note=note))
    return found


@router.get("/live/audio-samples/{name}")
def audio_sample(name: str, me: Me) -> FileResponse:
    if name not in SAMPLES:
        raise not_found("샘플 음성")
    path: Path = SAMPLES_DIR / f"{name}.wav"
    if not path.is_file():
        raise not_found("샘플 음성")
    return FileResponse(path, media_type="audio/wav")
