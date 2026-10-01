"""Things participants can do. Slash commands and buttons both call into here."""
from __future__ import annotations

import logging

import discord

from . import config, ui

log = logging.getLogger("santa")


def db_of(interaction: discord.Interaction):
    return interaction.client.db


async def reply(interaction: discord.Interaction, content: str = None, **kwargs) -> None:
    """Ephemeral reply that works whether or not we've already responded/deferred."""
    kwargs.setdefault("ephemeral", True)
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


async def send_dm(bot, user_id: int, *, notify_organizer_on_fail: bool = False, **kwargs) -> bool:
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        await user.send(**kwargs)
        bot.db.set_dm_ok(user_id, True)
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        bot.db.set_dm_ok(user_id, False)
        if notify_organizer_on_fail and user_id != config.ORGANIZER_ID:
            await send_dm(bot, config.ORGANIZER_ID, content=(
                f"⚠️ Heads up: I couldn't DM **{bot.db.name(user_id)}** — their DMs are closed. "
                "Ask them to turn on *Allow direct messages from server members* for this server."
            ))
        return False


async def require_participant(interaction: discord.Interaction) -> bool:
    db = db_of(interaction)
    if db.is_in(interaction.user.id):
        name = getattr(interaction.user, "display_name", None)
        if interaction.guild and name:
            db.update_name(interaction.user.id, name)
        return True
    await reply(interaction, "You're not signed up for Secret Santa yet! Use `/join` to hop in. 🎁")
    return False


async def require_drawn(interaction: discord.Interaction) -> bool:
    if not await require_participant(interaction):
        return False
    db = db_of(interaction)
    if db.phase == "signup":
        await reply(interaction, "Names haven't been drawn yet — hang tight! ⏳")
        return False
    if db.giftee_of(interaction.user.id) is None:
        await reply(interaction, "You're not in this year's draw. Ask the organizer if that seems wrong.")
        return False
    return True


# ---------------------------------------------------------------- signups
def signup_panel_embed(db) -> discord.Embed:
    count = len(db.participants())
    status = "✅ **Sign-ups are open!**" if db.phase == "signup" and db.get("signup_open") == "1" else "🔒 **Sign-ups are closed.**"
    lines = [status, "", *ui.event_lines(db)]
    lines += [
        "",
        "**How it works**",
        "1. Hit **Join** below",
        "2. Fill in your **wishlist** and **pick the dates** you can make",
        "3. Use `/history` to tell me who you've had (or who had you) before, so there are no repeats",
        "4. When names are drawn, I'll DM you your giftee 🤫",
        f"5. Bring your wrapped gift {ui.where_and_when(db)} 🎁",
        "",
        f"🎄 **{count}** {'person has' if count == 1 else 'people have'} joined so far",
    ]
    return ui.embed(f"🎅 {db.get('event_name')}", "\n".join(lines))


async def refresh_signup_panel(bot) -> None:
    db = bot.db
    channel_id, message_id = db.get("panel_channel_id"), db.get("panel_message_id")
    if not (channel_id and message_id):
        return
    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(embed=signup_panel_embed(db))
    except discord.HTTPException:
        log.warning("Couldn't update the sign-up panel message")


async def join(interaction: discord.Interaction) -> None:
    db = db_of(interaction)
    uid = interaction.user.id
    if db.is_in(uid):
        await reply(interaction, "You're already in! 🎉 Use the buttons to update your wishlist or dates.",
                    view=ui.buttons("wishlist", "dates"))
        return
    if db.phase != "signup" or db.get("signup_open") != "1":
        await reply(interaction, "Sign-ups are closed right now. Message the organizer if you want in!")
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    db.add_participant(uid, interaction.user.display_name)
    dm_ok = await send_dm(interaction.client, uid, embed=ui.embed(
        "🎄 You're in!",
        "This is where I'll send your giftee once names are drawn — and where anonymous "
        "messages from your Secret Santa will show up. Don't close your DMs! 🤫",
        ui.GREEN,
    ))
    e = ui.embed(
        "🎁 You're in!",
        "Next steps:\n"
        "📝 **Fill in your wishlist** so your Santa knows what to get\n"
        "📅 **Pick the dates** you can make for gift night\n"
        "🕰️ Use `/history` to name up to 2 people you've had and 2 who had you in past years",
        ui.GREEN,
    )
    if not dm_ok:
        e.add_field(
            name="⚠️ I can't DM you!",
            value="Right-click the server icon → **Privacy Settings** → turn on **Direct Messages**, "
                  "or you won't get your giftee.",
        )
    await reply(interaction, embed=e, view=ui.buttons("wishlist", "dates"))
    await refresh_signup_panel(interaction.client)


async def _can_leave(interaction: discord.Interaction) -> bool:
    db = db_of(interaction)
    if not db.is_in(interaction.user.id):
        await reply(interaction, "You weren't signed up. 🙂")
        return False
    if db.phase != "signup":
        await reply(interaction, "Names have already been drawn, so ask the organizer to take you out.")
        return False
    return True


async def leave(interaction: discord.Interaction) -> None:
    """Step 1: ask first — leaving wipes everything they've filled in."""
    if not await _can_leave(interaction):
        return
    db = db_of(interaction)
    uid = interaction.user.id
    lose = [label for label, has in (
        ("📝 your wishlist", db.has_wishlist(db.participant(uid))),
        ("📅 your date votes", db.has_voted(uid)),
        ("🕰️ your past-pairings history", bool(db.history_of(uid))),
    ) if has]
    warning = ("This deletes " + ", ".join(lose) + ", and re-joining won't bring them back."
               if lose else "You can re-join any time before the draw.")
    await reply(interaction, f"**Are you sure you want to leave Secret Santa?** 😢\n{warning}",
                view=ui.buttons("leave_no", "leave_yes"))


async def confirm_leave(interaction: discord.Interaction) -> None:
    if not await _can_leave(interaction):
        return
    db_of(interaction).remove_participant(interaction.user.id)
    await interaction.response.edit_message(
        content="You've left this year's Secret Santa. 👋 You can re-join any time before the draw.", view=None)
    await refresh_signup_panel(interaction.client)


async def cancel_leave(interaction: discord.Interaction) -> None:
    await interaction.response.edit_message(content="Phew 😮‍💨 You're still in! 🎁", view=None)


# ---------------------------------------------------------------- wishlist
class WishlistModal(discord.ui.Modal):
    def __init__(self, row):
        super().__init__(title="🎁 Your Wishlist")
        self.inputs = {}
        specs = [
            ("wish", "What would you love to get?", "Specific things, links, stores, gift cards…", 1000),
            ("interests", "Interests & hobbies", "Games, shows, teams, colours, anything you're into", 500),
            ("avoid", "Please avoid", "Allergies, things you already have, no candles…", 300),
            ("sizes", "Sizes", "Shirt, hoodie, shoe, ring…", 200),
            ("notes", "Anything else?", "Favourite snacks, drinks, colours, inside jokes…", 300),
        ]
        for key, label, placeholder, max_len in specs:
            field = discord.ui.TextInput(
                label=label, placeholder=placeholder, required=False, max_length=max_len,
                style=discord.TextStyle.paragraph if key in ("wish", "interests") else discord.TextStyle.short,
                default=row[key] if row and row[key] else None,
            )
            self.inputs[key] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        db = db_of(interaction)
        uid = interaction.user.id
        db.save_wishlist(uid, **{k: v.value.strip() for k, v in self.inputs.items()})
        await reply(interaction, "📝 Wishlist saved! You can update it any time.")
        # Let their Santa know (anonymously, obviously).
        santa = db.santa_of(uid) if db.phase == "drawn" else None
        if santa:
            e = ui.add_wishlist_fields(
                ui.embed(f"📝 {db.name(uid)} updated their wishlist!", color=ui.GOLD), db.participant(uid)
            )
            await send_dm(interaction.client, santa, embed=e)


async def open_wishlist(interaction: discord.Interaction) -> None:
    if await require_participant(interaction):
        await interaction.response.send_modal(WishlistModal(db_of(interaction).participant(interaction.user.id)))


# ---------------------------------------------------------------- date poll
async def open_date_picker(interaction: discord.Interaction) -> None:
    if not await require_participant(interaction):
        return
    db = db_of(interaction)
    options = db.date_options()
    if not options:
        await reply(interaction, "The organizer hasn't posted the date options yet. Check back soon! 📅")
        return
    mine = db.votes_of(interaction.user.id)
    select = discord.ui.Select(
        custom_id="santa:dates_pick",
        placeholder="Pick EVERY date you can make",
        min_values=1,
        max_values=len(options) + 1,
        options=[
            discord.SelectOption(label=ui.fmt_day(o["day"]), value=str(o["id"]), emoji="📅",
                                 default=o["id"] in mine)
            for o in options
        ] + [discord.SelectOption(label="None of these work for me", value="none", emoji="❌",
                                  default=db.has_voted(interaction.user.id) and not mine)],
    )
    view = discord.ui.View(timeout=None)
    view.add_item(select)
    await reply(interaction, "Which of these dates can you make? Pick all that work — you can change it later.",
                view=view)


async def submit_dates(interaction: discord.Interaction) -> None:
    if not await require_participant(interaction):
        return
    db = db_of(interaction)
    values = interaction.data.get("values", [])
    valid = {o["id"]: o["day"] for o in db.date_options()}
    ids = [int(v) for v in values if v != "none" and int(v) in valid]
    db.set_votes(interaction.user.id, ids)
    picked = ", ".join(ui.fmt_day(valid[i]) for i in sorted(ids, key=lambda i: valid[i])) or "none of them"
    await interaction.response.edit_message(content=f"📅 Got it! You can make: **{picked}**", view=None)


# ---------------------------------------------------------------- after the draw
async def show_my_giftee(interaction: discord.Interaction) -> None:
    if await require_drawn(interaction):
        await reply(interaction, embed=ui.giftee_embed(db_of(interaction), interaction.user.id),
                    view=ui.buttons("msg_giftee", "ready"))


class MessageModal(discord.ui.Modal):
    def __init__(self, to: str, giftee_name: str | None = None):
        title = f"💌 Message {giftee_name}"[:45] if to == "giftee" else "🎅 Message your Secret Santa"
        super().__init__(title=title)
        self.to = to
        self.text = discord.ui.TextInput(
            label="Your message (they won't see who you are)" if to == "giftee" else "Your message",
            style=discord.TextStyle.paragraph, max_length=1500,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await relay_message(interaction, self.to, self.text.value)


async def open_message(interaction: discord.Interaction, to: str) -> None:
    if not await require_drawn(interaction):
        return
    db = db_of(interaction)
    giftee_name = db.name(db.giftee_of(interaction.user.id))
    await interaction.response.send_modal(MessageModal(to, giftee_name))


async def relay_message(interaction: discord.Interaction, to: str, text: str) -> None:
    if not await require_drawn(interaction):
        return
    db = db_of(interaction)
    uid = interaction.user.id
    text = text.strip()
    if not text:
        await reply(interaction, "That message was empty!")
        return
    if to == "giftee":
        target = db.giftee_of(uid)
        e = ui.embed("🎅 A message from your Secret Santa", text, ui.RED)
        e.set_footer(text="Reply below — your Santa won't see anything except your message.")
        view = ui.buttons("reply_santa")
    else:
        target = db.santa_of(uid)
        e = ui.embed(f"🎁 A message from your giftee, {db.name(uid)}", text, ui.GREEN)
        view = ui.buttons("reply_giftee")
    if target is None:
        await reply(interaction, "Hmm, I couldn't find who to send that to. Tell the organizer!")
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    if await send_dm(interaction.client, target, embed=e, view=view, notify_organizer_on_fail=True):
        who = db.name(target) if to == "giftee" else "your Secret Santa"
        await reply(interaction, f"🤫 Sent to {who}!")
    else:
        await reply(interaction, "😬 I couldn't deliver that — they have DMs closed. "
                                 "I've let the organizer know so they can nudge them (without saying who you are).")


async def mark_ready(interaction: discord.Interaction, note: str | None = None) -> None:
    if not await require_drawn(interaction):
        return
    db = db_of(interaction)
    uid = interaction.user.id
    if db.assignment(uid)["ready_at"]:
        await reply(interaction, "🎁 You're already marked as ready. See you there!")
        return
    db.mark_ready(uid)
    await reply(interaction, f"🎁 Nice work, Santa! Don't forget to bring it {ui.where_and_when(db)}. 🎅")
    e = ui.embed("🎁 Your Secret Santa has your gift!",
                 f"It's bought and waiting for you. See you {ui.where_and_when(db)}! 👀", ui.GREEN)
    if note:
        e.add_field(name="Note from your Santa", value=note[:1000])
    await send_dm(interaction.client, db.giftee_of(uid), embed=e, view=ui.buttons("msg_santa"))


ROUTES = {
    "santa:join": join,
    "santa:leave": leave,
    "santa:leave_yes": confirm_leave,
    "santa:leave_no": cancel_leave,
    "santa:wishlist": open_wishlist,
    "santa:dates": open_date_picker,
    "santa:dates_pick": submit_dates,
    "santa:my_giftee": show_my_giftee,
    "santa:msg_giftee": lambda i: open_message(i, "giftee"),
    "santa:msg_santa": lambda i: open_message(i, "santa"),
    "santa:ready": mark_ready,
}
