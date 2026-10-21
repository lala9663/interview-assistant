"""De-identification leak check: run every sample through the de-identifier and report leaks.

    uv run python scripts/check_leaks.py
    uv run python scripts/check_leaks.py --samples path/to/samples.yaml --show-output

A sample fails when any value from its ground-truth list (or anything still shaped like a phone
number, e-mail or 주민번호) remains after de-identification, or when a `keep` phrase (ordinary
words next to identifiers) was swallowed by a replacement. Values are masked in the report
unless --show-values is given, so the script is safe to run on real samples. Exit code 1 when any
sample fails. Runs fully offline: in-memory SQLite and a throwaway encryption key.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from interview_assistant.deid.config import load_deid_config
from interview_assistant.deid.leaks import SampleReport, load_samples, mask, run_leak_check

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, default=ROOT / "tests/fixtures/deid_samples.yaml")
    parser.add_argument("--config", type=Path, default=ROOT / "config/deid.yaml")
    parser.add_argument("--show-output", action="store_true", help="print de-identified text")
    parser.add_argument("--show-values", action="store_true", help="do not mask leaked values")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    samples = load_samples(args.samples)
    reports = run_leak_check(samples, load_deid_config(args.config))
    show = (lambda v: v) if args.show_values else mask

    for report in reports:
        _print_report(report, show, args.show_output)

    failed = [r for r in reports if not r.ok]
    leaked_values = sum(len(r.leaks) + len(r.residual) for r in reports)
    total_expected = sum(r.expected for r in reports)
    print()
    print(
        f"samples {len(reports)}, failed {len(failed)}, "
        f"ground-truth values {total_expected}, leaked {leaked_values}"
    )
    return 1 if failed else 0


def _print_report(report: SampleReport, show, show_output: bool) -> None:
    status = "OK  " if report.ok else "FAIL"
    print(
        f"[{status}] {report.sample_id} ({report.kind}) "
        f"expected {report.expected}, replaced {report.replaced}, "
        f"leaks {len(report.leaks)}, residual {len(report.residual)}, lost {len(report.lost)}"
    )
    for e in report.leaks:
        print(f"    leak      {e.category.value:<10} {show(e.value)}")
    for kind, surface in report.residual:
        print(f"    residual  {kind:<10} {show(surface)}")
    for phrase in report.lost:
        print(f"    lost      {phrase}")
    for value in report.not_in_source:
        print(f"    fixture   {show(value)} not found in source text")
    if show_output:
        print(f"    output    {report.output}")


if __name__ == "__main__":
    sys.exit(main())
