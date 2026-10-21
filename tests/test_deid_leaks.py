"""Completion criterion for step 2: 20 synthetic samples, zero leaks, no network."""

import importlib.util

import pytest

from interview_assistant.deid import InMemoryTokenStore
from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.leaks import (
    ExpectedValue,
    Sample,
    check_sample,
    find_leaks,
    load_samples,
    run_leak_check,
)
from interview_assistant.models import DeidCategory

from .conftest import ROOT

SAMPLES = ROOT / "tests" / "fixtures" / "deid_samples.yaml"


@pytest.fixture(scope="module")
def samples():
    return load_samples(SAMPLES)


def test_fixture_set_is_complete(samples):
    assert len(samples) == 20
    assert len({s.id for s in samples}) == 20
    covered = {e.category for s in samples for e in s.expected}
    assert covered == set(DeidCategory)


def test_twenty_samples_zero_leaks(samples, deid_config, no_network):
    reports = run_leak_check(samples, deid_config)
    failures = {
        r.sample_id: (r.leaks, r.residual, r.lost, r.not_in_source) for r in reports if not r.ok
    }
    assert failures == {}
    assert sum(r.expected for r in reports) >= 80


def test_checker_catches_leaks_when_nothing_is_replaced(samples, deid_config):
    """Negative control: with no detectors every ground-truth value must be reported."""
    deid = Deidentifier([], InMemoryTokenStore(deid_config.token_formats()))
    for sample in samples:
        report = check_sample(
            sample, lambda s: (deid.deidentify(s.text, candidate_id=s.id).text, 0)
        )
        assert len(report.leaks) == len(sample.expected), sample.id


@pytest.mark.parametrize(
    "category, value, output",
    [
        (DeidCategory.phone, "010-0123-4567", "번호 010 0123 4567"),
        (DeidCategory.phone, "010-0123-4567", "+82 10.0123.4567"),
        (DeidCategory.phone, "+82 10-0123-4567", "01001234567"),
        (DeidCategory.birthdate, "1995-03-14", "95년 3월 14일"),
        (DeidCategory.birthdate, "1995년 3월 14일", "19950314"),
        (DeidCategory.email, "doyoon.kim@example.com", "DOYOON.KIM@EXAMPLE.COM"),
        (DeidCategory.email, "doyoon.kim@example.com", "아이디는 doyoon.kim"),
        (DeidCategory.candidate, "김도윤", "김 도 윤"),
        (DeidCategory.rrn, "950314-1******", "9503141******"),
    ],
)
def test_leak_patterns_see_through_formatting(category, value, output):
    assert find_leaks(output, [ExpectedValue(category, value)])


def test_fixture_errors_are_reported():
    sample = Sample(
        id="X",
        kind="",
        text="김도윤입니다",
        identity=None,
        expected=(ExpectedValue(DeidCategory.candidate, "박지훈"),),
        keep=("없는 문구",),
    )
    report = check_sample(sample, lambda s: (s.text, 0))
    assert report.not_in_source == ["박지훈", "없는 문구"] and not report.ok


def test_script_reports_success(capsys, no_network):
    path = ROOT / "scripts" / "check_leaks.py"
    spec = importlib.util.spec_from_file_location("check_leaks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([]) == 0
    out = capsys.readouterr().out
    assert "samples 20, failed 0" in out and "leaked 0" in out
    assert "doyoon.kim@example.com" not in out  # values stay masked by default
