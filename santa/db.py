"""All saved data lives in one SQLite file (santa.db). Don't open it during the event —
it contains the draw, and the whole point is that nobody (including you) peeks."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS participants (
    user_id   INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    dm_ok     INTEGER NOT NULL DEFAULT 1,
    wish      TEXT, interests TEXT, avoid TEXT, sizes TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS date_options (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS date_votes  (user_id INTEGER, option_id INTEGER, PRIMARY KEY (user_id, option_id));
CREATE TABLE IF NOT EXISTS date_voters (user_id INTEGER PRIMARY KEY);

-- self-reported past pairings (reporter said: santa had giftee before)
CREATE TABLE IF NOT EXISTS history (
    reporter_id INTEGER, santa_id INTEGER, giftee_id INTEGER,
    PRIMARY KEY (reporter_id, santa_id, giftee_id)
);
-- organizer rules
CREATE TABLE IF NOT EXISTS exclusions (a INTEGER, b INTEGER, PRIMARY KEY (a, b));
CREATE TABLE IF NOT EXISTS santa_pool (giftee_id INTEGER, santa_id INTEGER, PRIMARY KEY (giftee_id, santa_id));
-- the other direction: santa_id may only GIVE to one of these giftees
CREATE TABLE IF NOT EXISTS giftee_pool (santa_id INTEGER, giftee_id INTEGER, PRIMARY KEY (santa_id, giftee_id));

CREATE TABLE IF NOT EXISTS assignments (
    santa_id  INTEGER PRIMARY KEY,
    giftee_id INTEGER NOT NULL UNIQUE,
    ready_at  TEXT  -- when the santa said they have their gift
);
CREATE TABLE IF NOT EXISTS guesses (user_id INTEGER PRIMARY KEY, guess_id INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS archive (
    year TEXT, santa_id INTEGER, santa_name TEXT, giftee_id INTEGER, giftee_name TEXT, guessed_right INTEGER
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, due_utc TEXT NOT NULL, message TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULTS = {
    "phase": "signup",       # signup -> drawn -> revealed (after gift night's /santa-admin wrap-up)
    "signup_open": "1",
    "budget": "100",
    "event_name": "Secret Santa",
    "countdown": "1",
}

WISH_FIELDS = ("wish", "interests", "avoid", "sizes", "notes")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def q(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def run(self, sql, params=()):
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    # ---- settings ----
    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        if row:
            return row[0]
        return DEFAULTS.get(key, default)

    def set(self, key: str, value) -> None:
        if value is None:
            self.run("DELETE FROM settings WHERE key = ?", (key,))
        else:
            self.run("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))

    @property
    def phase(self) -> str:
        return self.get("phase")

    # ---- participants ----
    def participant(self, uid: int):
        return self.one("SELECT * FROM participants WHERE user_id = ?", (uid,))

    def participants(self):
        return self.q("SELECT * FROM participants ORDER BY name COLLATE NOCASE")

    def is_in(self, uid: int) -> bool:
        return self.participant(uid) is not None

    def name(self, uid: int) -> str:
        row = self.participant(uid)
        if row:
            return row["name"]
        row = self.one("SELECT santa_name FROM archive WHERE santa_id = ? ORDER BY year DESC", (uid,))
        return row[0] if row else f"user {uid}"

    def add_participant(self, uid: int, name: str) -> None:
        self.run(
            "INSERT OR IGNORE INTO participants (user_id, name, joined_at) VALUES (?, ?, ?)",
            (uid, name, utcnow()),
        )

    def update_name(self, uid: int, name: str) -> None:
        self.run("UPDATE participants SET name = ? WHERE user_id = ?", (name, uid))

    def set_dm_ok(self, uid: int, ok: bool) -> None:
        self.run("UPDATE participants SET dm_ok = ? WHERE user_id = ?", (int(ok), uid))

    def save_wishlist(self, uid: int, **fields) -> None:
        cols = [f for f in WISH_FIELDS if f in fields]
        sets = ", ".join(f"{c} = ?" for c in cols)
        self.run(f"UPDATE participants SET {sets} WHERE user_id = ?", [fields[c] or None for c in cols] + [uid])

    def has_wishlist(self, row) -> bool:
        return any(row[f] for f in WISH_FIELDS)

    def remove_participant(self, uid: int) -> None:
        for sql in (
            "DELETE FROM participants WHERE user_id = ?",
            "DELETE FROM date_votes WHERE user_id = ?",
            "DELETE FROM date_voters WHERE user_id = ?",
            "DELETE FROM history WHERE reporter_id = ?",
            "DELETE FROM santa_pool WHERE giftee_id = ? OR santa_id = ?",
            "DELETE FROM giftee_pool WHERE santa_id = ? OR giftee_id = ?",
            "DELETE FROM guesses WHERE user_id = ?",
        ):
            self.conn.execute(sql, (uid,) * sql.count("?"))
        self.conn.commit()

    # ---- date poll ----
    def date_options(self):
        return self.q("SELECT * FROM date_options ORDER BY day")

    def set_date_options(self, days: list[str]) -> None:
        """Replace the options. Votes for dates that stay on the list are kept."""
        for row in self.date_options():
            if row["day"] not in days:
                self.conn.execute("DELETE FROM date_votes WHERE option_id = ?", (row["id"],))
                self.conn.execute("DELETE FROM date_options WHERE id = ?", (row["id"],))
        self.conn.executemany("INSERT OR IGNORE INTO date_options (day) VALUES (?)", [(d,) for d in days])
        self.conn.commit()

    def set_votes(self, uid: int, option_ids: list[int]) -> None:
        self.conn.execute("DELETE FROM date_votes WHERE user_id = ?", (uid,))
        self.conn.executemany("INSERT INTO date_votes VALUES (?, ?)", [(uid, o) for o in option_ids])
        self.conn.execute("INSERT OR IGNORE INTO date_voters VALUES (?)", (uid,))
        self.conn.commit()

    def votes_of(self, uid: int) -> set[int]:
        return {r[0] for r in self.q("SELECT option_id FROM date_votes WHERE user_id = ?", (uid,))}

    def has_voted(self, uid: int) -> bool:
        return self.one("SELECT 1 FROM date_voters WHERE user_id = ?", (uid,)) is not None

    # ---- history & rules ----
    def history_of(self, uid: int):
        return self.q("SELECT santa_id, giftee_id FROM history WHERE reporter_id = ?", (uid,))

    def set_history(self, uid: int, i_had: list[int], had_me: list[int]) -> None:
        self.conn.execute("DELETE FROM history WHERE reporter_id = ?", (uid,))
        rows = [(uid, uid, g) for g in i_had] + [(uid, s, uid) for s in had_me]
        self.conn.executemany("INSERT OR IGNORE INTO history VALUES (?, ?, ?)", rows)
        self.conn.commit()

    def add_exclusion(self, a: int, b: int) -> None:
        self.run("INSERT OR IGNORE INTO exclusions VALUES (?, ?)", tuple(sorted((a, b))))

    def remove_exclusion(self, a: int, b: int) -> bool:
        return self.run("DELETE FROM exclusions WHERE a = ? AND b = ?", tuple(sorted((a, b)))).rowcount > 0

    def exclusions(self):
        return self.q("SELECT a, b FROM exclusions")

    def set_pool(self, giftee: int, santas: list[int]) -> None:
        self.conn.execute("DELETE FROM santa_pool WHERE giftee_id = ?", (giftee,))
        self.conn.executemany("INSERT INTO santa_pool VALUES (?, ?)", [(giftee, s) for s in santas])
        self.conn.commit()

    def clear_pool(self, giftee: int) -> bool:
        return self.run("DELETE FROM santa_pool WHERE giftee_id = ?", (giftee,)).rowcount > 0

    def pools(self) -> dict[int, set[int]]:
        """giftee -> the only people allowed to be their santa."""
        pools: dict[int, set[int]] = {}
        for giftee, santa in self.q("SELECT giftee_id, santa_id FROM santa_pool"):
            pools.setdefault(giftee, set()).add(santa)
        return pools

    def set_target_pool(self, santa: int, giftees: list[int]) -> None:
        self.conn.execute("DELETE FROM giftee_pool WHERE santa_id = ?", (santa,))
        self.conn.executemany("INSERT INTO giftee_pool VALUES (?, ?)", [(santa, g) for g in giftees])
        self.conn.commit()

    def clear_target_pool(self, santa: int) -> bool:
        return self.run("DELETE FROM giftee_pool WHERE santa_id = ?", (santa,)).rowcount > 0

    def target_pools(self) -> dict[int, set[int]]:
        """santa -> the only people they're allowed to give to."""
        pools: dict[int, set[int]] = {}
        for santa, giftee in self.q("SELECT santa_id, giftee_id FROM giftee_pool"):
            pools.setdefault(santa, set()).add(giftee)
        return pools

    def forbidden_pairs(self) -> set[tuple[int, int]]:
        forbidden = {(r[0], r[1]) for r in self.q("SELECT santa_id, giftee_id FROM history")}
        forbidden |= {(r[0], r[1]) for r in self.q("SELECT santa_id, giftee_id FROM archive")}
        for a, b in self.exclusions():
            forbidden |= {(a, b), (b, a)}
        return forbidden

    # ---- the draw ----
    def save_assignments(self, mapping: dict[int, int]) -> None:
        self.conn.execute("DELETE FROM assignments")
        self.conn.executemany("INSERT INTO assignments (santa_id, giftee_id) VALUES (?, ?)", mapping.items())
        self.conn.commit()

    def assignment_map(self) -> dict[int, int]:
        return {r[0]: r[1] for r in self.q("SELECT santa_id, giftee_id FROM assignments")}

    def apply_changes(self, new_map: dict[int, int], changed: list[int], removed: int | None = None) -> None:
        """Update only the santas whose giftee changed, keeping everyone else's gift-ready status."""
        if removed is not None:
            self.conn.execute("DELETE FROM assignments WHERE santa_id = ?", (removed,))
        for santa in changed:
            self.conn.execute("DELETE FROM assignments WHERE santa_id = ?", (santa,))
        for santa in changed:
            self.conn.execute(
                "INSERT INTO assignments (santa_id, giftee_id) VALUES (?, ?)", (santa, new_map[santa])
            )
        self.conn.commit()

    def giftee_of(self, santa: int) -> int | None:
        row = self.one("SELECT giftee_id FROM assignments WHERE santa_id = ?", (santa,))
        return row[0] if row else None

    def santa_of(self, giftee: int) -> int | None:
        row = self.one("SELECT santa_id FROM assignments WHERE giftee_id = ?", (giftee,))
        return row[0] if row else None

    def assignment(self, santa: int):
        return self.one("SELECT * FROM assignments WHERE santa_id = ?", (santa,))

    def assignments(self):
        return self.q("SELECT * FROM assignments")

    def mark_ready(self, santa: int) -> None:
        self.run("UPDATE assignments SET ready_at = ? WHERE santa_id = ?", (utcnow(), santa))

    # ---- guesses & archive ----
    def set_guess(self, uid: int, guess: int) -> None:
        self.run("INSERT OR REPLACE INTO guesses VALUES (?, ?)", (uid, guess))

    def guess_of(self, uid: int) -> int | None:
        row = self.one("SELECT guess_id FROM guesses WHERE user_id = ?", (uid,))
        return row[0] if row else None

    def archive_year(self, year: str) -> None:
        self.conn.execute("DELETE FROM archive WHERE year = ?", (year,))
        for a in self.assignments():
            guess = self.guess_of(a["giftee_id"])
            self.conn.execute(
                "INSERT INTO archive VALUES (?, ?, ?, ?, ?, ?)",
                (year, a["santa_id"], self.name(a["santa_id"]), a["giftee_id"], self.name(a["giftee_id"]),
                 int(guess == a["santa_id"]) if guess is not None else None),
            )
        self.conn.commit()

    def new_season(self) -> None:
        """Clear this year's data. Keeps exclusions (couples etc.) and the archive (so repeats stay blocked)."""
        for table in ("participants", "date_options", "date_votes", "date_voters", "history",
                      "santa_pool", "giftee_pool", "assignments", "guesses", "reminders"):
            self.conn.execute(f"DELETE FROM {table}")
        keep = ("budget", "event_name", "venue", "channel_id", "countdown")
        self.conn.execute(
            f"DELETE FROM settings WHERE key NOT IN ({','.join('?' * len(keep))})", keep
        )
        self.conn.commit()

    # ---- reminders ----
    def add_reminder(self, due_utc: str, message: str) -> int:
        return self.run("INSERT INTO reminders (due_utc, message) VALUES (?, ?)", (due_utc, message)).lastrowid

    def pending_reminders(self):
        return self.q("SELECT * FROM reminders WHERE sent = 0 ORDER BY due_utc")

    def due_reminders(self, now_utc: str):
        return self.q("SELECT * FROM reminders WHERE sent = 0 AND due_utc <= ?", (now_utc,))

    def mark_reminder_sent(self, rid: int) -> None:
        self.run("UPDATE reminders SET sent = 1 WHERE id = ?", (rid,))

    def cancel_reminder(self, rid: int) -> bool:
        return self.run("DELETE FROM reminders WHERE id = ? AND sent = 0", (rid,)).rowcount > 0
