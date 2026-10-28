"""Measure the live microphone path on this machine: from the end of the candidate's speech to the
final transcript, to the answer closing (end of answer), to the first follow-up card.

    uv run python scripts/bench_live_audio.py --sizes small medium --turns silence smart_turn --json out.json
    uv run python scripts/bench_live_audio.py --sizes small --turns silence --embedding bge-m3-int8 --llm-speed 1 --repeat 2

Runs the app's own pieces in one process, on a seeded demo database in a temporary folder: the
live hub with a `MicrophoneSource` (Silero VAD, the end-of-answer detector), local Whisper as the
streaming STT (beam 1, as the stt.streaming role), de-identification, and the follow-up stream
(`ai/followups.py`) with the fake LLM and fake embedding. Each sample WAV is fed in 100 ms chunks
on the wall clock, like a microphone, then silence until the answer closes; then follow-ups are
requested as the interview screen does on `qa.answered`.

Times are measured from the sample's last speech frame (Silero, as the microphone path decides it):
`endpoint` when the end-of-answer detector ended the answer, `final` the last final transcript
segment, `closed` the last `qa.answered` (an answer ended early and went on closes again), `first card` the first
suggestion shown (`suggestion.start`, a question-bank card or the first AI card), `first AI card`
the fake LLM's first. The fake LLM runs without simulated latency (speed 0): a real model adds its
time to first token on top. Whisper weights and the Smart Turn file must be downloaded already.

`--embedding bge-m3` / `bge-m3-int8` uses the real BGE-M3 instead (loaded once, the index built on
each run's database): the answer is then embedded while the candidate talks (live/prefetch.py),
beside Whisper on the same CPU, and the question-bank card waits for the search.
`--llm-speed 1` paces the fake LLM like the frontend mock (first token 0.55 s).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "src" / "interview_assistant" / "providers" / "samples"
LIVE = "0a1b2c3d-0000-4000-9000-live00000000"  # the seeded session in progress, with consent


def seeded(folder: Path):
    from interview_assistant.config import Settings
    from interview_assistant.crypto import FieldCipher
    from interview_assistant.db import make_engine, make_session_factory
    from interview_assistant.deid.service import DeidService
    from interview_assistant.demo.seed import seed
    from interview_assistant.models import Base

    path = folder / "bench.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{path.as_posix()}",
        encryption_key=FieldCipher.generate_key(),
        providers_file=ROOT / "config" / "providers.fake.yaml",
        deid_file=ROOT / "config" / "deid.yaml",
        uploads_dir=folder / "uploads",
        recordings_dir=folder / "recordings",
        weights_dir=ROOT / "weights",
        demo_speed=0,
        intake_workers=0,
    )
    engine = make_engine(settings.database_url, connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        seed(db, DeidService.from_settings(settings), settings)
    return settings, factory


async def run_one(settings, factory, size: str, turn_impl: str, wav: Path, embedding=None, llm_speed: float = 0.0) -> dict:
    from interview_assistant.ai.followups import follow_up_events
    from interview_assistant.live.microphone import FRAME, MicrophoneSource, speech_flags
    from interview_assistant.models import InterviewSession, QAItem, QuestionSource
    from interview_assistant.models.base import utcnow
    from interview_assistant.providers.audio import decode_pcm16
    from interview_assistant.providers.fake import FakeDiarization, FakeEmbedding, FakeLLM, FakeSTT
    from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT
    from interview_assistant.providers.turn.silence import SilenceTurn
    from interview_assistant.providers.turn.smart_turn import SmartTurn
    from interview_assistant.providers.vad.silero import SileroVAD
    from interview_assistant.runtime import Providers, build_runtime

    stt = FasterWhisperSTT(model=size, beam_size=1, weights_dir=settings.weights_dir)
    await stt.warm_up()
    providers = Providers(
        llm={"primary": FakeLLM(speed=llm_speed), "screening": FakeLLM()},
        stt={"streaming": stt, "batch": FakeSTT()},
        embedding=embedding or FakeEmbedding(),
        diarization=FakeDiarization(),
    )
    runtime = build_runtime(settings, providers=providers, session_factory=factory)
    runtime.retrieval.start()
    await runtime.retrieval.wait()
    vad = SileroVAD()
    await vad.warm_up()
    if turn_impl == "smart_turn":
        turn = SmartTurn(weights_dir=settings.weights_dir, pause_ms=1000, threshold=0.8, max_silence_ms=3000)
        await turn.warm_up()
    else:
        turn = SilenceTurn(silence_ms=2000)

    pcm = decode_pcm16(wav)
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    flags = speech_flags(vad, audio)
    last_speech_s = (np.flatnonzero(flags)[-1] + 1) * FRAME / 16000

    hub = runtime.hub
    with factory() as db:
        session = db.get(InterviewSession, LIVE)
        for qa in session.qa_items:  # close what the seed left open
            if qa.answered_at is None:
                qa.answered_at = utcnow()
        seq = max(q.seq for q in session.qa_items) + 1
        qa = QAItem(session_id=LIVE, seq=seq, question="그 프로젝트에서 맡은 일을 설명해 주세요.", question_source=QuestionSource.interviewer, asked_at=utcnow())
        db.add(qa)
        db.commit()
        qa_id = qa.id
    mic = MicrophoneSource(vad=vad, turn=turn)
    mic.attach("bench", "bench")
    queue = hub.subscribe(LIVE)
    await hub.attach_microphone(LIVE, mic)
    hub.listen(LIVE, qa_id)

    events: list[tuple[float, str, dict]] = []
    cards: dict[float, dict[str, float]] = {}  # qa.answered time -> first card times of its follow-ups
    ends: list[float] = []  # when the end-of-answer detector closed a part
    following: asyncio.Task | None = None

    async def follow(answered_at: float) -> None:
        """As the interview screen does on qa.answered: request follow-ups at once."""
        found = cards.setdefault(answered_at, {})
        ai = runtime.models.active.ai
        async for name, data in follow_up_events(factory, ai, runtime.deid, session_id=LIVE, qa_item_id=qa_id, retrieval=runtime.retrieval):
            if name == "suggestion.start":
                found.setdefault("first", time.monotonic())
                if data.get("source") == "ai":
                    found["ai"] = time.monotonic()
                    return

    async def watch():
        nonlocal following
        while True:
            name, data = await queue.get()
            now = time.monotonic()
            events.append((now, name, data))
            if name == "qa.answered":
                if following is not None:
                    following.cancel()
                following = asyncio.create_task(follow(now))
            if mic.ended_at and (not ends or ends[-1] != mic.ended_at):
                ends.append(mic.ended_at)

    watcher = asyncio.create_task(watch())
    chunk = 3200  # 100 ms
    started = time.monotonic()
    speech_end = started + last_speech_s
    i = 0
    while True:
        await asyncio.sleep(max(0.0, started + i * 0.1 - time.monotonic()))
        await mic.feed(pcm[i * chunk : (i + 1) * chunk] or bytes(chunk))
        i += 1
        if mic.ended_at and (not ends or ends[-1] != mic.ended_at):
            ends.append(mic.ended_at)
        # Done once the detector ended the answer after its last speech, the answer closed after
        # that, and that answer's follow-ups showed their first AI card.
        final_end = next((e for e in ends if e >= speech_end), None)
        last = [t for t, n, _ in events if n == "qa.answered" and final_end and t >= final_end]
        if last and "ai" in cards.get(last[-1], {}):
            break
        if time.monotonic() - started > len(pcm) / 32000 + 60:
            break
    watcher.cancel()
    if following is not None:
        following.cancel()
    finals = [t for t, n, d in events if n == "segment.final" and d["speaker"] == "candidate"]
    answered = [(t, d) for t, n, d in events if n == "qa.answered"]
    closed_at = answered[-1][0] if answered else None
    text = answered[-1][1]["answer_deidentified"] if answered else ""
    final_cards = cards.get(closed_at, {}) if closed_at else {}
    first_card, first_ai = final_cards.get("first"), final_cards.get("ai")
    endpoint = next((e for e in ends if e >= speech_end), None)
    await hub.end(LIVE)
    to = lambda t: None if t is None else round(t - speech_end, 2)  # noqa: E731
    return {
        "sample": wav.name,
        "stt": f"faster-whisper-{size}",
        "turn": turn_impl,
        "embedding": getattr(embedding, "model", "fake"),
        "last_speech_s": round(float(last_speech_s), 2),
        "endpoint_s": to(endpoint),
        "final_s": to(max(finals) if finals else None),
        "closed_s": to(closed_at),
        "first_card_s": to(first_card),
        "first_ai_card_s": to(first_ai),
        "closed_to_first_card_s": round(first_card - closed_at, 2) if first_card and closed_at else None,
        "parts": len(answered),
        "early_closes": sum(1 for e in ends if e < speech_end),
        "text": text,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", default=["small", "medium"])
    parser.add_argument("--turns", nargs="+", default=["silence", "smart_turn"])
    parser.add_argument("--samples", nargs="+", type=Path, default=[SAMPLES / "answer-pauses.wav", SAMPLES / "ko-fleurs-1894.wav"])
    parser.add_argument("--embedding", default="fake", choices=["fake", "bge-m3", "bge-m3-int8"])
    parser.add_argument("--llm-speed", type=float, default=0.0, help="fake LLM pace (1 = like the frontend mock)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per sample")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    embedding = None
    if args.embedding != "fake":
        from interview_assistant.providers.embedding.bge_m3 import BgeM3Embedding

        embedding = BgeM3Embedding(model=args.embedding, weights_dir=ROOT / "weights")
        await embedding.warm_up()
    rows = []
    with tempfile.TemporaryDirectory(prefix="ia-bench-live-") as tmp:
        folder = Path(tmp)
        settings, factory = seeded(folder)
        template = folder / "bench.db"
        for size in args.sizes:
            for turn in args.turns:
                for wav in [w for w in args.samples for _ in range(args.repeat)]:
                    run_dir = Path(tempfile.mkdtemp(prefix=f"{size}-{turn}-{wav.stem}-", dir=folder))
                    shutil.copyfile(template, run_dir / "bench.db")
                    run_settings = settings.model_copy(update={"database_url": f"sqlite+pysqlite:///{(run_dir / 'bench.db').as_posix()}"})
                    from interview_assistant.db import make_engine, make_session_factory

                    run_factory = make_session_factory(make_engine(run_settings.database_url, connect_args={"check_same_thread": False, "timeout": 30}))
                    row = await run_one(run_settings, run_factory, size, turn, wav, embedding, args.llm_speed)
                    run_factory.kw["bind"].dispose()
                    rows.append(row)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
        factory.kw["bind"].dispose()
    print()
    print("| STT | 답변 끝 판정 | 표본 | 말 끝 → 끝 판정 | → 최종 전사 | → 답변 닫힘 | → 첫 꼬리질문 카드 | → 첫 AI 카드 | 조기 닫힘 |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for size in args.sizes:
        for turn in args.turns:
            sel = [r for r in rows if r["stt"].endswith(size) and r["turn"] == turn]
            for r in sel:
                print(f"| {r['stt']} | {turn} | {r['sample']} | {r['endpoint_s']} | {r['final_s']} | {r['closed_s']} | {r['first_card_s']} | {r['first_ai_card_s']} | {r['early_closes']} |")
            vals = [r["closed_s"] for r in sel if r["closed_s"] is not None]
            if vals:
                print(f"|  |  | 평균 |  |  | {statistics.mean(vals):.2f} |  |  |  |")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
