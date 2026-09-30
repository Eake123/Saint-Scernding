"""Background jobs: scheduled reminders, the daily countdown, and automatic "got your gift?" nudges."""
from __future__ import annotations

import logging
import math
from datetime import date, datetime

import discord
from discord.ext import commands, tasks

from .. import config, runtime, ui
from ..actions import send_dm

log = logging.getLogger("santa")


class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    def channel(self):
        cid = self.db.get("channel_id")
        return self.bot.get_channel(int(cid)) if cid else None

    @tasks.loop(minutes=1)
    async def tick(self):
        try:
            runtime.write_heartbeat(
                connected=not self.bot.is_closed() and self.bot.is_ready(),
                latency_ms=round(self.bot.latency * 1000) if math.isfinite(self.bot.latency) else None,
                guild=bool(self.bot.get_guild(config.GUILD_ID)),
                participants=len(self.db.participants()),
                phase=self.db.phase,
            )
            await self.post_due_reminders()
            now = datetime.now(config.TIMEZONE)
            if now.hour >= config.DAILY_POST_HOUR and self.db.get("last_daily") != now.date().isoformat():
                self.db.set("last_daily", now.date().isoformat())
                await self.daily(now.date())
        except Exception:
            log.exception("Scheduler tick failed")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    async def post_due_reminders(self):
        channel = self.channel()
        for r in self.db.due_reminders(ui.to_utc_iso(discord.utils.utcnow())):
            self.db.mark_reminder_sent(r["id"])
            if channel:
                await channel.send(embed=ui.embed("⏰ Secret Santa reminder", r["message"], ui.GOLD))
            else:
                log.warning("Reminder #%s is due but no channel is set (/santa-admin setup channel:…)", r["id"])

    async def daily(self, today: date):
        db = self.db
        if db.phase != "drawn":
            return
        event = db.get("event_date")
        if not event:
            return
        rows = db.assignments()
        ready = sum(1 for r in rows if r["ready_at"])
        days = (date.fromisoformat(event) - today).days
        venue = db.get("venue")

        # Countdown post
        channel = self.channel()
        if db.get("countdown") == "1" and channel and days >= 0:
            if days == 0:
                head = "🎉 **IT'S GIFT NIGHT!** 🎉"
                body = f"Don't forget your gift! See you{f' at **{venue}**' if venue else ''} 🍻"
            else:
                head = f"🎄 **{days} day{'s' if days != 1 else ''}** until gift night{f' at {venue}' if venue else ''}!"
                body = f"🎁 {ready}/{len(rows)} Santas have their gift ready"
            await channel.send(embed=ui.embed(head, body, ui.GREEN))

        # Automatic DMs 3 days and 1 day out, only to people who haven't said they've got their gift
        for n in (3, 1):
            if days == n and not db.get(f"nudged_{n}"):
                db.set(f"nudged_{n}", 1)
                e = ui.embed(
                    "🎁 Gift night is coming up!",
                    f"Gift night is **{'tomorrow' if n == 1 else f'in {n} days'}** — got your gift yet? "
                    f"Bring it {ui.where_and_when(db)}.\nAlready got it? Hit the button.",
                    ui.GOLD)
                for r in rows:
                    if not r["ready_at"]:
                        await send_dm(self.bot, r["santa_id"], embed=e, view=ui.buttons("ready", "my_giftee"))


async def setup(bot):
    await bot.add_cog(Scheduler(bot))
