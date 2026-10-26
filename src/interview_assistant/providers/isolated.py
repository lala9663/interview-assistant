"""Run a native engine in its own worker process, so its libraries stay out of the server process.

Engines bundle native libraries, and two of ours clash when they share a process. PaddlePaddle
(PaddleOCR) ships Intel OpenMP `libiomp5md.dll` built 2019-01-09; CTranslate2 (faster-whisper)
ships its own, built 2025-09-10. Windows reuses a DLL already loaded under the same name, so once
Paddle is in, `ctranslate2.dll` gets the old OpenMP, which lacks procedures it imports, and fails
with "WinError 127". The other order happens to work, but an admin can turn engines on in any
order. Running Paddle here keeps its DLLs out of the server process altogether.

The child is `python -m interview_assistant.providers.isolated`. It builds the engine from a
"module:Class" path and keyword arguments, then answers method calls one at a time. Messages are
pickled (both ends are this code) and framed by length on the child's stdin and on a copy of its
stdout; stdout itself is pointed at stderr, so whatever the engine prints (Python or native code)
lands in the server log, never in the protocol. An exception in the engine is raised again in the
caller. A crashed or hung child (`timeout`) is killed and started again on the next call. The
child stops when its `WorkerProcess` is dropped or the server exits (stdin closes, it exits).
"""

from __future__ import annotations

import importlib
import os
import pickle
import struct
import subprocess
import sys
import threading
import weakref
from typing import IO, Any

from interview_assistant.providers.base import ProviderUnavailable

_HEADER = struct.Struct(">Q")


def _send(stream: IO[bytes], message: Any) -> None:
    data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(data)))
    stream.write(data)
    stream.flush()


def _receive(stream: IO[bytes]) -> Any:
    header = stream.read(_HEADER.size)
    if len(header) < _HEADER.size:
        raise EOFError("worker closed the pipe")
    (size,) = _HEADER.unpack(header)
    data = stream.read(size)
    if len(data) < size:
        raise EOFError("worker closed the pipe")
    return pickle.loads(data)


def _portable(exc: BaseException) -> BaseException:
    """The exception itself if it survives pickling, else a RuntimeError naming it."""
    try:
        pickle.loads(pickle.dumps(exc))
        return exc
    except Exception:
        return RuntimeError(f"{type(exc).__name__}: {exc}")


def _shutdown(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if proc.stdin:
            proc.stdin.close()  # the child reads EOF and exits
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        proc.wait()


class WorkerProcess:
    """One engine in one child process, started on the first call. Thread-safe: calls run one at a
    time, as the engines need anyway."""

    def __init__(self, target: str, kwargs: dict[str, Any], *, label: str, timeout: float = 600) -> None:
        self.target = target
        self.kwargs = kwargs
        self.label = label
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._finalizer: weakref.finalize | None = None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc and self._proc.poll() is None else None

    def call(self, method: str, *args: Any) -> Any:
        with self._lock:
            proc = self._start() if self._proc is None or self._proc.poll() is not None else self._proc
            status, value = self._exchange(proc, (method, args))
        if status == "error":
            raise value
        return value

    def close(self) -> None:
        with self._lock:
            self._stop()

    def _start(self) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            [sys.executable, "-m", __name__],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self._proc = proc
        self._finalizer = weakref.finalize(self, _shutdown, proc)
        status, value = self._exchange(proc, (self.target, self.kwargs))
        if status == "error":
            self._stop()
            raise value
        return proc

    def _exchange(self, proc: subprocess.Popen[bytes], message: Any) -> tuple[str, Any]:
        assert proc.stdin is not None and proc.stdout is not None
        expired = threading.Event()

        def kill() -> None:
            expired.set()
            proc.kill()

        timer = threading.Timer(self.timeout, kill)
        timer.daemon = True
        timer.start()
        try:
            _send(proc.stdin, message)
            return _receive(proc.stdout)
        except (EOFError, OSError, pickle.UnpicklingError) as exc:
            self._stop()
            why = f"{self.timeout:.0f}초 안에 끝나지 않아 멈췄습니다" if expired.is_set() else "작업 프로세스가 끝났습니다"
            raise ProviderUnavailable(f"{self.label}: {why}. 다음 요청에서 다시 시작합니다.") from exc
        finally:
            timer.cancel()

    def _stop(self) -> None:
        if self._finalizer is not None:
            self._finalizer()  # runs _shutdown once
            self._finalizer = None
        self._proc = None


def main() -> None:
    reader = sys.stdin.buffer
    writer = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())  # engine output goes to stderr, not the pipe
    sys.stdout = sys.stderr
    try:
        target, kwargs = _receive(reader)
        module, _, name = target.partition(":")
        engine = getattr(importlib.import_module(module), name)(**kwargs)
    except Exception as exc:
        _send(writer, ("error", _portable(exc)))
        return
    _send(writer, ("ok", None))
    while True:
        try:
            method, args = _receive(reader)
        except EOFError:
            return
        try:
            value = getattr(engine, method)(*args)
        except Exception as exc:
            _send(writer, ("error", _portable(exc)))
        else:
            _send(writer, ("ok", value))


if __name__ == "__main__":
    main()
