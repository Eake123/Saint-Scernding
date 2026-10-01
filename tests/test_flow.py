"""Runs a whole season end-to-end with fake Discord objects, so no real bot/token is needed."""
import os
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("ORGANIZER_ID", "100")
os.environ.setdefault("TIMEZONE", "America/Edmonton")

from santa import actions, config, ui  # noqa: E402
from santa.cogs.admin import Admin  # noqa: E402
from santa.cogs.participant import Participant  # noqa: E402
from santa.cogs.scheduler import Scheduler  # noqa: E402
from santa.cogs.secret import Secret  # noqa: E402
from santa.db import DB  # noqa: E402

ORG = config.ORGANIZER_ID


class Sink:
    """Records everything 'sent' to Discord."""

    def __init__(self):
        self.items = []

    async def send(self, content=None, **kw):
        self.items.append(SimpleNamespace(content=content, **kw))
        return FakeMessage()

    def text(self):
        out = []
        for i in self.items:
            out.append(i.content or "")
            e = getattr(i, "embed", None)
            if e:
                out += [e.title or "", e.description or ""] + [f"{f.name} {f.value}" for f in e.fields]
        return "\n".join(out)


class FakeMessage:
    id = 555

    async def edit(self, **kw):
        pass


class FakeChannel(Sink):
    id = 999
    mention = "#santa"

    async def fetch_message(self, _id):
        return FakeMessage()


class FakeResponse(Sink):
    def __init__(self):
        super().__init__()
        self.done = False
        self.modal = None

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kw):
        self.done = True
        return await self.send(content, **kw)

    async def defer(self, **kw):
        self.done = True

    async def send_modal(self, modal):
        self.done = True
        self.modal = modal

    async def edit_message(self, **kw):
        self.done = True
        return await self.send(kw.pop("content", None), **kw)


class FakeBot:
    def __init__(self, db):
        self.db = db
        self.claude = None
        self.channel = FakeChannel()
        self.dms: dict[int, Sink] = {}
        self.closed_dms: set[int] = set()

    def get_user(self, uid):
        bot = self

        class U:
            async def send(self, content=None, **kw):
                if uid in bot.closed_dms:
                    import discord
                    raise discord.Forbidden(SimpleNamespace(status=403, reason="closed"), "closed")
                return await bot.dms.setdefault(uid, Sink()).send(content, **kw)

        return U()

    def get_channel(self, _id):
        return self.channel

    def dm_text(self, uid):
        return self.dms.get(uid, Sink()).text()


class FakeInteraction:
    def __init__(self, bot, uid, data=None, guild=True):
        self.client = bot
        self.user = SimpleNamespace(id=uid, display_name=f"P{uid}", bot=False, mention=f"<@{uid}>")
        self.guild = object() if guild else None
        self.data = data or {}
        self.response = FakeResponse()
        self.followup = self.response
        self.channel_id = bot.channel.id
        self.channel = bot.channel

    def text(self):
        return self.response.text()


def user(uid):
    return SimpleNamespace(id=uid, display_name=f"P{uid}", bot=False)


async def call(cmd, cog, inter, *args, **kw):
    await cmd.callback(cog, inter, *args, **kw)
    return inter


async def confirm(bot, inter):
    """Click the 'yes' button on the last Confirm view the organizer was shown."""
    view = next(i.view for i in reversed(inter.response.items) if getattr(i, "view", None))
    yes = view.children[0]
    click = FakeInteraction(bot, ORG)
    await yes.callback(click)
    return click


@pytest.mark.asyncio
async def test_leave_needs_confirmation(tmp_path):
    db = DB(tmp_path / "leave.db")
    bot = FakeBot(db)
    await actions.join(FakeInteraction(bot, 1))
    db.save_wishlist(1, wish="socks")

    ask = FakeInteraction(bot, 1)
    await actions.leave(ask)
    assert db.is_in(1)  # one click does nothing yet
    assert "Are you sure" in ask.text() and "wishlist" in ask.text()
    assert [b.custom_id for b in ask.response.items[-1].view.children] == ["santa:leave_no", "santa:leave_yes"]

    await actions.cancel_leave(FakeInteraction(bot, 1))
    assert db.is_in(1) and db.participant(1)["wish"] == "socks"

    done = FakeInteraction(bot, 1)
    await actions.confirm_leave(done)
    assert not db.is_in(1) and "You've left" in done.text()


@pytest.mark.asyncio
async def test_full_season(tmp_path):
    db = DB(tmp_path / "flow.db")
    bot = FakeBot(db)
    admin, part, secret = Admin(bot), Participant(bot), Secret(bot)
    people = [ORG] + list(range(1, 8))  # organizer plays too
    gift_night = date.today() + timedelta(days=10)

    await call(admin.setup, admin, FakeInteraction(bot, ORG), event_date=gift_night.isoformat(),
               venue="The Last Straw", budget=100)
    await call(admin.post_signup, admin, FakeInteraction(bot, ORG))
    assert "The Last Straw" in bot.channel.text()

    await call(admin.intro, admin, FakeInteraction(bot, ORG))
    intro = next(i for i in bot.channel.items if getattr(i, "embeds", None))
    assert sum(len(e) for e in intro.embeds) <= 6000  # Discord's per-message limit
    assert "OPEN SOURCE" in "".join(e.title for e in intro.embeds)
    assert any(getattr(b, "url", None) == config.REPO_URL for b in intro.view.children)

    for uid in people:
        i = FakeInteraction(bot, uid)
        await actions.join(i)
        assert "You're in" in i.text()
    assert len(db.participants()) == len(people)

    # wishlist via modal
    i = FakeInteraction(bot, 1)
    await actions.open_wishlist(i)
    modal = i.response.modal
    modal.inputs["wish"]._value = "A skateboard"
    await modal.on_submit(FakeInteraction(bot, 1))
    assert db.participant(1)["wish"] == "A skateboard"

    # date poll
    await call(admin.dates, admin, FakeInteraction(bot, ORG), dates="Dec 11, Dec 12, Dec 18")
    opts = db.date_options()
    for uid in people:
        await actions.submit_dates(FakeInteraction(bot, uid, data={"values": [str(opts[-1]["id"])]}))
    r = await call(admin.date_results, admin, FakeInteraction(bot, ORG))
    assert f"{len(people)}/{len(people)}" in r.text()

    # rules
    await call(part.history, part, FakeInteraction(bot, 1), i_had=user(2), had_me=user(3))
    await call(admin.exclude, admin, FakeInteraction(bot, ORG), user(4), user(5))
    db.set_pool(6, [7, ORG])
    r = await call(admin.check_draw, admin, FakeInteraction(bot, ORG))
    assert "valid draw" in r.text()

    # the draw
    r = await call(admin.draw_names, admin, FakeInteraction(bot, ORG))
    click = await confirm(bot, r)
    assert "All done" in click.text()
    m = db.assignment_map()
    assert m[1] != 2 and m[3] != 1 and m[4] != 5 and m[5] != 4
    assert db.santa_of(6) in (7, ORG)
    for uid in people:
        assert "You're the Secret Santa for" in bot.dm_text(uid)
    # the organizer's own replies never contain the pairings
    assert "→" not in click.text()

    # messaging both ways
    santa_of_1 = db.santa_of(1)
    await actions.relay_message(FakeInteraction(bot, santa_of_1), "giftee", "what's your fav colour?")
    assert "what's your fav colour?" in bot.dm_text(1)
    await actions.relay_message(FakeInteraction(bot, 1, guild=False), "santa", "green!")
    assert "green!" in bot.dm_text(santa_of_1)

    # gift ready + guess + status
    await actions.mark_ready(FakeInteraction(bot, santa_of_1))
    assert "has your gift" in bot.dm_text(1)
    await call(secret.guess, secret, FakeInteraction(bot, 1), user(santa_of_1))
    r = await call(admin.status, admin, FakeInteraction(bot, ORG))
    assert f"1/{len(people)}" in r.text()

    # dropout + late joiner after the draw
    r = await call(admin.remove, admin, FakeInteraction(bot, ORG), user(7))
    await confirm(bot, r)
    assert not db.is_in(7) and len(db.assignment_map()) == len(people) - 1
    await call(admin.add, admin, FakeInteraction(bot, ORG), user(50))
    assert db.giftee_of(50) is not None and len(db.assignment_map()) == len(people)

    # scheduler: 3 days out nudges only people without a gift
    sched = Scheduler.__new__(Scheduler)
    sched.bot, sched.db = bot, db
    await sched.daily(gift_night - timedelta(days=3))
    assert "3 days" in bot.channel.text()
    # (a santa whose giftee changed in the remove/add above is correctly back to "not ready")
    for santa in db.assignment_map():
        nudged = "Gift night is coming up" in bot.dm_text(santa)
        assert nudged == (not db.assignment(santa)["ready_at"])

    # wrap-up after gift night
    r = await call(admin.wrap_up, admin, FakeInteraction(bot, ORG))
    await confirm(bot, r)
    assert "who had who" in bot.channel.text()
    assert db.phase == "revealed"
    r = await call(secret.hall_of_fame, secret, FakeInteraction(bot, 1))
    assert "guessed their Santa" in r.text()

    # next year
    r = await call(admin.new_season, admin, FakeInteraction(bot, ORG))
    await confirm(bot, r)
    assert db.participants() == [] and db.get("venue") == "The Last Straw"
