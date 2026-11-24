"""Render the artery map offscreen to PNG files for checking segment placement.

    python tools/ui/render_artery_map.py --out <folder>

Writes map_<dominance>_<theme>_<mode>.png: dominance right/left, theme meadow (light) / forest (dark), mode
idle (nothing selected) / all (every applicable segment selected, first segment ringed)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# No offscreen platform here: it has no fonts, so the segment numbers would draw as empty boxes. Nothing is shown
# on screen; the widget is only painted into an image.
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from PySide6.QtWidgets import QApplication  # noqa: E402

from cagsyntax.scoring.tables import SEGMENT_IDS, weight  # noqa: E402
from cagsyntax.ui import theme as T  # noqa: E402
from cagsyntax.ui.artery_map import CANVAS, CAPTION_H, ArteryMap  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the artery map to PNG files.")
    parser.add_argument("--out", required=True, help="folder for the PNG files")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for theme_name in ("meadow", "forest"):
        T.set_theme(T.get_theme().with_changes(**{k: T.PRESETS[theme_name][k] for k in T.COLOR_TOKENS}))
        for dom in ("right", "left"):
            for mode in ("idle", "all"):
                widget = ArteryMap()
                widget.resize(int(CANVAS), int(CANVAS) + CAPTION_H)
                widget.set_scoring_dominance(dom)
                if mode == "all":
                    chosen = [s for s in SEGMENT_IDS if weight(s, dom) is not None]
                    widget.set_selected(chosen)
                    widget.set_first_segment("6")
                target = out / f"map_{dom}_{theme_name}_{mode}.png"
                widget.grab().save(str(target))
                print("wrote", target)
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
