from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .preprocess import preprocess, resize_mask
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


def _read_card(model_path: Path) -> ModelCard:
    card_path = model_path.with_name(model_path.stem + ".card.json")
    try:
        data = json.loads(card_path.read_text(encoding="utf-8"))
        card = ModelCard(trained_on=str(data["trained_on"]), trained_at=str(data["trained_at"]),
                         input_size=int(data["input_size"]), classes=list(data["classes"]),
                         val_mean_dice=data.get("val_mean_dice"), test_mean_dice=data.get("test_mean_dice"),
                         notice=str(data.get("notice", "")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ModelUnavailable(f"The model card {card_path.name} is missing or unreadable ({exc}). "
                               "Copy segments.card.json next to the model file.") from exc
    if card.classes != list(SEGMENT_NAMES):
        raise ModelUnavailable("The model was trained for a different list of classes than the 25 SYNTAX "
                               "segments of this app; it cannot be used.")
    return card


class Segmenter:
    """The trained segment model (ONNX, CPU). predict() returns a boolean mask per SYNTAX segment."""

    def __init__(self, session, card: ModelCard):
        self._session = session
        self.card = card
        self._input_name = session.get_inputs()[0].name

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
        return cls(session, card)

    def predict(self, frame: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Boolean (25, H, W) masks in the frame's own size. The input is not modified."""
        height, width = np.asarray(frame).shape
        x = preprocess(frame, self.card.input_size)[None].astype(np.float32)
        logits = self._session.run(None, {self._input_name: x})[0][0]
        probs = 1.0 / (1.0 + np.exp(-logits))
        masks = probs > threshold
        return np.stack([resize_mask(masks[c], height, width) for c in range(masks.shape[0])])
