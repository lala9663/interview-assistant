"""Does server-side noise suppression help Whisper on noisy Korean speech? (docs/audio-input.md 7장)

    uv run python scripts/bench_denoise.py --fetch-noise noise/
    uv run python scripts/bench_denoise.py --fleurs <FLEURS dir> --noise noise/ --json denoise.json
    uv run python scripts/bench_denoise.py --cpu --noise noise/

Speech: `answer-pauses` (the diagnostic microphone sample) and FLEURS Korean test clips (CC BY 4.0;
the dir holds the clips and a `manifest.json` of `{"file", "id", "raw_transcription"}` rows, as for
scripts/bench_turns.py). Noise: four recordings from Wikimedia Commons (`NOISES`, licences checked,
about 18 MB). Each mixture is 1 s of noise, the clip with the noise under it, then 4 s of noise
(where the answer should close); the noise is scaled to the SNR over the clip's speech frames
(Silero VAD on the clean clip) and starts at a random point of its recording.

Every mixture goes through each suppressor as the microphone path runs it (a fresh stream, 100 ms
chunks, the output shifted back by the stream's delay), then:

- Whisper small as the live path uses it (`stt.streaming`, beam 1): Silero VAD on the suppressed
  audio, everything but speech (128 ms before, 300 ms after) replaced by silence, then `stream`
  (its final segments; partials are switched off, they do not change a final).
- Whisper large-v3 as the re-transcription after the interview uses it (`stt.batch`, beam 5, VAD).
  The product re-transcribes the raw recording, never the suppressed audio; this column says
  whether suppressing first would help it.
- CER against the FLEURS transcript (textmetrics.cer: spaces and punctuation ignored), summed
  over clips (edits / characters).
- VAD: noise taken for speech in the noise-only lead and tail (seconds of false speech per minute
  of noise), and the share of the clean clip's speech frames still heard as speech.
- Smart Turn (the default 1 s / 0.8 / 3 s): whether the answer closes within the 4 s tail, how
  long after the last speech, and ends before the last speech (early ends).

`--cpu` times each suppressor alone on 60 s of noisy speech in 100 ms chunks (ms of processing per
second of audio, one thread) and, for DeepFilterNet, how far each `context_ms` lands from the
whole recording processed at once.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from interview_assistant.live.microphone import FRAME, FRAME_MS, PREROLL_MS, speech_flags
from interview_assistant.providers.audio import SAMPLES_DIR, decode_pcm16, pcm_chunks, write_wav
from interview_assistant.providers.denoise import NoDenoise
from interview_assistant.providers.denoise.deepfilternet import DeepFilterNet, enhance
from interview_assistant.providers.denoise.resample import Downsampler, Upsampler
from interview_assistant.providers.denoise.rnnoise import RNNoise
from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT
from interview_assistant.providers.turn.smart_turn import SmartTurn
from interview_assistant.providers.vad.silero import SileroVAD
from interview_assistant.textmetrics import cer, normalize

RATE = 16000
LEAD_S, TAIL_S = 1.0, 4.0
SPEECH_PAD_MS = 300  # SileroVAD's default, as the live path gates

# Wikimedia Commons, checked 2026-10-30 (file page, licence, author; sha1 as Commons reports it).
NOISES: dict[str, dict[str, str]] = {
    "office": {
        "file": "Open-space_office_ambiance.ogg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/b1/Open-space_office_ambiance.ogg",
        "sha1": "09f9521a9b5ffb92be2ea939a09458eaf4453c76",
        "license": "CC BY-SA 4.0, Mooeypoo",
        "what": "개방형 사무실 소리(여럿이 말하는 소리, 전화, 키보드), 2분 53초",
    },
    "aircon": {
        "file": "Air_conditioner_hum_(Gravity_Sound).wav",
        "url": "https://upload.wikimedia.org/wikipedia/commons/9/99/Air_conditioner_hum_%28Gravity_Sound%29.wav",
        "sha1": "fc60ea75940b09e95b7a3b7e1441c03af1e9ae09",
        "license": "CC BY 4.0, Gravity Sound",
        "what": "에어컨 웅웅거림, 14초",
    },
    "fan": {
        "file": "Fan_(Gravity_Sound).wav",
        "url": "https://upload.wikimedia.org/wikipedia/commons/0/08/Fan_%28Gravity_Sound%29.wav",
        "sha1": "59e08387afa5cd94fe5738aa5d05d9b65b1af7b9",
        "license": "CC BY 4.0, Gravity Sound",
        "what": "선풍기, 34초",
    },
    "keyboard": {
        "file": "Laptop_keyboard.ogg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/6/67/Laptop_keyboard.ogg",
        "sha1": "aeea0229ffdb2420ed02ba2a4e351d10b4c45c29",
        "license": "Public domain, russiandoll",
        "what": "노트북 키보드 타이핑, 1분 4초",
    },
}
ANSWER_PAUSES_TEXT = (
    "보고서는 행정부의 현재 이라크 정책에 대해 거의 모든 측면에서 매우 비판적이며 즉각적인 방향 변경을 촉구합니다. "
    "파리 사람들은 자기중심적이고, 무례하고, 오만하다는 평판이 있습니다."
)
ANSWER_PAUSES_IDS = {1709, 1910}  # its two FLEURS rows: not picked again


def fetch_noise(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, n in NOISES.items():
        target = out / n["file"]
        for attempt in range(6):
            if target.exists():
                break
            request = urllib.request.Request(n["url"], headers={"User-Agent": "interview-assistant-bench/0.1 (noise suppression measurement)"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    target.write_bytes(response.read())
            except urllib.error.HTTPError as exc:  # Wikimedia answers 429 to bursts
                if exc.code != 429 or attempt == 5:
                    raise
                time.sleep(float(exc.headers.get("Retry-After") or 0) or 15 * (attempt + 1))
        digest = hashlib.sha1(target.read_bytes()).hexdigest()
        if digest != n["sha1"]:
            target.unlink()
            raise SystemExit(f"{name}: sha1 {digest} is not the checked {n['sha1']} (file removed)")
        print(f"{name}: {target} ({target.stat().st_size / 1e6:.1f} MB, {n['license']})")


def floats(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 32767 / 32768) * 32768).astype("<i2").tobytes()


def load_noises(folder: Path) -> dict[str, np.ndarray]:
    found = {}
    for name, n in NOISES.items():
        audio = floats(decode_pcm16(folder / n["file"]))
        found[name] = audio / (np.sqrt((audio**2).mean()) + 1e-9)
    return found


def load_speech(fleurs: Path | None, count: int) -> list[dict[str, Any]]:
    clips = [{"name": "answer-pauses", "audio": floats(decode_pcm16(SAMPLES_DIR / "answer-pauses.wav")), "text": ANSWER_PAUSES_TEXT}]
    if fleurs is not None:
        rows = json.loads((fleurs / "manifest.json").read_text(encoding="utf-8"))
        rows = [r for r in rows if r["id"] not in ANSWER_PAUSES_IDS and 6 <= r.get("seconds", 10) <= 14]
        for row in sorted(rows, key=lambda r: r["file"])[: count - 1]:
            audio = floats(decode_pcm16(fleurs / row["file"]))
            clips.append({"name": f"fleurs-{row['id']}", "audio": audio, "text": row.get("raw_transcription") or row["transcription"]})
    return clips


def mix(clean: np.ndarray, flags: np.ndarray, noise: np.ndarray, snr_db: float, rng: random.Random) -> np.ndarray:
    lead, tail = int(LEAD_S * RATE), int(TAIL_S * RATE)
    total = lead + len(clean) + tail
    start = rng.randrange(len(noise))
    part = np.resize(np.roll(noise, -start), total)
    speech = np.repeat(flags, FRAME)
    power = float((clean[: len(speech)][speech] ** 2).mean())
    out = np.concatenate([np.zeros(lead, np.float32), clean, np.zeros(tail, np.float32)])
    out = out + part * math.sqrt(power / 10 ** (snr_db / 10))
    peak = float(np.abs(out).max())
    return (out * (0.95 / peak) if peak > 0.95 else out).astype(np.float32)


def suppress(provider: Any, audio: np.ndarray) -> tuple[np.ndarray, float]:
    """A fresh stream in 100 ms chunks; the output shifted back by its delay. (audio, seconds spent)"""
    stream = provider.stream()
    pcm = pcm16(audio) + bytes(2 * stream.delay_samples)
    started = time.perf_counter()
    out = b"".join(stream.process(pcm[i : i + 3200]) for i in range(0, len(pcm), 3200))
    spent = time.perf_counter() - started
    return floats(out)[stream.delay_samples : stream.delay_samples + len(audio)], spent


def gate(audio: np.ndarray, flags: np.ndarray) -> np.ndarray:
    """What the live path hands STT (live/microphone.py `_gate`): speech, 128 ms before it and
    the pad after it; every other frame digital silence."""
    keep = flags.copy()
    before, after = PREROLL_MS // FRAME_MS, math.ceil(SPEECH_PAD_MS / FRAME_MS)
    for i in np.flatnonzero(flags):
        keep[max(0, i - before) : i + after + 1] = True
    out = audio[: len(flags) * FRAME].copy().reshape(-1, FRAME)
    out[~keep] = 0
    return out.reshape(-1)


async def live_text(stt: FasterWhisperSTT, audio: np.ndarray) -> str:
    finals = [s.text async for s in stt.stream(pcm_chunks(pcm16(audio))) if s.is_final]
    return " ".join(t for t in finals if t)


async def batch_text(stt: FasterWhisperSTT, audio: np.ndarray, folder: Path) -> str:
    path = folder / "clip.wav"
    write_wav(path, pcm16(audio))
    return " ".join(s.text for s in await stt.transcribe(path.resolve().as_uri()) if s.text)


async def turn(provider: SmartTurn, audio: np.ndarray, flags: np.ndarray, last_speech_ms: int) -> dict[str, Any]:
    tracker = provider.tracker(FRAME_MS)
    ends = []
    for i, speech in enumerate(flags):
        if await tracker.push(bool(speech), audio[i * FRAME : (i + 1) * FRAME]):
            ends.append(((i + 1) * FRAME_MS, tracker.reason))
            tracker = provider.tracker(FRAME_MS)
    final = next((e for e in ends if e[0] >= last_speech_ms), None)
    return {
        "early_ends": sum(1 for e in ends if e[0] < last_speech_ms),
        "closed": final is not None,
        "close_ms": None if final is None else final[0] - last_speech_ms,
        "reason": None if final is None else final[1],
    }


def vad_stats(flags: np.ndarray, clean_flags: np.ndarray) -> dict[str, float]:
    lead = int(LEAD_S * 1000) // FRAME_MS
    speech = np.zeros(len(flags), dtype=bool)
    speech[lead : lead + len(clean_flags)] = clean_flags
    span = np.flatnonzero(speech)
    quiet = np.ones(len(flags), dtype=bool)
    quiet[max(0, span[0] - 10) : span[-1] + 16] = False  # around the speech: pads, breaths
    return {
        "false_s_per_min": round(float(flags[quiet].sum()) * FRAME_MS / 1000 / (quiet.sum() * FRAME_MS / 60000), 2),
        "recall": round(float(flags[speech].mean()), 4),
    }


def suppressors(names: list[str], weights: Path) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for name in names:
        impl, _, limit = name.partition(":")
        lim = float(limit or 0)
        if impl == "off":
            found[name] = NoDenoise()
        elif impl == "rnnoise":
            found[name] = RNNoise(atten_lim_db=lim)
        elif impl.startswith("deepfilternet"):
            context = impl.partition("@")[2]
            found[name] = DeepFilterNet(weights_dir=weights, atten_lim_db=lim, **({"context_ms": int(context)} if context else {}))
        else:
            raise SystemExit(f"unknown suppressor {name}")
    return found


async def run(args: argparse.Namespace) -> list[dict[str, Any]]:
    vad = SileroVAD()
    noises = load_noises(args.noise)
    clips = load_speech(args.fleurs, args.clips)
    found = suppressors(args.denoise, args.weights)
    for p in found.values():
        await p.warm_up()
    small = FasterWhisperSTT(model="small", beam_size=1, weights_dir=args.weights, cpu_threads=args.threads) if "small" in args.models else None
    if small is not None:
        small.partial_every_s = float("inf")  # partials never change a final; they only cost time here
    large = FasterWhisperSTT(model="large-v3", beam_size=5, weights_dir=args.weights, cpu_threads=args.threads) if "large-v3" in args.models else None
    turns = SmartTurn(weights_dir=args.weights, pause_ms=1000, threshold=0.8, max_silence_ms=3000)
    await turns.warm_up()
    for stt in (small, large):
        if stt is not None:
            await stt.warm_up()
    rows: list[dict[str, Any]] = []
    done = set()
    if args.json and args.json.exists() and args.resume:
        rows = json.loads(args.json.read_text(encoding="utf-8"))
        done = {(r["clip"], r["noise"], r["snr"], r["denoise"]) for r in rows}
    folder = Path(tempfile.mkdtemp(prefix="bench-denoise-"))
    conditions = [("clean", None)] + [(n, s) for s in args.snrs for n in args.noises]
    for index, clip in enumerate(clips):
        clean_flags = speech_flags(vad, clip["audio"])
        last_speech_ms = int(LEAD_S * 1000) + int(np.flatnonzero(clean_flags)[-1] + 1) * FRAME_MS
        for noise, snr in conditions:
            rng = random.Random(f"{clip['name']}/{noise}/{snr}")
            if noise == "clean":
                audio = np.concatenate([np.zeros(int(LEAD_S * RATE), np.float32), clip["audio"], np.zeros(int(TAIL_S * RATE), np.float32)])
            else:
                audio = mix(clip["audio"], clean_flags, noises[noise], snr, rng)
            for name, provider in found.items():
                if (clip["name"], noise, snr, name) in done:
                    continue
                processed, spent = suppress(provider, audio)
                flags = speech_flags(vad, processed)
                row: dict[str, Any] = {
                    "clip": clip["name"], "noise": noise, "snr": snr, "denoise": name,
                    "seconds": round(len(audio) / RATE, 2), "chars": len(normalize(clip["text"])),
                    "denoise_s": round(spent, 3), **vad_stats(flags, clean_flags),
                    **await turn(turns, processed, flags, last_speech_ms),
                }
                if small is not None:
                    text = await live_text(small, gate(processed, flags))
                    row |= {"small_text": text, "small_cer": round(cer(clip["text"], text), 4)}
                if large is not None and index < args.large_clips and (snr is None or snr in args.large_snrs):
                    text = await batch_text(large, processed, folder)
                    row |= {"large_text": text, "large_cer": round(cer(clip["text"], text), 4)}
                rows.append(row)
                print(f"{clip['name']} {noise} {snr} {name}: small {row.get('small_cer')} large {row.get('large_cer')} "
                      f"vad false {row['false_s_per_min']}/min recall {row['recall']} closed {row['closed']}", flush=True)
                if args.json:
                    args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def report(rows: list[dict[str, Any]]) -> None:
    names = list(dict.fromkeys(r["denoise"] for r in rows))
    snrs = list(dict.fromkeys(r["snr"] for r in rows))

    def pooled(sel: list[dict[str, Any]], key: str) -> str:
        sel = [r for r in sel if key in r]
        chars = sum(r["chars"] for r in sel)
        return f"{100 * sum(r[key] * r['chars'] for r in sel) / chars:.1f}%" if chars else "-"

    for model in ("small_cer", "large_cer"):
        if not any(model in r for r in rows):
            continue
        print(f"\n{model} (edits / characters; noise types pooled)")
        print("| 억제 | " + " | ".join("깨끗" if s is None else f"{s}dB" for s in snrs) + " |")
        print("| --- |" + " ---: |" * len(snrs))
        for name in names:
            print(f"| {name} | " + " | ".join(pooled([r for r in rows if r["denoise"] == name and r["snr"] == s], model) for s in snrs) + " |")
        noises = [n for n in dict.fromkeys(r["noise"] for r in rows) if n != "clean"]
        print(f"\n{model} by noise (SNRs pooled)")
        print("| 억제 | " + " | ".join(noises) + " |")
        print("| --- |" + " ---: |" * len(noises))
        for name in names:
            print(f"| {name} | " + " | ".join(pooled([r for r in rows if r["denoise"] == name and r["noise"] == n], model) for n in noises) + " |")
    print("\nVAD and Smart Turn (all noisy mixtures)")
    print("| 억제 | 잡음을 말로 봄 (초/분) | 말소리 유지 | 답변 닫힘 | 닫힐 때까지 평균 | 조기 끊김 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name in names:
        sel = [r for r in rows if r["denoise"] == name and r["noise"] != "clean"]
        closed = [r for r in sel if r["closed"]]
        mean_close = sum(r["close_ms"] for r in closed) / len(closed) / 1000 if closed else float("nan")
        print(
            f"| {name} | {np.mean([r['false_s_per_min'] for r in sel]):.1f} | {100 * np.mean([r['recall'] for r in sel]):.1f}% "
            f"| {len(closed)}/{len(sel)} | {mean_close:.2f}초 | {sum(r['early_ends'] for r in sel)} |"
        )


def cpu(args: argparse.Namespace) -> None:
    noises = load_noises(args.noise)
    speech = floats(decode_pcm16(SAMPLES_DIR / "answer-pauses.wav"))
    clean = np.resize(speech, 60 * RATE)
    flags = speech_flags(SileroVAD(), clean)
    audio = mix(clean, flags, noises["fan"], 10, random.Random(0))[: 60 * RATE]
    found = suppressors(args.denoise, args.weights)
    print("| 억제 | 지연 | 처리 시간 (음성 1초당) |")
    print("| --- | ---: | ---: |")
    for name, provider in found.items():
        if not provider.enabled:
            continue
        suppress(provider, audio[: 2 * RATE])  # load
        times = [suppress(provider, audio)[1] for _ in range(3)]
        print(f"| {name} | {provider.stream().delay_samples / 16:.0f}ms | {min(times) / 60 * 1000:.0f}ms (3회 중 최소) |")
    dfn = DeepFilterNet(weights_dir=args.weights)
    session = dfn._load()
    whole = Downsampler().process(enhance(session, Upsampler().process(audio)))[80:]
    print("\n| DeepFilterNet 앞 문맥 | 전체 한 번 처리와의 차이 (SNR) | 처리 시간 (음성 1초당) |")
    print("| ---: | ---: | ---: |")
    for context in (0, 100, 200, 300, 500, 1000):
        provider = DeepFilterNet(weights_dir=args.weights, context_ms=context)
        out, spent = suppress(provider, audio)
        a, b = out[RATE : len(whole)], whole[RATE : len(out)]
        n = min(len(a), len(b))
        diff = 10 * math.log10(float((b[:n] ** 2).sum()) / float(((a[:n] - b[:n]) ** 2).sum()))
        print(f"| {context}ms | {diff:.1f}dB | {spent / 60 * 1000:.0f}ms |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-noise", type=Path)
    parser.add_argument("--noise", type=Path)
    parser.add_argument("--fleurs", type=Path)
    parser.add_argument("--clips", type=int, default=12)
    parser.add_argument("--noises", nargs="+", default=list(NOISES))
    parser.add_argument("--snrs", nargs="+", type=float, default=[20, 10, 5])
    parser.add_argument("--denoise", nargs="+", default=["off", "rnnoise", "deepfilternet"])
    parser.add_argument("--models", nargs="+", default=["small", "large-v3"])
    parser.add_argument("--large-clips", type=int, default=6)
    parser.add_argument("--large-snrs", nargs="+", type=float, default=[10, 5])
    parser.add_argument("--weights", type=Path, default=Path("weights"))
    parser.add_argument("--threads", type=int, default=0, help="Whisper CPU threads (0: the provider's own choice)")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--resume", action="store_true", help="skip rows already in --json")
    parser.add_argument("--report", action="store_true", help="only print the tables of --json")
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    if args.fetch_noise:
        fetch_noise(args.fetch_noise)
        return
    if args.report:
        report(json.loads(args.json.read_text(encoding="utf-8")))
        return
    if args.cpu:
        cpu(args)
        return
    report(asyncio.run(run(args)))


if __name__ == "__main__":
    sys.exit(main())
