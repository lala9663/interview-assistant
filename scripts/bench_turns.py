"""Compare end-of-answer detectors (답변 끝 판정) on Korean answers with thinking pauses.

    uv run python scripts/bench_turns.py --build-fleurs <FLEURS dir> --out samples/
    uv run python scripts/bench_turns.py --samples samples/ [--samples tts/] --json result.json

`--build-fleurs` makes answers with thinking pauses from FLEURS Korean clips (CC BY 4.0; the dir
holds the clips and a `manifest.json` of `{"file", "gender"}` rows):

- `mid_*`: one sentence with a pause of 1.0-3.0 s put into its longest inner gap (between 30% and
  75% of the sentence), where a reader takes a breath: a thought cut off mid-sentence.
- `between_*`: two sentences of the same speaker with a 1.0-3.0 s pause between them: the
  candidate finished one thought and goes on after thinking.
- `single_*`: one sentence, no pause (how fast each detector closes a plain answer).

Pauses are filled with the clip's own room tone (its quietest stretch), not digital silence.
Any other WAV in a samples dir counts too, named `<kind>_*.wav` (TTS answers: `tts_*`).

Every sample runs offline through the same path as the microphone (live/microphone.py): Silero VAD
per 32 ms frame with hysteresis, then each detector. After an early end the next part starts at
the next speech, as the hub does, and can end early again. Reported per detector and kind:
early ends (an end before the answer's last speech), samples cut at least once, and the delay from
the last speech to the end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
import wave
from pathlib import Path

import numpy as np

from interview_assistant.live.microphone import FRAME, FRAME_MS, speech_flags
from interview_assistant.providers.audio import decode_pcm16, write_wav
from interview_assistant.providers.turn.silence import SilenceTurn
from interview_assistant.providers.turn.smart_turn import SmartTurn
from interview_assistant.providers.vad.silero import SileroVAD

RATE = 16000
PAUSES = (1.0, 1.5, 2.0, 2.5, 3.0)


def _load(path: Path) -> np.ndarray:
    return np.frombuffer(decode_pcm16(path), dtype="<i2").astype(np.float32) / 32768.0


def _room_tone(audio: np.ndarray, flags: np.ndarray, seconds: float) -> np.ndarray:
    """`seconds` of the clip's quietest non-speech audio, repeated."""
    quiet = [audio[i * FRAME : (i + 1) * FRAME] for i, f in enumerate(flags) if not f]
    quiet.sort(key=lambda x: float(np.sqrt((x**2).mean())))
    base = np.concatenate(quiet[: max(8, len(quiet) // 3)] or [np.zeros(FRAME, np.float32)])
    reps = int(np.ceil(seconds * RATE / len(base)))
    return np.tile(base, reps)[: int(seconds * RATE)]


def _speech_span(flags: np.ndarray) -> tuple[int, int]:
    idx = np.flatnonzero(flags)
    return int(idx[0]) * FRAME, int(idx[-1] + 1) * FRAME


def build_fleurs(src: Path, out: Path, count: int = 8) -> None:
    rows = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    rng = random.Random(7)
    vad = SileroVAD()
    out.mkdir(parents=True, exist_ok=True)
    clips = []
    for row in rows:
        audio = _load(src / row["file"])
        clips.append((row, audio, speech_flags(vad, audio)))
    made = 0
    for row, audio, flags in clips:  # mid: the longest inner gap between 30% and 75%
        if made >= count:
            break
        start, end = _speech_span(flags)
        gaps, run = [], 0
        for i in range(start // FRAME, end // FRAME):
            if not flags[i]:
                run += 1
            elif run:
                gaps.append((i - run, run))
                run = 0
        lo, hi = start + 0.3 * (end - start), start + 0.75 * (end - start)
        inner = [(i, r) for i, r in gaps if lo <= i * FRAME <= hi]
        if not inner:
            continue
        at, run = max(inner, key=lambda g: g[1])
        cut = (at + run // 2) * FRAME
        pause = PAUSES[made % len(PAUSES)]
        joined = np.concatenate([audio[:cut], _room_tone(audio, flags, pause), audio[cut:]])
        write_wav(out / f"mid_{made:02d}.wav", (np.clip(joined, -1, 1) * 32767).astype("<i2").tobytes())
        made += 1
    by_gender: dict[int, list] = {}
    for clip in clips:
        by_gender.setdefault(clip[0]["gender"], []).append(clip)
    made = 0
    for group in by_gender.values():
        rng.shuffle(group)
        for (row_a, a, fa), (row_b, b, fb) in zip(group[0::2], group[1::2], strict=False):
            if made >= count:
                break
            _, end_a = _speech_span(fa)
            start_b, _ = _speech_span(fb)
            pause = PAUSES[made % len(PAUSES)]
            joined = np.concatenate([a[:end_a], _room_tone(a, fa, pause), b[start_b:]])
            write_wav(out / f"between_{made:02d}.wav", (np.clip(joined, -1, 1) * 32767).astype("<i2").tobytes())
            made += 1
    for i, (row, audio, _) in enumerate(clips[-count:]):
        write_wav(out / f"single_{i:02d}.wav", (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


async def run_detector(provider, flags: np.ndarray, audio: np.ndarray) -> tuple[list[int], list[float]]:
    """End times (ms) over the whole sample, with a new part from the next speech after each end,
    and the time each model call took."""
    ends: list[int] = []
    tracker = provider.tracker(FRAME_MS)
    waiting = False  # an end happened; the next part starts with speech
    calls: list[float] = []
    for i, speech in enumerate(flags):
        frame = audio[i * FRAME : (i + 1) * FRAME]
        if waiting:
            if not speech:
                continue
            tracker, waiting = provider.tracker(FRAME_MS), False
        before = tracker.probability
        started = time.perf_counter()
        ended = await tracker.push(bool(speech), frame)
        if tracker.probability is not before:
            calls.append((time.perf_counter() - started) * 1000)
        if ended:
            ends.append((i + 1) * FRAME_MS)
            waiting = True
    if not waiting:  # the sample ran out before the detector ended: pad with silence
        silent = np.zeros(FRAME, np.float32)
        i = len(flags)
        while not await tracker.push(False, silent):
            i += 1
        ends.append((i + 1) * FRAME_MS)
    return ends, calls


def detectors(weights: Path) -> dict[str, object]:
    found: dict[str, object] = {f"silence {ms}ms": SilenceTurn(silence_ms=ms) for ms in (700, 1000, 1500, 2000, 2500, 3000)}
    for pause in (200, 500, 1000, 1500, 2000):
        for threshold in (0.5, 0.8):
            found[f"smart turn ({pause / 1000:g}s, {threshold:g}, max 3s)"] = SmartTurn(
                weights_dir=weights, pause_ms=pause, threshold=threshold
            )
    return found


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-fleurs", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--samples", type=Path, action="append", default=[])
    parser.add_argument("--weights", type=Path, default=Path("weights"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.build_fleurs:
        build_fleurs(args.build_fleurs, args.out)
        print(f"built samples in {args.out}")
        if not args.samples:
            return
    vad = SileroVAD()
    found = detectors(args.weights)
    for provider in found.values():
        await provider.warm_up()
    files = sorted(p for d in args.samples for p in d.glob("*.wav"))
    rows = []
    for path in files:
        with wave.open(str(path)) as w:
            seconds = w.getnframes() / w.getframerate()
        audio = _load(path)
        flags = speech_flags(vad, audio)
        n = len(flags)
        last = int(np.flatnonzero(flags)[-1] + 1) * FRAME_MS
        kind = path.stem.split("_")[0]
        for name, provider in found.items():
            ends, calls = await run_detector(provider, flags, audio[: n * FRAME])
            early = [e for e in ends if e < last]
            final = next(e for e in ends if e >= last)
            rows.append(
                {
                    "file": path.name,
                    "kind": kind,
                    "seconds": round(seconds, 2),
                    "detector": name,
                    "early_ends": len(early),
                    "delay_ms": final - last,
                    "model_ms": calls,
                }
            )
    report(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def report(rows: list[dict]) -> None:
    kinds = sorted({r["kind"] for r in rows})
    names = list(dict.fromkeys(r["detector"] for r in rows))
    print("| 판정 | " + " | ".join(f"{k}: 조기 끊김 (표본) / 끝 뒤 지연 평균·최대" for k in kinds) + " | 전체 조기 끊김 | 전체 지연 평균 |")
    print("| --- |" + " --- |" * (len(kinds) + 2))
    for name in names:
        cells = []
        mine = [r for r in rows if r["detector"] == name]
        for k in kinds:
            sel = [r for r in mine if r["kind"] == k]
            cut = sum(r["early_ends"] for r in sel)
            samples = sum(1 for r in sel if r["early_ends"])
            delays = [r["delay_ms"] for r in sel]
            cells.append(f"{cut}회 ({samples}/{len(sel)}) / {statistics.mean(delays) / 1000:.2f}·{max(delays) / 1000:.2f}초")
        total_cut = sum(r["early_ends"] for r in mine)
        total_samples = sum(1 for r in mine if r["early_ends"])
        mean_delay = statistics.mean(r["delay_ms"] for r in mine) / 1000
        print(f"| {name} | " + " | ".join(cells) + f" | {total_cut}회 ({total_samples}/{len(mine)}) | {mean_delay:.2f}초 |")
    calls = [c for r in rows for c in r["model_ms"]]
    if calls:
        print(f"\nSmart Turn 호출 {len(calls)}회: 평균 {statistics.mean(calls):.0f}ms, 최대 {max(calls):.0f}ms")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
