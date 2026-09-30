# 🎅 Saint Scernding

![Saint Scernding trailer](docs/trailer.gif)

**A Secret Santa Discord bot.** A self-hosted Discord bot that runs your whole Secret Santa for an **in-person gift exchange**:
sign-ups, wishlists, a date poll, a fair *blind* draw, anonymous messages, "got your gift?" nudges, and a
hall of fame so nobody gets the same person twice.

Built for groups that meet up somewhere (a bar, someone's place…) and hand over wrapped gifts in person.
The bot handles everything *before* the night. How gifts get handed out on the night is up to you. The bot
never decides the order.

## ✨ Features

**For everyone**
- 🎁 **One-click sign-up** from a panel with a live headcount
- 📝 **Wishlists**: likes, interests, "please avoid", sizes
- 📅 **Date poll**: everyone picks every date they can make, and the organizer sees the best one
- 🕰️ **No repeats**: each person can list up to 2 people they've had and 2 who've had them in past years
- 🤫 **Anonymous messaging both ways**: message your giftee without revealing yourself, or message your Santa. Every message has a Reply button.
- 💡 **AI gift ideas** based on your giftee's wishlist and the budget (optional, uses Claude)
- 🕵️ **Guess your Santa**: guesses lock on gift night, and correct guessers get bragging rights

**For the organizer** (`/santa-admin`, only you can use it)
- 👥 **Roster** showing who's in and who hasn't done their wishlist, date vote or opened their DMs (+ CSV export)
- 🤫 **Blind suggestions**: for someone who doesn't know many people, pick a few people who know them.
  One of those people is secretly chosen as their Santa. **You never find out which one.**
- 🚫 **Exclusions** (e.g. couples never get each other)
- 🎲 **The draw**: avoids mutual pairs, respects every rule, DMs everyone their giftee.
  **The organizer can play too.** No command ever shows who has whom.
- 🔄 **Late joiners & dropouts after the draw**: the fewest possible people get a new giftee
- 📊 **Gift tracker & nudges**: see who has their gift ready and DM reminders to the rest
- ⏰ **Scheduled announcements**, a **daily countdown**, and **automatic "got your gift?" DMs** 3 days and 1 day out
- 🏆 **Wrap-up**: after gift night, post a who-had-who recap + guess results and save the year so those pairings
  never repeat

---

## 🚀 Setup (≈15 minutes)

You need **Python 3.11+** on the computer that will run the bot. The bot runs only while that computer is on.
([Hosting it 24/7](#-hosting-247) is optional.)

### 1. Create the bot on Discord
1. Go to <https://discord.com/developers/applications> → **New Application**. Give it a name and an avatar.
2. **Bot** tab:
   - **Reset Token** → **Copy**. This is the bot's password. **Never share it or commit it.**
   - Turn **off** *Public Bot* so only you can add it to servers.
3. **OAuth2 → URL Generator**:
   - Scopes: **bot** and **applications.commands**
   - Bot permissions: **View Channels**, **Send Messages**, **Embed Links**, **Attach Files**, **Read Message History**
   - Open the generated URL, pick your server, **Authorize**.

No privileged intents are needed.

### 2. Get your IDs
Discord **User Settings → Advanced → Developer Mode: ON**, then:
- Right-click your **server icon** → **Copy Server ID**
- Right-click **your own name** → **Copy User ID**

### 3. Configure
```bash
git clone https://github.com/Eake123/Saint-Scernding.git
cd Saint-Scernding
cp .env.example .env
```
Fill in `.env`: `DISCORD_TOKEN`, `GUILD_ID` (server ID), `ORGANIZER_ID` (your user ID) and `TIMEZONE`.
For `/gift-ideas`, also add an `ANTHROPIC_API_KEY` from <https://console.anthropic.com>
(pay-as-you-go, around a cent per suggestion).

### 4. Run
- **Windows:** double-click `start.bat`. The first run installs everything.
- **Mac/Linux:**
  ```bash
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  .venv/bin/python bot.py
  ```

When you see `🎅 Logged in as … — ready!`, the bot is live and its slash commands are in your server.

> 💡 To hide `/santa-admin` from everyone else, go to **Server Settings → Integrations → your bot → /santa-admin**, turn off
> `@everyone` and add yourself. Others can't use it anyway, but this keeps it out of their command list.

---

## 🎄 Running a season

| When | Organizer | Everyone |
|---|---|---|
| **Kickoff** | `/santa-admin setup`: channel, `budget`, `venue`, `event_name`<br>`/santa-admin post-signup`: the **Join** panel<br>`/santa-admin dates`: date poll (leave empty for every Fri & Sat in December before Christmas) | **Join** → **wishlist** → **pick dates** → `/history` |
| **Sign-ups** | `/santa-admin roster`, `/santa-admin date-results`<br>`/santa-admin exclude`, `/santa-admin suggest`<br>`/santa-admin nudge` | |
| **Pick the night** | `/santa-admin setup event_date:` with the winning date<br>`/santa-admin check-draw`: test run, nothing saved | |
| **Draw** | `/santa-admin draw` 🎲 | Everyone gets a DM with their giftee + wishlist |
| **Shopping** | `/santa-admin status`, `/santa-admin nudge`<br>`/santa-admin remind`, `/santa-admin announce`<br>`/santa-admin add` / `remove` | `/message-giftee`, `/message-santa`<br>`/gift-ideas`, `/gift-ready`, `/guess` |
| **Gift night** 🍻 | Hand out gifts however your group does it | |
| **After** | `/santa-admin wrap-up` | `/hall-of-fame` |
| **Next year** | `/santa-admin new-season` (keeps exclusions, venue, budget and history) | |

### How the secret parts work
- **Nobody sees the draw.** That includes the organizer. The only place it exists is `santa.db`, so don't open it mid-season.
- **Blind suggestions** are strict: one person from the pool *will* get that giftee, chosen at random at draw time.
  A pool of one isn't blind, and the bot warns you about that.
- **Anonymous messages:** the giftee never learns who their Santa is. The Santa sees the giftee's name,
  which they already know.
- **Guesses lock on gift night**, the day everyone finds out in person.
- **If someone's DMs are closed**, the bot tells them when they join and flags them in `/santa-admin roster`.
  They can still use `/my-giftee` in the server.

---

## ☁️ Keeping it running 24/7
**Windows (recommended if your PC is usually on):** run this once in PowerShell from the bot's folder:
```powershell
.\install_autostart.ps1              # starts hidden when you log in, no admin needed
.\install_autostart.ps1 -AtStartup   # or: starts when Windows boots, even before login (run PowerShell as admin)
.\install_autostart.ps1 -Remove      # undo
```
It registers a Scheduled Task that runs `supervisor.py`, which restarts the bot if it ever stops.
Only one copy of the bot can run at a time. `start.bat` will tell you if the background one is already running.

**Is it OK?** Run `.venv\Scripts\python healthcheck.py` to see whether it's connected, its last heartbeat,
restarts and recent errors. Logs are in `logs/`.

**Elsewhere:** any small always-on machine works, such as a Raspberry Pi or a cheap VPS. Copy the folder along with your `.env`,
then run `python supervisor.py` (or `bot.py` under systemd, pm2 or Docker). Reminders that were due while the bot was off get
posted when it comes back.

## 🛠️ Development
```bash
pip install -r requirements-dev.txt
pytest
```
| Path | What |
|---|---|
| `santa/draw.py` | The draw algorithm: constraint search, repairs for late joiners and dropouts. Pure Python. |
| `santa/db.py` | SQLite storage |
| `santa/actions.py` | Participant actions shared by buttons and slash commands |
| `santa/cogs/` | Slash commands: `participant`, `secret`, `admin`, `scheduler` |
| `tests/` | Unit tests plus a full-season end-to-end test using fake Discord objects |

PRs welcome! Please keep the golden rule: **nothing may ever reveal a pairing to anyone except the Santa themselves**
(until `/santa-admin wrap-up`).

## 📄 License
[MIT](LICENSE)
