"""Run the two vision models over a DICOM run and report what they saw, with full evidence.

This is the bridge between the existing pieces: `dicom_import.read_xa` (frames, C-arm angles, UIDs), the segment model
(`ai.segmenter`), the stenosis model (`ai.stenosis`) and the placement of narrowings in segments (`ai.suggest`). It
adds no new vision: whatever no model measures (QCA %, vessel diameter, lesion length, morphology) stays None.

Until a contrast-based key-frame choice exists, the default is the middle frame of each series; pass `frames` to
analyse others."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..ai.segment_names import SEGMENT_NAMES
from ..ai.suggest import suggest
from ..contract.models import ModelRef
from ..dicom_import.reader import read_header, read_xa
from ..dicom_import.views import label_view
from .schema import RawCVLesionCandidate, RunPerceptionSummary

DEFAULT_MIN_SEGMENT_PIXELS = 100          # fewer pixels than this and a segment is not counted as visible


class PerceptionError(ValueError):
    """A run could not be analysed. The message is meant to be shown to a person."""


@dataclass
class StudyPerception:
    runs: list[RunPerceptionSummary] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)       # (file name, reason)


def _identity(model) -> str:
    return getattr(model, "model_id", None) or model.card.trained_at


def _check_models(segmenter, stenosis) -> None:
    if segmenter is None:
        raise PerceptionError("No segment model is available: install segments.onnx and segments.card.json first.")
    if stenosis is None:
        raise PerceptionError("No stenosis model is available: install stenosis.onnx and stenosis.card.json first.")


def perceive_series(path: Path, segmenter, stenosis, frames: list[int] | None = None,
                    min_segment_pixels: int = DEFAULT_MIN_SEGMENT_PIXELS) -> RunPerceptionSummary:
    _check_models(segmenter, stenosis)
    path = Path(path)
    try:
        series = read_xa(path)
    except Exception as exc:                          # unreadable, rejected or not DICOM
        raise PerceptionError(f"{path.name}: {exc}") from exc
    count = len(series.frames)
    chosen = [count // 2] if frames is None else sorted({int(f) for f in frames})
    if not chosen:
        raise PerceptionError(f"{path.name}: no frame was chosen to analyse.")
    for index in chosen:
        if not 0 <= index < count:
            raise PerceptionError(f"{path.name}: frame {index} does not exist (the series has {count} frames).")
    series_uid = path.stem                            # the store names each file after its series
    candidates: list[RawCVLesionCandidate] = []
    visible: set[int] = set()
    for index in chosen:
        image = series.frames[index]
        masks = segmenter.predict(image)
        for channel in range(masks.shape[0]):
            if int(masks[channel].sum()) >= min_segment_pixels:
                visible.add(channel)
        for rank, s in enumerate(suggest(stenosis.candidates(image), masks)):
            candidates.append(RawCVLesionCandidate(
                candidate_id=f"{series_uid}:f{index}:c{rank}", predicted_segment=s.segment, stenosis_score=s.score,
                segment_overlap=s.overlap, series_instance_uid=series_uid, sop_instance_uid=series.sop_instance_uid,
                frame_index=index, primary_angle_deg=series.primary_angle, secondary_angle_deg=series.secondary_angle,
                bbox_xyxy=tuple(int(v) for v in s.box) if s.box is not None else None, pixels=s.pixels))
    candidates.sort(key=lambda c: (-c.stenosis_score, c.frame_index, c.candidate_id))
    try:
        study_uid = read_header(path).study_uid or None
    except Exception as exc:                          # without its study uid the series cannot be tied to a patient
        raise PerceptionError(f"{path.name}: the header could not be read ({exc}).") from exc
    return RunPerceptionSummary(
        series_instance_uid=series_uid, sop_instance_uid=series.sop_instance_uid, study_instance_uid=study_uid,
        view_label=label_view(series.primary_angle, series.secondary_angle), frame_count=count, analysed_frames=chosen,
        visible_segments=[SEGMENT_NAMES[c] for c in sorted(visible)], candidates=candidates,
        models=[ModelRef(name="segments", identity=_identity(segmenter)),
                ModelRef(name="stenosis", identity=_identity(stenosis))])


def perceive_study(paths: list[Path], segmenter, stenosis, frames: list[int] | None = None,
                   min_segment_pixels: int = DEFAULT_MIN_SEGMENT_PIXELS) -> StudyPerception:
    """Analyse every file of a study. A file that cannot be read is listed in `skipped` and the rest carry on."""
    _check_models(segmenter, stenosis)
    result = StudyPerception()
    for path in paths:
        try:
            result.runs.append(perceive_series(path, segmenter, stenosis, frames, min_segment_pixels))
        except PerceptionError as exc:
            result.skipped.append((Path(path).name, str(exc)))
        except Exception as exc:                      # a model or validation problem in one series must not end the study
            result.skipped.append((Path(path).name, f"{Path(path).name}: {exc}"))
    if not result.runs:
        raise PerceptionError(f"None of the {len(paths)} file(s) could be analysed. First problem: "
                              f"{result.skipped[0][1] if result.skipped else 'no files were given'}")
    return result
