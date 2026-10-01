"""Shared exception types.

Kept out of santa/cogs/ on purpose: discord.py's load_extension() executes each cog module afresh,
so a class defined in a cog is a *different* class from the one bot.py imports — isinstance() checks fail.
"""
from discord import app_commands


class NotOrganizer(app_commands.CheckFailure):
    pass
