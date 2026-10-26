"""Measure local Whisper (faster-whisper, CPU int8) on this machine: load time, processing time per
clip, speed against real time, memory, and character error rate against reference transcripts.

    uv run python scripts/bench_whisper.py --manifest clips.json --sizes small medium large-v3

`clips.json` is a list of {"file": "a.wav", "text": "정답 전사"} (paths relative to the manifest).
Models must already be downloaded (admin > 모델 설정, or IA_WEIGHTS_DIR). Each model runs in its own
process so the memory figure is that model's alone. Per clip and model it times batch decoding
(beam 5, VAD on: the stt.batch path) and greedy decoding (beam 1), after one warm-up run, then
streams the clip at the speed of speech like a microphone (`stream`, beam 1: the stt.streaming
path) and measures how long after each utterance ends its final transcript arrives. Output: a
Markdown table (stdout) and the raw numbers (--json).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def peak_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # a 64-bit pseudo handle
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise OSError(ctypes.get_last_error())
        return int(counters.PeakWorkingSetSize)
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def run_one(size: str, clips: list[dict], weights_dir: Path, threads: int) -> dict:
    """Runs inside the child process."""
    import numpy as np

    from interview_assistant.ai_models.probe import cer
    from interview_assistant.providers.audio import decode_pcm16
    from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT

    audio = {}
    for clip in clips:
        pcm = decode_pcm16(Path(clip["file"]))
        audio[clip["file"]] = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    baseline = peak_memory_bytes()
    stt = FasterWhisperSTT(model=size, weights_dir=weights_dir, cpu_threads=threads, beam_size=1)
    started = time.perf_counter()
    stt._load()
    load_s = time.perf_counter() - started
    loaded = peak_memory_bytes()
    asyncio.run(stt.warm_up())  # also times one call, as the server does
    first = audio[clips[0]["file"]]
    stt._decode(first[: 16000 * 5], beam_size=1, vad=False)  # warm-up

    rows = []
    for clip in clips:
        samples = audio[clip["file"]]
        seconds = len(samples) / 16000
        row = {"file": Path(clip["file"]).name, "seconds": round(seconds, 2)}
        for label, beam, vad in (("batch", 5, True), ("greedy", 1, False)):
            t = time.perf_counter()
            text = " ".join(s.text.strip() for s in stt._decode(samples, beam_size=beam, vad=vad))
            elapsed = time.perf_counter() - t
            row[label] = {
                "elapsed_s": round(elapsed, 2),
                "rtf": round(elapsed / seconds, 3),
                "cer": round(cer(clip["text"], text), 4),
                "text": text,
            }
        row["stream"] = asyncio.run(_stream(stt, decode_pcm16(Path(clip["file"])), clip["text"]))
        rows.append(row)
    return {
        "size": size,
        "threads": threads,
        "load_s": round(load_s, 2),
        "memory_model_mb": round((loaded - baseline) / 2**20),
        "memory_peak_mb": round(peak_memory_bytes() / 2**20),
        "clips": rows,
    }


async def _stream(stt, pcm: bytes, reference: str) -> dict:
    from interview_assistant.ai_models.probe import cer
    from interview_assistant.providers.audio import pcm_chunks

    started = time.perf_counter()
    lags, finals, partials = [], [], 0
    async for segment in stt.stream(pcm_chunks(pcm, realtime=True)):
        if segment.is_final:
            finals.append(segment.text)
            lags.append(time.perf_counter() - started - segment.end_ms / 1000)
        else:
            partials += 1
    return {
        "final_lag_s": [round(x, 2) for x in lags],
        "partials": partials,
        "cer": round(cer(reference, " ".join(finals)), 4),
    }


def table(results: list[dict]) -> str:
    lines = [
        "| 모델 | 로드(초) | 메모리(모델/최대 MB) | 사후 beam5: 처리 시간 / 실시간 대비 | CER | greedy: 처리 시간 / 실시간 대비 | CER | 스트리밍: 확정 지연 평균/최대(초) | CER |",
        "| --- | ---: | ---: | --- | ---: | --- | ---: | --- | ---: |",
    ]
    for r in results:
        audio = sum(c["seconds"] for c in r["clips"])

        def total(label: str) -> tuple[float, float]:
            elapsed = sum(c[label]["elapsed_s"] for c in r["clips"])
            ref = [c[label]["cer"] * 1 for c in r["clips"]]
            return elapsed, sum(ref) / len(ref)

        b, b_cer = total("batch")
        g, g_cer = total("greedy")
        lags = [x for c in r["clips"] for x in c["stream"]["final_lag_s"]]
        s_cer = sum(c["stream"]["cer"] for c in r["clips"]) / len(r["clips"])
        lag = f"{sum(lags) / len(lags):.1f} / {max(lags):.1f}" if lags else "–"
        lines.append(
            f"| {r['size']} | {r['load_s']} | {r['memory_model_mb']} / {r['memory_peak_mb']} | "
            f"{b:.1f}초 / {audio / b:.2f}배 | {b_cer:.1%} | {g:.1f}초 / {audio / g:.2f}배 | {g_cer:.1%} | "
            f"{lag} | {s_cer:.1%} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--sizes", nargs="+", default=["small", "medium", "large-v3-turbo", "large-v3"]
    )
    parser.add_argument(
        "--weights-dir", type=Path, default=Path(os.environ.get("IA_WEIGHTS_DIR", "weights"))
    )
    parser.add_argument("--threads", type=int, default=0, help="0: the provider's automatic choice")
    parser.add_argument("--json", type=Path, help="write raw results here")
    parser.add_argument("--one", help=argparse.SUPPRESS)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")  # child output is read as UTF-8 (Windows: cp949)
    clips = json.loads(args.manifest.read_text(encoding="utf-8"))
    for clip in clips:
        clip["file"] = str((args.manifest.parent / clip["file"]).resolve())
    if args.one:
        print(
            json.dumps(run_one(args.one, clips, args.weights_dir, args.threads), ensure_ascii=False)
        )
        return

    results = []
    for size in args.sizes:
        print(f"... {size}", file=sys.stderr, flush=True)
        child = subprocess.run(
            [
                sys.executable,
                __file__,
                "--manifest",
                str(args.manifest),
                "--weights-dir",
                str(args.weights_dir),
                "--threads",
                str(args.threads),
                "--one",
                size,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if child.returncode != 0:
            print(f"{size} failed:\n{child.stderr[-2000:]}", file=sys.stderr)
            continue
        results.append(json.loads(child.stdout.strip().splitlines()[-1]))
    audio = sum(c["seconds"] for c in results[0]["clips"]) if results else 0
    print(
        f"클립 {len(clips)}개, 합계 {audio:.1f}초. 실시간 대비 = 음성 길이 / 처리 시간 (1보다 크면 실시간보다 빠름).\n"
    )
    print(table(results))
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
