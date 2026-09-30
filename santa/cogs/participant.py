"""Commands everyone can use before the draw, plus the button router."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import actions, ui
from ..actions import reply

log = logging.getLogger("santa")


class Participant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        handler = actions.ROUTES.get((interaction.data or {}).get("custom_id", ""))
        if not handler:
            return
        try:
            await handler(interaction)
        except Exception:
            log.exception("Button handler failed")
            try:
                await reply(interaction, "😵 Something went wrong. Try again, or tell the organizer.")
            except discord.HTTPException:
                pass

    @app_commands.command(name="join", description="Join this year's Secret Santa 🎁")
    async def join(self, interaction: discord.Interaction):
        await actions.join(interaction)

    @app_commands.command(name="leave", description="Drop out of Secret Santa (before names are drawn)")
    async def leave(self, interaction: discord.Interaction):
        await actions.leave(interaction)

    @app_commands.command(name="wishlist", description="Fill in or update your wishlist 📝")
    async def wishlist(self, interaction: discord.Interaction):
        await actions.open_wishlist(interaction)

    @app_commands.command(name="dates", description="Pick which dates you can make for gift night 📅")
    async def dates(self, interaction: discord.Interaction):
        await actions.open_date_picker(interaction)

    @app_commands.command(name="history", description="Who you've had, and who's had you, in past years (so there are no repeats)")
    @app_commands.describe(
        i_had="Someone you were Secret Santa for before",
        i_had_2="Another person you were Secret Santa for",
        had_me="Someone who was YOUR Secret Santa before",
        had_me_2="Another person who was your Secret Santa",
    )
    async def history(self, interaction: discord.Interaction,
                      i_had: discord.User | None = None, i_had_2: discord.User | None = None,
                      had_me: discord.User | None = None, had_me_2: discord.User | None = None):
        if not await actions.require_participant(interaction):
            return
        uid = interaction.user.id
        if self.db.phase != "signup":
            await reply(interaction, "Names have already been drawn, so history is locked in for this year.")
            return
        gave = list(dict.fromkeys(u.id for u in (i_had, i_had_2) if u))
        got = list(dict.fromkeys(u.id for u in (had_me, had_me_2) if u))
        if uid in gave + got:
            await reply(interaction, "You can't have been your own Secret Santa. 😄")
            return
        if any(u.bot for u in (i_had, i_had_2, had_me, had_me_2) if u):
            await reply(interaction, "Bots don't do Secret Santa. 🤖")
            return

        if not gave and not got:
            current = self.db.history_of(uid)
            if current:
                lines = [f"🎁 You had {ui.mention(g)}" if s == uid else f"🎅 {ui.mention(s)} had you" for s, g in current]
                await reply(interaction, "**Your history on file:**\n" + "\n".join(lines) +
                            "\n\nRun `/history` again with new names to replace it.")
            else:
                await reply(interaction, "You haven't told me any history yet. Fill in the options on `/history` "
                                         "(up to 2 people you had, and 2 who had you).")
            return

        self.db.set_history(uid, gave, got)
        lines = [f"🎁 You won't get {ui.mention(g)} again" for g in gave]
        lines += [f"🎅 {ui.mention(s)} won't get you again" for s in got]
        await reply(interaction, "🕰️ **Saved!**\n" + "\n".join(lines) +
                    "\n\n*(Running `/history` again replaces this list.)*",
                    allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="santa", description="Your Secret Santa status, deadlines, and what to do next 🎄")
    async def santa(self, interaction: discord.Interaction):
        db = self.db
        e = ui.embed(f"🎄 {db.get('event_name')}")
        info = ui.event_lines(db) + [f"👥 **Participants:** {len(db.participants())}"]
        e.description = "\n".join(info)

        row = db.participant(interaction.user.id)
        if not row:
            e.add_field(name="You", value="Not signed up yet — use `/join`!", inline=False)
            await reply(interaction, embed=e)
            return

        check = lambda ok: "✅" if ok else "⬜"
        todo = [
            f"{check(db.has_wishlist(row))} Wishlist (`/wishlist`)",
            f"{check(db.has_voted(row['user_id']) or not db.date_options())} Dates (`/dates`)",
            f"{check(bool(db.history_of(row['user_id'])))} Past pairings (`/history`, optional)",
            f"{check(row['dm_ok'])} DMs open so I can reach you",
        ]
        if db.phase == "drawn":
            mine = db.assignment(row["user_id"])
            if mine:
                todo += [
                    f"{check(mine['ready_at'])} Got your gift (`/gift-ready`)",
                    f"{check(db.guess_of(row['user_id']))} Guessed your Santa (`/guess`)",
                ]
        e.add_field(name="Your checklist", value="\n".join(todo), inline=False)
        keys = ("my_giftee", "msg_giftee", "msg_santa") if db.phase == "drawn" else ("wishlist", "dates")
        await reply(interaction, embed=e, view=ui.buttons(*keys))


async def setup(bot):
    await bot.add_cog(Participant(bot))
