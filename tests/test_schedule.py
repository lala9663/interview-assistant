"""Schedule matching: same results as frontend/src/lib/lib.test.ts, plus booked time."""

from interview_assistant.schedule import absorb, common_free, merge, subtract, suggest_slots

H = 3_600_000
T0 = 1_800_000_000_000 - 1_800_000_000_000 % H


def test_common_free_matches_the_frontend_cases():
    by = {
        "a": [(T0 + 9 * H, T0 + 12 * H)],
        "b": [(T0 + 10 * H, T0 + 11.5 * H)],
        "c": [(T0 + 11 * H, T0 + 15 * H)],
    }
    by = {k: [(int(a), int(b)) for a, b in v] for k, v in by.items()}
    assert common_free(by, ["a", "b"]) == [(T0 + 10 * H, int(T0 + 11.5 * H), ["a", "b"])]
    assert common_free(by, ["a", "b", "c"]) == [(T0 + 11 * H, int(T0 + 11.5 * H), ["a", "b", "c"])]
    slots = suggest_slots(by, ["a", "b", "c"], 60, min_count=2)
    assert slots[0][0] == T0 + 10 * H and len(slots[0][2]) >= 2


def test_merge_and_subtract():
    assert merge([(5, 8), (1, 3), (3, 4)]) == [(1, 4), (5, 8)]
    assert subtract([(0, 10)], [(2, 3), (5, 12)]) == [(0, 2), (3, 5)]
    assert subtract([(0, 10)], []) == [(0, 10)]


def test_absorb_joins_every_block_the_new_one_touches():
    others = {"a": (0, 10), "b": (20, 30), "c": (40, 50)}
    # Touching counts: 10–20 joins a and b; c is apart.
    assert absorb(others, (10, 20)) == ((0, 30), ["a", "b"])
    assert absorb(others, (12, 15)) == ((12, 15), [])
    assert absorb(others, (5, 45)) == ((0, 50), ["a", "b", "c"])
    # Old rows on top of each other are joined through one another.
    assert absorb({"x": (0, 10), "y": (5, 25)}, (20, 30)) == ((0, 30), ["x", "y"])
    assert absorb({}, (1, 2)) == ((1, 2), [])


def test_slots_are_aligned_and_bounded():
    by = {"a": [(T0 + 9 * H + 600_000, T0 + 13 * H)], "b": [(T0 + 9 * H, T0 + 13 * H)]}
    starts = [
        s
        for s, _, _ in suggest_slots(by, ["a", "b"], 60, start_from=T0 + 10 * H, until=T0 + 12 * H)
    ]
    assert starts == [T0 + 10 * H, T0 + 11 * H]
    assert suggest_slots(by, [], 60) == []
