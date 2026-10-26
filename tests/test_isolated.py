"""Engines in worker processes (providers/isolated.py): calls, errors, crashes, hangs, shutdown."""

from __future__ import annotations

import gc
import os
import sys
import time

import pytest

from interview_assistant.providers.base import ProviderUnavailable
from interview_assistant.providers.isolated import WorkerProcess

from .conftest import ROOT

ENGINE = "tests.isolated_engines:Echo"


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))  # the child imports tests.isolated_engines
    w = WorkerProcess(ENGINE, {"greeting": "안녕"}, label="테스트 엔진", timeout=60)
    yield w
    w.close()


def test_calls_run_in_another_process_even_when_the_engine_prints(worker):
    assert worker.call("echo", {"쪽": [1, 2]}) == ("안녕", {"쪽": [1, 2]})
    assert worker.call("pid") not in (None, os.getpid())
    assert worker.call("echo", b"\x00" * 3_000_000)[1] == b"\x00" * 3_000_000  # page-sized message
    assert "tests.isolated_engines" not in sys.modules  # the engine was never imported here


def test_engine_errors_are_raised_in_the_caller_and_the_worker_lives_on(worker):
    pid = worker.call("pid")
    with pytest.raises(ProviderUnavailable, match="엔진을 쓸 수 없습니다"):
        worker.call("fail")
    with pytest.raises(RuntimeError, match="_Unpicklable: 1/2"):
        worker.call("odd")
    assert worker.call("pid") == pid


def test_a_crashed_worker_is_reported_and_started_again(worker):
    pid = worker.call("pid")
    with pytest.raises(ProviderUnavailable, match="테스트 엔진: 작업 프로세스가 끝났습니다"):
        worker.call("crash")
    assert worker.pid is None
    assert worker.call("pid") != pid
    assert worker.call("echo", 1) == ("안녕", 1)


def test_a_hung_worker_is_stopped_after_the_timeout(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    w = WorkerProcess(ENGINE, {}, label="테스트 엔진", timeout=3)
    w.call("pid")  # started
    started = time.perf_counter()
    with pytest.raises(ProviderUnavailable, match="3초 안에 끝나지 않아"):
        w.call("sleep", 60)
    assert time.perf_counter() - started < 30
    assert w.call("sleep", 0) == 0  # a fresh worker
    w.close()


def test_a_target_that_cannot_be_built_fails_the_call(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    w = WorkerProcess("tests.isolated_engines:Missing", {}, label="테스트 엔진")
    with pytest.raises(AttributeError, match="Missing"):
        w.call("pid")
    assert w.pid is None


def test_the_worker_stops_when_dropped(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    w = WorkerProcess(ENGINE, {}, label="테스트 엔진")
    w.call("pid")
    proc = w._proc
    assert proc is not None and proc.poll() is None
    del w  # as when the model manager evicts a provider
    gc.collect()
    assert proc.wait(timeout=15) == 0  # stdin closed: the child exits on its own
