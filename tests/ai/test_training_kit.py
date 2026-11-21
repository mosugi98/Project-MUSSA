import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "training"
SRC_AI = ROOT / "src" / "cagsyntax" / "ai"
EXPECTED = {"train_segmentation.py", "segment_names.json", "README.txt", "mussa_ai/__init__.py", "mussa_ai/sampling.py",
            "mussa_ai/arcade.py", "mussa_ai/preprocess.py", "mussa_ai/metrics.py", "mussa_ai/segment_names.py"}
ARCADE_MD5 = "c5b1973ade06f7dff210f878161e1a76"
ARCADE_URL = "https://zenodo.org/records/10390295/files/arcade.zip?download=1"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    make_kit = load_module(TOOLS / "make_kit.py", "make_kit")
    out = tmp_path_factory.mktemp("kit") / "kit.zip"
    names = make_kit.build_kit(out)
    return out, names


def test_kit_contains_exactly_the_expected_files(kit):
    out, names = kit
    assert set(names) == EXPECTED
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == EXPECTED


def test_kit_copies_of_the_shared_modules_are_byte_identical_to_the_app_sources(kit):  # Review Focus 5
    out, _ = kit
    with zipfile.ZipFile(out) as z:
        for name in ("arcade.py", "preprocess.py", "metrics.py", "segment_names.py"):
            assert z.read(f"mussa_ai/{name}") == (SRC_AI / name).read_bytes(), name


def test_kit_holds_no_hospital_data(kit):
    _, names = kit
    forbidden = {"data", "store", "cases.sqlite", "mussa-data", "dataset contoh"}
    for name in names:
        assert not (set(part.lower() for part in Path(name).parts) & forbidden), name
        assert not name.endswith((".dcm", ".sqlite", ".json")) or name == "segment_names.json"


def test_kit_is_self_contained_and_matches_the_engines_segment_names(kit, tmp_path):
    out, _ = kit
    with zipfile.ZipFile(out) as z:
        z.extractall(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    code = ("from mussa_ai import arcade, preprocess, metrics, segment_names; "
            "import sys; assert 'cagsyntax' not in sys.modules; print(len(segment_names.SEGMENT_NAMES))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "25"
    from cagsyntax.scoring.tables import SEGMENT_IDS
    assert json.loads((tmp_path / "segment_names.json").read_text()) == list(SEGMENT_IDS)


def test_training_script_parses_and_lists_every_option_without_torch_installed():
    script = TOOLS / "train_segmentation.py"
    compile(script.read_text(encoding="utf-8"), str(script), "exec")
    mod = load_module(script, "train_segmentation")
    help_text = mod.build_parser().format_help()
    for option in ("--arcade", "--out", "--epochs", "--batch-size", "--lr", "--size", "--encoder", "--smoke", "--patience", "--pos-weight"):
        assert option in help_text, option
    args = mod.build_parser().parse_args(["--arcade", "a", "--out", "o"])
    assert (args.epochs, args.batch_size, args.lr, args.size, args.encoder) == (60, 8, 3e-4, 512, "resnet34")
    assert (args.patience, args.pos_weight) == (15, 5.0)
    smoke = mod.apply_smoke(mod.build_parser().parse_args(["--arcade", "a", "--out", "o", "--smoke"]))
    assert (smoke.epochs, smoke.size, smoke.limit) == (1, 128, 8)


def test_training_script_geometry_helpers_are_correct_without_torch():
    mod = load_module(TOOLS / "train_segmentation.py", "train_segmentation_geo")
    import numpy as np
    from PIL import Image
    # identity transform leaves an image unchanged
    img = (np.arange(64 * 64).reshape(64, 64) % 255).astype(np.uint8)
    same = mod.affine_image(img, theta=0.0, scale=1.0, tx=0.0, ty=0.0, resample=Image.Resampling.NEAREST)
    assert np.array_equal(same, img)
    # a pure shift moves content by the requested number of pixels
    dot = np.zeros((64, 64), dtype=np.uint8)
    dot[20, 20] = 255
    moved = mod.affine_image(dot, theta=0.0, scale=1.0, tx=5.0, ty=-3.0, resample=Image.Resampling.NEAREST)
    assert moved[17, 25] == 255 and moved.sum() == 255
    # masks and images get the identical geometry (same coefficients)
    m = np.zeros((2, 64, 64), dtype=bool)
    m[0, 20, 20] = True
    img2, m2 = mod.augment_pair(dot, m, np.random.default_rng(1), geometry_only=True)
    ys, xs = np.nonzero(img2 > 0)
    weights = img2[ys, xs].astype(float)
    cy, cx = np.average(ys, weights=weights), np.average(xs, weights=weights)   # bilinear may spread the dot
    my, mx = np.nonzero(m2[0])
    assert len(my) == 1 and abs(cy - my[0]) < 1.0 and abs(cx - mx[0]) < 1.0 and not m2[1].any()


def test_notebook_is_valid_and_has_the_cells_in_order(kit):
    nb = json.loads((TOOLS / "MUSSA_ARCADE_segments.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    text = [("".join(c["source"]), c["cell_type"]) for c in nb["cells"]]
    code = "\n".join(t for t, kind in text if kind == "code")
    assert ARCADE_URL in code and ARCADE_MD5 in code
    positions = [code.index(marker) for marker in
                 ("pip", "hashlib", "files.upload", "train_segmentation.py", "files.download")]
    assert positions == sorted(positions)
    assert "segments.onnx" in code and "segments.card.json" in code


def test_the_training_dataset_can_be_pickled_for_dataloader_workers(tmp_path):
    """DataLoader workers on Windows (and Python 3.14 everywhere) pickle the dataset, so the class
    must live at module level. Found by running the real script with workers."""
    import pickle
    import numpy as np
    from tests.ai.test_arcade import make_split
    mod = load_module(TOOLS / "train_segmentation.py", "train_segmentation_pickle")
    sys.modules["train_segmentation_pickle"] = mod          # pickle re-imports classes by module name
    root = make_split(tmp_path)
    data = mod.SegmentationData(root, size=32, augment=True, limit=1)
    clone = pickle.loads(pickle.dumps(data))
    assert len(clone) == 1 and clone.size == 32 and clone.augment is True
    data.epoch = 3
    assert pickle.loads(pickle.dumps(data)).epoch == 3


def test_the_best_weights_are_saved_before_the_onnx_export_so_a_failed_export_loses_nothing():
    src = (TOOLS / "train_segmentation.py").read_text(encoding="utf-8")
    assert src.index("segments_best.pt") < src.index("export_onnx(model, args.size")
    assert "torch.save" in src


def test_notebook_installs_the_export_packages_and_checks_the_exported_model_before_download():
    nb = json.loads((TOOLS / "MUSSA_ARCADE_segments.ipynb").read_text(encoding="utf-8"))
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert "onnxscript" in code and "onnxruntime" in code and "onnx " in code + " "
    assert "(1, 25" in code and code.index("onnxruntime.InferenceSession") < code.index("files.download")


def test_notebook_works_on_colab_and_kaggle():
    nb = json.loads((TOOLS / "MUSSA_ARCADE_segments.ipynb").read_text(encoding="utf-8"))
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    for needle in ("/kaggle/working", "/kaggle/input", "ON_COLAB", "__MACOSX"):
        assert needle in code, needle
    assert "KIT" in code and "internet" in "".join("".join(c["source"]) for c in nb["cells"]).lower()


def test_training_script_has_the_task_oversampling_and_fine_tuning_options():
    mod = load_module(TOOLS / "train_segmentation.py", "train_segmentation_opts")
    args = mod.build_parser().parse_args(["--arcade", "a", "--out", "o"])
    assert (args.task, args.rare_power, args.init_weights, args.extra_train) == ("segments", 0.5, None, [])
    more = mod.build_parser().parse_args(["--arcade", "a", "--out", "o", "--task", "stenosis", "--rare-power", "0",
                                          "--init-weights", "w.pt", "--extra-train", "x", "--extra-train", "y"])
    assert (more.task, more.rare_power, more.init_weights, more.extra_train) == ("stenosis", 0.0, "w.pt", ["x", "y"])
    with pytest.raises(SystemExit):
        mod.build_parser().parse_args(["--arcade", "a", "--out", "o", "--task", "vessels"])


def test_task_settings_name_the_classes_folder_and_output_files():
    mod = load_module(TOOLS / "train_segmentation.py", "train_segmentation_tasks")
    seg, ste = mod.task_settings("segments"), mod.task_settings("stenosis")
    assert len(seg["classes"]) == 25 and seg["folder"] == "syntax" and seg["model"] == "segments.onnx"
    assert ste["classes"] == ["stenosis"] and ste["folder"] == "stenosis" and ste["model"] == "stenosis.onnx"
    assert ste["card"] == "stenosis.card.json" and seg["card"] == "segments.card.json"
    assert ste["mode"] == "stenosis" and seg["mode"] == "segments"


def test_the_kit_contains_the_sampling_module_byte_identical(kit):
    out, names = kit
    assert "mussa_ai/sampling.py" in names
    with zipfile.ZipFile(out) as z:
        assert z.read("mussa_ai/sampling.py") == (SRC_AI / "sampling.py").read_bytes()
