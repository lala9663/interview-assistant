"""Microphone input: VAD gating, end-of-answer detection, the WebSocket / HTTP chunk routes,
consent, where the recording goes, the interviewer asking aloud, answer prefetch."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import wave

import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from interview_assistant.live import codes
from interview_assistant.live.audio import Turn
from interview_assistant.live.microphone import FRAME, PREROLL_MS, MicrophoneSource, SpeechState
from interview_assistant.live.prefetch import AnswerPrefetch
from interview_assistant.live.recording import WavRecorder
from interview_assistant.providers.audio import SAMPLE, decode_pcm16, uri_to_path
from interview_assistant.providers.base import ProviderUnavailable, VADProvider, VoiceStream
from interview_assistant.providers.turn.silence import SilenceTurn
from interview_assistant.providers.turn.smart_turn import SmartTurn, SmartTurnTracker
from interview_assistant.providers.vad.silero import SileroVAD
from tests.api_util import SCHEDULED, wait_for

RATE = 16000
TURN = Turn("s", "p", "q")


def tone(seconds: float, amplitude: float = 0.3) -> bytes:
    t = np.arange(int(seconds * RATE)) / RATE
    return (np.sin(2 * np.pi * 220 * t) * amplitude * 32767).astype("<i2").tobytes()


def silence(seconds: float) -> bytes:
    return bytes(int(seconds * RATE) * 2)


def room(seconds: float) -> bytes:
    """Quiet room noise, below what counts as speech."""
    noise = np.random.default_rng(0).normal(0, 0.01, int(seconds * RATE))
    return (noise * 32767).astype("<i2").tobytes()


def chunks(pcm: bytes, ms: int = 100):
    size = RATE * 2 * ms // 1000
    return [pcm[i : i + size] for i in range(0, len(pcm), size)]


class LoudnessStream(VoiceStream):
    def probabilities(self, frames):
        rms = np.sqrt((np.asarray(frames) ** 2).mean(axis=1))
        return (rms > 0.05).astype(np.float32)


class LoudnessVAD(VADProvider):
    """Stands in for Silero on synthetic PCM: a tone is speech, digital silence is not."""

    model = "loudness"

    def stream(self):
        return LoudnessStream()


async def drain(source, turn=TURN) -> bytes:
    return b"".join([chunk async for chunk in source.open(turn)])


# --- the microphone source -----------------------------------------------------------------


def test_speech_state_keeps_speech_until_well_below_the_threshold():
    state = SpeechState(0.5)
    assert [state.update(p) for p in (0.4, 0.6, 0.4, 0.36, 0.34, 0.6)] == [False, True, True, True, False, True]


async def test_only_speech_reaches_stt_and_the_timing_stays():
    mic = MicrophoneSource(vad=LoudnessVAD(), turn=SilenceTurn(silence_ms=600))
    pcm = room(1.0) + tone(1.0) + room(1.5)
    reader = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    for chunk in chunks(pcm):
        await mic.feed(chunk)
    out = await asyncio.wait_for(reader, 2)
    assert mic.last_end["reason"] == "silence"
    samples = np.frombuffer(out, dtype="<i2")
    # Same timeline, delayed by the pre-roll: audible from (1.0 s - pre-roll) to 1 s of tone plus the pad.
    first = np.flatnonzero(samples)[0] / RATE
    last = np.flatnonzero(samples)[-1] / RATE
    assert first == pytest.approx(1.0 - PREROLL_MS / 1000, abs=0.04)
    assert last == pytest.approx(2.0 + 0.3, abs=0.05)
    assert not samples[: int(0.8 * RATE)].any()  # room sound before the answer: silence
    # The part ended 0.6 s into the silence (a frame is 32 ms).
    assert mic.last_end["at_ms"] == pytest.approx(2600, abs=40)


async def test_the_answer_goes_on_after_an_early_end():
    mic = MicrophoneSource(vad=LoudnessVAD(), turn=SilenceTurn(silence_ms=500))
    first = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    for chunk in chunks(tone(0.8) + silence(0.7)):
        await mic.feed(chunk)
    assert len(await asyncio.wait_for(first, 1)) > 0
    more = asyncio.create_task(mic.more(TURN))
    await mic.feed(silence(0.3))
    assert not more.done()
    await mic.feed(tone(0.1))
    assert await asyncio.wait_for(more, 1) is True
    second = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    for chunk in chunks(tone(0.5) + silence(0.7)):
        await mic.feed(chunk)
    audio = np.frombuffer(await asyncio.wait_for(second, 1), dtype="<i2")
    assert np.count_nonzero(audio) / RATE >= 0.55  # the onset kept from before the part opened


async def test_speech_while_the_last_part_is_still_closing_is_kept_for_the_next():
    """The hub reopens only after STT finished the previous part (seconds on a CPU): what the
    candidate says meanwhile must reach the next part whole."""
    mic = MicrophoneSource(vad=LoudnessVAD(), turn=SilenceTurn(silence_ms=500))
    first = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    for chunk in chunks(tone(0.5) + room(0.7)):
        await mic.feed(chunk)
    await asyncio.wait_for(first, 1)
    for chunk in chunks(room(2.0) + tone(2.5) + room(0.3)):  # nobody has opened the next part yet
        await mic.feed(chunk)
    second = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    for chunk in chunks(room(0.7)):
        await mic.feed(chunk)
    audio = np.frombuffer(await asyncio.wait_for(second, 1), dtype="<i2") / 32767
    frames = audio[: len(audio) // FRAME * FRAME].reshape(-1, FRAME)
    loud = np.sqrt((frames**2).mean(axis=1)) > 0.1
    assert loud.sum() * FRAME / RATE == pytest.approx(2.5, abs=0.07)  # the whole 2.5 s
    assert len(audio) / RATE < 2.5 + 0.3 + 0.7 + 0.5  # not the 2 s of room sound before it


async def test_talk_before_a_new_question_is_not_its_answer():
    mic = MicrophoneSource(vad=LoudnessVAD(), turn=SilenceTurn(silence_ms=500))
    for chunk in chunks(tone(4.0)):  # the candidate talks while no question is open
        await mic.feed(chunk)
    mic.keep_recent()  # the hub starts listening to a new question
    reader = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    for chunk in chunks(room(0.7)):
        await mic.feed(chunk)
    audio = np.frombuffer(await asyncio.wait_for(reader, 1), dtype="<i2")
    assert np.count_nonzero(audio) / RATE < 1.6 + 0.7


async def test_switching_roles_or_turning_the_microphone_off_ends_the_part():
    mic = MicrophoneSource(vad=LoudnessVAD(), turn=SilenceTurn(silence_ms=5000))
    reader = asyncio.create_task(drain(mic))
    await asyncio.sleep(0)
    await mic.feed(tone(0.5))
    mic.set_role("interviewer")
    assert await asyncio.wait_for(reader, 1)
    asking = asyncio.create_task(drain(mic, Turn("s", "p", "", speaker="interviewer")))
    await asyncio.sleep(0)
    await mic.feed(tone(0.5) + silence(6))  # no end-of-answer while the interviewer talks
    assert not asking.done()
    mic.detach()
    assert await asyncio.wait_for(asking, 1)
    assert not mic.connected and not mic.speaking


async def test_no_vad_means_no_transcription_but_the_recording_runs(tmp_path):
    recorder = WavRecorder(tmp_path / "r.wav")
    mic = MicrophoneSource(vad=None, turn=None, recorder=recorder)
    assert not mic.transcribable
    await mic.feed(tone(0.5))
    assert recorder.seconds == pytest.approx(0.5)


def test_recording_appends_after_a_reconnect_and_stays_a_valid_wav(tmp_path):
    path = tmp_path / "rec" / "s.wav"
    first = WavRecorder(path)
    first.write(tone(0.5))
    first.close()
    second = WavRecorder(path)
    second.write(tone(0.25))
    with wave.open(str(path)) as w:  # readable while still open (header rewritten every write)
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.getnframes() == int(0.75 * RATE)
    second.close()


# --- Silero VAD and Smart Turn ---------------------------------------------------------------


def test_silero_finds_the_speech_in_a_korean_sample_and_none_in_noise():
    vad = SileroVAD()
    pcm = silence(1.0) + decode_pcm16(SAMPLE) + silence(1.0)
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    frames = audio[: len(audio) // FRAME * FRAME].reshape(-1, FRAME)
    whole = vad.stream().probabilities(frames)
    stream = vad.stream()
    parts = np.concatenate([stream.probabilities(frames[i : i + 3]) for i in range(0, len(frames), 3)])
    assert np.abs(whole - parts).max() < 1e-3  # chunk by chunk = all at once
    state = SpeechState(vad.threshold)
    speech = np.array([state.update(float(p)) for p in whole])
    seconds = np.flatnonzero(speech) * FRAME / RATE
    assert 1.0 <= seconds[0] and seconds[-1] <= 12.6  # never in the silence around the clip
    assert len(seconds) * FRAME / RATE > 4.5  # the sentence: 2.3 s to 8.5 s of the clip
    noise = (np.random.default_rng(1).normal(0, 0.003, 93 * FRAME)).astype(np.float32)
    assert (vad.stream().probabilities(noise.reshape(-1, FRAME)) < 0.5).all()


class Scores:
    """A Smart Turn whose model answers from a list, to test the waiting logic."""

    min_speech_ms = 250
    pause_ms = 1000
    threshold = 0.8
    max_silence_ms = 3000

    def __init__(self, *scores: float) -> None:
        self.scores = list(scores)
        self.calls = 0

    def probability(self, audio) -> float:
        self.calls += 1
        return self.scores.pop(0)


async def push(tracker, speech: bool, seconds: float) -> int | None:
    """Frames pushed until the tracker ended (ms into this stretch), or None."""
    frame = np.zeros(FRAME, np.float32)
    for i in range(int(seconds * 1000 / 32)):
        if await tracker.push(speech, frame):
            return (i + 1) * 32
    return None


async def test_smart_turn_ends_when_the_model_hears_a_finished_sentence():
    model = Scores(0.95)
    tracker = SmartTurnTracker(model, 32)
    assert await push(tracker, True, 1.0) is None
    assert await push(tracker, False, 2.0) == pytest.approx(1000, abs=32)
    assert tracker.reason == "model" and model.calls == 1


async def test_smart_turn_waits_on_an_unfinished_sentence_up_to_the_longest_silence():
    model = Scores(0.3, 0.2)
    tracker = SmartTurnTracker(model, 32)
    await push(tracker, True, 1.0)
    assert await push(tracker, False, 1.5) is None  # asked once at 1 s: not finished
    assert await push(tracker, True, 0.5) is None  # goes on: the next pause is asked again
    assert await push(tracker, False, 4.0) == pytest.approx(3000, abs=32)
    assert tracker.reason == "max_silence" and model.calls == 2


def test_smart_turn_without_its_downloaded_file_refuses_to_load(tmp_path, no_network):
    with pytest.raises(ProviderUnavailable, match="내려받"):
        SmartTurn(weights_dir=tmp_path)._load()


# --- prefetch ------------------------------------------------------------------------------


class Recording:
    serving = object()

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def encode(self, texts):
        self.texts += texts
        return []


async def test_prefetch_embeds_the_latest_answer_and_never_one_the_guard_stops():
    from interview_assistant.deid.types import KnownIdentity

    retrieval = Recording()
    prefetch = AnswerPrefetch(retrieval)
    known = KnownIdentity(name="홍길동")
    prefetch.push(["첫 문장입니다."], known)
    prefetch.push(["첫 문장입니다. 둘째 문장입니다."], known)  # replaces the waiting one
    await prefetch.wait()
    prefetch.push(["저는 홍길동입니다."], known)  # an identifier left in: not embedded
    await prefetch.wait()
    assert retrieval.texts == ["첫 문장입니다. 둘째 문장입니다."]


# --- the API -------------------------------------------------------------------------------


def _start(api, consent: bool) -> str:
    api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": consent})
    assert api.post(f"/api/sessions/{SCHEDULED}/start").status_code == 200
    return SCHEDULED


START = {"type": "start", "format": "pcm16", "sample_rate": 16000, "source": "microphone",
         "constraints": {"echoCancellation": True, "noiseSuppression": False, "autoGainControl": False}}
SPEECH = decode_pcm16(SAMPLE)


def test_no_consent_keeps_the_microphone_off(api):
    sid = _start(api, consent=False)
    with api.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        ws.send_json(START)
        assert ws.receive_json() == {"type": "error", **codes.describe(codes.NO_CONSENT)}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4403 and closed.value.reason == "NO-CONSENT"
    chunk = api.post(f"/api/sessions/{sid}/audio/chunks?stream=abcdefgh01&seq=0", content=silence(0.1))
    assert chunk.status_code == 403 and chunk.json()["detail"]["code"] == "NO-CONSENT"
    assert not list((api.runtime.settings.recordings_dir).glob("*"))


def test_a_spoken_answer_is_transcribed_closed_by_silence_and_recorded_in_the_raw_zone(api, tmp_path):
    sid = _start(api, consent=True)
    with api.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        ws.send_json(START)
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["role"] == "candidate" and ready["notices"] == []
        qa = api.post(
            f"/api/sessions/{sid}/qa-items", json={"question": "공정 개선 경험은?", "question_source": "interviewer"}
        ).json()
        for chunk in chunks(silence(0.5) + SPEECH + silence(2.5)):
            ws.send_bytes(chunk)
        assert ws.receive_json() == {"type": "state", "speaking": True, "role": "candidate"}
        detail = wait_for(api, f"/api/sessions/{sid}", lambda d: d["qa_items"][-1]["answer_deidentified"])
    answer = detail["qa_items"][-1]
    assert answer["id"] == qa["id"]
    assert answer["answer_deidentified"].startswith("[fake 전사] 오디오")  # fake STT got gated PCM
    segments = api.get(f"/api/sessions/{sid}/transcript").json()["segments"]
    assert [s["speaker"] for s in segments if s["qa_item_id"] == qa["id"]] == ["interviewer", "candidate"]

    with api.runtime.session_factory() as db:
        from interview_assistant.models import AuditLog, InterviewSession

        session = db.get(InterviewSession, sid)
        path = uri_to_path(session.recording_uri)
        actions = [a.action for a in db.query(AuditLog).filter_by(target_id=sid)]
    recordings = api.runtime.settings.recordings_dir
    assert path == (recordings / f"{sid}.wav").resolve()
    with wave.open(str(path)) as w:  # everything received, raw
        assert w.getnframes() == len(silence(0.5) + SPEECH + silence(2.5)) // 2
    raw_zone = {recordings.resolve(), (tmp_path / "uploads").resolve()}
    written = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix not in (".db", ".db-journal")]
    assert all(p.resolve().parent in raw_zone for p in written), written
    assert {"audio.connected", "audio.constraints", "audio.disconnected"} <= set(actions)


def test_wrong_format_and_a_second_connection_are_refused(api):
    sid = _start(api, consent=True)
    with api.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        ws.send_json({**START, "sample_rate": 48000})
        assert ws.receive_json()["code"] == "AUDIO-FORMAT"
    with api.websocket_connect(f"/api/sessions/{sid}/audio") as first:
        first.send_json(START)
        assert first.receive_json()["type"] == "ready"
        with api.websocket_connect(f"/api/sessions/{sid}/audio") as second:
            second.send_json(START)
            assert second.receive_json()["code"] == "MIC-TAKEN"


def test_http_chunks_stand_in_for_a_blocked_websocket(api):
    sid = _start(api, consent=True)
    url = f"/api/sessions/{sid}/audio/chunks?stream=stream-0001"
    for seq, chunk in enumerate(chunks(SPEECH[RATE * 2 * 3 : RATE * 2 * 5], ms=300)):
        body = api.post(f"{url}&seq={seq}", content=chunk, headers={"X-Audio-Format": "pcm16;rate=16000"})
        assert body.status_code == 200
    assert body.json() == {"speaking": True, "role": "candidate", "notices": []}
    mic = api.runtime.hub.microphone(sid)
    received = mic.received_ms
    api.post(f"{url}&seq=1", content=tone(0.3))  # sent again after a timeout: ignored
    assert mic.received_ms == received and mic.transport == "http"
    assert api.post(f"{url}&seq=9", content=b"", headers={"X-Audio-Format": "pcm16;rate=48000"}).status_code == 415
    assert api.delete(url).status_code == 204
    assert not mic.connected


def test_a_question_asked_aloud_becomes_the_next_question(api):
    sid = _start(api, consent=True)
    with api.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        ws.send_json(START)
        ws.receive_json()
        assert api.post(f"/api/sessions/{sid}/live/role", json={"role": "interviewer"}).json() == {
            "role": "interviewer",
            "qa_item": None,
        }
        for chunk in chunks(SPEECH[: RATE * 2 * 3] + silence(0.5)):
            ws.send_bytes(chunk)
        ws.receive_json()  # speaking
        switched = api.post(f"/api/sessions/{sid}/live/role", json={"role": "candidate"}).json()
    qa = switched["qa_item"]
    assert switched["role"] == "candidate" and qa["question_source"] == "interviewer"
    assert qa["question"].startswith("[fake 전사] 오디오")
    segments = api.get(f"/api/sessions/{sid}/transcript").json()["segments"]
    assert [(s["speaker"], s["qa_item_id"]) for s in segments] == [("interviewer", qa["id"])]


def test_switching_roles_needs_a_microphone(api):
    sid = _start(api, consent=True)
    response = api.post(f"/api/sessions/{sid}/live/role", json={"role": "interviewer"})
    assert response.status_code == 409


def test_sample_audio_for_diagnosis_is_listed_and_served(api):
    samples = api.get("/api/live/audio-samples").json()
    assert {s["name"] for s in samples} >= {"ko-fleurs-1894"}
    wav = api.get("/api/live/audio-samples/ko-fleurs-1894")
    assert wav.headers["content-type"] == "audio/wav" and wav.content[:4] == b"RIFF"
    assert api.get("/api/live/audio-samples/..%2Frecordings").status_code == 404


def test_after_the_interview_the_recording_is_transcribed_again_when_the_admin_asked(api):
    roles = {r["role"]: r for r in api.get("/api/admin/models").json()["roles"]}
    options = {**roles["stt.batch"]["spec"]["options"], "retranscribe": True}
    applied = api.post(
        "/api/admin/models/stt.batch/apply", json={"impl": "fake", "options": options, "reason": "GPU 없음"}
    )
    assert applied.status_code == 200
    sid = _start(api, consent=True)  # started after the change: pinned to it
    with api.websocket_connect(f"/api/sessions/{sid}/audio") as ws:
        ws.send_json(START)
        ws.receive_json()
        api.post(f"/api/sessions/{sid}/qa-items", json={"question": "경험을 말해 주세요.", "question_source": "interviewer"})
        for chunk in chunks(SPEECH + silence(2.5)):
            ws.send_bytes(chunk)
        wait_for(api, f"/api/sessions/{sid}", lambda d: d["qa_items"][-1]["answer_deidentified"])
    assert api.post(f"/api/sessions/{sid}/end").status_code == 200
    batch = wait_for(api, f"/api/sessions/{sid}/transcript?source=batch", lambda b: b["segments"])["segments"]
    assert [s["speaker"] for s in batch] == ["candidate"]
    assert batch[0]["text"].startswith("[fake 전사] 오디오 14.0초")  # the whole recording
    live = api.get(f"/api/sessions/{sid}/transcript").json()["segments"]
    assert all(s["segment_id"] != batch[0]["segment_id"] for s in live)


def test_the_admin_can_test_the_vad_and_the_end_of_answer_detector_on_the_sample(api):
    def run(role: str, spec: dict) -> dict:
        response = api.post(f"/api/admin/models/{role}/test", data={"spec": json.dumps(spec)})
        assert response.status_code == 200, response.text
        return response.json()

    vad = run("audio.vad", {"impl": "silero", "options": {}})
    assert vad["ok"] and "말소리" in vad["summary"] and vad["output"]["speech"]
    turn = run("audio.turn", {"impl": "silence", "options": {"silence_ms": 1500}})
    assert turn["ok"] and turn["output"]["ends"][-1]["reason"] == "silence"
    assert "1.5초 뒤 답변 끝" in turn["summary"]
    off = run("audio.denoise", {"impl": "off", "options": {}})
    assert off["ok"] and "끔" in off["summary"]


@pytest.mark.skipif(importlib.util.find_spec("pyrnnoise") is None, reason="pyrnnoise not installed (uv sync --extra denoise)")
def test_the_admin_can_test_both_noise_suppressors_on_the_sample(api):
    def run(spec: dict) -> dict:
        response = api.post("/api/admin/models/audio.denoise/test", data={"spec": json.dumps(spec)})
        assert response.status_code == 200, response.text
        return response.json()

    rn = run({"impl": "rnnoise", "options": {}})
    assert rn["ok"], rn
    assert rn["output"]["same_length"] and rn["output"]["delay_ms"] == 35
    assert "지연 35ms" in rn["summary"] and "말소리 구간" in rn["summary"]
    assert rn["output"]["other_change_db"] < rn["output"]["speech_change_db"]  # the rest is turned down more
    # The test server's weights folder is empty: DeepFilterNet's test is refused, naming the file.
    spec = {"impl": "deepfilternet", "options": {}}
    refused = api.post("/api/admin/models/audio.denoise/test", data={"spec": json.dumps(spec)})
    assert refused.status_code == 409 and "deepfilternet3" in refused.json()["detail"]
