import pytest

from santa import letter

pytestmark = pytest.mark.skipif(not letter.available(), reason="assets/santa-letter.png missing")


def test_clean_name_drops_emoji():
    assert letter.clean_name("Phusion 🍜") == "Phusion"
    assert letter.clean_name("unbanned (honor restricted)") == "unbanned (honor restricted)"
    assert letter.clean_name("🎄🎄") == "your giftee"


@pytest.mark.parametrize("name", ["Sam", "Max Mourner", "District Attorney Zach",
                                  "averyveryveryverylongusernamewithnospaces", "Zoë Ångström", "山田太郎"])
def test_render_any_name(name):
    im = letter.render(name, "$100", "Fri, Dec 11", "The Last Street")
    assert im.size == letter._base().size
    cx, cy = letter.PAPER_CENTER
    box = (cx - 120, cy - 150, cx + 120, cy + 150)
    assert im.crop(box).tobytes() != letter._base().crop(box).tobytes()  # something was written on the paper
    buf = letter.render_jpeg(name, "$100")
    assert buf.getbuffer().nbytes > 10_000
