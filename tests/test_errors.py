import importlib.util
import os

os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("ORGANIZER_ID", "100")

from santa.errors import NotOrganizer  # noqa: E402


def test_not_organizer_survives_extension_loading():
    # discord.py's load_extension executes the cog module afresh; the error it raises must still
    # be the same class bot.py's error handler checks for.
    spec = importlib.util.find_spec("santa.cogs.admin")
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.NotOrganizer is NotOrganizer
