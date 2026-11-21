from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from PIL import Image

from .preprocess import preprocess
from .segment_names import SEGMENT_NAMES


class ModelUnavailable(Exception):
    """The segment model cannot be used. The message is shown to the user."""


@dataclass
class ModelCard:
    trained_on: str
    trained_at: str
    input_size: int
    classes: list[str]
    val_mean_dice: float | None
    test_mean_dice: float | None
    notice: str
    thresholds: dict = field(default_factory=dict)      # segment name -> probability cut-off (default 0.5)


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
                               "Copy segments.card.json next to the model file.") from exc
    if card.classes != list(SEGMENT_NAMES):
        raise ModelUnavailable("The model was trained for a different list of classes than the 25 SYNTAX "
                               "segments of this app; it cannot be used.")
    _check_thresholds(card.thresholds, card_path.name)
    return card


def _check_thresholds(thresholds, card_name: str) -> None:
    ok = isinstance(thresholds, dict) and all(
        name in SEGMENT_NAMES and isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 < v < 1.0
        for name, v in thresholds.items())
    if not ok:
        raise ModelUnavailable(f"The thresholds in {card_name} are not valid: each must be a number above 0 and "
                               "below 1, named after one of the 25 SYNTAX segments. Remove them or re-tune.")


def file_identity(path: Path, trained_at: str) -> str:
    """"<training date> <first 8 characters of the file's SHA-256>": tells apart two models trained on the same day."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"{trained_at} {digest.hexdigest()[:8]}"


class Segmenter:
    """The trained segment model (ONNX, CPU). predict() returns a boolean mask per SYNTAX segment."""

    def __init__(self, session, card: ModelCard, model_id: str | None = None):
        self._session = session
        self.card = card
        self.model_id = model_id or card.trained_at
        self._input_name = session.get_inputs()[0].name
        self.thresholds = [float(card.thresholds.get(name, 0.5)) for name in SEGMENT_NAMES]

    @classmethod
    def load(cls, model_path: Path) -> "Segmenter":
        model_path = Path(model_path)
        if not model_path.is_file():
            raise ModelUnavailable(f"No model file at {model_path}.")
        card = _read_card(model_path)
        try:
            import onnxruntime as ort
            session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        except Exception as exc:                      # onnxruntime raises several error types
            raise ModelUnavailable(f"{model_path.name} is not a valid ONNX model ({exc}).") from exc
        size, classes = card.input_size, len(SEGMENT_NAMES)
        inp = session.get_inputs()[0]
        if list(inp.shape[1:]) != [1, size, size]:
            raise ModelUnavailable(f"The model's input shape {inp.shape} is not [N, 1, {size}, {size}] "
                                   "(wrong input shape, or a card size that does not match the model).")
        # The exporter only records the batch axis, so the output size is not reliable metadata:
        # check the real output by running the model once on a blank frame.
        try:
            result = session.run(None, {inp.name: np.zeros((1, 1, size, size), dtype=np.float32)})[0]
        except Exception as exc:
            raise ModelUnavailable(f"{model_path.name} failed a test run ({exc}).") from exc
        if tuple(result.shape) != (1, classes, size, size):
            raise ModelUnavailable(f"The model produces output of shape {tuple(result.shape)}; "
                                   f"(1, {classes}, {size}, {size}) is required: {classes} channels, one per "
                                   "SYNTAX segment, at the card size.")
        return cls(session, card, file_identity(model_path, card.trained_at))

    def _logits(self, frame: np.ndarray) -> np.ndarray:
        """Float (25, H, W) logits in the frame's own size (nearest-neighbour resize)."""
        height, width = np.asarray(frame).shape
        x = preprocess(frame, self.card.input_size)[None].astype(np.float32)
        raw = self._session.run(None, {self._input_name: x})[0][0].astype(np.float32)
        return np.stack([np.asarray(Image.fromarray(raw[c], mode="F").resize((width, height), Image.Resampling.NEAREST))
                         for c in range(raw.shape[0])])

    def probabilities(self, frame: np.ndarray) -> np.ndarray:
        """Float32 (25, H, W) probabilities in the frame's own size. The input is not modified."""
        logits = self._logits(frame)
        return (1.0 / (1.0 + np.exp(-np.clip(logits, -60.0, 60.0)))).astype(np.float32)

    def predict(self, frame: np.ndarray, threshold: float | None = None) -> np.ndarray:
        """Boolean (25, H, W) masks in the frame's own size. Each segment uses its own cut-off from the
        model card (0.5 when the card has none); a `threshold` argument overrides all of them."""
        if threshold is not None:
            cut = np.full(len(SEGMENT_NAMES), float(threshold), dtype=np.float64)
        else:
            cut = np.asarray(self.thresholds, dtype=np.float64)
        t = np.clip(cut, 1e-6, 1.0 - 1e-6)
        limit = np.log(t / (1.0 - t)).astype(np.float32)[:, None, None]     # sigmoid(logit) > t, without exp overflow
        return self._logits(frame) > limit
