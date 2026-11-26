from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "src" / "cagsyntax" / "ui" / "assets"


def test_heart_image_is_a_1200_square_with_transparency():
    with Image.open(ASSETS / "heart_anterior.png") as im:
        assert im.size == (1200, 1200)
        assert im.mode == "RGBA"


def test_licence_file_names_author_licence_and_source():
    text = (ASSETS / "LICENSE-artwork.md").read_text(encoding="utf-8")
    for needle in ("DBCLS", "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0",
                   "https://doi.org/10.7875/togopic.2024.242", "modified"):
        assert needle in text


def test_the_share_alike_image_is_not_bundled():
    names = {p.name.lower() for p in ASSETS.iterdir()}
    assert not any("coronary_arteries.svg" in n for n in names)
