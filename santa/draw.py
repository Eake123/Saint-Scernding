"""The name-drawing logic. Pure Python, no Discord stuff, so it can be tested on its own.

Everything is expressed as santa -> giftee (santa gives a gift TO giftee).
"""
from __future__ import annotations

import random
from typing import Callable, Iterable

Allowed = Callable[[int, int], bool]


class DrawError(Exception):
    def __init__(self, message: str, stuck: Iterable[int] = ()):
        super().__init__(message)
        self.stuck = list(stuck)


class _OutOfBudget(Exception):
    pass


def make_allowed(forbidden: set[tuple[int, int]], pools: dict[int, set[int]]) -> Allowed:
    """forbidden: (santa, giftee) pairs that must not happen.
    pools: giftee -> the only people allowed to be their santa (organizer's blind suggestions)."""

    def allowed(santa: int, giftee: int) -> bool:
        if santa == giftee or (santa, giftee) in forbidden:
            return False
        pool = pools.get(giftee)
        return not pool or santa in pool

    return allowed


def draw(
    people: Iterable[int],
    allowed: Allowed,
    rng: random.Random | None = None,
    avoid_mutual: bool = True,
    attempts: int = 200,
    node_budget: int = 20_000,
    prefer: dict[int, int] | None = None,
) -> dict[int, int]:
    """Return {santa: giftee} covering everyone, or raise DrawError.

    Tries first to avoid mutual pairs (A has B and B has A) since those make guessing too easy,
    and falls back to allowing them if that's impossible.
    prefer: an existing {santa: giftee} to stay as close to as possible (used when patching a draw)."""
    rng = rng or random.SystemRandom()
    people = list(dict.fromkeys(people))
    if len(people) < 2:
        raise DrawError("Need at least 2 people to draw names.")

    options = {g: [s for s in people if allowed(s, g)] for g in people}
    stuck = [g for g, opts in options.items() if not opts]
    if stuck:
        raise DrawError("Some people have nobody who is allowed to be their Santa.", stuck)

    preferred_santa = {g: s for s, g in (prefer or {}).items()}
    for no_mutual in ([True, False] if avoid_mutual else [False]):
        for _ in range(attempts):
            result, exhausted = _attempt(people, options, rng, no_mutual, node_budget, preferred_santa)
            if result:
                return {santa: giftee for giftee, santa in result.items()}
            if exhausted:  # searched every possibility: truly impossible with these rules
                break
    raise DrawError(
        "There's no way to draw names that satisfies every rule. "
        "Try removing an exclusion or adding more people to a suggestion pool."
    )


def _attempt(people, options, rng, no_mutual, budget, preferred_santa):
    santa_of: dict[int, int] = {}  # giftee -> santa
    used: set[int] = set()
    nodes = 0
    tiebreak = {p: rng.random() for p in people}

    def candidates(giftee):
        return [
            s for s in options[giftee]
            if s not in used and not (no_mutual and santa_of.get(s) == giftee)
        ]

    def solve() -> bool:
        nonlocal nodes
        if len(santa_of) == len(people):
            return True
        nodes += 1
        if nodes > budget:
            raise _OutOfBudget
        # Fill the most constrained person first.
        best, best_c = None, None
        for g in people:
            if g in santa_of:
                continue
            c = candidates(g)
            if not c:
                return False
            if best_c is None or (len(c), tiebreak[g]) < (len(best_c), tiebreak[best]):
                best, best_c = g, c
        rng.shuffle(best_c)
        keep = preferred_santa.get(best)
        if keep in best_c:  # try their current santa first
            best_c.remove(keep)
            best_c.insert(0, keep)
        for s in best_c:
            santa_of[best] = s
            used.add(s)
            if solve():
                return True
            del santa_of[best]
            used.discard(s)
        return False

    try:
        return (santa_of if solve() else None), True
    except _OutOfBudget:
        return None, False


def remove_person(
    assign: dict[int, int], leaving: int, allowed: Allowed, rng: random.Random | None = None
) -> tuple[dict[int, int], list[int]]:
    """Take someone out after the draw. Returns (new {santa: giftee}, santas whose giftee changed)."""
    rng = rng or random.SystemRandom()
    a = dict(assign)
    giftee = a.pop(leaving)
    santa = next(s for s, g in a.items() if g == leaving)
    del a[santa]

    # Simplest fix: the leaver's santa takes over the leaver's giftee.
    if allowed(santa, giftee):
        a[santa] = giftee
        return a, [santa]

    # Otherwise swap with another pair: santa takes y, x takes the orphaned giftee.
    pairs = list(a.items())
    rng.shuffle(pairs)
    for x, y in pairs:
        if allowed(santa, y) and allowed(x, giftee):
            a[santa] = y
            a[x] = giftee
            return a, [santa, x]

    # Last resort: re-solve everyone, keeping as many existing pairings as possible.
    remaining = [p for p in assign if p != leaving]
    return _resolve(remaining, a, allowed, rng,
                    "Couldn't rearrange the draw around this removal without breaking a rule.")


def _resolve(people, current, allowed, rng, fail_message):
    try:
        new = draw(people, allowed, rng=rng, avoid_mutual=False, prefer=current)
    except DrawError:
        raise DrawError(fail_message) from None
    return new, [s for s in people if current.get(s) != new[s]]


def add_person(
    assign: dict[int, int], newcomer: int, allowed: Allowed, rng: random.Random | None = None
) -> tuple[dict[int, int], list[int]]:
    """Slot a late joiner into the draw. Returns (new {santa: giftee}, santas whose giftee changed)."""
    rng = rng or random.SystemRandom()
    pairs = list(assign.items())
    rng.shuffle(pairs)
    for x, y in pairs:
        if allowed(x, newcomer) and allowed(newcomer, y):
            a = dict(assign)
            a[x] = newcomer
            a[newcomer] = y
            return a, [x, newcomer]
    return _resolve(list(assign) + [newcomer], assign, allowed, rng,
                    "Couldn't fit this person into the draw without breaking a rule.")
