"""De-identification leak check: run every sample through the de-identifier and report leaks.

    uv run python scripts/check_leaks.py
    uv run python scripts/check_leaks.py --samples path/to/samples.yaml --show-output
    uv run python scripts/check_leaks.py --documents
    uv run python scripts/check_leaks.py --documents --report

Text mode (default): a sample fails when any value from its ground-truth list (or anything still
shaped like a phone number, e-mail or 주민번호) remains after de-identification, or when a `keep`
phrase (ordinary words next to identifiers) was swallowed by a replacement.

Document mode (--documents [MANIFEST]): every file is extracted (PDF, DOCX, PPTX, HTML),
de-identified block by block including its file name and properties, and checked the same way.
It also fails when a planted value was not extracted from where it was planted, when images
were not dropped, or when a scanned file is not classified as needing OCR. Scanned files are
held ("OCR 필요, 처리 보류") and reported apart from the leak count. --report [PATH] also writes
the HTML review report (default reports/deid-review.html), which contains the raw extracted
text: keep it local.

Values and file names are masked in the console unless --show-values is given, so the script is
safe to run on real samples. Exit code 1 when any sample fails. Runs fully offline: in-memory
SQLite and a throwaway encryption key.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from interview_assistant.deid.config import load_deid_config
from interview_assistant.deid.leaks import (
    CHECKED,
    ERROR,
    OCR_HOLD,
    DocumentReport,
    SampleReport,
    load_document_samples,
    load_samples,
    mask,
    run_document_leak_check,
    run_leak_check,
)
from interview_assistant.deid.review import render_review_report
from interview_assistant.documents import BlockKind

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/resumes/manifest.yaml"
REPORT = ROOT / "reports/deid-review.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, default=ROOT / "tests/fixtures/deid_samples.yaml")
    parser.add_argument("--config", type=Path, default=ROOT / "config/deid.yaml")
    parser.add_argument(
        "--documents", type=Path, nargs="?", const=MANIFEST, metavar="MANIFEST",
        help=f"check files listed in a manifest (default {MANIFEST.relative_to(ROOT)})",
    )  # fmt: skip
    parser.add_argument(
        "--report", type=Path, nargs="?", const=REPORT, metavar="PATH",
        help=f"write the HTML review report (default {REPORT.relative_to(ROOT)}); implies --documents",
    )  # fmt: skip
    parser.add_argument("--show-output", action="store_true", help="print de-identified text")
    parser.add_argument("--show-values", action="store_true", help="do not mask leaked values")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    show = (lambda v: v) if args.show_values else mask
    config = load_deid_config(args.config)

    if args.documents is not None or args.report is not None:
        return _documents(args, config, show)

    samples = load_samples(args.samples)
    reports = run_leak_check(samples, config)
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


def _documents(args, config, show) -> int:
    manifest = args.documents or MANIFEST
    reports = run_document_leak_check(load_document_samples(manifest), config)
    for report in reports:
        _print_document(report, show, args.show_output)

    checked = [r for r in reports if r.status == CHECKED]
    held = [r for r in reports if r.status == OCR_HOLD]
    errors = [r for r in reports if r.status == ERROR]
    failed = [r for r in reports if not r.ok]
    print()
    print(
        f"documents checked {len(checked)}, failed {sum(1 for r in checked if not r.ok)}, "
        f"ground-truth values {sum(len(r.sample.expected) for r in checked)}, "
        f"leaked {sum(r.leaked_values for r in checked)}"
    )
    print(
        f"ocr hold {len(held)}, misclassified {sum(1 for r in reports if _misclassified(r))}"
        + (f", errors {len(errors)}" if errors else "")
        + (f": {', '.join(r.sample.id for r in held)}" if held else "")
    )

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        html = render_review_report(
            reports,
            token_pattern=config.token_formats().pattern(),
            source=_display(manifest),
            generated=datetime.now(),
        )
        args.report.write_text(html, encoding="utf-8")
        print(f"review report: {args.report.resolve()} (contains raw text: keep it local)")
    return 1 if failed else 0


def _misclassified(r: DocumentReport) -> bool:
    return any("분류됨" in p or "OCR 필요 쪽" in p for p in r.problems)


def _print_document(report: DocumentReport, show, show_output: bool) -> None:
    s, doc = report.sample, report.document
    name = s.upload_name if show is not mask else _mask_name(s.upload_name)
    if report.status == ERROR:
        print(f"[FAIL] {s.id} {s.format:<4} {name}: {report.error}")
        return
    if report.status == OCR_HOLD:
        tag = "HOLD" if report.ok else "FAIL"
        print(
            f"[{tag}] {s.id} {s.format:<4} OCR 필요 {len(doc.ocr_pages)}/{len(doc.pages)}쪽, "
            f"처리 보류 (텍스트를 만들지 않음)  {name}"
        )
    else:
        status = "OK  " if report.ok else "FAIL"
        print(
            f"[{status}] {s.id} {s.format:<4} blocks {len(doc.blocks)}, expected {len(s.expected)}, "
            f"replaced {report.deidentified.replacements}, images dropped {doc.images_dropped}, "
            f"hidden blocks {len(doc.blocks_of(BlockKind.hidden))}  {name}"
        )
    for problem in report.problems:
        print(f"    problem   {problem}")
    for e, label in report.leaks:
        print(f"    leak      {e.category.value:<10} {show(e.value)}  ({label})")
    for kind, surface, label in report.residual:
        print(f"    residual  {kind:<10} {show(surface)}  ({label})")
    for phrase in report.lost:
        print(f"    lost      {phrase}")
    for value in report.not_in_source:
        print(f"    extract   {show(value)} not found in extracted text")
    for value, kind in report.missing:
        print(f"    extract   {show(value)} not found in a '{kind}' block")
    if show_output and report.deidentified is not None:
        for line in report.deidentified.text.splitlines():
            print(f"    | {line}")


def _mask_name(name: str) -> str:
    """File names usually start with the applicant's name: keep only the extension."""
    stem, dot, ext = name.rpartition(".")
    return f"{'*' * len(stem)}{dot}{ext}" if dot else "*" * len(name)


def _display(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
