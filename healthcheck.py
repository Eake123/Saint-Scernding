"""Is Saint Scernding healthy? Prints a short report; exit code 0 = healthy, 1 = something's wrong.

    .venv\\Scripts\\python healthcheck.py [--hours 24]
"""
import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

from santa import runtime

LINE_TIME = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]")


def recent_lines(name: str, since: datetime) -> list[str]:
    """Lines from logs/<name> (and its rotated copies) newer than `since` (local time)."""
    lines = []
    for path in sorted(runtime.LOG_DIR.glob(f"{name}*"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        keep = False
        for line in text:
            m = LINE_TIME.match(line)
            if m:
                keep = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= since
            if keep:
                lines.append(line)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24, help="how far back to look in the logs")
    args = parser.parse_args()
    since = datetime.now() - timedelta(hours=args.hours)
    problems, report = [], []

    supervisor = runtime.is_locked("supervisor.lock")
    bot = runtime.is_locked("bot.lock")
    report.append(f"Supervisor running: {'yes' if supervisor else 'NO'}")
    report.append(f"Bot process running: {'yes' if bot else 'NO'}")
    if not bot:
        problems.append("bot process is not running")
    elif not supervisor:
        report.append("  (bot is running without the supervisor, so it won't auto-restart)")

    hb = runtime.read_heartbeat()
    if not hb:
        problems.append("no heartbeat file yet")
    else:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb["time"])).total_seconds()
        report.append(f"Last heartbeat: {age:.0f}s ago | connected={hb.get('connected')} | "
                      f"latency={hb.get('latency_ms')}ms | in server={hb.get('guild')} | "
                      f"phase={hb.get('phase')} | participants={hb.get('participants')}")
        if age > 300:
            problems.append(f"heartbeat is stale ({age / 60:.0f} min old)")
        elif not hb.get("connected"):
            problems.append("bot is running but not connected to Discord")
        if hb.get("guild") is False:
            problems.append("bot is not in the server set by GUILD_ID")

    restarts = [l for l in recent_lines("supervisor.log", since) if "Bot stopped" in l]
    report.append(f"Restarts in last {args.hours:g}h: {len(restarts)}")
    if len(restarts) >= 3:
        problems.append(f"bot restarted {len(restarts)} times in {args.hours:g}h")
    for l in restarts[-3:]:
        report.append(f"  {l}")

    errors = [l for l in recent_lines("santa.log", since) if "[ERROR" in l or "[CRITICAL" in l]
    report.append(f"Errors in last {args.hours:g}h: {len(errors)}")
    for l in errors[-5:]:
        report.append(f"  {l[:300]}")
    if errors:
        problems.append(f"{len(errors)} error(s) logged")

    print("HEALTHY" if not problems else "PROBLEMS: " + "; ".join(problems))
    print("\n".join(report))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
