"""Shared look-and-feel: colors, buttons, embeds, and date parsing."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

import discord

from . import config

RED = discord.Color.from_rgb(196, 30, 58)
GREEN = discord.Color.from_rgb(22, 125, 74)
GOLD = discord.Color.from_rgb(212, 160, 23)

# Every button the bot ever posts. Clicks are routed by custom_id (see actions.ROUTES),
# so they keep working after the bot restarts, even on old messages.
BUTTONS = {
    "join":       ("santa:join",        "Join",                   "🎁", discord.ButtonStyle.success),
    "leave":      ("santa:leave",       "Leave",                  "👋", discord.ButtonStyle.secondary),
    "leave_yes":  ("santa:leave_yes",   "Yes, leave",             "👋", discord.ButtonStyle.danger),
    "leave_no":   ("santa:leave_no",    "Stay in",                "🎁", discord.ButtonStyle.success),
    "wishlist":   ("santa:wishlist",    "My wishlist",            "📝", discord.ButtonStyle.primary),
    "dates":      ("santa:dates",       "Pick dates",             "📅", discord.ButtonStyle.primary),
    "my_giftee":  ("santa:my_giftee",   "Who do I have?",         "🎅", discord.ButtonStyle.primary),
    "msg_giftee": ("santa:msg_giftee",  "Message my giftee",      "💌", discord.ButtonStyle.primary),
    "msg_santa":  ("santa:msg_santa",   "Message my Santa",       "🎅", discord.ButtonStyle.primary),
    "ready":      ("santa:ready",       "I've got my gift",       "🎁", discord.ButtonStyle.success),
    "reply_santa":  ("santa:msg_santa",  "Reply to my Santa",     "↩️", discord.ButtonStyle.primary),
    "reply_giftee": ("santa:msg_giftee", "Reply to my giftee",    "↩️", discord.ButtonStyle.primary),
}


def buttons(*keys: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for key in keys:
        custom_id, label, emoji, style = BUTTONS[key]
        view.add_item(discord.ui.Button(custom_id=custom_id, label=label, emoji=emoji, style=style))
    return view


def embed(title: str, description: str = "", color=RED) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def mention(uid: int) -> str:
    return f"<@{uid}>"


def budget_text(db) -> str:
    return f"${db.get('budget')}"


def add_wishlist_fields(e: discord.Embed, row) -> discord.Embed:
    labels = {
        "wish": "🎁 Would love",
        "interests": "✨ Interests & hobbies",
        "avoid": "🚫 Please avoid",
        "sizes": "📏 Sizes",
        "notes": "📝 Other notes",
    }
    any_filled = False
    for key, label in labels.items():
        if row[key]:
            e.add_field(name=label, value=row[key][:1024], inline=False)
            any_filled = True
    if not any_filled:
        e.add_field(name="📝 Wishlist", value="*Nothing yet — try messaging them anonymously to ask!*", inline=False)
    return e


def event_lines(db) -> list[str]:
    """Budget / date / venue lines used in a few embeds."""
    lines = [f"💰 **Budget:** {budget_text(db)}"]
    if db.get("event_date"):
        lines.append(f"🗓️ **Gift night:** {fmt_day(db.get('event_date'))}")
    if db.get("venue"):
        lines.append(f"📍 **Where:** {db.get('venue')}")
    return lines


def where_and_when(db) -> str:
    """'to The Last Straw on Fri, Dec 18' — whatever parts are set."""
    parts = []
    if db.get("venue"):
        parts.append(f"to **{db.get('venue')}**")
    if db.get("event_date"):
        parts.append(f"on **{fmt_day(db.get('event_date'))}**")
    return " ".join(parts) or "on gift night"


def giftee_embed(db, santa_id: int) -> discord.Embed:
    giftee = db.participant(db.giftee_of(santa_id))
    e = embed(f"🎅 You're the Secret Santa for… {giftee['name']}!", color=GREEN)
    e.description = (
        "\n".join(event_lines(db))
        + f"\n\nBring your wrapped gift {where_and_when(db)}. "
        "Keep it secret! 🤫 Use the buttons below to message them anonymously."
    )
    return add_wishlist_fields(e, giftee)


SECRET_BUTTONS = ("my_giftee", "msg_giftee", "msg_santa", "ready")


# ---- dates ----
_DAY_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d %Y", "%B %d %Y")
_DAY_FORMATS_NO_YEAR = ("%m/%d", "%b %d", "%B %d")
_TIME_FORMATS = ("%H:%M", "%I:%M%p", "%I%p")


def today() -> date:
    return datetime.now(config.TIMEZONE).date()


def parse_day(text: str) -> date:
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip().replace(",", " "))
    text = re.sub(r"^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+", "", text, flags=re.I)
    text = " ".join(text.split())
    for fmt in _DAY_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    for fmt in _DAY_FORMATS_NO_YEAR:
        try:
            d = datetime.strptime(f"{text} 2000", f"{fmt} %Y").date()
        except ValueError:
            continue
        d = d.replace(year=today().year)
        return d.replace(year=d.year + 1) if d < today() - timedelta(days=60) else d
    raise ValueError(f"I couldn't read the date “{text}”. Try something like 2026-12-18 or Dec 18.")


def parse_when(text: str) -> datetime:
    """'Dec 10 6pm', '2026-12-10 18:00', 'Dec 10' (noon) -> aware datetime in the configured timezone."""
    parts = text.strip().split()
    t = time(12, 0)
    if len(parts) > 1:
        tail = parts[-1].lower().replace(".", "")
        for fmt in _TIME_FORMATS:
            try:
                t = datetime.strptime(tail, fmt).time()
                parts = parts[:-1]
                break
            except ValueError:
                pass
    d = parse_day(" ".join(parts))
    return datetime.combine(d, t, tzinfo=config.TIMEZONE)


def fmt_day(iso: str | None) -> str:
    if not iso:
        return "not set"
    d = date.fromisoformat(iso)
    return f"{d:%a, %b} {d.day}"


def fmt_when(dt_utc_iso: str) -> str:
    dt = datetime.fromisoformat(dt_utc_iso).astimezone(config.TIMEZONE)
    return f"{dt:%a, %b} {dt.day} at {dt:%I:%M %p}".replace(" 0", " ")


def to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def fridays_and_saturdays_before_christmas() -> list[str]:
    year = today().year if today() <= date(today().year, 12, 24) else today().year + 1
    days = []
    d = date(year, 12, 1)
    while d < date(year, 12, 25):
        if d.weekday() in (4, 5):
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days
