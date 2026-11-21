"""Tools for labelling your own angiograms and preparing them for training.

1. export_frames: one PNG per series (the middle frame by default) from the MUSSA store, for a labelling tool.
2. check_coco: read a labelled folder (COCO format, as exported by CVAT) and explain every problem in plain words.
3. split_coco: split it into train and val folders that the training script reads, keeping every study whole.

Nothing here reads or writes patient identifiers: the MUSSA store is already de-identified."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from ..dicom_import.models import ImportRejected
from ..dicom_import.reader import read_header, read_xa
from .segment_names import SEGMENT_NAMES

STENOSIS = "stenosis"
VALID_LABELS = set(SEGMENT_NAMES) | {STENOSIS}
MIN_USEFUL_IMAGES = 20


# ---------------------------------------------------------------- frames for labelling
@dataclass
class FramesResult:
    written: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)      # (file name, reason)


def _to_8bit(frame: np.ndarray) -> np.ndarray:
    data = np.asarray(frame, dtype=np.float64)
    low, high = float(data.min()), float(data.max())
    if high <= low:
        return np.zeros(data.shape, dtype=np.uint8)
    return np.round((data - low) / (high - low) * 255.0).astype(np.uint8)


def export_frames(store_dir: Path, out_dir: Path, frame="middle") -> FramesResult:
    """Write PNG frames of every series in the MUSSA store. `frame` is "middle", "all" or a frame number.
    Also writes frames.csv (file, series_uid, study_uid, frame) so labelled images can be traced and split by study."""
    store_dir, out_dir = Path(store_dir), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"{out_dir} is not empty. Choose a new folder so nothing is overwritten.")
    out_dir.mkdir(parents=True, exist_ok=True)
    result, rows = FramesResult(), []
    for path in sorted(store_dir.glob("*.dcm")):
        try:
            series = read_xa(path)
            study_uid = read_header(path).study_uid
        except (ImportRejected, Exception) as exc:                   # one bad file must not stop the rest
            result.skipped.append((path.name, str(exc)))
            continue
        count = len(series.frames)
        if frame == "all":
            chosen = list(range(count))
        elif frame == "middle":
            chosen = [count // 2]
        else:
            chosen = [int(frame)]
        if any(not 0 <= i < count for i in chosen):
            result.skipped.append((path.name, f"frame {frame} does not exist (the series has {count} frames)"))
            continue
        for i in chosen:
            name = f"{path.stem}_f{i}.png"
            Image.fromarray(_to_8bit(series.frames[i])).save(out_dir / name)
            result.written.append(out_dir / name)
            rows.append({"file": name, "series_uid": path.stem, "study_uid": study_uid, "frame": str(i)})
    with (out_dir / "frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "series_uid", "study_uid", "frame"])
        writer.writeheader()
        writer.writerows(rows)
    return result


# ---------------------------------------------------------------- checking a labelled folder
@dataclass
class LabelReport:
    images: int = 0
    annotations: int = 0
    per_category: dict = field(default_factory=dict)
    never_labelled: list = field(default_factory=list)       # SYNTAX segments with no label at all
    unlabelled_images: int = 0
    problems: list = field(default_factory=list)             # these stop training
    warnings: list = field(default_factory=list)             # worth knowing, do not stop training

    @property
    def ok(self) -> bool:
        return not self.problems


def find_annotation_file(root: Path) -> Path | None:
    folder = Path(root) / "annotations"
    for name in (f"{Path(root).name}.json", "instances_default.json"):
        if (folder / name).is_file():
            return folder / name
    found = sorted(folder.glob("*.json")) if folder.is_dir() else []
    return found[0] if len(found) == 1 else None


def check_coco(root: Path) -> LabelReport:
    root = Path(root)
    report = LabelReport()
    path = find_annotation_file(root)
    if path is None:
        report.problems.append(f"No annotation file found in {root / 'annotations'} "
                               "(expected <folder name>.json or instances_default.json).")
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        images, annotations, categories = data["images"], data["annotations"], data["categories"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report.problems.append(f"{path.name} cannot be read as a COCO file ({exc}).")
        return report
    names = {c["id"]: c["name"] for c in categories}
    for category_id, name in names.items():
        if name not in VALID_LABELS:
            tidy = str(name).strip().lower()
            if tidy in VALID_LABELS:
                report.problems.append(f"The label {name!r} must be written exactly as {tidy!r} (no spaces or capitals).")
            else:
                report.problems.append(f"The label {name!r} is not one of the 25 SYNTAX segment names or 'stenosis'.")
    by_id = {im["id"]: im for im in images}
    report.images = len(images)
    for im in images:
        if not (root / "images" / im["file_name"]).is_file():
            report.problems.append(f"Image file {im['file_name']} is listed but missing from the images folder.")
    labelled, outside = set(), 0
    for ann in annotations:
        image = by_id.get(ann.get("image_id"))
        if image is None:
            report.problems.append(f"Label {ann.get('id')} points at an image that is not in the file.")
            continue
        if ann.get("category_id") not in names:
            report.problems.append(f"Label {ann.get('id')} has a category that is not defined.")
            continue
        seg = ann.get("segmentation")
        if not isinstance(seg, list):
            report.problems.append(f"Label {ann.get('id')} on {image['file_name']} is a brush or bitmap mask; "
                                   "draw polygons instead.")
            continue
        if not seg or any(len(poly) < 6 or len(poly) % 2 for poly in seg):
            report.problems.append(f"Label {ann.get('id')} on {image['file_name']} has a polygon with fewer than 3 points.")
            continue
        report.annotations += 1
        labelled.add(image["id"])
        name = names[ann["category_id"]]
        report.per_category[name] = report.per_category.get(name, 0) + 1
        xs = [v for poly in seg for v in poly[0::2]]
        ys = [v for poly in seg for v in poly[1::2]]
        if max(xs) > image["width"] * 1.05 or max(ys) > image["height"] * 1.05 or min(xs) < 0 or min(ys) < 0:
            outside += 1
    report.unlabelled_images = sum(1 for im in images if im["id"] not in labelled)
    report.never_labelled = [s for s in SEGMENT_NAMES if s not in report.per_category]
    if report.unlabelled_images:
        report.warnings.append(f"{report.unlabelled_images} image(s) have no labels. That is fine for stenosis training "
                               "(a frame with no narrowing), but check it is on purpose for segments.")
    if outside:
        report.warnings.append(f"{outside} polygon(s) run outside the image; the parts outside are cut off.")
    if report.images < MIN_USEFUL_IMAGES:
        report.warnings.append(f"Only {report.images} images: too few to train on alone. Use them to fine-tune "
                               "the ARCADE model (--init-weights), and label more.")
    rare = [f"{name} ({n})" for name, n in sorted(report.per_category.items()) if n < 5]
    if rare:
        report.warnings.append("Labels with fewer than 5 examples (the model will barely learn them): " + ", ".join(rare))
    return report


def format_check(report: LabelReport) -> str:
    lines = [f"{report.images} images, {report.annotations} labels."]
    if report.per_category:
        lines.append("Labels per name: " + ", ".join(f"{k}: {v}" for k, v in sorted(report.per_category.items())))
    if report.never_labelled:
        lines.append("Segments never labelled: " + ", ".join(report.never_labelled))
    lines += [f"WARNING: {w}" for w in report.warnings]
    lines += [f"PROBLEM: {p}" for p in report.problems]
    lines.append("")
    lines.append("OK: this folder can be used for training." if report.ok else
                 f"NOT OK: fix the {len(report.problems)} problem(s) above, then check again.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- splitting
@dataclass
class SplitResult:
    train_images: int
    val_images: int
    train_annotations: int
    val_annotations: int
    groups: int


def _group_of(source: Path) -> dict:
    """file name -> study uid from frames.csv, when it is there."""
    table = Path(source) / "frames.csv"
    if not table.is_file():
        return {}
    with table.open(encoding="utf-8", newline="") as handle:
        return {row["file"]: row["study_uid"] for row in csv.DictReader(handle)}


def split_coco(source: Path, out_root: Path, val_fraction: float = 0.2, seed: str = "mussa") -> SplitResult:
    """Split a COCO export into out_root/train and out_root/val (ARCADE layout). Images of one study stay
    together (a study is a patient's visit, so a model must not see part of it while training and the rest
    while being tested). The split is repeatable."""
    source, out_root = Path(source), Path(out_root)
    if not 0.0 < val_fraction < 1.0:
        raise ValueError("val_fraction must be above 0 and below 1.")
    if out_root.exists() and any(out_root.iterdir()):
        raise ValueError(f"{out_root} is not empty. Choose a new folder so nothing is overwritten.")
    path = find_annotation_file(source)
    if path is None:
        raise ValueError(f"No annotation file found in {source / 'annotations'}.")
    data = json.loads(path.read_text(encoding="utf-8"))
    studies = _group_of(source)
    groups: dict[str, list] = {}
    for im in data["images"]:
        groups.setdefault(studies.get(im["file_name"], im["file_name"]), []).append(im)
    if len(groups) < 2:
        raise ValueError("Splitting needs at least 2 studies (or 2 images) to put some in train and some in val.")
    ranked = sorted(groups, key=lambda g: hashlib.sha256(f"{seed}:{g}".encode()).hexdigest())
    n_val = min(max(1, round(val_fraction * len(ranked))), len(ranked) - 1)
    members = {"val": ranked[:n_val], "train": ranked[n_val:]}
    counts = {}
    for split, keys in members.items():
        chosen = [im for key in sorted(keys) for im in groups[key]]
        new_ids = {im["id"]: i for i, im in enumerate(chosen, 1)}
        annotations = []
        for ann in data["annotations"]:
            if ann["image_id"] in new_ids:
                annotations.append({**ann, "id": len(annotations) + 1, "image_id": new_ids[ann["image_id"]]})
        (out_root / split / "images").mkdir(parents=True)
        (out_root / split / "annotations").mkdir()
        for im in chosen:
            shutil.copy2(source / "images" / im["file_name"], out_root / split / "images" / im["file_name"])
        doc = {"images": [{**im, "id": new_ids[im["id"]]} for im in chosen], "annotations": annotations,
               "categories": data["categories"]}
        (out_root / split / "annotations" / f"{split}.json").write_text(json.dumps(doc), encoding="utf-8")
        counts[split] = (len(chosen), len(annotations))
    return SplitResult(train_images=counts["train"][0], val_images=counts["val"][0],
                       train_annotations=counts["train"][1], val_annotations=counts["val"][1], groups=len(groups))
