"""De-identifier end to end: token consistency, formats, allow list, overlaps, config."""

import pytest
import yaml

from interview_assistant.deid import (
    DeidCategory,
    Deidentifier,
    InMemoryTokenStore,
    KnownIdentity,
    SqlTokenStore,
    TokenFormats,
    build_deidentifier,
    build_detectors,
    load_deid_config,
)
from interview_assistant.deid.detectors import Entity
from interview_assistant.models import Candidate, DeidMapping

KNOWN = KnownIdentity(
    name="김도윤",
    aliases=("Doyoon Kim",),
    phones=("010-0123-4567",),
    emails=("doyoon.kim@example.com",),
    schools=("한빛대학교",),
)


def _candidates(session, *pseudonyms):
    rows = [Candidate(pseudonym=p) for p in pseudonyms]
    session.add_all(rows)
    session.flush()
    return rows


@pytest.fixture
def memory_deid(deid_config):
    return build_deidentifier(deid_config, InMemoryTokenStore(deid_config.token_formats()))


def test_same_value_same_token_within_text(memory_deid):
    text = "서울대 졸업 후 SNU 대학원, 서울대학교 연구실. 카카오와 Kakao, 그리고 쿠팡."
    out = memory_deid.deidentify(text, candidate_id="c1").text
    assert out == "[학교-1] 졸업 후 [학교-1] 대학원, [학교-1] 연구실. [회사-1]와 [회사-1], 그리고 [회사-2]."


def test_tokens_stable_across_sessions_and_documents(db_factory, cipher, deid_config):
    formats = deid_config.token_formats()
    with db_factory() as session:
        (cand,) = _candidates(session, "CAND-1")
        deid = build_deidentifier(deid_config, SqlTokenStore(session, cipher, formats))
        resume = deid.deidentify(
            "김도윤, 한빛대학교 졸업, 카카오 재직, 010-0123-4567", candidate_id=cand.id, known=KNOWN
        ).text
        session.commit()
        cand_id = cand.id

    # A later interview session, a new store and a new DB session: same tokens.
    with db_factory() as session:
        deid = build_deidentifier(deid_config, SqlTokenStore(session, cipher, formats))
        answer = deid.deidentify(
            "도윤입니다. 쿠팡보다 카카오가 좋았고, 한빛대 때 연락처는 010.0123.4567였습니다.",
            candidate_id=cand_id,
            known=KNOWN,
        ).text
        session.commit()

    assert resume == "[지원자], [학교-1] 졸업, [회사-1] 재직, [전화-1]"
    assert answer == "[지원자]입니다. [회사-2]보다 [회사-1]가 좋았고, [학교-1] 때 연락처는 [전화-1]였습니다."


def test_numbering_is_per_candidate(db_factory, cipher, deid_config):
    with db_factory() as session:
        a, b = _candidates(session, "CAND-A", "CAND-B")
        deid = build_deidentifier(
            deid_config, SqlTokenStore(session, cipher, deid_config.token_formats())
        )
        assert deid.deidentify("네이버, 카카오", candidate_id=a.id).text == "[회사-1], [회사-2]"
        assert deid.deidentify("카카오, 네이버", candidate_id=b.id).text == "[회사-1], [회사-2]"
        rows = session.query(DeidMapping).all()
        assert len(rows) == 4
        # The same school under two candidates is not linkable through the lookup hash.
        hashes = {r.candidate_id: r.value_hash for r in rows if r.token == "[회사-1]"}
        assert hashes[a.id] != hashes[b.id]


def test_token_format_is_configurable(deid_config):
    formats = TokenFormats({c: f"<{c.value.upper()}_{{n}}>" for c in DeidCategory})
    deid = build_deidentifier(deid_config, InMemoryTokenStore(formats))
    out = deid.deidentify("김도윤, 서울대, 카카오, 네이버", candidate_id="c", known=KNOWN).text
    assert out == "<CANDIDATE_1>, <SCHOOL_1>, <COMPANY_1>, <COMPANY_2>"


def test_unnumbered_format_shares_one_token(deid_config):
    templates = {c: f"[{c.value}-{{n}}]" for c in DeidCategory}
    templates[DeidCategory.company] = "[회사]"
    deid = build_deidentifier(deid_config, InMemoryTokenStore(TokenFormats(templates)))
    assert deid.deidentify("카카오, 네이버", candidate_id="c").text == "[회사], [회사]"


@pytest.mark.parametrize(
    "templates, message",
    [
        ({"candidate": "[지원자]"}, "missing"),
        ({c: "[같음]" for c in DeidCategory}, "differ"),
        ({**{c: f"[{c.value}{{n}}]" for c in DeidCategory}, "school": "  "}, "empty"),
        ({**{c: f"[{c.value}{{n}}]" for c in DeidCategory}, "school": "x" * 60}, "long"),
    ],
)
def test_token_format_validation(templates, message):
    with pytest.raises(ValueError, match=message):
        TokenFormats(templates)


def test_token_pattern_matches_rendered_tokens(deid_config):
    formats = deid_config.token_formats()
    pattern = formats.pattern()
    assert pattern.fullmatch("[학교-12]") and pattern.fullmatch("[지원자]")
    assert not pattern.fullmatch("[학교]")


def test_allow_list_exempts_only_organisations(deid_config):
    config = deid_config.model_copy(update={"allow": ["삼성전자", "김도윤"]})
    deid = build_deidentifier(config, InMemoryTokenStore(config.token_formats()))
    out = deid.deidentify("김도윤입니다. 삼성전자에 지원했고 카카오에 다녔습니다.", candidate_id="c", known=KNOWN)
    assert out.text == "[지원자]입니다. 삼성전자에 지원했고 [회사-1]에 다녔습니다."


def test_known_company_is_never_allow_listed(deid_config):
    config = deid_config.model_copy(update={"allow": ["삼성전자"]})
    deid = build_deidentifier(config, InMemoryTokenStore(config.token_formats()))
    known = KnownIdentity(name="김도윤", companies=("삼성전자",))
    assert deid.deidentify("삼성전자 출신", candidate_id="c", known=known).text == "[회사-1] 출신"


def test_overlapping_detections_merge_into_longest(memory_deid):
    known = KnownIdentity(name="김도윤", aliases=("Doyoon",), emails=())
    out = memory_deid.deidentify("메일은 doyoon@example.com 입니다", candidate_id="c", known=known)
    assert out.text == "메일은 [이메일-1] 입니다"
    assert [r.category for r in out.replacements] == [DeidCategory.email]


def test_merge_covers_partial_overlaps():
    class Fixed:
        def __init__(self, name, priority, spans):
            self.name, self.priority, self.spans = name, priority, spans

        def detect(self, text, known=None):
            from interview_assistant.deid import Detection

            for start, end, cat in self.spans:
                yield Detection(start, end, cat, text[start:end], self.name, self.priority)

    text = "0123456789"
    detectors = [
        Fixed("a", 0, [(2, 5, DeidCategory.person)]),
        Fixed("b", 1, [(4, 8, DeidCategory.company)]),
    ]
    store = InMemoryTokenStore(TokenFormats({c: f"<{c.value}{{n}}>" for c in DeidCategory}))
    out = Deidentifier(detectors, store).deidentify(text, candidate_id="c")
    assert out.text == "01<company1>89"  # union 2..8, labelled by the longer span


def test_replacements_carry_no_original_values(memory_deid):
    out = memory_deid.deidentify("김도윤 010-0123-4567", candidate_id="c", known=KNOWN)
    dumped = repr(out.replacements)
    assert "김도윤" not in dumped and "0123" not in dumped
    assert [(r.start, r.end) for r in out.replacements] == [(0, 3), (4, 17)]


def test_text_without_identifiers_is_unchanged(memory_deid):
    text = "대규모 트래픽 처리를 위해 캐시 계층을 두고, 배포 전 체크리스트를 돌렸습니다."
    out = memory_deid.deidentify(text, candidate_id="c", known=KNOWN)
    assert out.text == text and out.replacements == ()


def test_config_resolves_dictionary_paths_relative_to_file(tmp_path):
    (tmp_path / "dict").mkdir()
    (tmp_path / "dict" / "co.txt").write_text("# comment\n\n가나테크 | 가나\n", encoding="utf-8")
    config_file = tmp_path / "deid.yaml"
    tokens = {c.value: f"[{c.value}-{{n}}]" for c in DeidCategory}
    config_file.write_text(
        yaml.safe_dump(
            {"deid": {"tokens": tokens, "dictionaries": {"company": ["dict/co.txt"]}}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    config = load_deid_config(config_file)
    assert config.dictionaries[DeidCategory.company] == [tmp_path / "dict" / "co.txt"]
    deid = build_deidentifier(config, InMemoryTokenStore(config.token_formats()))
    assert deid.deidentify("가나에서 일함", candidate_id="c").text == "[company-1]에서 일함"


def test_config_detector_errors(deid_config):
    dictionary = deid_config.load_dictionary()
    with pytest.raises(ValueError, match="unknown detector"):
        build_detectors(deid_config.model_copy(update={"detectors": ["bogus"]}), dictionary)
    with pytest.raises(ValueError, match="no recognizer"):
        build_detectors(deid_config.model_copy(update={"detectors": ["ner"]}), dictionary)


def test_ner_plugs_in_through_config(deid_config):
    class Recognizer:
        def recognize(self, text):
            i = text.index("박서준")
            return [Entity(i, i + 3, "PS")]

    config = deid_config.model_copy(update={"detectors": [*deid_config.detectors, "ner"]})
    deid = build_deidentifier(
        config, InMemoryTokenStore(config.token_formats()), recognizer=Recognizer()
    )
    assert deid.deidentify("박서준과 일했다", candidate_id="c").text == "[인물-1]과 일했다"
