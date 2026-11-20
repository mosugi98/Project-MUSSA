from cagsyntax.export.splits import SPLITS, suggest_split


def test_known_examples_are_stable():
    # hard-coded so a change of the rule is noticed: bucket = sha256("mussa-split:" + key) % 100
    assert suggest_split("patient-a") == "train"      # bucket 49
    assert suggest_split("patient-b") == "val"        # bucket 80
    assert suggest_split("395fe09f") == "test"        # bucket 89


def test_same_patient_always_gets_the_same_split_and_it_is_valid():
    for key in ("x", "patient-a", "a" * 64, ""):
        assert suggest_split(key) == suggest_split(key) and suggest_split(key) in SPLITS


def test_shares_are_close_to_70_15_15_over_many_patients():
    n = 3000
    counts = {s: 0 for s in SPLITS}
    for i in range(n):
        counts[suggest_split(f"patient-{i}")] += 1
    assert abs(counts["train"] / n - 0.70) < 0.03
    assert abs(counts["val"] / n - 0.15) < 0.03
    assert abs(counts["test"] / n - 0.15) < 0.03
