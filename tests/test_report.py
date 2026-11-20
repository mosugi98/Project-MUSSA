import pytest

from cagsyntax.report import LevelStats, disagreement_report
from cagsyntax.scoring import CaseResult
from cagsyntax.store import CaseStore


def result(total, group, status="complete"):
    return CaseResult(status=status, issues=[], total=total, group=group, dominance="right",
                      scoring_dominance="right", lesions=[])


@pytest.fixture
def store(tmp_path):
    s = CaseStore(tmp_path / "cases.sqlite")
    yield s
    s.close()


def put(store, uid, user, total, group, status="complete"):
    store.ensure_case(uid, "h")
    return store.save_entry(uid, user.id, {}, result(total, group, status))


def test_empty_store_has_no_rows(store):
    assert disagreement_report(store) == []


def test_report_per_level_against_the_confirmed_snapshot(store):
    card1 = store.add_user("Card1", "cardiologist")
    card2 = store.add_user("Card2", "cardiologist")
    r1, r2, r3, r4 = (store.add_user(f"Res{i}", "resident") for i in range(1, 5))
    confirmed = put(store, "A", card1, 20.0, "low")
    store.confirm("A", confirmed.id, card1.id)
    put(store, "A", r1, 20.0, "low")            # same total, same group
    put(store, "A", r2, 24.0, "intermediate")   # differs, group differs
    put(store, "A", r3, 18.0, "low")            # differs, group same
    put(store, "A", card2, 20.0, "low")         # cardiologist agreeing
    put(store, "A", r4, None, None, status="incomplete")   # not counted
    put(store, "B", r1, 30.0, "intermediate")   # case without confirmation: not counted
    rows = disagreement_report(store)
    assert rows == [
        LevelStats("resident", compared=3, same_total=1, same_group=2, mean_abs_diff=2.0, max_abs_diff=4.0),
        LevelStats("cardiologist", compared=1, same_total=1, same_group=1, mean_abs_diff=0.0, max_abs_diff=0.0),
    ]


def test_confirmed_entry_itself_is_excluded(store):
    card = store.add_user("Card", "cardiologist")
    e = put(store, "A", card, 20.0, "low")
    store.confirm("A", e.id, card.id)
    assert disagreement_report(store) == []


def test_compares_with_the_snapshot_not_the_scorers_later_edit(store):
    card = store.add_user("Card", "cardiologist")
    res = store.add_user("Res", "resident")
    e = put(store, "A", card, 20.0, "low")
    store.confirm("A", e.id, card.id)
    put(store, "A", res, 20.0, "low")
    put(store, "A", card, 40.0, "high")         # cardiologist edits after confirming
    [row] = disagreement_report(store)
    assert row.level == "resident" and row.same_total == 1
