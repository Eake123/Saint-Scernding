import random

import pytest

from santa.draw import DrawError, add_person, draw, make_allowed, remove_person


def check_valid(result, people, allowed):
    assert sorted(result) == sorted(people)
    assert sorted(result.values()) == sorted(people)
    for santa, giftee in result.items():
        assert allowed(santa, giftee), (santa, giftee)


@pytest.mark.parametrize("seed", range(50))
def test_basic_draw_is_valid(seed):
    people = list(range(1, 26))
    allowed = make_allowed(set(), {})
    result = draw(people, allowed, rng=random.Random(seed))
    check_valid(result, people, allowed)
    # no mutual pairs when avoidable
    assert all(result[result[s]] != s for s in result)


@pytest.mark.parametrize("seed", range(50))
def test_rules_are_respected(seed):
    rng = random.Random(seed)
    people = list(range(1, 31))
    forbidden = set()
    for p in people:  # everyone reports two past giftees
        for other in rng.sample([x for x in people if x != p], 2):
            forbidden.add((p, other))
    forbidden |= {(1, 2), (2, 1), (3, 4), (4, 3)}  # couples
    pools = {5: {6, 7, 8}, 9: {10, 11}, 12: {6, 13}}
    allowed = make_allowed(forbidden, pools)
    result = draw(people, allowed, rng=rng)
    check_valid(result, people, allowed)
    for giftee, pool in pools.items():
        santa = next(s for s, g in result.items() if g == giftee)
        assert santa in pool


@pytest.mark.parametrize("seed", range(50))
def test_two_way_groups(seed):
    # 1 and 2 only know people in {3, 4, 5}: both their Santa and their giftee must come from there
    people = list(range(1, 16))
    group = {3, 4, 5}
    allowed = make_allowed(set(), {1: group, 2: group}, {1: group, 2: group})
    result = draw(people, allowed, rng=random.Random(seed))
    check_valid(result, people, allowed)
    for p in (1, 2):
        assert result[p] in group  # who they get
        assert next(s for s, g in result.items() if g == p) in group  # who gets them


def test_two_way_group_choice_is_random():
    people = list(range(1, 11))
    allowed = make_allowed(set(), {1: {2, 3, 4}}, {1: {2, 3, 4}})
    gives, gets = set(), set()
    for seed in range(200):
        result = draw(people, allowed, rng=random.Random(seed))
        gives.add(result[1])
        gets.add(next(s for s, g in result.items() if g == 1))
    assert gives == {2, 3, 4} and gets == {2, 3, 4}


def test_pool_choice_is_random():
    people = list(range(1, 11))
    allowed = make_allowed(set(), {1: {2, 3, 4}})
    seen = set()
    for seed in range(200):
        result = draw(people, allowed, rng=random.Random(seed))
        seen.add(next(s for s, g in result.items() if g == 1))
    assert seen == {2, 3, 4}


def test_impossible_rules_fail_cleanly():
    people = [1, 2, 3]
    # 1 and 2 both may only be gifted by 3
    allowed = make_allowed(set(), {1: {3}, 2: {3}})
    with pytest.raises(DrawError):
        draw(people, allowed, rng=random.Random(0))


def test_nobody_allowed_reports_who():
    allowed = make_allowed({(2, 1), (3, 1)}, {})
    with pytest.raises(DrawError) as err:
        draw([1, 2, 3], allowed)
    assert err.value.stuck == [1]


def test_two_people_allows_mutual():
    assert draw([1, 2], make_allowed(set(), {})) == {1: 2, 2: 1}


@pytest.mark.parametrize("seed", range(20))
def test_remove_falls_back_to_resolve(seed):
    # 3 may only be gifted by 2 or 5. Removing 2 means 5 must take over 3,
    # which no single swap can do, so the draw has to be re-solved.
    assign = {1: 2, 2: 3, 3: 4, 4: 5, 5: 1}
    allowed = make_allowed(set(), {3: {2, 5}})
    after, changed = remove_person(assign, 2, allowed, random.Random(seed))
    check_valid(after, [1, 3, 4, 5], allowed)
    assert after[5] == 3
    assert set(changed) == {s for s in after if assign[s] != after[s]}


@pytest.mark.parametrize("seed", range(30))
def test_remove_and_add(seed):
    rng = random.Random(seed)
    people = list(range(1, 21))
    allowed = make_allowed({(1, 2)}, {})
    result = draw(people, allowed, rng=rng)

    leaving = rng.choice(people)
    after, changed = remove_person(result, leaving, allowed, rng)
    remaining = [p for p in people if p != leaving]
    check_valid(after, remaining, allowed)
    assert 1 <= len(changed) <= 2  # no pools here, so a simple fix always exists
    for s in remaining:
        if s not in changed:
            assert after[s] == result[s]

    after2, changed2 = add_person(after, 99, allowed, rng)
    check_valid(after2, remaining + [99], allowed)
    assert 99 in changed2 and len(changed2) == 2
