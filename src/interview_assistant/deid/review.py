"""Human review report for the document leak check: one self-contained HTML file.

Per sample: the extracted text next to its de-identified version block by block (file name and
properties first), replaced spans and tokens highlighted, surviving ground-truth values marked,
dropped images and hidden blocks counted, and an OK / 누출 choice with a note. Choices stay in
the browser (localStorage) and can be copied out as TSV or saved as JSON.

The page contains the raw extracted text by design, so it belongs to the raw zone: keep it on
the reviewer's machine (reports/ is git-ignored), never attach or upload it. No external
resources are loaded.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime
from html import escape

from interview_assistant.deid.leaks import CHECKED, ERROR, OCR_HOLD, DocumentReport, leak_pattern
from interview_assistant.documents.types import BlockKind

_KIND_LABELS = {
    BlockKind.filename: "파일명",
    BlockKind.metadata: "문서 속성",
    BlockKind.body: "본문",
    BlockKind.table: "표",
    BlockKind.header: "머리글",
    BlockKind.footer: "바닥글",
    BlockKind.notes: "노트",
    BlockKind.comment: "메모·주석",
    BlockKind.link: "링크",
    BlockKind.hidden: "숨은 텍스트",
}
_CATEGORY_LABELS = {
    "candidate": "지원자",
    "person": "인물",
    "phone": "전화",
    "email": "이메일",
    "birthdate": "생년월일",
    "rrn": "주민번호",
    "address": "주소",
    "school": "학교",
    "company": "회사",
}
_WHERE_LABELS = {k.value: v for k, v in _KIND_LABELS.items()} | {"image": "이미지 속 글자"}


def render_review_report(
    reports: Sequence[DocumentReport],
    *,
    token_pattern: re.Pattern[str],
    source: str = "",
    generated: datetime | None = None,
) -> str:
    generated = generated or datetime.now()
    checked = [r for r in reports if r.status == CHECKED]
    held = [r for r in reports if r.status == OCR_HOLD]
    errors = [r for r in reports if r.status == ERROR]
    leaked = sum(r.leaked_values for r in checked)
    expected = sum(len(r.sample.expected) for r in checked)
    held_ok = sum(1 for r in held if r.ok)
    sections = "\n".join(_section(r, token_pattern) for r in reports)
    nav = "".join(
        f'<a class="chip {_status_class(r)}" href="#{escape(r.sample.id)}">{escape(r.sample.id)}</a>'
        for r in reports
    )
    fingerprint = hashlib.sha256(
        "\n".join(
            f"{r.sample.id}:{r.status}:{r.deidentified.text if r.deidentified else ''}"
            for r in reports
        ).encode("utf-8")
    ).hexdigest()[:16]
    ids = json.dumps([r.sample.id for r in reports])
    summary = (
        f"텍스트형 {len(checked)}건 자동 검사: 실패 {sum(1 for r in checked if not r.ok)}건, "
        f"정답 값 {expected}개 중 누출 {leaked}개 · "
        f"OCR 필요·처리 보류 {len(held)}건 (분류 정확 {held_ok}/{len(held)})"
        + (f" · 오류 {len(errors)}건" if errors else "")
    )
    return _PAGE.format(
        css=_CSS,
        js=_JS.replace("__FINGERPRINT__", fingerprint).replace("__IDS__", ids),
        generated=escape(generated.strftime("%Y-%m-%d %H:%M")),
        source=escape(source),
        summary=escape(summary),
        nav=nav,
        sections=sections,
        total=len(reports),
    )


def _status_class(r: DocumentReport) -> str:
    if r.status == OCR_HOLD:
        return "hold" if r.ok else "bad"
    return "good" if r.ok else "bad"


def _badge(r: DocumentReport) -> str:
    if r.status == ERROR:
        return '<span class="badge bad">오류</span>'
    if r.status == OCR_HOLD:
        cls = "hold" if r.ok else "bad"
        text = "OCR 필요 · 처리 보류" if r.ok else "OCR 분류 틀림"
        return f'<span class="badge {cls}">{text}</span>'
    if r.ok:
        return '<span class="badge good">자동 검사 OK</span>'
    return f'<span class="badge bad">자동 검사 실패 · 누출 {r.leaked_values}</span>'


def _section(r: DocumentReport, tokens: re.Pattern[str]) -> str:
    s = r.sample
    doc = r.document
    fmt = f"{s.format.upper()}{' (스캔)' if s.scanned else ''}"
    facts = []
    if doc is not None:
        if doc.format in ("pdf", "pptx"):
            facts.append(f"{'슬라이드' if doc.format == 'pptx' else '쪽'} {len(doc.pages)}")
        facts.append(f"버린 이미지 {doc.images_dropped}개")
        facts.append(f"숨은 텍스트 블록 {len(doc.blocks_of(BlockKind.hidden))}개")
        if doc.needs_ocr:
            facts.append(f"OCR 필요 쪽 {', '.join(map(str, doc.ocr_pages))}")
    if r.deidentified is not None:
        facts.append(f"치환 {r.deidentified.replacements}곳")
    facts.append(f"정답 값 {len(s.expected)}개")
    traps = "".join(f'<span class="trap">{escape(t)}</span>' for t in s.traps)

    notes = []
    if r.error:
        notes.append(f"<li>추출 오류: {escape(r.error)}</li>")
    notes += [f"<li>{escape(p)}</li>" for p in r.problems]
    notes += [
        f"<li>누출: {escape(_CATEGORY_LABELS.get(e.category.value, e.category.value))} "
        f"<code>{escape(e.value)}</code> ({escape(label)})</li>"
        for e, label in r.leaks
    ]
    notes += [f"<li>남은 {escape(k)} 형태: <code>{escape(v)}</code> ({escape(label)})</li>" for k, v, label in r.residual]
    notes += [f"<li>과잉 치환: <code>{escape(k)}</code>가 사라짐</li>" for k in r.lost]
    notes += [f"<li>추출 누락: <code>{escape(v)}</code>가 추출 텍스트에 없음</li>" for v in r.not_in_source]
    notes += [
        f"<li>위치 누락: <code>{escape(v)}</code>가 {escape(_WHERE_LABELS.get(k, k))} 블록에 없음</li>"
        for v, k in r.missing
    ]
    problems = f'<ul class="problems">{"".join(notes)}</ul>' if notes else ""

    if r.status == OCR_HOLD:
        body = (
            '<p class="hold-note">텍스트 레이어가 없는 쪽이 있어 OCR이 필요합니다. 텍스트를 만들지 않았고, '
            "이 문서는 비식별화도 LLM 전송도 하지 않고 보류합니다. 아래는 파일에 실제로 있는 텍스트(파일명·속성·"
            "텍스트 레이어)이며, 정답 목록은 OCR 도입 후 확인할 값입니다.</p>"
            + _raw_table(doc)
        )
        choices = (("ok", "보류 확인"), ("leak", "분류 틀림"))
    elif r.status == CHECKED:
        body = _pair_table(r, tokens)
        choices = (("ok", "OK (누출 없음)"), ("leak", "누출 발견"))
    else:
        body = ""
        choices = (("ok", "확인"), ("leak", "문제 있음"))

    return f"""
<section id="{escape(s.id)}" class="sample" data-id="{escape(s.id)}">
  <header class="sample-head">
    <h2>{escape(s.id)} <span class="fmt">{escape(fmt)}</span> <span class="file">{escape(s.upload_name)}</span></h2>
    {_badge(r)}
  </header>
  <p class="facts">{" · ".join(escape(f) for f in facts)}</p>
  <div class="traps">{traps}</div>
  {problems}
  {body}
  <details class="truth"><summary>정답 목록 ({len(s.expected)}개)</summary>{_truth_table(r)}</details>
  <div class="review">
    <span class="review-label">검수</span>
    <label><input type="radio" name="v-{escape(s.id)}" value="ok"> {choices[0][1]}</label>
    <label><input type="radio" name="v-{escape(s.id)}" value="leak"> {choices[1][1]}</label>
    <textarea name="n-{escape(s.id)}" rows="1" placeholder="메모 (누출 위치, 과잉 치환 등)"></textarea>
  </div>
</section>"""


def _pair_table(r: DocumentReport, tokens: re.Pattern[str]) -> str:
    assert r.document is not None and r.deidentified is not None
    rows = []
    for raw, deid in zip(r.document.blocks, r.deidentified.blocks, strict=True):
        src_spans = [(x.start, x.end, "src", f"{x.category.value} → {x.token}") for x in deid.replacements]
        out_spans = [(m.start(), m.end(), "tok", "") for m in tokens.finditer(deid.text)]
        for e in r.sample.expected:
            out_spans += [(m.start(), m.end(), "leak", "누출") for m in leak_pattern(e).finditer(deid.text)]
        kind = _KIND_LABELS.get(raw.kind, raw.kind.value)
        cls = f"kind-{raw.kind.value}"
        rows.append(
            f'<tr class="{cls}"><th><span class="kind">{escape(kind)}</span>{escape(raw.label)}</th>'
            f"<td><pre>{_highlight(raw.text, src_spans)}</pre></td>"
            f"<td><pre>{_highlight(deid.text, out_spans)}</pre></td></tr>"
        )
    return (
        '<table class="pair"><thead><tr><th>위치</th><th>원본 추출 텍스트</th><th>비식별본 (LLM에 가는 텍스트)</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _raw_table(doc) -> str:
    if doc is None:
        return ""
    rows = "".join(
        f'<tr class="kind-{b.kind.value}"><th><span class="kind">{escape(_KIND_LABELS.get(b.kind, b.kind.value))}</span>'
        f"{escape(b.label)}</th><td><pre>{escape(b.text)}</pre></td></tr>"
        for b in doc.blocks
    )
    return f'<table class="pair single"><thead><tr><th>위치</th><th>파일에 있는 텍스트 (전송 안 함)</th></tr></thead><tbody>{rows}</tbody></table>'


def _truth_table(r: DocumentReport) -> str:
    leaked = {e for e, _ in r.leaks}
    missing = {v for v, _ in r.missing} | set(r.not_in_source)
    rows = []
    for e in r.sample.expected:
        if r.status == OCR_HOLD:
            result = "보류"
        elif e in leaked:
            result = '<b class="bad-text">누출</b>'
        elif e.value in missing:
            result = '<b class="bad-text">추출 누락</b>'
        else:
            result = "치환됨"
        where = ", ".join(_WHERE_LABELS.get(w, w) for w in e.where)
        rows.append(
            f"<tr><td>{escape(_CATEGORY_LABELS.get(e.category.value, e.category.value))}</td>"
            f"<td><code>{escape(e.value)}</code></td><td>{escape(where)}</td><td>{result}</td></tr>"
        )
    keep = ""
    if r.sample.keep:
        keep = '<p class="keep">남아야 하는 표현: ' + ", ".join(f"<code>{escape(k)}</code>" for k in r.sample.keep) + "</p>"
    return (
        '<table class="truth-table"><thead><tr><th>분류</th><th>값</th><th>넣은 곳</th><th>결과</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>{keep}"
    )


def _highlight(text: str, spans: list[tuple[int, int, str, str]]) -> str:
    """Escape `text`, wrapping spans in <mark>. Leak marks win over others; overlaps are dropped."""
    order = {"leak": 0, "src": 1, "tok": 1}
    chosen: list[tuple[int, int, str, str]] = []
    for span in sorted(spans, key=lambda s: (order.get(s[2], 2), s[0], -(s[1] - s[0]))):
        if span[1] > span[0] and all(span[1] <= c[0] or span[0] >= c[1] for c in chosen):
            chosen.append(span)
    out, pos = [], 0
    for start, end, cls, title in sorted(chosen):
        out.append(escape(text[pos:start]))
        attr = f' title="{escape(title)}"' if title else ""
        out.append(f'<mark class="{cls}"{attr}>{escape(text[start:end])}</mark>')
        pos = end
    out.append(escape(text[pos:]))
    return "".join(out)


_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>비식별화 검토 리포트</title>
<style>{css}</style>
</head>
<body>
<div class="warning">원본 영역 문서입니다. 추출한 원문이 그대로 들어 있습니다. 커밋, 공유, 메일 첨부, 업로드 금지.</div>
<main>
<h1>비식별화 검토 리포트 <small>파일 → 텍스트 추출 → 비식별화 → 누출 검사</small></h1>
<p class="meta">생성 {generated} · 샘플 {source}</p>
<p class="summary">{summary}</p>
<div class="progress" id="progress">검수 0/{total}</div>
<div class="actions"><button type="button" id="copy">결과 복사 (TSV)</button><button type="button" id="save">결과 저장 (JSON)</button><button type="button" id="reset">검수 초기화</button><span id="msg"></span></div>
<p class="legend"><mark class="src">치환된 원문</mark> <mark class="tok">[토큰]</mark> <mark class="leak">남은 정답 값</mark> · 검수 선택은 이 브라우저에만 저장됩니다.</p>
<nav class="toc">{nav}</nav>
{sections}
</main>
<script>{js}</script>
</body>
</html>
"""

_CSS = """
:root { --bg:#f7f7f8; --panel:#fff; --text:#1d1f23; --muted:#5f6670; --line:#dfe2e6;
  --good:#1a7f45; --good-bg:#e3f4ea; --bad:#b42318; --bad-bg:#fde8e6; --hold:#8a5a00; --hold-bg:#fdf1d6;
  --src:#fff0b3; --tok:#dbe8ff; --tok-text:#173a8a; --leak:#ffc9c2; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181c; --panel:#1f2227; --text:#e6e8eb; --muted:#9aa3ad;
  --line:#33373e; --good:#6fd39b; --good-bg:#183324; --bad:#ff8a7e; --bad-bg:#3a1d1a; --hold:#f0c060;
  --hold-bg:#3a2e12; --src:#5a4c10; --tok:#22345a; --tok-text:#b8cdff; --leak:#6b2620; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:14px/1.55 system-ui, "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; }
main { max-width:1400px; margin:0 auto; padding:16px; }
.warning { background:var(--bad); color:#fff; padding:8px 16px; font-weight:600; text-align:center; }
h1 { font-size:22px; margin:12px 0 4px; } h1 small { font-size:13px; color:var(--muted); font-weight:400; margin-left:8px; }
.meta, .legend, .facts { color:var(--muted); margin:4px 0; }
.summary { font-weight:600; margin:8px 0; }
.progress { margin:8px 0; font-weight:600; }
.actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:8px 0; }
button { font:inherit; padding:5px 12px; border:1px solid var(--line); background:var(--panel); color:var(--text); border-radius:6px; cursor:pointer; }
#msg { color:var(--muted); }
.toc { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0 20px; position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:2; }
.chip { padding:2px 10px; border-radius:999px; text-decoration:none; font-weight:600; border:2px solid transparent; }
.chip.good { background:var(--good-bg); color:var(--good); } .chip.bad { background:var(--bad-bg); color:var(--bad); }
.chip.hold { background:var(--hold-bg); color:var(--hold); }
.chip.reviewed-ok { border-color:var(--good); } .chip.reviewed-leak { border-color:var(--bad); }
.sample { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:0 0 20px; scroll-margin-top:56px; }
.sample-head { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
.sample h2 { font-size:17px; margin:0; } .fmt { color:var(--muted); font-weight:500; margin:0 6px; } .file { font-weight:400; font-size:14px; }
.badge { padding:3px 10px; border-radius:6px; font-weight:600; white-space:nowrap; }
.badge.good { background:var(--good-bg); color:var(--good); } .badge.bad { background:var(--bad-bg); color:var(--bad); }
.badge.hold { background:var(--hold-bg); color:var(--hold); }
.traps { display:flex; flex-wrap:wrap; gap:4px; margin:6px 0 10px; }
.trap { font-size:12px; padding:1px 8px; border:1px solid var(--line); border-radius:999px; color:var(--muted); }
.problems { color:var(--bad); margin:6px 0 10px; }
.hold-note { background:var(--hold-bg); color:var(--hold); padding:8px 10px; border-radius:6px; }
.bad-text { color:var(--bad); }
table { border-collapse:collapse; width:100%; }
.pair { table-layout:fixed; margin:6px 0; }
.pair th, .pair td { border:1px solid var(--line); padding:6px 8px; vertical-align:top; text-align:left; }
.pair thead th { background:var(--bg); font-weight:600; }
.pair tbody th { width:150px; font-weight:500; font-size:13px; }
.pair.single tbody th { width:180px; }
.kind { display:block; font-size:11px; color:var(--muted); }
.kind-metadata th, .kind-filename th { background:var(--bg); }
.kind-hidden th .kind { color:var(--bad); }
pre { margin:0; white-space:pre-wrap; word-break:break-word; font:13px/1.5 ui-monospace, "Cascadia Mono", Consolas, "D2Coding", monospace; }
mark { border-radius:3px; padding:0 1px; color:inherit; }
mark.src { background:var(--src); } mark.tok { background:var(--tok); color:var(--tok-text); } mark.leak { background:var(--leak); outline:1px solid var(--bad); }
details.truth { margin:8px 0; } details.truth summary { cursor:pointer; color:var(--muted); }
.truth-table th, .truth-table td { border:1px solid var(--line); padding:3px 8px; text-align:left; font-size:13px; }
.keep { color:var(--muted); font-size:13px; }
code { font-family:ui-monospace, Consolas, monospace; font-size:12.5px; }
.review { display:flex; gap:14px; align-items:center; flex-wrap:wrap; border-top:1px dashed var(--line); padding-top:10px; margin-top:10px; }
.review-label { font-weight:600; } .review textarea { flex:1; min-width:220px; font:inherit; padding:4px 8px; background:var(--bg); color:var(--text); border:1px solid var(--line); border-radius:6px; }
@media (max-width: 760px) { .pair, .pair thead, .pair tbody, .pair tr, .pair th, .pair td { display:block; width:100%; } .pair thead { display:none; } .pair tbody th { width:auto; } }
"""

_JS = r"""
(function () {
  var KEY = "deid-review/__FINGERPRINT__";
  var IDS = __IDS__;
  var state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function refresh() {
    var done = 0, ok = 0, leak = 0;
    IDS.forEach(function (id) {
      var s = state[id] || {};
      var chip = document.querySelector('.toc a[href="#' + id + '"]');
      if (chip) { chip.classList.remove("reviewed-ok", "reviewed-leak"); if (s.v) chip.classList.add("reviewed-" + s.v); }
      if (s.v) { done++; if (s.v === "ok") ok++; else leak++; }
    });
    document.getElementById("progress").textContent = "검수 " + done + "/" + IDS.length + " · OK " + ok + " · 누출·문제 " + leak;
  }
  IDS.forEach(function (id) {
    var s = state[id] || {};
    document.querySelectorAll('input[name="v-' + id + '"]').forEach(function (el) {
      el.checked = s.v === el.value;
      el.addEventListener("change", function () { state[id] = state[id] || {}; state[id].v = el.value; save(); refresh(); });
    });
    var note = document.querySelector('textarea[name="n-' + id + '"]');
    if (note) {
      note.value = s.n || "";
      note.addEventListener("input", function () { state[id] = state[id] || {}; state[id].n = note.value; save(); });
    }
  });
  function rows() {
    return IDS.map(function (id) {
      var s = state[id] || {};
      var sec = document.getElementById(id);
      var auto = sec ? sec.querySelector(".badge").textContent : "";
      return [id, auto, s.v === "ok" ? "OK" : s.v === "leak" ? "누출/문제" : "미검수", (s.n || "").replace(/\s+/g, " ")];
    });
  }
  function flash(text) { var m = document.getElementById("msg"); m.textContent = text; setTimeout(function () { m.textContent = ""; }, 2500); }
  document.getElementById("copy").addEventListener("click", function () {
    var tsv = [["샘플", "자동 검사", "검수", "메모"]].concat(rows()).map(function (r) { return r.join("\t"); }).join("\n");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(tsv).then(function () { flash("복사했습니다"); }, function () { fallback(tsv); });
    } else { fallback(tsv); }
  });
  function fallback(text) {
    var t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); flash("복사했습니다"); } catch (e) { flash("복사 실패"); }
    document.body.removeChild(t);
  }
  document.getElementById("save").addEventListener("click", function () {
    var data = rows().map(function (r) { return { sample: r[0], auto: r[1], review: r[2], note: r[3] }; });
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "deid-review-result.json";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  });
  document.getElementById("reset").addEventListener("click", function () {
    if (!confirm("검수 선택과 메모를 모두 지울까요?")) return;
    state = {}; save();
    document.querySelectorAll(".review input").forEach(function (el) { el.checked = false; });
    document.querySelectorAll(".review textarea").forEach(function (el) { el.value = ""; });
    refresh();
  });
  refresh();
})();
"""
