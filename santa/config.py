"""Reads settings from the .env file next to bot.py."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _id(name: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw.isdigit():
        raise SystemExit(f"{name} is missing or isn't a number in your .env file. See README.md.")
    return int(raw)


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = _id("GUILD_ID")
ORGANIZER_ID = _id("ORGANIZER_ID")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "America/New_York").strip())
DAILY_POST_HOUR = int(os.getenv("DAILY_POST_HOUR", "10"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip() or None
DB_PATH = ROOT / "santa.db"
