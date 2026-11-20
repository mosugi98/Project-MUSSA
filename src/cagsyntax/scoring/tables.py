"""Official SYNTAX Score I tables, transcribed from the official calculator's JavaScript.

SOURCE/VERSION record where the numbers come from. They were checked against the official
calculator by running its own code over generated cases (see tools/oracle and
tests/scoring/golden.json); the 2005 paper was not consulted.
"""
from __future__ import annotations

SOURCE = "https://syntaxscore.org/calculator/syntaxscore/javascript/frameset.js"
VERSION = "official calculator 2.28"

# id, weight for right dominance, weight for left dominance (None = segment not applicable).
# Row order is the official table order; "most proximal" is judged in this order.
_ROWS = [
    ("1", 1, 0), ("2", 1, 0), ("3", 1, 0), ("4", 1, None),
    ("16", 0.5, None), ("16a", 0.5, None), ("16b", 0.5, None), ("16c", 0.5, None),
    ("5", 5, 6), ("6", 3.5, 3.5), ("7", 2.5, 2.5), ("8", 1, 1),
    ("9", 1, 1), ("9a", 1, 1), ("10", 0.5, 0.5), ("10a", 0.5, 0.5),
    ("11", 1.5, 2.5), ("12", 1, 1), ("12a", 1, 1), ("12b", 1, 1),
    ("13", 0.5, 1.5), ("14", 0.5, 1), ("14a", 0.5, 1), ("14b", 0.5, 1),
    ("15", None, 1),
]
SEGMENT_IDS: tuple[str, ...] = tuple(r[0] for r in _ROWS)
_WEIGHTS = {r[0]: (r[1], r[2]) for r in _ROWS}


def weight(segment: str, dominance: str) -> float | None:
    """Weight of a segment for "right" or "left" dominance; None if it does not apply."""
    pair = _WEIGHTS.get(segment)
    if pair is None:
        return None
    return pair[1] if dominance == "left" else pair[0]


# Medina class -> (main proximal, main distal, side branch, points)
MEDINA = {
    "A": (1, 0, 0, 1), "B": (0, 1, 0, 1), "C": (1, 1, 0, 1),
    "D": (1, 1, 1, 2), "E": (0, 0, 1, 2), "F": (1, 0, 1, 2), "G": (0, 1, 1, 2),
}

OSTIAL_SEGMENTS = {"1", "5", "6", "11"}

_E: frozenset[str] = frozenset()
_D5 = frozenset({"9", "9a", "10", "10a", "12", "12a", "12b", "14a", "14b"})
_D11 = frozenset({"12", "12a", "12b", "14a", "14b"})
# Occlusion main segment -> (start index, end index in SEGMENT_IDS, denied segment ids).
# Used to count segments "beyond the occlusion" (official meSegmentVisualizedTableHelp).
VISUALIZED_HELP: dict[str, tuple[int, int, frozenset[str]]] = {
    "1": (0, 4, _E), "2": (1, 4, _E), "3": (2, 4, _E), "4": (3, 4, frozenset({"4", "16"})),
    "16": (4, 4, _E), "16a": (5, 5, _E), "16b": (6, 6, _E), "16c": (7, 7, _E),
    "5": (8, 24, _D5), "6": (9, 11, _E), "7": (10, 11, _E), "8": (11, 11, _E),
    "9": (12, 12, _E), "9a": (13, 13, _E), "10": (14, 14, _E), "10a": (15, 15, _E),
    "11": (16, 24, _D11), "12": (17, 17, _E), "12a": (18, 18, _E), "12b": (19, 19, _E),
    "13": (20, 21, _E), "14": (21, 21, _E), "14a": (22, 22, _E), "14b": (23, 23, _E),
    "15": (24, 24, _E),
}
