"""Files end to end: extract -> de-identify -> leak check, and the review report.

Completion criterion: the 17 text resumes leak nothing (file names and properties included),
the 3 scanned ones are held as needing OCR, no network.
"""

import importlib.util
import re
import shutil
import sys

import pytest

from interview_assistant.deid import InMemoryTokenStore, KnownIdentity
from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.detectors import PatternRule, RegexDetector
from interview_assistant.deid.documents import OcrRequired, deidentify_document
from interview_assistant.deid.leaks import (
    CHECKED,
    OCR_HOLD,
    check_document,
    load_document_samples,
    run_document_leak_check,
)
from interview_assistant.deid.review import render_review_report
from interview_assistant.documents import (
    BlockKind,
    ExtractedDocument,
    TextBlock,
    extract_document,
    normalize_text,
)
from interview_assistant.models import DeidCategory

from .conftest import ROOT

MANIFEST = ROOT / "tests" / "fixtures" / "resumes" / "manifest.yaml"


@pytest.fixture(scope="module")
def samples():
    return load_document_samples(MANIFEST)


@pytest.fixture(scope="module")
def reports(samples, deid_config):
    return {r.sample.id: r for r in run_document_leak_check(samples, deid_config)}


def test_seventeen_text_resumes_zero_leaks(samples, deid_config, no_network):
    reports = run_document_leak_check(samples, deid_config)
    checked = [r for r in reports if r.status == CHECKED]
    failures = {
        r.sample.id: (r.problems, r.leaks, r.residual, r.lost, r.not_in_source, r.missing)
        for r in reports
        if not r.ok
    }
    assert failures == {}
    assert len(checked) == 17
    assert sum(r.leaked_values for r in checked) == 0
    assert sum(len(r.sample.expected) for r in checked) >= 200
    where = {w for r in checked for e in r.sample.expected for w in e.where}
    assert {"filename", "metadata", "header", "footer", "notes", "comment", "link", "hidden"} <= where


def test_scanned_resumes_are_held_not_checked(reports):
    held = {i for i, r in reports.items() if r.status == OCR_HOLD}
    assert held == {"R18", "R19", "R20"}
    for i in held:
        assert reports[i].ok and reports[i].deidentified is None


def test_checker_sees_every_block_when_nothing_is_replaced(samples, deid_config):
    """Negative control: with no detectors every ground-truth value leaks, including the ones
    that sit only in the file name, the properties, link targets or hidden text."""
    deid = Deidentifier([], InMemoryTokenStore(deid_config.token_formats()))

    def enroll(pseudonym, identity):
        return pseudonym, identity

    labels = set()
    for sample in samples:
        if sample.scanned:
            continue
        report = check_document(sample, deid, enroll)
        assert {e for e, _ in report.leaks} == set(sample.expected), sample.id
        labels |= {label for _, label in report.leaks}
    assert {"파일명", "작성자", "링크", "1쪽 숨은 텍스트", "머리글 1", "슬라이드 1 노트"} <= labels


def test_one_token_per_value_across_blocks(reports):
    """The applicant's phone number and e-mail address are written in many ways and places, yet
    get one token each; a referee's (R04, R09, R14) gets its own."""
    for i, r in reports.items():
        if r.status != CHECKED:
            continue
        text = r.deidentified.text
        expected = r.sample.expected
        # Last ten digits: "+82 (0)10 ...", "+82-10-..." and "010-..." are the same number.
        phones = {
            re.sub(r"\D", "", normalize_text(e.value))[-10:]
            for e in expected
            if e.category is DeidCategory.phone
        }
        emails = {e.value.lower() for e in expected if e.category is DeidCategory.email}
        assert len(set(re.findall(r"\[전화-\d+\]", text))) == len(phones), i
        assert len(set(re.findall(r"\[이메일-\d+\]", text))) == len(emails), i


def test_replacements_are_relative_to_each_block(reports):
    for r in reports.values():
        if r.status != CHECKED:
            continue
        for raw, deid in zip(r.document.blocks, r.deidentified.blocks, strict=True):
            out, pos = [], 0
            for x in deid.replacements:
                assert 0 <= x.start < x.end <= len(raw.text)
                out += [raw.text[pos : x.start], x.token]
                pos = x.end
            assert "".join(out) + raw.text[pos:] == deid.text


def _doc(*texts):
    blocks = tuple(TextBlock(BlockKind.body, f"b{i}", t) for i, t in enumerate(texts))
    return ExtractedDocument(filename="x", format="pdf", blocks=blocks)


def test_names_titled_in_one_block_are_caught_in_another(deid_config):
    from interview_assistant.deid import build_deidentifier

    deid = build_deidentifier(deid_config, InMemoryTokenStore(deid_config.token_formats()))
    result = deidentify_document(deid, _doc("추천인: 오태호 팀장님", "태호 님께도 감사드립니다"), candidate_id="c")
    assert [b.text for b in result.blocks] == ["추천인: [인물-1] 팀장님", "[인물-1] 님께도 감사드립니다"]


def test_a_span_across_blocks_falls_back_to_one_block_at_a_time(deid_config):
    crossing = RegexDetector("crossing", 9, [PatternRule(DeidCategory.person, re.compile(r"끝\s+\S\s+시작"))])
    deid = Deidentifier([crossing], InMemoryTokenStore(deid_config.token_formats()))
    result = deidentify_document(deid, _doc("이것이 끝", "시작입니다"), candidate_id="c")
    assert [b.text for b in result.blocks] == ["이것이 끝", "시작입니다"]


def test_documents_needing_ocr_are_refused(samples, deid_config):
    scan = next(s for s in samples if s.id == "R20")
    document = extract_document(scan.path.read_bytes(), scan.upload_name)
    deid = Deidentifier([], InMemoryTokenStore(deid_config.token_formats()))
    with pytest.raises(OcrRequired) as exc:
        deidentify_document(deid, document, candidate_id="c", known=KnownIdentity(name="금태민"))
    assert exc.value.pages == [2]


def test_review_report(reports, deid_config):
    html = render_review_report(list(reports.values()), token_pattern=deid_config.token_formats().pattern())
    assert all(f'id="R{n:02d}"' in html for n in range(1, 21))
    assert html.count('type="radio"') == 40
    assert html.count("OCR 필요 · 처리 보류") == 3
    assert '<mark class="tok">[지원자]</mark>' in html
    assert '<mark class="src"' in html and "권하린" in html  # raw text side by side
    assert "버린 이미지" in html and "문서 속성" in html and "숨은 텍스트" in html
    assert "누출 0개" in html
    assert not re.search(r"<(?:script|img|link|iframe)[^>]+(?:src|href)=", html)  # nothing external


def _load_script(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def test_script_documents_mode(tmp_path, capsys, no_network):
    report = tmp_path / "review.html"
    assert _load_script("check_leaks.py").main(["--documents", "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "documents checked 17, failed 0" in out and "leaked 0" in out
    assert "ocr hold 3, misclassified 0" in out
    assert "권하린" not in out and "harin.kwon" not in out  # names and file names stay masked
    assert report.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_generator_reproduces_the_committed_fixtures(tmp_path):
    """The manifest is written from what the generator placed; regenerating must not drift."""
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    generator = _load_script("make_resume_fixtures.py")
    try:
        font = generator.find_font(None)
    except SystemExit:
        pytest.skip("no Korean TrueType font on this machine (set IA_FIXTURE_FONT)")
    assert generator.main(["--font", str(font), "--out", str(tmp_path)]) == 0
    committed = MANIFEST.parent
    assert (tmp_path / "manifest.yaml").read_text(encoding="utf-8") == (committed / "manifest.yaml").read_text(
        encoding="utf-8"
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(p.name for p in committed.iterdir())
    for name in ("육지안_이력서.html", "jegal_yunho_resume.html", "이력서-마수빈.html", "하예린 이력서.htm"):
        assert (tmp_path / name).read_bytes() == (committed / name).read_bytes()
    shutil.rmtree(tmp_path, ignore_errors=True)
