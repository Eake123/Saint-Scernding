"""Secret Santa bot. Run with start.bat (or: .venv\\Scripts\\python bot.py).
For always-on use, run install_autostart.ps1 once instead — it keeps the bot running via supervisor.py."""
import logging
import sys

import anthropic
import discord
from discord import app_commands
from discord.ext import commands

from santa import config, runtime
from santa.actions import reply
from santa.db import DB
from santa.errors import NotOrganizer

log = logging.getLogger("santa")


class SantaBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.db = DB(config.DB_PATH)
        self.claude = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self):
        for ext in ("participant", "secret", "admin", "scheduler"):
            await self.load_extension(f"santa.cogs.{ext}")
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Synced %d slash commands to your server", len(synced))

    async def on_ready(self):
        log.info("🎅 Logged in as %s — ready!", self.user)
        if not self.get_guild(config.GUILD_ID):
            log.warning("I'm not in the server with GUILD_ID=%s yet. Use the invite link from README.md.", config.GUILD_ID)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, NotOrganizer):
            msg = "🎅 Only the Secret Santa organizer can use that!"
            log.info("Blocked %s from an organizer-only command", interaction.user)
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Slow down! Try again in {error.retry_after:.0f}s."
        else:
            log.exception("Command failed", exc_info=error)
            msg = "😵 Something went wrong. Try again, or tell the organizer."
        try:
            await reply(interaction, msg)
        except discord.HTTPException:
            pass


def main():
    lock = runtime.acquire_lock("bot.lock")
    if lock is None:
        print("Saint Scernding is already running on this computer (probably started automatically). "
              "Close that one first if you want to run it here.", file=sys.stderr)
        sys.exit(runtime.EXIT_ALREADY_RUNNING)
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing from your .env file. See README.md.")

    discord.utils.setup_logging(handler=runtime.file_handler("santa.log"), level=logging.INFO)
    if runtime.has_console():
        discord.utils.setup_logging(level=logging.INFO)
    runtime.quiet_voice_warnings()
    SantaBot().run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
