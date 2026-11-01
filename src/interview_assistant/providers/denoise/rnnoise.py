"""RNNoise (Xiph, BSD-3-Clause): a small recurrent network that turns down noise between and under
speech, 10 ms frames of 48 kHz audio.

The library is the one built into pyrnnoise's wheels (Apache-2.0; xiph/rnnoise commit 70f1d25 of
2025-02-22, after v0.2, the model compiled in). Only that file is loaded, with ctypes: pyrnnoise's
own Python module imports plotting and file-reading packages this project leaves out
(pyproject.toml). Like the Silero file inside faster-whisper, its size and sha256 are pinned per
platform and checked when it loads; a different build refuses to load until the pin is reviewed.
Nothing is downloaded.

The microphone's 16 kHz goes up to 48 kHz and back (`resample.At48k`). RNNoise's output lags its
input by two frames (20 ms, measured); with a frame of waiting and the filters the stream is about
35 ms late, and costs 0.05-0.22 s of CPU per second of audio on this laptop (docs/audio-input.md 7장).
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np

from interview_assistant.providers.base import DenoiseProvider, ProviderUnavailable
from interview_assistant.providers.denoise.resample import At48k, mix_dry

FRAME = 480  # 10 ms at 48 kHz
INNER_DELAY = 2 * FRAME
# The native library in pyrnnoise 0.4.5's wheels: file -> (size, sha256).
LIBRARIES: dict[str, tuple[int, str]] = {
    "rnnoise.dll": (14825472, "06770aeb8855ef942b5dcdb436f84dfdd5867b716ba4b4c8a2c66ade03197f31"),  # win_amd64
    "librnnoise.so": (14840960, "de5120abce147a72ba343296744ae7cc0a97298e19307c7d3f01cce8c34b18ff"),  # manylinux x86_64
}
_FLOAT_P = ctypes.POINTER(ctypes.c_float)


def library_path() -> Path | None:
    """Where pyrnnoise keeps its library, found without importing pyrnnoise."""
    try:
        spec = importlib.util.find_spec("pyrnnoise")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    name = "rnnoise.dll" if sys.platform == "win32" else "librnnoise.dylib" if sys.platform == "darwin" else "librnnoise.so"
    return Path(list(spec.submodule_search_locations)[0]) / name


def _check_file(path: Path | None) -> Path:
    if path is None:
        raise ProviderUnavailable("RNNoise에는 pyrnnoise가 필요합니다 (uv sync --extra denoise).")
    if not path.is_file():
        raise ProviderUnavailable(f"RNNoise 라이브러리 파일이 없습니다: {path}")
    pinned = LIBRARIES.get(path.name)
    if pinned is None:
        raise ProviderUnavailable(f"이 플랫폼의 RNNoise 라이브러리({path.name})는 검토하지 않았습니다.")
    size, sha256 = pinned
    if path.stat().st_size != size or hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        raise ProviderUnavailable("RNNoise 라이브러리가 검토한 것과 다릅니다 (pyrnnoise 버전 확인).")
    return path


def _open(path: Path) -> Any:
    lib = ctypes.CDLL(str(path))
    lib.rnnoise_create.argtypes = [ctypes.c_void_p]
    lib.rnnoise_create.restype = ctypes.c_void_p
    lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
    lib.rnnoise_destroy.restype = None
    lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p, _FLOAT_P, _FLOAT_P]
    lib.rnnoise_process_frame.restype = ctypes.c_float
    lib.rnnoise_get_frame_size.restype = ctypes.c_int
    if lib.rnnoise_get_frame_size() != FRAME:
        raise ProviderUnavailable("RNNoise 라이브러리의 프레임 크기가 480이 아닙니다.")
    return lib


class RNNoiseStream(At48k):
    block = FRAME
    holdback = FRAME - 1
    inner_delay = INNER_DELAY

    def __init__(self, lib: Any, atten_lim_db: float) -> None:
        super().__init__()
        self._lib = lib
        self._state = lib.rnnoise_create(None)
        self._limit = atten_lim_db
        self._dry = np.zeros(INNER_DELAY, dtype=np.float32)  # the input, as late as the output

    def _run(self, x: np.ndarray) -> np.ndarray:
        frames = np.ascontiguousarray(x * 32768.0, dtype=np.float32).reshape(-1, FRAME)
        out = np.empty_like(frames)
        for inp, res in zip(frames, out, strict=True):
            self._lib.rnnoise_process_frame(self._state, res.ctypes.data_as(_FLOAT_P), inp.ctypes.data_as(_FLOAT_P))
        enhanced = out.reshape(-1) / 32768.0
        if self._limit <= 0:
            return enhanced
        dry = np.concatenate([self._dry, x])
        self._dry = dry[len(x) :]
        return mix_dry(enhanced, dry[: len(x)], self._limit)

    def __del__(self) -> None:
        state, self._state = getattr(self, "_state", None), None
        if state:
            self._lib.rnnoise_destroy(state)


class RNNoise(DenoiseProvider):
    enabled = True

    def __init__(self, atten_lim_db: float = 0, **_: Any) -> None:
        self.model = "rnnoise-0.2"
        self.atten_lim_db = float(atten_lim_db)
        self._lib: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._lib is None:
                self._lib = _open(_check_file(library_path()))
            return self._lib

    async def warm_up(self) -> None:
        self._load()

    def stream(self) -> RNNoiseStream:
        return RNNoiseStream(self._load(), self.atten_lim_db)
