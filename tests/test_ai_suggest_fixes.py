"""Regression tests for the findings of the final review of the AI suggestions branch."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv
import importlib.util
import json
import re
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from cagsyntax.ai.labels import check_coco, export_frames, split_coco
from cagsyntax.ai.segment_names import SEGMENT_NAMES
from cagsyntax.ai.segmenter import Segmenter
from cagsyntax.ai.stenosis import StenosisFinder
from cagsyntax.store import CaseStore
from tests.ai.test_arcade import make_split
from tests.ai.test_labels import SALT, big_source, make_store
from tests.ai.toy_models import make_toy_model, write_card
from tests.dicom_factory import make_xa
from tests.test_scoring_fixes import make_two_studies, open_case, other_study_row
from tests.test_scoring_flow import fill_lad
from tests.test_suggest_app import FakeSegmenter, FakeStenosis, case_window, choose, segments_of

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def no_dialog(win):
    win._choose_suggestions = lambda s: (_ for _ in ()).throw(AssertionError("the dialog must not open"))


def fakes(win, segmenter=None, stenosis=None):
    win.segmenter = segmenter or FakeSegmenter()
    win.stenosis = stenosis or FakeStenosis()
    win.messages = []
    win._warn = win.messages.append
    return win


# ---- 1 (Critical): suggestions must never reach another patient's form ----
def test_suggestions_from_a_series_of_another_case_are_refused(qapp, tmp_path):
    win, _ = open_case(tmp_path, src=make_two_studies(tmp_path))
    fill_lad(win)                                                   # unsaved edits keep the form on this case
    win.item_list.setCurrentRow(other_study_row(win))               # ...while another study's series is on screen
    fakes(win)
    choose(win, {"6", "11"})
    before = [les.segments for les in win.panel.case().lesions]
    assert win.suggest_lesions() is None
    assert "different case" in win.statusBar().currentMessage().lower()
    assert [les.segments for les in win.panel.case().lesions] == before
    assert win.store.suggestion_events(win._scoring_study[0]) == []


def test_suggestions_are_refused_while_the_scoring_panel_is_hidden(qapp, tmp_path):
    win = case_window(tmp_path)
    no_dialog(win)
    win.scoring_dock.hide()
    assert win.suggest_lesions() is None
    assert "scoring panel" in win.statusBar().currentMessage().lower()
    assert segments_of(win) == [[]]


def test_suggestions_still_work_for_the_series_of_the_open_case(qapp, tmp_path):
    win = case_window(tmp_path)
    choose(win, {"6"})
    assert [s.segment for s in win.suggest_lesions()] == ["6"]


# ---- 2: the logged frame is the analysed frame ----
def test_the_log_records_the_frame_that_was_analysed_even_if_the_cine_moves(qapp, tmp_path):
    win = case_window(tmp_path)
    analysed = win.cine.frame_index()

    def chooser(suggestions):
        win.cine.player.seek(3)                                     # the scorer scrolls while the list is open
        return [s for s in suggestions if s.segment == "6"]

    win._choose_suggestions = chooser
    win.suggest_lesions()
    assert win.cine.frame_index() != analysed
    assert {e.frame for e in win.store.suggestion_events(win._scoring_study[0])} == {analysed}


def test_suggestions_are_refused_while_the_cine_is_playing(qapp, tmp_path):
    win = case_window(tmp_path)
    no_dialog(win)
    win.cine.player.playing = True
    assert win.suggest_lesions() is None
    assert "pause" in win.statusBar().currentMessage().lower()
    win.cine.player.playing = False


# ---- 3: burned-in text must not leak into labelling images ----
def burned_store(tmp_path):
    from cagsyntax.dicom_import.importer import import_path
    src = tmp_path / "in"
    src.mkdir()
    make_xa(src / "clean.dcm", burned_in=False, primary=10.0)
    make_xa(src / "text.dcm", burned_in=True, primary=20.0)
    store = tmp_path / "store"
    import_path(src, store, SALT)
    return store


def test_series_that_may_have_burned_in_text_are_not_exported_for_labelling_by_default(tmp_path):
    result = export_frames(burned_store(tmp_path), tmp_path / "png")
    assert len(result.written) == 1 and len(result.skipped) == 1
    assert "burned-in" in result.skipped[0][1].lower()
    rows = list(csv.DictReader((tmp_path / "png" / "frames.csv").open(encoding="utf-8")))
    assert len(rows) == 1


def test_burned_in_series_can_be_included_when_the_scorer_has_checked_them(tmp_path):
    result = export_frames(burned_store(tmp_path), tmp_path / "png", include_burned_in=True)
    assert len(result.written) == 2 and result.skipped == []


# ---- 4: CVAT may keep images in a subfolder ----
def to_cvat_layout(root: Path, subfolder="default"):
    (root / "images" / subfolder).mkdir()
    for image in list((root / "images").glob("*.png")):
        shutil.move(str(image), str(root / "images" / subfolder / image.name))


def test_check_finds_images_inside_a_subfolder_of_images(tmp_path):
    root = make_split(tmp_path)
    to_cvat_layout(root)
    assert check_coco(root).ok


def test_check_still_names_an_image_missing_everywhere(tmp_path):
    root = make_split(tmp_path)
    to_cvat_layout(root)
    (root / "images" / "default" / "2.png").unlink()
    assert any("2.png" in p for p in check_coco(root).problems)


def test_split_copes_with_images_in_a_subfolder_and_writes_a_flat_loadable_folder(tmp_path):
    src = big_source(tmp_path)
    to_cvat_layout(src)
    data = json.loads((src / "annotations" / "instances_default.json").read_text())
    out = tmp_path / "labelled"
    result = split_coco(src, out)
    assert result.train_images + result.val_images == len(data["images"])
    from cagsyntax.ai.arcade import ArcadeSplit
    assert len(ArcadeSplit(out / "train")) == result.train_images


def test_a_failed_split_leaves_no_half_written_output(tmp_path):
    src = big_source(tmp_path)
    (src / "images" / "s0_0.png").unlink()                          # one image is really missing
    out = tmp_path / "labelled"
    with pytest.raises(ValueError) as exc:
        split_coco(src, out)
    assert "s0_0.png" in str(exc.value) and not out.exists()


# ---- 10: check_coco gaps ----
def test_a_png_whose_size_differs_from_the_json_is_a_problem(tmp_path):
    root = make_split(tmp_path)
    Image.fromarray(np.zeros((80, 70), dtype=np.uint8)).save(root / "images" / "1.png")
    assert any("size" in p.lower() and "1.png" in p for p in check_coco(root).problems)


def test_malformed_entries_are_reported_in_plain_words_not_as_crashes(tmp_path):
    root = make_split(tmp_path)
    path = root / "annotations" / "train.json"
    data = json.loads(path.read_text())
    del data["images"][0]["file_name"]
    data["annotations"][1]["segmentation"] = [["a", "b", "c", "d", "e", "f"]]
    path.write_text(json.dumps(data))
    report = check_coco(root)
    assert not report.ok and report.problems


def test_images_with_segment_labels_but_no_stenosis_label_get_a_training_warning(tmp_path):
    report = check_coco(make_split(tmp_path))                       # image 2 has a segment and no stenosis label
    assert any("stenosis" in w and "narrowing" in w for w in report.warnings)


# ---- 9: model identity in the log ----
def test_a_loaded_model_has_an_identity_that_changes_with_the_file(tmp_path):
    a = make_toy_model(tmp_path / "a" / "segments.onnx", size=32) if (tmp_path / "a").mkdir() is None else None
    write_card(a, size=32)
    b = make_toy_model(tmp_path / "b.onnx", size=32, positive=(1,)) if True else None
    (tmp_path / "b.card.json").write_text((tmp_path / "a" / "segments.card.json").read_text())
    ida, idb = Segmenter.load(a).model_id, Segmenter.load(b).model_id
    assert re.fullmatch(r"2026-11-21 [0-9a-f]{8}", ida) and ida != idb


def test_the_stenosis_finder_has_a_model_id_too(tmp_path):
    model = make_toy_model(tmp_path / "stenosis.onnx", size=32, channels=1, positive=(0,))
    write_card(model, size=32, classes=["stenosis"])
    assert re.fullmatch(r"2026-11-21 [0-9a-f]{8}", StenosisFinder.load(model).model_id)


def test_the_log_uses_the_model_id_when_the_model_has_one(qapp, tmp_path):
    seg, ste = FakeSegmenter(), FakeStenosis()
    seg.model_id, ste.model_id = "2026-11-20 aaaa1111", "2026-11-21 bbbb2222"
    win = case_window(tmp_path, segmenter=seg, stenosis=ste)
    choose(win, {"6"})
    win.suggest_lesions()
    e = win.store.suggestion_events(win._scoring_study[0])[0]
    assert e.segment_model == "segments 2026-11-20 aaaa1111" and e.stenosis_model == "stenosis 2026-11-21 bbbb2222"


# ---- 6, 7, 8: honest messages ----
class SegmentFour(FakeSegmenter):
    def predict(self, frame, threshold=None):
        masks = np.zeros((25,) + frame.shape, dtype=bool)
        masks[SEGMENT_NAMES.index("4"), : frame.shape[0] // 2] = True
        return masks


def test_a_suggestion_for_a_segment_that_does_not_exist_for_the_dominance_adds_nothing_and_says_so(qapp, tmp_path):
    win = case_window(tmp_path, segmenter=SegmentFour())
    win.panel.set_dominance("left")                                 # segment 4 does not exist for left dominance
    choose(win, {"4"})
    win.suggest_lesions()
    assert segments_of(win) == [[]]                                 # no empty lesion left behind
    message = win.statusBar().currentMessage().lower()
    assert "added 1" not in message and ("removed" in message or "not valid" in message)


def test_lesions_beyond_the_limit_are_reported_not_dropped_silently(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("cagsyntax.app.MAX_LESIONS", 1)
    win = case_window(tmp_path)
    choose(win, {"6", "11"})
    win.suggest_lesions()
    assert segments_of(win) == [["6"]]
    assert "limit" in win.statusBar().currentMessage().lower()


def test_cancelling_is_documented_as_recording_nothing():
    from cagsyntax import app
    assert "cancel" in app.MainWindow.suggest_lesions.__doc__.lower()


def test_a_segment_already_marked_diffuse_is_not_added_again(qapp, tmp_path):
    win = case_window(tmp_path)
    win.panel.set_dominance("right")
    win.panel.toggle_diffuse("6")
    choose(win, {"6", "11"})
    win.suggest_lesions()
    assert segments_of(win) == [["11"]]


def test_the_dialog_does_not_call_the_model_score_a_confidence():
    from cagsyntax.ai.suggest import Suggestion
    from cagsyntax.ui.suggest_dialog import describe
    text = describe(Suggestion("6", 0.91, 120, 1.0, (0, 0, 1, 1))).lower()
    assert "confidence" not in text and "model score" in text and "91%" in text


# ---- store: back up before upgrading ----
def test_a_version_one_store_is_backed_up_before_it_is_upgraded(tmp_path):
    from tests.test_store_suggestions import V1_SCHEMA
    path = tmp_path / "cases.sqlite"
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    con.execute("INSERT INTO users(name, name_key, level) VALUES('Ana', 'ana', 'resident')")
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    CaseStore(path).close()
    backup = tmp_path / "cases.sqlite.v1.bak"
    assert backup.exists()
    old = sqlite3.connect(backup)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 1
    assert old.execute("SELECT name FROM users").fetchone()[0] == "Ana"
    old.close()


def test_an_existing_backup_is_never_overwritten(tmp_path):
    from tests.test_store_suggestions import V1_SCHEMA
    path = tmp_path / "cases.sqlite"
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    con.execute("PRAGMA user_version = 1")
    con.commit()
    con.close()
    (tmp_path / "cases.sqlite.v1.bak").write_text("older backup")
    CaseStore(path).close()
    assert (tmp_path / "cases.sqlite.v1.bak").read_text() == "older backup"


def test_a_new_store_makes_no_backup(tmp_path):
    CaseStore(tmp_path / "cases.sqlite").close()
    assert not (tmp_path / "cases.sqlite.v1.bak").exists()


# ---- training script and notebook ----
def load_train():
    spec = importlib.util.spec_from_file_location("train_fix", ROOT / "tools" / "training" / "train_segmentation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extra_validation_folders_are_an_option():
    mod = load_train()
    args = mod.build_parser().parse_args(["--arcade", "a", "--out", "o", "--extra-val", "x", "--extra-val", "y"])
    assert args.extra_val == ["x", "y"]
    assert mod.build_parser().parse_args(["--arcade", "a", "--out", "o"]).extra_val == []


def test_the_card_records_which_encoder_weights_were_really_used():
    mod = load_train()
    parse = mod.build_parser().parse_args
    assert mod.effective_encoder_weights(parse(["--arcade", "a", "--out", "o"])) == "imagenet"
    assert mod.effective_encoder_weights(parse(["--arcade", "a", "--out", "o", "--encoder-weights", "none"])) == "none"
    assert mod.effective_encoder_weights(parse(["--arcade", "a", "--out", "o", "--init-weights", "w.pt"])) == "from w.pt"


def notebook_code():
    nb = json.loads((ROOT / "tools" / "training" / "MUSSA_ARCADE_segments.ipynb").read_text(encoding="utf-8"))
    return chr(10).join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def test_the_notebook_validates_on_your_own_val_folder_too():
    assert notebook_code().count("--extra-val") >= 2


def test_the_final_cell_picks_each_model_separately_so_one_failed_fine_tune_cannot_crash_it():
    code = notebook_code()
    assert "def pick(" in code and "FINAL =" not in code
    assert "out_ft" in code and "from the ARCADE-only run" in code
