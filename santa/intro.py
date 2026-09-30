"""The big, loud, deeply cringe announcement posted by /santa-admin intro."""
from __future__ import annotations

import discord

from . import config, ui


def intro_embeds(db) -> list[discord.Embed]:
    venue = db.get("venue") or "the spot"
    when = ui.fmt_day(db.get("event_date")) if db.get("event_date") else "TBD (vote with `/dates`!! 🗳️)"
    budget = ui.budget_text(db)

    hello = ui.embed(
        "🎅🎄✨ HO HO HOLY SH*T IT'S SECRET SANTA SZN ✨🎄🎅",
        "Hiiii besties 👋🥺💅\n\n"
        "It is I, **Saint Scernding** 😇🎅🕯️, patron saint of gifts 🎁, gossip 🗣️ and "
        "questionable decisions 🍻🍻🍻\n\n"
        "I have been SUMMONED 🔮✨ to run this year's Secret Santa and bestie... "
        "it's giving ✨*organized*✨ 💅💯🔥\n\n"
        f"💰 **Budget:** {budget} 💸💸 (no cheaping out 👀)\n"
        f"📍 **Where:** {venue} 🍻\n"
        f"🗓️ **When:** {when}",
        ui.RED,
    )

    how = ui.embed(
        "📜✨ HOW THIS WORKS (read it or Santa cries 😭🎅💔)",
        "1️⃣ Smash **Join** 🎁👇 you're IN baby 🥳\n"
        "2️⃣ `/wishlist` 📝 tell your Santa what you want 🛍️ (and what NOT to get 🚫🕯️ no candles bestie 🙅)\n"
        f"3️⃣ `/dates` 📅 pick EVERY night you can make it to {venue} 🍻🗓️\n"
        "4️⃣ `/history` 🕰️ snitch on who you had before 👉👈 and who had YOU, so there are "
        "NO REPEATS 🙅‍♂️🔁🚫\n"
        "5️⃣ 🎲 **THE DRAW** 🎲 I slide into your DMs with your giftee 🤫📩 Not even the organizer "
        "knows. NOT. EVEN. THEM. 😱🔒🤐\n"
        "6️⃣ `/message-giftee` 💌 message your giftee **100% ANONYMOUSLY** 🕵️‍♂️👀 and "
        "`/message-santa` 🎅📨 to talk to whoever has YOU (reply buttons!!! 🔁💬)\n"
        "7️⃣ `/gift-ideas` 💡🧠 brain empty? the robot's got you 🤖✨\n"
        "8️⃣ `/gift-ready` 🎁✅ when you've got it, and your giftee gets a lil teaser 😏🔥\n"
        "9️⃣ `/guess` 🕵️ who has you?? 🤔 locks on gift night 🔒 get it right = ETERNAL bragging rights 👑🏆\n"
        f"🔟 🍻 **GIFT NIGHT** 🍻 bring your wrapped gift to **{venue}** 🎁🎁🎁 and FIND OUT 😳💥\n\n"
        "Lost?? 😵‍💫 `/santa` shows your personal checklist anytime ✅✅✅",
        ui.GREEN,
    )

    oss = ui.embed(
        "🚨🚨🚨 BREAKING NEWS: I AM OPEN SOURCE 🚨🚨🚨",
        "That's right 😤💻🔥 every. single. line. of me is **FREE** 🆓 and **PUBLIC** 🌍 on GitHub 🐙✨\n\n"
        "👀 Read my code (I have no secrets… except the draw 🤫)\n"
        "🍴 Fork me\n"
        "🖥️ Run me in YOUR server for YOUR friends\n"
        "🛠️ Open a PR and make me even more unhinged\n"
        "🧪 Stacked with automated tests so the draw is actually fair 🧮✅\n"
        "📜 MIT licensed = do basically whatever you want 🤯\n\n"
        "Built with love 💖, Python 🐍 and ZERO corporate overlords 🙅‍♂️🏢🚫\n\n"
        f"👉 **{config.REPO_URL}** 👈\n\n"
        "Smash that ⭐ **STAR** ⭐ like it owes you money 💸⭐💸⭐💸",
        ui.GOLD,
    )
    oss.set_footer(text="Saint Scernding 😇 • open source Secret Santa • now hit Join below 🎁👇")
    return [hello, how, oss]


def intro_view() -> discord.ui.View:
    view = ui.buttons("join", "wishlist", "dates")
    view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, url=config.REPO_URL,
                                    label="Star me on GitHub", emoji="⭐"))
    return view
