"""The stenosis model: finds narrowed places on a frame and returns them as separate candidates.

It is a second ONNX model (one output channel, trained on ARCADE `stenosis`) that runs beside the segment model.
Candidates are suggestions for the scorer to accept or reject, never a diagnosis."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .preprocess import preprocess
from .segmenter import ModelCard, ModelUnavailable

CLASS_NAME = "stenosis"
DEFAULT_THRESHOLD = 0.5


@dataclass
class Candidate:
    mask: np.ndarray            # bool (H, W): the pixels of this candidate
    box: tuple                  # (x0, y0, x1, y1), x1 and y1 exclusive
    pixels: int
    score: float                # mean probability inside the candidate, 0 to 1


def _label(above: np.ndarray) -> np.ndarray:
    """8-connected component labels (0 = background) of a boolean image, found run by run: each row is cut
    into runs of True pixels and runs that touch (also diagonally) in neighbouring rows are joined. Far faster
    than visiting pixels one by one, even when a poor model lights up a large area."""
    height, width = above.shape
    parent: list[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    rows: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        edges = np.diff(np.concatenate(([0], above[y].astype(np.int8), [0])))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        row = []
        for s, e in zip(starts.tolist(), ends.tolist()):
            parent.append(len(parent))
            row.append((s, e, len(parent) - 1))
        rows.append(row)
        if y and row and rows[y - 1]:
            above_row, k = rows[y - 1], 0
            for s, e, run in row:
                while k < len(above_row) and above_row[k][1] < s:      # ends before this run starts (and is not adjacent)
                    k += 1
                m = k
                while m < len(above_row) and above_row[m][0] <= e:
                    a, b = find(run), find(above_row[m][2])
                    if a != b:
                        parent[max(a, b)] = min(a, b)
                    m += 1
    labels = np.zeros((height, width), dtype=np.int32)
    for y, row in enumerate(rows):
        for s, e, run in row:
            labels[y, s:e] = find(run) + 1
    return labels


def find_candidates(probability: np.ndarray, threshold: float, min_pixels: int = 30) -> list[Candidate]:
    """Separate 8-connected regions above `threshold`, dropping those smaller than `min_pixels`.
    Best score first."""
    probability = np.asarray(probability)
    labels = _label(probability > threshold)
    sizes = np.bincount(labels.ravel())
    found: list[Candidate] = []
    for label in np.flatnonzero(sizes >= max(1, min_pixels)):
        if label == 0:
            continue
        mask = labels == label
        ys, xs = np.nonzero(mask)
        found.append(Candidate(mask=mask, box=(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                               pixels=int(sizes[label]), score=float(probability[mask].mean())))
    return sorted(found, key=lambda c: -c.score)


def _read_card(model_path: Path) -> ModelCard:
    card_path = model_path.with_name(model_path.stem + ".card.json")
    try:
        data = json.loads(card_path.read_text(encoding="utf-8"))
        card = ModelCard(trained_on=str(data["trained_on"]), trained_at=str(data["trained_at"]),
                         input_size=int(data["input_size"]), classes=list(data["classes"]),
                         val_mean_dice=data.get("val_mean_dice"), test_mean_dice=data.get("test_mean_dice"),
                         notice=str(data.get("notice", "")), thresholds=data.get("thresholds") or {})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelUnavailable(f"The model card {card_path.name} is missing or unreadable ({exc}). "
                               "Copy stenosis.card.json next to the model file.") from exc
    if card.classes != [CLASS_NAME]:
        raise ModelUnavailable("This is not a stenosis model: its card does not list the single class 'stenosis'.")
    t = card.thresholds
    if not (isinstance(t, dict) and set(t) <= {CLASS_NAME} and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < v < 1.0 for v in t.values())):
        raise ModelUnavailable(f"The threshold in {card_path.name} is not valid: it must be a number above 0 "
                               "and below 1, stored under 'stenosis'.")
    return card


class StenosisFinder:
    """The stenosis model (ONNX, CPU)."""

    def __init__(self, session, card: ModelCard):
        self._session = session
        self.card = card
        self._input_name = session.get_inputs()[0].name
        self.threshold = float(card.thresholds.get(CLASS_NAME, DEFAULT_THRESHOLD))

    @classmethod
    def load(cls, model_path: Path) -> "StenosisFinder":
        model_path = Path(model_path)
        if not model_path.is_file():
            raise ModelUnavailable(f"No stenosis model file at {model_path}.")
        card = _read_card(model_path)
        try:
            import onnxruntime as ort
            session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        except Exception as exc:
            raise ModelUnavailable(f"{model_path.name} is not a valid ONNX model ({exc}).") from exc
        size = card.input_size
        inp = session.get_inputs()[0]
        if list(inp.shape[1:]) != [1, size, size]:
            raise ModelUnavailable(f"The model's input shape {inp.shape} is not [N, 1, {size}, {size}].")
        try:                                           # the exporter does not record the output size: run once
            result = session.run(None, {inp.name: np.zeros((1, 1, size, size), dtype=np.float32)})[0]
        except Exception as exc:
            raise ModelUnavailable(f"{model_path.name} failed a test run ({exc}).") from exc
        if tuple(result.shape) != (1, 1, size, size):
            raise ModelUnavailable(f"The model produces output of shape {tuple(result.shape)}; "
                                   f"(1, 1, {size}, {size}) is required for a stenosis model.")
        return cls(session, card)

    def probability(self, frame: np.ndarray) -> np.ndarray:
        """Float32 (H, W) stenosis probability in the frame's own size. The input is not modified."""
        height, width = np.asarray(frame).shape
        x = preprocess(frame, self.card.input_size)[None].astype(np.float32)
        logits = self._session.run(None, {self._input_name: x})[0][0, 0].astype(np.float32)
        logits = np.asarray(Image.fromarray(logits, mode="F").resize((width, height), Image.Resampling.NEAREST))
        return (1.0 / (1.0 + np.exp(-np.clip(logits, -60.0, 60.0)))).astype(np.float32)

    def candidates(self, frame: np.ndarray, threshold: float | None = None, min_pixels: int = 30) -> list[Candidate]:
        cut = self.threshold if threshold is None else float(threshold)
        return find_candidates(self.probability(frame), cut, min_pixels)
