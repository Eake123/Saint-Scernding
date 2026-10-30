"""/santa-admin … — organizer-only commands. Nothing here ever shows you who has whom."""
from __future__ import annotations

import csv
import io
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from .. import actions, config, ui
from ..actions import reply, send_dm
from ..draw import DrawError, add_person, draw, make_allowed, remove_person
from ..errors import NotOrganizer
from ..intro import intro_embeds, intro_view

log = logging.getLogger("santa")


class Confirm(discord.ui.View):
    """Yes/Cancel buttons on an ephemeral message."""

    def __init__(self, on_yes, label: str, style=discord.ButtonStyle.danger):
        super().__init__(timeout=300)
        yes = discord.ui.Button(label=label, style=style)
        no = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        async def yes_cb(interaction: discord.Interaction):
            self.stop()
            await interaction.response.edit_message(view=None)
            await on_yes(interaction)

        async def no_cb(interaction: discord.Interaction):
            self.stop()
            await interaction.response.edit_message(content="Cancelled. 👍", embed=None, view=None)

        yes.callback, no.callback = yes_cb, no_cb
        self.add_item(yes)
        self.add_item(no)


class AnnounceModal(discord.ui.Modal, title="📣 Announcement"):
    def __init__(self, cog, ping: bool):
        super().__init__()
        self.cog, self.ping = cog, ping
        self.heading = discord.ui.TextInput(label="Title", max_length=200, default="🎄 Secret Santa update")
        self.body = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=3500)
        self.add_item(self.heading)
        self.add_item(self.body)

    async def on_submit(self, interaction: discord.Interaction):
        channel = await self.cog.channel(interaction)
        await channel.send(
            content="@everyone" if self.ping else None,
            embed=ui.embed(self.heading.value, self.body.value),
            allowed_mentions=discord.AllowedMentions(everyone=self.ping),
        )
        await reply(interaction, f"📣 Posted in {channel.mention}.")


class Admin(commands.GroupCog, group_name="santa-admin", group_description="Organizer tools for Secret Santa"):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != config.ORGANIZER_ID:
            raise NotOrganizer()
        return True

    # ------------------------------------------------------------ helpers
    async def channel(self, interaction: discord.Interaction | None = None):
        cid = self.db.get("channel_id")
        if cid:
            ch = self.bot.get_channel(int(cid))
            if ch:
                return ch
        if interaction is not None:
            self.db.set("channel_id", interaction.channel_id)
            return interaction.channel
        return None

    def allowed(self):
        people = {p["user_id"] for p in self.db.participants()}

        def active(raw: dict[int, set[int]]) -> dict[int, set[int]]:
            # ignore people who've left; a pool with nobody left in it no longer restricts anything
            return {k: v & people for k, v in raw.items() if k in people and v & people}

        return make_allowed(self.db.forbidden_pairs(), active(self.db.pools()), active(self.db.target_pools()))

    def names(self, ids) -> str:
        return ", ".join(f"**{self.db.name(i)}**" for i in ids) or "nobody"

    def try_draw(self):
        people = [p["user_id"] for p in self.db.participants()]
        return draw(people, self.allowed())

    def draw_error_text(self, err: DrawError) -> str:
        text = f"❌ {err}"
        if err.stuck:
            text += (f"\n\nNobody is allowed to be the Santa for: {self.names(err.stuck)}.\n"
                     "Check their `/history`, exclusions, and suggestion pool (`/santa-admin rules`).")
        return text

    # ------------------------------------------------------------ setup & sign-ups
    @app_commands.command(name="setup", description="Set the channel, budget, gift night date, venue and name")
    @app_commands.describe(
        channel="Where announcements, reminders and the wrap-up get posted",
        budget="Gift budget in dollars",
        event_date="The night everyone meets up to hand over gifts, e.g. Dec 19",
        venue="Where you're meeting, e.g. a bar or someone's place",
        event_name="e.g. 'Secret Santa 2026'",
        countdown="Post a countdown 30, 15 and 5 days before gift night, and on the day",
    )
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None,
                    budget: app_commands.Range[int, 1, 10000] | None = None, event_date: str | None = None,
                    venue: str | None = None, event_name: str | None = None, countdown: bool | None = None):
        db = self.db
        if event_date:
            try:
                db.set("event_date", ui.parse_day(event_date).isoformat())
            except ValueError as e:
                await reply(interaction, f"❌ {e}")
                return
            db.set("nudged_3", None)
            db.set("nudged_1", None)
        if channel:
            db.set("channel_id", channel.id)
        if budget:
            db.set("budget", budget)
        if venue:
            db.set("venue", venue[:100])
        if event_name:
            db.set("event_name", event_name[:100])
        if countdown is not None:
            db.set("countdown", int(countdown))

        ch = db.get("channel_id")
        e = ui.embed("⚙️ Secret Santa settings", color=ui.GOLD)
        e.description = "\n".join([
            f"**Name:** {db.get('event_name')}",
            f"**Channel:** {f'<#{ch}>' if ch else 'not set (uses wherever you run commands)'}",
            f"**Budget:** {ui.budget_text(db)}",
            f"**Gift night:** {ui.fmt_day(db.get('event_date'))}",
            f"**Venue:** {db.get('venue') or 'not set'}",
            f"**Countdown (30/15/5 days + day of):** {'on' if db.get('countdown') == '1' else 'off'} "
            f"(posts at {config.DAILY_POST_HOUR}:00, {config.TIMEZONE.key})",
            f"**Phase:** {db.phase} · sign-ups {'open' if db.get('signup_open') == '1' else 'closed'}",
        ])
        await reply(interaction, embed=e)
        await actions.refresh_signup_panel(self.bot)

    async def _post_panel(self, channel) -> None:
        msg = await channel.send(embed=actions.signup_panel_embed(self.db),
                                 view=ui.buttons("join", "wishlist", "dates", "leave"))
        self.db.set("panel_channel_id", channel.id)
        self.db.set("panel_message_id", msg.id)

    @app_commands.command(name="intro", description="Post the big hype explainer 🎉 (+ the sign-up panel under it)")
    @app_commands.describe(channel="Where to post it (defaults to the Secret Santa channel, or here)",
                           with_signup="Also post the live sign-up panel underneath (default yes)")
    async def intro(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None,
                    with_signup: bool = True):
        channel = channel or await self.channel(interaction)
        try:
            await channel.send(embeds=intro_embeds(self.db), view=intro_view())
            if with_signup:
                await self._post_panel(channel)
        except discord.Forbidden:
            await reply(interaction, f"❌ I don't have permission to post in {channel.mention}.")
            return
        await reply(interaction, f"🎉 Intro posted in {channel.mention}. Tip: set `venue`, `budget` and "
                                 "`event_date` with `/santa-admin setup` first so the intro shows them.")

    @app_commands.command(name="post-signup", description="Post the sign-up panel with a Join button")
    @app_commands.describe(channel="Where to post it (defaults to the Secret Santa channel, or here)")
    async def post_signup(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        channel = channel or await self.channel(interaction)
        try:
            await self._post_panel(channel)
        except discord.Forbidden:
            await reply(interaction, f"❌ I don't have permission to post in {channel.mention}.")
            return
        await reply(interaction, f"✅ Sign-up panel posted in {channel.mention}. The counter on it updates live.")

    @app_commands.command(name="signups", description="Open or close sign-ups")
    @app_commands.choices(state=[
        app_commands.Choice(name="open", value="open"), app_commands.Choice(name="closed", value="closed"),
    ])
    async def signups(self, interaction: discord.Interaction, state: app_commands.Choice[str]):
        self.db.set("signup_open", "1" if state.value == "open" else "0")
        await reply(interaction, f"Sign-ups are now **{state.value}**.")
        await actions.refresh_signup_panel(self.bot)

    @app_commands.command(name="roster", description="See everyone who's joined (and what they still need to do)")
    async def roster(self, interaction: discord.Interaction):
        db = self.db
        people = db.participants()
        if not people:
            await reply(interaction, "Nobody has joined yet. Post the sign-up panel with `/santa-admin post-signup`!")
            return
        has_dates = bool(db.date_options())
        lines, rows = [], []
        for i, p in enumerate(people, 1):
            wish, voted, hist = db.has_wishlist(p), db.has_voted(p["user_id"]), bool(db.history_of(p["user_id"]))
            flags = ("📝" if wish else "⬜") + (("📅" if voted else "⬜") if has_dates else "") + ("🕰️" if hist else "")
            lines.append(f"`{i:>2}.` {ui.mention(p['user_id'])} {flags}{'' if p['dm_ok'] else ' ⚠️ DMs closed'}")
            rows.append([p["name"], str(p["user_id"]), p["joined_at"][:10], wish, voted, hist, bool(p["dm_ok"])])

        e = ui.embed(f"👥 Roster — {len(people)} people", "\n".join(lines)[:4000], ui.GOLD)
        e.set_footer(text="📝 wishlist · 📅 voted on dates · 🕰️ gave past history · ⬜ not done yet")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["name", "user_id", "joined", "wishlist", "voted_dates", "history", "dms_open"])
        w.writerows(rows)
        file = discord.File(io.BytesIO(buf.getvalue().encode()), filename="secret-santa-roster.csv")
        await reply(interaction, embed=e, file=file)

    @app_commands.command(name="add", description="Add someone yourself (works even after the draw)")
    async def add(self, interaction: discord.Interaction, person: discord.Member):
        db = self.db
        if person.bot or db.is_in(person.id):
            await reply(interaction, f"{person.display_name} is {'a bot' if person.bot else 'already in'}!")
            return
        if db.phase == "signup":
            db.add_participant(person.id, person.display_name)
            await reply(interaction, f"✅ Added **{person.display_name}**. They can use `/wishlist` and `/dates`.")
            await send_dm(self.bot, person.id, embed=ui.embed(
                "🎄 You've been added to Secret Santa!",
                "The organizer signed you up. Use `/wishlist` and `/dates` in the server to get set up.", ui.GREEN))
            await actions.refresh_signup_panel(self.bot)
            return
        if db.phase != "drawn":
            await reply(interaction, "This year's Secret Santa is already over!")
            return

        db.add_participant(person.id, person.display_name)
        try:
            new_map, changed = add_person(db.assignment_map(), person.id, self.allowed())
        except DrawError as err:
            db.remove_participant(person.id)
            await reply(interaction, f"❌ {err}")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        db.apply_changes(new_map, changed)
        for santa in changed:
            title = "🎄 You've been added to Secret Santa!" if santa == person.id else "🔄 Change of plans!"
            note = ("The organizer added you after names were drawn."
                    if santa == person.id else "Someone joined late, so your giftee has changed. Sorry for the switcheroo!")
            await send_dm(self.bot, santa, embed=ui.embed(title, note, ui.GOLD))
            msg = await actions.giftee_message(db, santa, None if santa == person.id else "🔄 Your NEW Secret Santa mission 🎅")
            await send_dm(self.bot, santa, view=ui.buttons(*ui.SECRET_BUTTONS), **msg)
        others = len(changed) - 1
        await reply(interaction, f"✅ Added **{person.display_name}** and quietly slotted them into the draw. "
                                 f"{others} other {'person' if others == 1 else 'people'} got a new giftee "
                                 "(I didn't tell you who) 🤫")

    @app_commands.command(name="remove", description="Take someone out (works even after the draw)")
    async def remove(self, interaction: discord.Interaction, person: discord.User):
        db = self.db
        if not db.is_in(person.id):
            await reply(interaction, f"{person.display_name} isn't signed up.")
            return
        if db.phase != "drawn":
            db.remove_participant(person.id)
            await reply(interaction, f"✅ Removed **{person.display_name}**.")
            await actions.refresh_signup_panel(self.bot)
            return

        async def go(inter: discord.Interaction):
            try:
                new_map, changed = remove_person(db.assignment_map(), person.id, self.allowed())
            except DrawError as err:
                await reply(inter, f"❌ {err}")
                return
            db.apply_changes(new_map, changed, removed=person.id)
            db.remove_participant(person.id)
            for santa in changed:
                await send_dm(self.bot, santa, embed=ui.embed(
                    "🔄 Change of plans!", "Someone had to drop out, so you have a new giftee. "
                    "If you already bought something, message the organizer.", ui.GOLD))
                msg = await actions.giftee_message(db, santa, "🔄 Your NEW Secret Santa mission 🎅")
                await send_dm(self.bot, santa, view=ui.buttons(*ui.SECRET_BUTTONS), **msg)
            await reply(inter, f"✅ Removed **{person.display_name}** and patched up the draw. "
                               f"{len(changed)} {'person has' if len(changed) == 1 else 'people have'} a new giftee "
                               "(I didn't tell you who) 🤫")

        await reply(interaction, f"Names are already drawn. Remove **{person.display_name}** and re-shuffle "
                                 "just enough people to cover the gap?",
                    view=Confirm(go, "Remove them"))

    # ------------------------------------------------------------ dates
    @app_commands.command(name="dates", description="Set the gift-night date options and post the poll")
    @app_commands.describe(
        dates="Comma-separated, e.g. 'Dec 11, Dec 12, Dec 18'. Leave empty for every Fri & Sat in December before Christmas",
        post="Post the poll in the Secret Santa channel (default yes)",
    )
    async def dates(self, interaction: discord.Interaction, dates: str | None = None, post: bool = True):
        try:
            days = (sorted({ui.parse_day(d).isoformat() for d in re.split(r"[,;\n]+", dates) if d.strip()})
                    if dates else ui.fridays_and_saturdays_before_christmas())
        except ValueError as e:
            await reply(interaction, f"❌ {e}")
            return
        if not 1 <= len(days) <= 24:
            await reply(interaction, "Please give between 1 and 24 dates.")
            return
        self.db.set_date_options(days)
        listed = "\n".join(f"📅 {ui.fmt_day(d)}" for d in days)
        if post:
            channel = await self.channel(interaction)
            where = f" at {self.db.get('venue')}" if self.db.get("venue") else ""
            e = ui.embed(f"📅 When should gift night{where} be?",
                         f"{listed}\n\nHit the button and pick **every** date you can make. "
                         "You can change your answer any time.", ui.GREEN)
            await channel.send(embed=e, view=ui.buttons("dates"))
        await reply(interaction, f"✅ Date options set{' and poll posted' if post else ''}:\n{listed}\n\n"
                                 "See results with `/santa-admin date-results`.")

    @app_commands.command(name="date-results", description="See which date works best for everyone")
    async def date_results(self, interaction: discord.Interaction):
        db = self.db
        options = db.date_options()
        if not options:
            await reply(interaction, "No date options yet — set them with `/santa-admin dates`.")
            return
        people = {p["user_id"] for p in db.participants()}
        voters = {r[0] for r in db.q("SELECT user_id FROM date_voters")} & people
        results = []
        for o in options:
            yes = {r[0] for r in db.q("SELECT user_id FROM date_votes WHERE option_id = ?", (o["id"],))} & voters
            results.append((len(yes), o["day"], voters - yes))
        results.sort(key=lambda r: (-r[0], r[1]))
        best = results[0][0]
        lines = []
        for count, day, cant in results:
            medal = "🏆" if count == best and count > 0 else "📅"
            cant_txt = f" · can't: {', '.join(db.name(u) for u in cant)}" if cant and len(cant) <= 8 else (
                f" · {len(cant)} can't" if cant else "")
            lines.append(f"{medal} **{ui.fmt_day(day)}** — {count}/{len(voters)}{cant_txt}")
        missing = people - voters
        e = ui.embed("📅 Date poll results", "\n".join(lines), ui.GOLD)
        if missing:
            e.add_field(name=f"Haven't voted yet ({len(missing)})",
                        value=", ".join(db.name(u) for u in missing)[:1024], inline=False)
        e.set_footer(text="Tip: lock in the winner with /santa-admin setup event_date:…")
        await reply(interaction, embed=e)

    # ------------------------------------------------------------ rules
    @app_commands.command(name="exclude", description="Make sure two people never get each other (e.g. couples)")
    async def exclude(self, interaction: discord.Interaction, person1: discord.User, person2: discord.User):
        if person1.id == person2.id:
            await reply(interaction, "Pick two different people.")
            return
        self.db.add_exclusion(person1.id, person2.id)
        await reply(interaction, f"🚫 **{person1.display_name}** and **{person2.display_name}** won't get each other. "
                                 "(This carries over to future years too.)")

    @app_commands.command(name="unexclude", description="Remove an exclusion between two people")
    async def unexclude(self, interaction: discord.Interaction, person1: discord.User, person2: discord.User):
        ok = self.db.remove_exclusion(person1.id, person2.id)
        await reply(interaction, "✅ Removed." if ok else "Those two weren't excluded.")

    @app_commands.command(name="suggest", description="Blindly limit someone to a group of people they know (who gets them / who they get)")
    @app_commands.describe(
        person="The person who should only be paired with people they know",
        direction="Both ways (default), only who gets them, or only who they get",
    )
    @app_commands.choices(direction=[
        app_commands.Choice(name="both ways: who gets them AND who they get", value="both"),
        app_commands.Choice(name="only who gets them (their Santa)", value="santa"),
        app_commands.Choice(name="only who they get (their giftee)", value="giftee"),
    ])
    async def suggest(self, interaction: discord.Interaction, person: discord.User,
                      direction: app_commands.Choice[str] | None = None):
        db = self.db
        way = direction.value if direction else "both"
        if db.phase != "signup":
            await reply(interaction, "Names are already drawn, so suggestions are locked.")
            return
        if not db.is_in(person.id):
            await reply(interaction, f"{person.display_name} hasn't joined yet.")
            return
        current = (db.pools().get(person.id, set()) | db.target_pools().get(person.id, set()))
        select = discord.ui.UserSelect(placeholder=f"Who knows {person.display_name} well?", min_values=1, max_values=10)

        async def picked(inter: discord.Interaction):
            chosen = [u for u in select.values if u.id != person.id and db.is_in(u.id)]
            skipped = [u.display_name for u in select.values if u not in chosen]
            if not chosen:
                await inter.response.edit_message(content="None of those people are signed up. Try again.", view=None)
                return
            ids = [u.id for u in chosen]
            if way in ("both", "santa"):
                db.set_pool(person.id, ids)
            else:
                db.clear_pool(person.id)
            if way in ("both", "giftee"):
                db.set_target_pool(person.id, ids)
            else:
                db.clear_target_pool(person.id)
            group = ", ".join(f"**{u.display_name}**" for u in chosen)
            what = {"both": "both their Santa **and** the person they gift to",
                    "santa": "their Santa", "giftee": "the person they gift to"}[way]
            msg = (f"🤫 Done! For **{person.display_name}**, {what} will be secretly picked from: {group}.\n"
                   "You won't find out who.")
            if len(chosen) == 1:
                msg += "\n\n⚠️ With only one person it's not blind — you'll know exactly who it is."
                if way == "both":
                    msg += " They'd also have to swap gifts with each other (A gets B *and* B gets A)."
            if any(u.id == config.ORGANIZER_ID for u in chosen):
                msg += "\n\n⚠️ You put yourself in the group — so you'll know a little about where they landed."
            if skipped:
                msg += f"\n\n(Skipped, not signed up: {', '.join(skipped)})"
            msg += "\n\nRun `/santa-admin check-draw` to make sure all the rules can still fit together."
            await inter.response.edit_message(content=msg, view=None)

        select.callback = picked
        view = discord.ui.View(timeout=300)
        view.add_item(select)
        what = {"both": "both their Santa **and** who they gift to", "santa": "their Santa",
                "giftee": "who they gift to"}[way]
        intro = (f"Pick the people **{person.display_name}** knows (3+ is best). At the draw, {what} "
                 "will be chosen at random from this group — nobody (including you) will know who.")
        if current:
            intro += f"\n\nCurrent group: {self.names(current)} (picking again replaces it)"
        await reply(interaction, intro, view=view)

    @app_commands.command(name="unsuggest", description="Remove someone's suggestion group(s) so they can be paired with anyone")
    async def unsuggest(self, interaction: discord.Interaction, person: discord.User):
        ok = self.db.clear_pool(person.id) | self.db.clear_target_pool(person.id)
        await reply(interaction, "✅ Removed — they can be paired with anyone now." if ok else "They didn't have a group.")

    @app_commands.command(name="rules", description="See exclusions, suggestion pools and history on file")
    async def rules(self, interaction: discord.Interaction):
        db = self.db
        e = ui.embed("📋 Draw rules", color=ui.GOLD)
        ex = db.exclusions()
        e.add_field(name=f"🚫 Exclusions ({len(ex)})",
                    value="\n".join(f"{db.name(a)} ↔ {db.name(b)}" for a, b in ex)[:1024] or "none", inline=False)
        pools, targets = db.pools(), db.target_pools()
        lines = []
        for p in sorted(set(pools) | set(targets), key=lambda u: db.name(u).lower()):
            if pools.get(p) == targets.get(p):
                lines.append(f"{db.name(p)} ⇄ gets & is gotten by one of {', '.join(db.name(s) for s in pools[p])}")
            else:
                if p in pools:
                    lines.append(f"{db.name(p)} ← gotten by one of {', '.join(db.name(s) for s in pools[p])}")
                if p in targets:
                    lines.append(f"{db.name(p)} → gets one of {', '.join(db.name(s) for s in targets[p])}")
        e.add_field(name=f"🤫 Suggestion groups ({len(lines)})", value="\n".join(lines)[:1024] or "none", inline=False)
        reporters = db.q("SELECT COUNT(DISTINCT reporter_id), COUNT(*) FROM history")[0]
        years = db.q("SELECT COUNT(DISTINCT year) FROM archive")[0][0]
        e.add_field(name="🕰️ Past pairings blocked",
                    value=f"{reporters[1]} from `/history` ({reporters[0]} people told me) + "
                          f"everything from {years} past year(s) run by this bot", inline=False)
        await reply(interaction, embed=e)

    # ------------------------------------------------------------ the draw
    @app_commands.command(name="check-draw", description="Test whether names CAN be drawn with the current rules (nothing is saved)")
    async def check_draw(self, interaction: discord.Interaction):
        db = self.db
        people = db.participants()
        try:
            self.try_draw()
        except DrawError as err:
            await reply(interaction, self.draw_error_text(err))
            return
        msg = [f"✅ A valid draw exists for **{len(people)}** people. Nothing was saved."]
        no_wish = [p["user_id"] for p in people if not db.has_wishlist(p)]
        no_dm = [p["user_id"] for p in people if not p["dm_ok"]]
        if no_wish:
            msg.append(f"📝 No wishlist yet ({len(no_wish)}): {self.names(no_wish)}")
        if no_dm:
            msg.append(f"⚠️ DMs closed ({len(no_dm)}): {self.names(no_dm)} — they won't get their giftee by DM")
        await reply(interaction, "\n\n".join(msg))

    @app_commands.command(name="draw", description="Draw names and DM everyone their giftee 🎲")
    async def draw_names(self, interaction: discord.Interaction):
        db = self.db
        if db.phase != "signup":
            await reply(interaction, "Names have already been drawn this year!")
            return
        count = len(db.participants())
        try:
            self.try_draw()
        except DrawError as err:
            await reply(interaction, self.draw_error_text(err))
            return

        async def go(inter: discord.Interaction):
            try:
                mapping = self.try_draw()
            except DrawError as err:
                await reply(inter, self.draw_error_text(err))
                return
            db.save_assignments(mapping)
            db.set("phase", "drawn")
            db.set("signup_open", "0")
            await reply(inter, f"🎲 Names drawn! Sending {count} DMs… (this takes a moment)")
            failed = []
            for santa in mapping:
                ok = await send_dm(self.bot, santa, view=ui.buttons(*ui.SECRET_BUTTONS),
                                   **await actions.giftee_message(db, santa))
                if not ok:
                    failed.append(santa)
            channel = await self.channel(inter)
            try:
                await channel.send(embed=ui.embed(
                    "🎲 Names have been drawn!",
                    "Check your DMs to find out who you're Secret Santa for! 🤫\n\n"
                    "• `/my-giftee` — see your giftee and their wishlist\n"
                    "• `/message-giftee` / `/message-santa` — anonymous messages\n"
                    "• `/gift-ideas` — stuck? get some ideas\n"
                    "• `/gift-ready` once you've got your gift\n"
                    "• `/guess` — guess who has you! Locks on gift night 🕵️\n\n"
                    f"🎁 Bring your wrapped gift {ui.where_and_when(db)}!", ui.GREEN))
            except discord.HTTPException:
                log.warning("Couldn't post the draw announcement in #%s", channel)
            await actions.refresh_signup_panel(self.bot)
            done = f"✅ All done! {count - len(failed)}/{count} people got their DM."
            if failed:
                done += (f"\n\n⚠️ Couldn't DM: {self.names(failed)}. Ask them to use `/my-giftee` in the server "
                         "(and to open their DMs so messages reach them).")
            await reply(inter, done)

        await reply(interaction, f"Ready to draw names for **{count}** people? This closes sign-ups, "
                                 "locks the rules, and DMs everyone their giftee. You won't see the results.",
                    view=Confirm(go, "🎲 Draw names!", discord.ButtonStyle.success))

    # ------------------------------------------------------------ during the event
    @app_commands.command(name="status", description="Who has their gift ready, and how many guesses are in")
    async def status(self, interaction: discord.Interaction):
        db = self.db
        if db.phase != "drawn":
            await reply(interaction, "Names haven't been drawn yet.")
            return
        rows = db.assignments()
        not_ready = [r["santa_id"] for r in rows if not r["ready_at"]]
        guessed = db.q("SELECT COUNT(*) FROM guesses")[0][0]
        e = ui.embed("🎁 Gift tracker", color=ui.GOLD)
        e.description = (f"🎁 **Gift ready:** {len(rows) - len(not_ready)}/{len(rows)}\n"
                         f"🕵️ **Guesses made:** {guessed}/{len(rows)}")
        if not_ready:
            e.add_field(name="Haven't said they've got their gift", value=self.names(not_ready)[:1024], inline=False)
        e.set_footer(text="Nudge them with /santa-admin nudge")
        await reply(interaction, embed=e)

    @app_commands.command(name="nudge", description="DM a friendly reminder to everyone who hasn't done something")
    @app_commands.describe(what="What they haven't done", message="Optional extra line to include")
    @app_commands.choices(what=[
        app_commands.Choice(name="filled in their wishlist", value="wishlist"),
        app_commands.Choice(name="voted on dates", value="dates"),
        app_commands.Choice(name="got their gift yet", value="gift"),
    ])
    async def nudge(self, interaction: discord.Interaction, what: app_commands.Choice[str], message: str | None = None):
        db = self.db
        people = db.participants()
        if what.value == "wishlist":
            targets = [p["user_id"] for p in people if not db.has_wishlist(p)]
            text, keys = "Your Secret Santa is waiting on your wishlist! 📝", ("wishlist",)
        elif what.value == "dates":
            targets = [p["user_id"] for p in people if not db.has_voted(p["user_id"])]
            text, keys = "Don't forget to pick which dates you can make! 📅", ("dates",)
        else:
            if db.phase != "drawn":
                await reply(interaction, "Names haven't been drawn yet.")
                return
            targets = [r["santa_id"] for r in db.assignments() if not r["ready_at"]]
            text = (f"Have you got your Secret Santa gift yet? 🎁 Bring it {ui.where_and_when(db)}.\n"
                    "Already got it? Hit the button below.")
            keys = ("ready", "my_giftee")
        if not targets:
            await reply(interaction, "Everyone's already done that! 🎉")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        e = ui.embed("🔔 Secret Santa reminder", text + (f"\n\n{message}" if message else ""), ui.GOLD)
        sent = 0
        for uid in targets:
            sent += await send_dm(self.bot, uid, embed=e, view=ui.buttons(*keys))
        await reply(interaction, f"🔔 Nudged {sent}/{len(targets)} people.")

    @app_commands.command(name="remind", description="Schedule an announcement in the Secret Santa channel")
    @app_commands.describe(when="e.g. 'Dec 10 6pm' or '2026-12-10 18:00'", message="What to post")
    async def remind(self, interaction: discord.Interaction, when: str, message: str):
        try:
            dt = ui.parse_when(when)
        except ValueError as e:
            await reply(interaction, f"❌ {e}")
            return
        due = ui.to_utc_iso(dt)
        if due <= ui.to_utc_iso(discord.utils.utcnow()):
            await reply(interaction, "That time is in the past!")
            return
        rid = self.db.add_reminder(due, message)
        await reply(interaction, f"⏰ Reminder #{rid} scheduled for **{ui.fmt_when(due)}**:\n> {message}")

    @app_commands.command(name="reminders", description="List scheduled reminders, or cancel one")
    @app_commands.describe(cancel="Reminder number to cancel")
    async def reminders(self, interaction: discord.Interaction, cancel: int | None = None):
        if cancel is not None:
            ok = self.db.cancel_reminder(cancel)
            await reply(interaction, f"🗑️ Cancelled reminder #{cancel}." if ok else f"No pending reminder #{cancel}.")
            return
        rows = self.db.pending_reminders()
        lines = [f"`#{r['id']}` **{ui.fmt_when(r['due_utc'])}** — {r['message'][:100]}" for r in rows]
        await reply(interaction, "⏰ **Scheduled reminders**\n" + "\n".join(lines) if rows else "No reminders scheduled.")

    @app_commands.command(name="announce", description="Post an announcement in the Secret Santa channel")
    @app_commands.describe(ping_everyone="Ping @everyone (default no)")
    async def announce(self, interaction: discord.Interaction, ping_everyone: bool = False):
        await interaction.response.send_modal(AnnounceModal(self, ping_everyone))

    # ------------------------------------------------------------ after gift night
    @app_commands.command(name="wrap-up", description="After gift night: post the who-had-who recap + guess results, and save the year")
    @app_commands.describe(post="Post the recap in the channel (default yes). No = just save it quietly")
    async def wrap_up(self, interaction: discord.Interaction, post: bool = True):
        db = self.db
        if db.phase != "drawn":
            await reply(interaction, "Names haven't been drawn yet!" if db.phase == "signup" else "Already wrapped up!")
            return

        async def go(inter: discord.Interaction):
            quiet = discord.AllowedMentions.none()
            rows = sorted(db.assignments(), key=lambda r: db.name(r["giftee_id"]).lower())
            if post:
                lines, correct = [], []
                for r in rows:
                    santa, giftee = r["santa_id"], r["giftee_id"]
                    guess = db.guess_of(giftee)
                    tail = " 🕵️✅" if guess == santa else ""
                    if guess == santa:
                        correct.append(giftee)
                    lines.append(f"🎁 {ui.mention(santa)} → {ui.mention(giftee)}{tail}")
                e = ui.embed(f"🎄 {db.get('event_name')} — who had who", "\n".join(lines)[:4000], ui.GREEN)
                if correct:
                    e.add_field(name="🕵️ Guessed their Santa", value=", ".join(ui.mention(u) for u in correct)[:1024])
                e.set_footer(text="Thanks for playing, everyone! ❤️")
                channel = await self.channel(inter)
                await channel.send(embed=e, allowed_mentions=quiet)
            db.archive_year(str(ui.today().year))
            db.set("phase", "revealed")
            await reply(inter, "✅ Saved to `/hall-of-fame`. These pairings are now blocked from repeating next year. "
                               "Start fresh with `/santa-admin new-season` whenever you're ready.")

        what = "post every pairing in the channel and save" if post else "quietly save"
        await reply(interaction, f"Gift night's done? This will {what} this year's draw. Can't be undone.",
                    view=Confirm(go, "🎄 Wrap it up", discord.ButtonStyle.success))

    @app_commands.command(name="new-season", description="Clear everything and start a fresh Secret Santa")
    async def new_season(self, interaction: discord.Interaction):
        db = self.db
        warning = ("Names are drawn but you haven't run `/santa-admin wrap-up` — this throws away the draw "
                   "without saving it. " if db.phase == "drawn" else "")

        async def go(inter: discord.Interaction):
            db.new_season()
            await reply(inter, "🆕 Fresh start! Participants, dates, history and pools are cleared. "
                               "Exclusions, budget, venue, channel and the hall of fame were kept. "
                               "Post a new sign-up panel with `/santa-admin post-signup`.")

        await reply(interaction, f"{warning}Clear this season's participants, dates, history, pools and draw?",
                    view=Confirm(go, "Start new season"))


async def setup(bot):
    await bot.add_cog(Admin(bot))
