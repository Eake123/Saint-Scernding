import random

from santa.db import DB
from santa.draw import add_person, draw, make_allowed, remove_person


def make_db(tmp_path, n=12):
    db = DB(tmp_path / "t.db")
    for i in range(1, n + 1):
        db.add_participant(i, f"P{i}")
    return db


def test_rules_feed_into_draw(tmp_path):
    db = make_db(tmp_path)
    db.set_history(1, i_had=[2, 3], had_me=[4])
    db.add_exclusion(5, 6)
    db.set_pool(7, [8, 9])
    forbidden = db.forbidden_pairs()
    assert {(1, 2), (1, 3), (4, 1), (5, 6), (6, 5)} <= forbidden
    assert (2, 1) not in forbidden

    allowed = make_allowed(forbidden, db.pools())
    for seed in range(20):
        m = draw([p["user_id"] for p in db.participants()], allowed, rng=random.Random(seed))
        assert m[1] not in (2, 3) and m[4] != 1 and m[5] != 6 and m[6] != 5
        assert next(s for s, g in m.items() if g == 7) in (8, 9)


def test_history_replaces(tmp_path):
    db = make_db(tmp_path)
    db.set_history(1, [2], [3])
    db.set_history(1, [4], [])
    assert {tuple(r) for r in db.history_of(1)} == {(1, 4)}


def test_assignment_changes_keep_other_status(tmp_path):
    db = make_db(tmp_path)
    allowed = make_allowed(set(), {})
    m = draw(range(1, 13), allowed, rng=random.Random(1))
    db.save_assignments(m)
    for s in m:
        db.mark_ready(s)

    new, changed = remove_person(m, 3, allowed, random.Random(2))
    db.apply_changes(new, changed, removed=3)
    db.remove_participant(3)
    assert db.assignment_map() == new
    for s in new:
        assert bool(db.assignment(s)["ready_at"]) == (s not in changed)

    db.add_participant(50, "Late")
    new2, changed2 = add_person(new, 50, allowed, random.Random(3))
    db.apply_changes(new2, changed2)
    assert db.assignment_map() == new2


def test_dates_keep_votes(tmp_path):
    db = make_db(tmp_path)
    db.set_date_options(["2026-12-11", "2026-12-12"])
    ids = {o["day"]: o["id"] for o in db.date_options()}
    db.set_votes(1, [ids["2026-12-11"], ids["2026-12-12"]])
    db.set_date_options(["2026-12-12", "2026-12-18"])
    assert db.votes_of(1) == {ids["2026-12-12"]}
    assert db.has_voted(1)


def test_archive_blocks_repeats_and_new_season(tmp_path):
    db = make_db(tmp_path, 4)
    db.save_assignments({1: 2, 2: 3, 3: 4, 4: 1})
    db.set_guess(2, 1)
    db.add_exclusion(1, 3)
    db.set("budget", 50)
    db.archive_year("2026")
    db.new_season()
    assert db.participants() == []
    assert db.get("budget") == "50" and db.phase == "signup"
    assert {(1, 2), (2, 3), (3, 4), (4, 1), (1, 3)} <= db.forbidden_pairs()
    assert db.q("SELECT guessed_right FROM archive WHERE giftee_id = 2")[0][0] == 1
    assert db.name(1) == "P1"
