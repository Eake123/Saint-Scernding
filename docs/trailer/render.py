"""Render the README trailer: docs/trailer/index.html -> frames/*.png -> docs/trailer.gif.

    pip install playwright
    playwright install chromium
    python docs/trailer/render.py                 # full render + GIF
    python docs/trailer/render.py --at 3 9.6 21   # just a few stills into frames/ for checking

Every frame is drawn by the page's window.render(t), so the output is the same on every run.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "frames"
GIF = HERE.parent / "trailer.gif"
W, H = 800, 450


def render_frames(times: list[float], names: list[str]) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(HERE.joinpath("index.html").as_uri())
        page.wait_for_function("window.__ready === true", timeout=120_000)
        broken = page.evaluate("window.__broken")
        if broken:
            print("⚠️ emoji that failed to load:", broken)
        for t, name in zip(times, names):
            page.evaluate(f"render({t})")
            page.screenshot(path=str(FRAMES / name))
        browser.close()


def build_gif(fps: int, colors: int) -> None:
    run = lambda *args: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], cwd=HERE, check=True)
    run("-framerate", str(fps), "-i", "frames/%04d.png",
        "-vf", f"palettegen=stats_mode=full:max_colors={colors}", "palette.png")
    run("-framerate", str(fps), "-i", "frames/%04d.png", "-i", "palette.png",
        "-lavfi", "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", "-loop", "0", str(GIF))
    print(f"✅ {GIF} — {GIF.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--colors", type=int, default=256)
    ap.add_argument("--at", type=float, nargs="+", help="only render stills at these times (seconds)")
    args = ap.parse_args()

    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir()

    if args.at:
        render_frames(args.at, [f"at_{t:05.2f}.png" for t in args.at])
        print(f"stills in {FRAMES}")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        page.goto(HERE.joinpath("index.html").as_uri())
        page.wait_for_function("window.__ready === true", timeout=120_000)
        duration = page.evaluate("window.DURATION")
        browser.close()

    n = round(duration * args.fps)
    render_frames([i / args.fps for i in range(n)], [f"{i:04d}.png" for i in range(n)])
    build_gif(args.fps, args.colors)


if __name__ == "__main__":
    main()
