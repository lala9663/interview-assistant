"""Reverse map encrypted at rest, re-identification as the only decrypting path, key handling."""

import pytest
from sqlalchemy import select, text

from interview_assistant.config import Settings
from interview_assistant.crypto import FieldCipher, InvalidToken, MissingEncryptionKey
from interview_assistant.deid import (
    KnownIdentity,
    SqlTokenStore,
    build_deidentifier,
    open_identity,
    seal_identity,
)
from interview_assistant.deid.reidentify import lookup_token, reidentify_text
from interview_assistant.models import ActorType, AuditLog, Candidate, DeidCategory, DeidMapping

KNOWN = KnownIdentity(name="김도윤", phones=("010-0123-4567",), schools=("한빛대학교",))
RAW = "김도윤입니다. 한빛대 졸업, 연락처 010-0123-4567, 카카오 근무."


@pytest.fixture
def stored(db_factory, cipher, deid_config):
    """One candidate whose text was de-identified and committed: (factory, candidate_id, text)."""
    with db_factory() as session:
        candidate = Candidate(pseudonym="CAND-1")
        session.add(candidate)
        session.flush()
        deid = build_deidentifier(
            deid_config, SqlTokenStore(session, cipher, deid_config.token_formats())
        )
        out = deid.deidentify(RAW, candidate_id=candidate.id, known=KNOWN).text
        session.commit()
        return db_factory, candidate.id, out


def test_reverse_map_is_encrypted_at_rest(stored):
    factory, candidate_id, out = stored
    assert out == "[지원자]입니다. [학교-1] 졸업, 연락처 [전화-1], [회사-1] 근무."
    with factory() as session:
        dump = " ".join(
            str(v) for row in session.execute(text("SELECT * FROM deid_mappings")) for v in row
        )
    for plain in ("김도윤", "한빛대학교", "01001234567", "카카오"):
        assert plain not in dump
    assert "[학교-1]" in dump


def test_reidentify_text_restores_canonical_values_and_audits(stored, cipher):
    factory, candidate_id, out = stored
    with factory() as session:
        restored = reidentify_text(
            session,
            cipher,
            candidate_id=candidate_id,
            text=out,
            actor_type=ActorType.user,
            actor_id="hr-001",
            purpose="지원자 설명 요구 대응",
        )
        session.commit()
        logs = session.scalars(select(AuditLog)).all()

    assert restored == "김도윤입니다. 한빛대학교 졸업, 연락처 01001234567, 카카오 근무."
    assert len(logs) == 1
    log = logs[0]
    assert log.action == "deid.reidentify_text"
    assert (log.actor_id, log.target_id) == ("hr-001", candidate_id)
    assert log.details == {"purpose": "지원자 설명 요구 대응", "tokens_resolved": 4}


def test_lookup_token_is_scoped_to_candidate(stored, cipher):
    factory, candidate_id, _ = stored
    with factory() as session:
        other = Candidate(pseudonym="CAND-2")
        session.add(other)
        session.flush()
        def lookup(cid, token):
            return lookup_token(
                session, cipher, candidate_id=cid, token=token,
                actor_type=ActorType.system, actor_id=None, purpose="test",
            )  # fmt: skip

        assert lookup(candidate_id, "[학교-1]") == "한빛대학교"
        assert lookup(other.id, "[학교-1]") is None
        assert lookup(candidate_id, "[학교-9]") is None
        assert session.query(AuditLog).count() == 3


def test_reidentify_leaves_other_candidates_tokens(stored, cipher):
    factory, _, out = stored
    with factory() as session:
        other = Candidate(pseudonym="CAND-2")
        session.add(other)
        session.flush()
        restored = reidentify_text(
            session, cipher, candidate_id=other.id, text=out,
            actor_type=ActorType.system, actor_id=None, purpose="test",
        )  # fmt: skip
    assert restored == out


def test_wrong_key_cannot_read_reverse_map(stored):
    factory, candidate_id, _ = stored
    wrong = FieldCipher(FieldCipher.generate_key())
    with factory() as session, pytest.raises(InvalidToken):
        lookup_token(
            session, wrong, candidate_id=candidate_id, token="[지원자]",
            actor_type=ActorType.system, actor_id=None, purpose="test",
        )  # fmt: skip


def test_deleting_candidate_deletes_reverse_map(stored):
    factory, candidate_id, _ = stored
    with factory() as session:
        assert session.query(DeidMapping).count() == 4
        session.delete(session.get(Candidate, candidate_id))
        session.commit()
        assert session.query(DeidMapping).count() == 0


def test_unnumbered_category_keeps_single_row(db_factory, cipher, deid_config):
    with db_factory() as session:
        candidate = Candidate(pseudonym="CAND-1")
        session.add(candidate)
        session.flush()
        store = SqlTokenStore(session, cipher, deid_config.token_formats())
        first = store.token_for(candidate.id, DeidCategory.candidate, "김도윤")
        renamed = store.token_for(candidate.id, DeidCategory.candidate, "김도윤A")
        assert first == renamed == "[지원자]"
        assert session.query(DeidMapping).count() == 1


def test_cipher_round_trip_and_lookup_hash(cipher):
    token = cipher.encrypt("김도윤")
    assert token != "김도윤" and cipher.encrypt("김도윤") != token  # randomized
    assert cipher.decrypt(token) == "김도윤"
    assert cipher.lookup_hash("c1", "phone", "010") == cipher.lookup_hash("c1", "phone", "010")
    assert cipher.lookup_hash("c1", "phone", "010") != cipher.lookup_hash("c2", "phone", "010")
    other = FieldCipher(FieldCipher.generate_key())
    assert other.lookup_hash("c1", "phone", "010") != cipher.lookup_hash("c1", "phone", "010")


def test_cipher_key_comes_from_environment(monkeypatch):
    monkeypatch.delenv("IA_ENCRYPTION_KEY", raising=False)
    with pytest.raises(MissingEncryptionKey):
        FieldCipher.from_settings(Settings(_env_file=None))
    key = FieldCipher.generate_key()
    monkeypatch.setenv("IA_ENCRYPTION_KEY", key)
    from_env = FieldCipher.from_settings(Settings(_env_file=None))
    assert FieldCipher(key).decrypt(from_env.encrypt("x")) == "x"


def test_identity_seal_round_trip(cipher):
    identity = KnownIdentity(
        name="김도윤", aliases=("Doyoon Kim",), birthdate="1995-03-14", companies=("카카오",)
    )
    sealed = seal_identity(cipher, identity)
    assert "김도윤" not in sealed
    assert open_identity(cipher, sealed) == identity
