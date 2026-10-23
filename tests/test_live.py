"""Live transcript hub and the follow-up stream parser."""

import asyncio
import random
import shutil

import pytest

from interview_assistant.ai.followups import SuggestionParser, ground
from interview_assistant.demo import mock_data
from interview_assistant.demo.seed import fake_identity
from interview_assistant.live.audio import AudioSource
from interview_assistant.live.hub import stable_prefix
from interview_assistant.models import InterviewSession, QAItem, TranscriptSegment
from interview_assistant.providers import fake_tasks
from interview_assistant.runtime import build_runtime
from tests.api_util import LIVE
from tests.conftest import api_settings, file_session_factory, instant_providers

BLOCKS = (
    "앞말 <suggestion><competency>데이터 기반 분석</competency>"
    "<question>근거 데이터는 무엇이었나요?</question>"
    "<rationale>근거 확인</rationale><grounding>DOE로 확인했습니다</grounding></suggestion>\n"
    "<suggestion>\n<competency>협업</competency>\n<question>누구와 <b>합의</b>했나요?</question>"
    "<rationale>조율 방식</rationale><grounding></grounding></suggestion>"
)


def _parse(chunks):
    parser = SuggestionParser()
    return [e for chunk in chunks for e in parser.feed(chunk)]


@pytest.mark.parametrize("seed", range(40))
def test_parser_gives_the_same_events_however_the_stream_is_cut(seed):
    rng = random.Random(seed)
    cuts = sorted(rng.sample(range(1, len(BLOCKS)), rng.randint(1, 60)))
    chunks = [BLOCKS[a:b] for a, b in zip([0, *cuts], [*cuts, len(BLOCKS)])]
    events = _parse(chunks)
    assert [e.kind for e in events if e.kind != "delta"] == ["start", "done", "start", "done"]
    starts = [e.fields["competency"] for e in events if e.kind == "start"]
    assert starts == ["데이터 기반 분석", "협업"]
    done = [e.fields for e in events if e.kind == "done"]
    assert done[0]["question"] == "근거 데이터는 무엇이었나요?"
    assert done[1]["question"] == "누구와 <b>합의</b>했나요?"  # other markup is text
    # Deltas rebuild each question and never contain the closing tag.
    first_done = next(i for i, e in enumerate(events) if e.kind == "done")
    deltas = "".join(e.text for e in events[:first_done] if e.kind == "delta")
    assert deltas == done[0]["question"]
    assert all("</question" not in e.text for e in events if e.kind == "delta")


def test_grounding_is_kept_verbatim_or_replaced_by_the_closest_answer_sentence():
    answer = "챔버별로 나눠 봤습니다. 상단 슬롯에서만 두께가 얇았습니다. 히터를 보정했습니다."
    assert (
        ground("“상단 슬롯에서만 두께가 얇았습니다”", answer) == "상단 슬롯에서만 두께가 얇았습니다"
    )
    assert ground("상단 슬롯 두께가 얇았다", answer) == "상단 슬롯에서만 두께가 얇았습니다"
    assert ground("x", "") == ""


def test_fake_follow_ups_parse_into_three_grounded_suggestions():
    prompt = (
        "<follow_up_request>\n<competencies>\n- 문제 해결: a\n- 협업: b\n</competencies>\n"
        "<target_competency>\n협업\n</target_competency>\n<answer>\n"
        "처음에는 원인을 몰랐습니다. 데이터를 3주치 모아 비교했습니다. 결국 생산팀과 합의했습니다.\n"
        "</answer>\n</follow_up_request>"
    )
    rng = random.Random(1)
    text = fake_tasks.follow_up_text(prompt, rng)
    events = _parse(list(fake_tasks.chunks(text, rng)))
    done = [e.fields for e in events if e.kind == "done"]
    assert [d["competency"] for d in done] == ["협업", "문제 해결", "협업"]
    assert all(d["grounding"] in prompt for d in done)


def test_partial_text_holds_back_what_may_be_half_an_identifier():
    assert stable_prefix("저는 강도") == "저는"
    assert stable_prefix("저는 강도윤입니다. 연") == "저는 강도윤입니다."
    assert stable_prefix("번호는 010-0000-00") == "번호는"
    assert stable_prefix("번호는 010 0000 0007 이고") == "번호는"
    assert stable_prefix("메일은 cand@exam") == "메일은"
    assert stable_prefix("한") == ""


class Says(AudioSource):
    def __init__(self, *sentences: str) -> None:
        self.sentences = sentences

    async def open(self, turn):
        for sentence in self.sentences:
            yield sentence.encode("utf-8")


@pytest.fixture
def live_runtime(seeded_db, tmp_path):
    template, key = seeded_db
    path = tmp_path / "live.db"
    shutil.copyfile(template, path)
    factory = file_session_factory(path)
    identity = fake_identity(
        7, next(c for c in mock_data()["candidates"] if c["n"] == 7)["profile"]
    )
    audio = Says(
        f"네 저는 {identity.name}입니다.",
        f"연락처는 {identity.phones[0]} 이고 메일은 {identity.emails[0]} 입니다.",
        f"{identity.companies[0]}에서 4년 일했습니다.",
    )
    runtime = build_runtime(
        api_settings(path, key, tmp_path),
        providers=instant_providers(),
        session_factory=factory,
        audio=audio,
    )
    yield runtime, identity
    factory.kw["bind"].dispose()


def _pending_qa(runtime) -> str:
    with runtime.session_factory() as db:
        return next(q.id for q in db.get(InterviewSession, LIVE).qa_items if q.answered_at is None)


async def test_hub_streams_deidentified_segments_and_closes_the_answer(
    live_runtime, no_external_network
):
    """Opening the stream while a question waits for its answer (seeded: Q3 asked a minute ago)
    starts listening; every published text is de-identified, partial results included."""
    runtime, identity = live_runtime
    qa_id = _pending_qa(runtime)
    received: list[tuple[str, dict]] = []

    async def subscriber():
        async for event in runtime.hub.events(LIVE):
            received.append(event)
            if event[0] == "qa.answered":
                await runtime.hub.end(LIVE)

    await asyncio.wait_for(subscriber(), 5)

    names = [e for e, _ in received]
    assert names[0] == "status" and received[0][1]["recording"] == "recording"
    assert names.count("segment.final") == 3 and "segment.partial" in names
    assert all(
        d["speaker"] == "candidate" and d["qa_item_id"] == qa_id
        for e, d in received
        if e.startswith("segment")
    )
    assert names[-2:] == ["qa.answered", "status"]

    secrets = [
        identity.name,
        identity.phones[0],
        "0000",
        identity.emails[0],
        "cand0007",
        identity.companies[0],
    ]
    for event, data in received:
        text = str(data)
        for secret in secrets:
            assert secret not in text, (event, secret)
    partial_ids = {d["segment_id"] for e, d in received if e == "segment.partial"}
    final_ids = {d["segment_id"] for e, d in received if e == "segment.final"}
    assert partial_ids <= final_ids  # a partial is replaced by the final with the same id
    answered = received[-2][1]
    assert answered["qa_item_id"] == qa_id
    assert answered["answer_deidentified"].startswith("네 저는 [지원자]입니다. 연락처는 [전화-1]")
    assert "[회사-1]에서 4년" in answered["answer_deidentified"]  # seeded token, same value

    with runtime.session_factory() as db:
        qa = db.get(QAItem, qa_id)
        assert identity.name in qa.answer_text  # raw zone keeps the original
        stored = [
            s
            for s in db.query(TranscriptSegment).filter_by(qa_item_id=qa_id).all()
            if s.speaker.value == "candidate"
        ]
        assert len(stored) == 3 and all(identity.name not in s.text_deidentified for s in stored)


async def test_interrupting_closes_the_answer_with_what_was_heard(
    live_runtime, no_external_network
):
    runtime, _ = live_runtime
    qa_id = _pending_qa(runtime)

    class Slow(AudioSource):
        async def open(self, turn):
            yield "첫 문장입니다.".encode()
            await asyncio.sleep(30)
            yield "들리지 않는 문장.".encode()

    runtime.hub.audio = Slow()
    runtime.hub.listen(LIVE, qa_id, announce=False)
    for _ in range(100):
        await asyncio.sleep(0.01)
        with runtime.session_factory() as db:
            if db.query(TranscriptSegment).filter_by(qa_item_id=qa_id).count():
                break
    await runtime.hub.interrupt(LIVE)
    with runtime.session_factory() as db:
        assert db.get(QAItem, qa_id).answer_deidentified == "첫 문장입니다."
