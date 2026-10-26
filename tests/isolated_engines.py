"""Engines for tests/test_isolated.py. Imported only inside worker processes, never by the tests."""

from __future__ import annotations

import os
import time

from interview_assistant.providers.base import ProviderUnavailable


class _Unpicklable(Exception):
    def __init__(self, a: int, b: int) -> None:  # two required args: unpickling it fails
        super().__init__(f"{a}/{b}")


class Echo:
    def __init__(self, greeting: str = "안녕") -> None:
        print("engine starting", flush=True)  # a chatty engine must not break the protocol
        self.greeting = greeting

    def echo(self, value: object) -> tuple[str, object]:
        print("python noise", flush=True)
        os.write(1, b"native noise\n")  # what C code writing to fd 1 would do
        return self.greeting, value

    def pid(self) -> int:
        return os.getpid()

    def fail(self) -> None:
        raise ProviderUnavailable("엔진을 쓸 수 없습니다")

    def odd(self) -> None:
        raise _Unpicklable(1, 2)

    def crash(self) -> None:
        os._exit(3)

    def sleep(self, seconds: float) -> float:
        time.sleep(seconds)
        return seconds
