"""Commands for after the draw: messaging, gift-ready, guessing, gift ideas."""
from __future__ import annotations

import logging

import anthropic
import discord
from discord import app_commands
from discord.ext import commands

from .. import actions, ui
from ..actions import reply

log = logging.getLogger("santa")

GIFT_IDEAS_SYSTEM = (
    "You help someone in a Discord Secret Santa pick a gift for a friend. Gifts are wrapped and "
    "handed over in person at a group get-together. Suggest 5 specific, "
    "thoughtful gift ideas that fit within the budget, based only on the wishlist info provided. "
    "Respect anything listed under 'please avoid'. For each idea give one line: the idea in bold, "
    "a rough price, and a few words on why it fits. Mix safe picks with one or two creative ones. "
    "Keep the whole reply under 1200 characters and use Discord markdown. No intro or sign-off."
)


class Secret(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="my-giftee", description="See who you're Secret Santa for, and their wishlist 🤫")
    async def my_giftee(self, interaction: discord.Interaction):
        await actions.show_my_giftee(interaction)

    @app_commands.command(name="message-giftee", description="Send an anonymous message to the person you're gifting 💌")
    @app_commands.describe(message="What to say (they won't know it's you)")
    async def message_giftee(self, interaction: discord.Interaction, message: str):
        await actions.relay_message(interaction, "giftee", message)

    @app_commands.command(name="message-santa", description="Send a message to your Secret Santa 🎅")
    @app_commands.describe(message="What to say to whoever has you")
    async def message_santa(self, interaction: discord.Interaction, message: str):
        await actions.relay_message(interaction, "santa", message)

    @app_commands.command(name="gift-ready", description="Tell me you've got your gift 🎁 (stops the reminders; your giftee isn't told)")
    async def gift_ready(self, interaction: discord.Interaction):
        await actions.mark_ready(interaction)

    @app_commands.command(name="guess", description="Guess who your Secret Santa is! Locks on gift night 🕵️")
    @app_commands.describe(person="Who you think has you")
    async def guess(self, interaction: discord.Interaction, person: discord.User):
        if not await actions.require_drawn(interaction):
            return
        event = self.db.get("event_date")
        if event and ui.today().isoformat() >= event:
            await reply(interaction, "🔒 Guesses are locked — it's gift night!")
            return
        if person.id == interaction.user.id:
            await reply(interaction, "You can't be your own Santa. 😄")
            return
        if not self.db.is_in(person.id):
            await reply(interaction, f"{person.display_name} isn't in Secret Santa this year!")
            return
        had = self.db.guess_of(interaction.user.id)
        self.db.set_guess(interaction.user.id, person.id)
        verb = "Changed your guess to" if had else "Locked in your guess:"
        await reply(interaction, f"🕵️ {verb} **{self.db.name(person.id)}**. We'll find out on gift night!")

    @app_commands.command(name="gift-ideas", description="Get AI gift ideas for your giftee, based on their wishlist 💡")
    @app_commands.describe(hint="Anything extra you know about them, e.g. 'just got a new puppy'")
    @app_commands.checks.cooldown(1, 30)
    async def gift_ideas(self, interaction: discord.Interaction, hint: str | None = None):
        if not await actions.require_drawn(interaction):
            return
        if self.bot.claude is None:
            await reply(interaction, "Gift ideas aren't switched on — the organizer needs to add an "
                                     "`ANTHROPIC_API_KEY` to the bot's settings.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        giftee = self.db.participant(self.db.giftee_of(interaction.user.id))
        about = [f"Budget: {ui.budget_text(self.db)} (USD)"]
        for key, label in (("wish", "Would love"), ("interests", "Interests"), ("avoid", "Please avoid"),
                           ("sizes", "Sizes"), ("notes", "Other notes")):
            if giftee[key]:
                about.append(f"{label}: {giftee[key]}")
        if hint:
            about.append(f"Extra info from their Santa: {hint}")
        if len(about) == 1:
            about.append("(They haven't filled in a wishlist, so suggest crowd-pleasers that suit most people.)")

        try:
            response = await self.bot.claude.beta.messages.create(
                model="claude-opus-5-5",
                max_tokens=2000,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=GIFT_IDEAS_SYSTEM,
                messages=[{"role": "user", "content": "\n".join(about)}],
            )
        except anthropic.RateLimitError:
            await reply(interaction, "🧠 Too many people asking at once — try again in a minute.")
            return
        except anthropic.APIStatusError as e:
            log.error("Gift ideas API error %s: %s", e.status_code, e.message)
            await reply(interaction, "😵 The gift-idea brain is having a moment. Try again later.")
            return
        except anthropic.APIConnectionError:
            await reply(interaction, "😵 Couldn't reach the gift-idea brain. Try again later.")
            return

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "refusal" or not text:
            await reply(interaction, "Couldn't come up with ideas for that one — try a different hint?")
            return
        e = ui.embed(f"💡 Gift ideas for {giftee['name']}", text[:4000], ui.GOLD)
        e.set_footer(text=f"Budget {ui.budget_text(self.db)} · AI suggestions, double-check prices!")
        await reply(interaction, embed=e)

    @app_commands.command(name="hall-of-fame", description="Past Secret Santa years 🏆")
    async def hall_of_fame(self, interaction: discord.Interaction):
        years = self.db.q(
            "SELECT year, COUNT(*) AS n, SUM(guessed_right) AS right FROM archive GROUP BY year ORDER BY year DESC"
        )
        if not years:
            await reply(interaction, "No past years yet — this is the first one! 🎄")
            return
        e = ui.embed("🏆 Secret Santa Hall of Fame", color=ui.GOLD)
        for y in years:
            e.add_field(name=f"🎄 {y['year']}",
                        value=f"👥 {y['n']} people · 🕵️ {y['right'] or 0} guessed their Santa", inline=False)
        lines: dict[str, list[str]] = {}
        for r in self.db.q("SELECT * FROM archive WHERE santa_id = ?", (interaction.user.id,)):
            lines.setdefault(r["year"], []).append(f"you gave to **{r['giftee_name']}**")
        for r in self.db.q("SELECT * FROM archive WHERE giftee_id = ?", (interaction.user.id,)):
            lines.setdefault(r["year"], []).append(f"**{r['santa_name']}** gave to you")
        if lines:
            e.add_field(name="Your history",
                        value="\n".join(f"{y}: " + ", ".join(v) for y, v in sorted(lines.items(), reverse=True)),
                        inline=False)
        await reply(interaction, embed=e)


async def setup(bot):
    await bot.add_cog(Secret(bot))
