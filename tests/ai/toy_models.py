"""Tiny ONNX models and model cards for tests. They need only the `onnx` package."""
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from cagsyntax.ai.segment_names import SEGMENT_NAMES


def make_toy_model(path: Path, size: int = 32, positive: tuple[int, ...] = (8, 9), logit: float = 5.0,
                   channels: int = 25, in_channels: int = 1) -> Path:
    """Model with input `image` [N, in_channels, size, size] and output `masks` [N, channels, size, size]
    holding constant logits: +logit for the `positive` channels, -5 for the others."""
    weights = numpy_helper.from_array(np.zeros((1, channels, 1, 1), dtype=np.float32), "zero")
    bias = np.full((1, channels, 1, 1), -5.0, dtype=np.float32)
    for c in positive:
        bias[0, c] = logit
    nodes = [
        helper.make_node("ReduceMean", ["image"], ["mean"], axes=[1], keepdims=1) if in_channels != 1 else
        helper.make_node("Identity", ["image"], ["mean"]),
        helper.make_node("Mul", ["mean", "zero"], ["flat"]),
        helper.make_node("Add", ["flat", "bias"], ["masks"]),
    ]
    graph = helper.make_graph(
        nodes, "toy",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, ["N", in_channels, size, size])],
        [helper.make_tensor_value_info("masks", TensorProto.FLOAT, ["N", channels, size, size])],
        initializer=[weights, numpy_helper.from_array(bias, "bias")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))
    return path


def write_card(model_path: Path, size: int = 32, classes=None, **extra) -> Path:
    card = {"format_version": 1, "trained_on": "toy test model", "trained_at": "2026-11-21", "input_size": size,
            "classes": list(SEGMENT_NAMES) if classes is None else classes, "val_mean_dice": 0.5,
            "test_mean_dice": None, "notice": "test only"}
    card.update(extra)
    path = model_path.with_name(model_path.stem + ".card.json")
    path.write_text(json.dumps(card), encoding="utf-8")
    return path
