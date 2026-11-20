from cagsyntax.scoring.tables import (MEDINA, OSTIAL_SEGMENTS, SEGMENT_IDS, SOURCE, VERSION,
                                      VISUALIZED_HELP, weight)


def test_source_and_version_recorded():
    assert SOURCE == "https://syntaxscore.org/calculator/syntaxscore/javascript/frameset.js"
    assert "2.28" in VERSION


def test_25_segments_in_official_order():
    assert len(SEGMENT_IDS) == 25
    assert SEGMENT_IDS[:5] == ("1", "2", "3", "4", "16")
    assert SEGMENT_IDS[8] == "5" and SEGMENT_IDS[24] == "15"


def test_weights_match_official_table():
    assert weight("5", "right") == 5 and weight("5", "left") == 6
    assert weight("6", "right") == 3.5
    assert weight("1", "left") == 0
    assert weight("13", "left") == 1.5 and weight("13", "right") == 0.5
    assert weight("14a", "left") == 1 and weight("14a", "right") == 0.5
    assert weight("15", "left") == 1
    assert weight("11", "right") == 1.5 and weight("11", "left") == 2.5


def test_segments_not_applicable_to_dominance_are_none():
    for seg in ("4", "16", "16a", "16b", "16c"):
        assert weight(seg, "left") is None and weight(seg, "right") is not None
    assert weight("15", "right") is None
    assert weight("99", "right") is None


def test_medina_points():
    assert MEDINA["A"] == (1, 0, 0, 1)
    assert [MEDINA[k][3] for k in "ABC"] == [1, 1, 1]
    assert [MEDINA[k][3] for k in "DEFG"] == [2, 2, 2, 2]
    assert MEDINA["G"][:3] == (0, 1, 1)


def test_ostial_segments():
    assert OSTIAL_SEGMENTS == {"1", "5", "6", "11"}


def test_visualized_help_ranges_and_deny_lists():
    assert VISUALIZED_HELP["1"] == (0, 4, frozenset())
    assert VISUALIZED_HELP["4"] == (3, 4, frozenset({"4", "16"}))
    assert VISUALIZED_HELP["5"][:2] == (8, 24)
    assert VISUALIZED_HELP["5"][2] == frozenset({"9", "9a", "10", "10a", "12", "12a", "12b", "14a", "14b"})
    assert VISUALIZED_HELP["11"] == (16, 24, frozenset({"12", "12a", "12b", "14a", "14b"}))
    assert VISUALIZED_HELP["13"][:2] == (20, 21)
    assert VISUALIZED_HELP["15"] == (24, 24, frozenset())
    assert set(VISUALIZED_HELP) == set(SEGMENT_IDS)
