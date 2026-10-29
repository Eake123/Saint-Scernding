"""Writes the giftee's name onto the letter Saint Scernding is holding (assets/santa-letter.png)."""
from __future__ import annotations

import io
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BASE_IMAGE = ROOT / "assets" / "santa-letter.png"

# Where the blank paper sits in BASE_IMAGE (measured by hand): centre, usable size, and its tilt.
PAPER_CENTER = (815, 585)
PAPER_SIZE = (285, 360)
PAPER_TILT = -3.2  # degrees; negative = clockwise, matching the paper

INK = (59, 35, 20)
RED_INK = (128, 22, 26)

FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", Path("/usr/share/fonts"),
             Path("/usr/local/share/fonts"), Path.home() / "Library" / "Fonts", Path("/Library/Fonts")]
FONTS = {
    # first one found wins; falls back to Pillow's built-in font
    "script": ["MTCORSVA.TTF", "Gabriola.ttf", "segoesc.ttf", "DejaVuSerif-Italic.ttf"],
    "serif": ["BOOKOS.TTF", "georgia.ttf", "pala.ttf", "DejaVuSerif.ttf"],
    "wide": ["segoeui.ttf", "arialuni.ttf", "NotoSans-Regular.ttf", "DejaVuSans.ttf"],
}


@lru_cache(maxsize=None)
def _font_path(role: str) -> str | None:
    for name in FONTS[role]:
        for d in FONT_DIRS:
            hits = [d / name] if (d / name).exists() else (list(d.rglob(name)) if d.is_dir() and d.name != "Fonts" else [])
            if hits:
                return str(hits[0])
    return None


@lru_cache(maxsize=None)
def _font(role: str, size: int) -> ImageFont.FreeTypeFont:
    path = _font_path(role)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


@lru_cache(maxsize=1)
def _base() -> Image.Image:
    return Image.open(BASE_IMAGE).convert("RGB")


def available() -> bool:
    return BASE_IMAGE.exists()


def clean_name(name: str) -> str:
    """Drop emoji and other symbols the letter fonts can't draw ('Phusion 🍜' -> 'Phusion')."""
    keep = []
    for ch in unicodedata.normalize("NFC", name):
        cat = unicodedata.category(ch)
        if cat[0] in "LNPZ" or cat in ("Sm", "Sc"):
            keep.append(ch)
    cleaned = " ".join("".join(keep).split())
    return cleaned or "your giftee"


def _fit_name(draw: ImageDraw.ImageDraw, name: str, max_w: int) -> tuple[list[str], ImageFont.FreeTypeFont]:
    role = "script" if all(ord(c) < 0x250 for c in name) else "wide"
    for size in range(64, 29, -2):
        f = _font(role, size)
        if draw.textlength(name, font=f) <= max_w:
            return [name], f
    # too long for one line: split into two balanced lines
    words = name.split()
    if len(words) > 1:
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    else:
        lines = [name[: len(name) // 2] + "-", name[len(name) // 2:]]
    for size in range(44, 15, -2):
        f = _font(role, size)
        if all(draw.textlength(l, font=f) <= max_w for l in lines):
            return lines, f
    return lines, _font(role, 16)


def render(name: str, budget: str, when: str | None = None, venue: str | None = None) -> Image.Image:
    w = PAPER_SIZE[0]
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    items: list[tuple] = []  # ("text", str, font, fill, gap) | ("divider", gap)
    items.append(("text", "Ho ho ho!", _font("script", 44), RED_INK, 12))
    items.append(("text", "This year, you are", _font("serif", 20), INK, 5))
    items.append(("text", "the Secret Santa for", _font("serif", 20), INK, 14))
    lines, name_font = _fit_name(measure, clean_name(name), w - 44)
    for i, l in enumerate(lines):
        items.append(("text", l, name_font, RED_INK, 4 if i < len(lines) - 1 else 6))
    items.append(("divider", 26))
    small = _font("serif", 19)
    details = [f"Budget: {budget}"] + ([f"Gift Night: {when}"] if when else []) + ([venue] if venue else [])
    for t in details:
        items.append(("text", t, small, INK, 7))
    return _compose(items, "Shhh... keep it secret!")


def render_notice(heading: list[str], big: str, details: list[str], footer: str) -> Image.Image:
    """Saint Scernding holding up an announcement (e.g. a date change) instead of a giftee's name."""
    w = PAPER_SIZE[0]
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    items: list[tuple] = [("text", "Ho ho ho!", _font("script", 44), RED_INK, 12)]
    for i, t in enumerate(heading):
        items.append(("text", t, _font("serif", 20), INK, 5 if i < len(heading) - 1 else 14))
    lines, big_font = _fit_name(measure, big, w - 44)
    for i, l in enumerate(lines):
        items.append(("text", l, big_font, RED_INK, 4 if i < len(lines) - 1 else 6))
    items.append(("divider", 26))
    for t in details:
        items.append(("text", t, _font("serif", 19), INK, 7))
    return _compose(items, footer)


def _compose(items: list[tuple], footer: str) -> Image.Image:
    """Lay the items out centred on the paper (above the footer), tilt, and paste onto the photo."""
    w, h = PAPER_SIZE
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def height(item):
        if item[0] == "divider":
            return item[1]
        _, text, font, _, gap = item
        box = font.getbbox(text)
        return box[3] - box[1] + gap

    footer_h = 52
    y = max(4, (h - footer_h - sum(height(i) for i in items)) / 2)
    for item in items:
        if item[0] == "divider":
            mid = y + item[1] / 2
            d.line([(w * 0.25, mid), (w * 0.75, mid)], fill=RED_INK + (190,), width=2)
            d.ellipse([(w / 2 - 4, mid - 4), (w / 2 + 4, mid + 4)], fill=RED_INK)
        else:
            _, text, font, fill, _ = item
            d.text(((w - d.textlength(text, font=font)) / 2, y - font.getbbox(text)[1]), text, font=font, fill=fill)
        y += height(item)

    script = _font("script", 27)
    d.text(((w - d.textlength(footer, font=script)) / 2, h - 44), footer, font=script, fill=RED_INK)

    # a touch of transparency so it reads as ink on paper, then tilt to match the paper
    alpha = layer.getchannel("A").point(lambda a: int(a * 0.92))
    layer.putalpha(alpha)
    layer = layer.rotate(PAPER_TILT, resample=Image.BICUBIC, expand=True)

    out = _base().copy()
    cx, cy = PAPER_CENTER
    out.paste(layer, (round(cx - layer.width / 2), round(cy - layer.height / 2)), layer)
    return out


def render_jpeg(*args, **kwargs) -> io.BytesIO:
    buf = io.BytesIO()
    render(*args, **kwargs).save(buf, "JPEG", quality=88, optimize=True)
    buf.seek(0)
    return buf
