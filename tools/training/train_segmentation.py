"""Train the MUSSA segment model on ARCADE (runs in a cloud notebook; PyTorch only here).

    python train_segmentation.py --arcade <folder with syntax/ and stenosis/> --out <folder>

Trains a multi-label U-Net (25 sigmoid outputs, one per SYNTAX segment) on syntax/train, picks the
best epoch on syntax/val by mean Dice, evaluates once on syntax/test, and writes segments.onnx and
segments.card.json. ARCADE is public (CC0); nothing from any hospital is used here.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

try:                                      # inside the kit
    from mussa_ai.arcade import ArcadeSplit
    from mussa_ai.preprocess import preprocess, resize_mask
    from mussa_ai.segment_names import SEGMENT_NAMES
except ImportError:                       # inside the project (PYTHONPATH=src)
    from cagsyntax.ai.arcade import ArcadeSplit
    from cagsyntax.ai.preprocess import preprocess, resize_mask
    from cagsyntax.ai.segment_names import SEGMENT_NAMES

SEED = 20261121
CARD_FORMAT = 1


# ------------------------------------------------------------------ options
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Train the MUSSA segment model on ARCADE.")
    p.add_argument("--arcade", required=True, help="folder that holds the syntax/ and stenosis/ folders")
    p.add_argument("--out", required=True, help="folder for segments.onnx and segments.card.json")
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--size", type=int, default=512, help="model input size in pixels")
    p.add_argument("--encoder", default="resnet34")
    p.add_argument("--encoder-weights", choices=("imagenet", "none"), default="imagenet")
    p.add_argument("--limit", type=int, default=None, help="use only the first N images of each split")
    p.add_argument("--smoke", action="store_true", help="tiny one-epoch run to check the pipeline")
    return p


def apply_smoke(args: argparse.Namespace) -> argparse.Namespace:
    if args.smoke:
        args.epochs, args.size, args.limit, args.batch_size = 1, 128, 8, 4
    return args


# ------------------------------------------------------------------ augmentation (numpy / Pillow only)
def affine_coeffs(width: int, height: int, theta: float, scale: float, tx: float, ty: float):
    """Pillow AFFINE coefficients mapping output pixel -> input pixel for: rotate by theta about the
    centre, scale, then shift by (tx, ty)."""
    cos, sin = math.cos(-theta) / scale, math.sin(-theta) / scale
    a, b, d, e = cos, -sin, sin, cos
    cx, cy = width / 2.0, height / 2.0
    c = cx - (a * cx + b * cy) - (a * tx + b * ty)
    f = cy - (d * cx + e * cy) - (d * tx + e * ty)
    return (a, b, c, d, e, f)


def affine_image(img: np.ndarray, theta: float, scale: float, tx: float, ty: float, resample) -> np.ndarray:
    h, w = img.shape
    out = Image.fromarray(img).transform((w, h), Image.Transform.AFFINE,
                                         affine_coeffs(w, h, theta, scale, tx, ty), resample=resample, fillcolor=0)
    return np.asarray(out)


def augment_pair(img: np.ndarray, masks: np.ndarray, rng: np.random.Generator, geometry_only: bool = False):
    """Same random geometry for image and masks: rotation up to 10 degrees, scale 0.9-1.1, shift up to 5%.
    No flips (anatomy is orientation-specific). Unless geometry_only, also gamma and light noise (linear
    brightness and contrast changes would be undone by the per-frame min-max in preprocess)."""
    h, w = img.shape
    theta = math.radians(rng.uniform(-10, 10))
    scale = rng.uniform(0.9, 1.1)
    tx, ty = rng.uniform(-0.05, 0.05) * w, rng.uniform(-0.05, 0.05) * h
    out_img = affine_image(img, theta, scale, tx, ty, Image.Resampling.BILINEAR)
    out_masks = np.zeros_like(masks)
    for c in range(masks.shape[0]):
        if masks[c].any():
            moved = affine_image(masks[c].astype(np.uint8) * 255, theta, scale, tx, ty, Image.Resampling.NEAREST)
            out_masks[c] = moved > 127
    if not geometry_only:
        gamma = rng.uniform(0.7, 1.4)
        data = 255.0 * (out_img.astype(np.float32) / 255.0) ** gamma
        data = data + rng.normal(0.0, rng.uniform(0.0, 0.02) * 255.0, size=data.shape)
        out_img = np.clip(data, 0, 255).astype(np.uint8)
    return out_img, out_masks


# ------------------------------------------------------------------ training
class SegmentationData:
    """Map-style dataset of ARCADE images and 25-channel masks. It is a plain module-level class
    (no torch base class) so DataLoader workers can pickle it on Windows and on Python 3.14."""

    def __init__(self, split_root, size: int, augment: bool, limit: int | None = None):
        self.split = ArcadeSplit(split_root)
        self.size, self.augment, self.epoch = size, augment, 0
        self.n = min(len(self.split), limit) if limit else len(self.split)

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, i: int):
        import torch
        img, masks = self.split.load_image(i), self.split.load_masks(i)
        if self.augment:
            img, masks = augment_pair(img, masks, np.random.default_rng((SEED, self.epoch, i)))
        x = preprocess(img, self.size)
        y = np.stack([resize_mask(masks[c], self.size, self.size) for c in range(masks.shape[0])])
        return torch.from_numpy(x), torch.from_numpy(y.astype(np.float32))


def train(args: argparse.Namespace) -> dict:
    import torch
    import torch.nn.functional as F
    import segmentation_models_pytorch as smp
    from torch.utils.data import DataLoader

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    syntax = Path(args.arcade) / "syntax"

    train_set = SegmentationData(syntax / "train", args.size, True, args.limit)
    val_set = SegmentationData(syntax / "val", args.size, False, args.limit)
    workers = 0 if args.smoke else 2
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True, num_workers=workers)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, num_workers=workers)

    model = smp.Unet(encoder_name=args.encoder,
                     encoder_weights=None if args.encoder_weights == "none" else "imagenet",
                     in_channels=1, classes=len(SEGMENT_NAMES)).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=max(1, args.epochs))
    bce = torch.nn.BCEWithLogitsLoss()

    def loss_fn(logits, y):
        p = torch.sigmoid(logits)
        inter = (p * y).sum(dim=(2, 3))
        dice = (2 * inter + 1.0) / (p.sum(dim=(2, 3)) + y.sum(dim=(2, 3)) + 1.0)
        return bce(logits, y) + (1.0 - dice).mean()

    @torch.no_grad()
    def evaluate(loader):
        """Dice per segment from pixel counts pooled over all images; None for absent segments."""
        model.eval()
        inter = torch.zeros(len(SEGMENT_NAMES), dtype=torch.float64)
        psum, tsum = inter.clone(), inter.clone()
        for x, y in loader:
            pred = (torch.sigmoid(model(x.to(device))) > 0.5).float().cpu()
            inter += (pred * y).sum(dim=(0, 2, 3)).double()
            psum += pred.sum(dim=(0, 2, 3)).double()
            tsum += y.sum(dim=(0, 2, 3)).double()
        scores = {}
        for c, name in enumerate(SEGMENT_NAMES):
            total = float(psum[c] + tsum[c])
            scores[name] = None if total == 0 else float(2 * inter[c] / total)
        present = [v for v in scores.values() if v is not None]
        return (sum(present) / len(present) if present else 0.0), scores

    best, best_state, history = -1.0, None, []
    for epoch in range(args.epochs):
        model.train()
        train_set.epoch = epoch
        started, total_loss = time.time(), 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimiser.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            optimiser.step()
            total_loss += loss.item() * x.shape[0]
        schedule.step()
        val_dice, _ = evaluate(val_loader)
        history.append({"epoch": epoch + 1, "train_loss": total_loss / len(train_set), "val_mean_dice": val_dice})
        print(f"epoch {epoch + 1}/{args.epochs}  loss {history[-1]['train_loss']:.4f}  "
              f"val mean dice {val_dice:.4f}  ({time.time() - started:.0f}s)", flush=True)
        if val_dice > best:
            best, best_state = val_dice, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)

    test_dice, test_scores = None, None
    if not args.smoke:
        test_set = SegmentationData(syntax / "test", args.size, False, args.limit)
        test_dice, test_scores = evaluate(DataLoader(test_set, batch_size=args.batch_size, num_workers=workers))
        print(f"test mean dice {test_dice:.4f}", flush=True)

    onnx_path = out_dir / "segments.onnx"
    export_onnx(model, args.size, onnx_path, torch)
    card = {
        "format_version": CARD_FORMAT,
        "trained_on": ("ARCADE syntax" if not args.smoke else "ARCADE syntax (SMOKE TEST ONLY, not a real model)")
                      + ", https://zenodo.org/records/10390295, CC0",
        "trained_at": datetime.now(timezone.utc).date().isoformat(),
        "input_size": args.size, "classes": list(SEGMENT_NAMES),
        "preprocess": "ai/preprocess.py v1: per-frame min-max, resize, mean 0.5 std 0.5",
        "val_mean_dice": best, "test_mean_dice": test_dice, "per_segment_test_dice": test_scores,
        "training": {"epochs": args.epochs, "batch_size": args.batch_size, "lr": args.lr,
                     "encoder": args.encoder, "encoder_weights": args.encoder_weights, "seed": SEED,
                     "device": device, "history": history},
        "notice": "Educational research model trained on public ARCADE data. Not a certified medical "
                  "device; suggestions only, never a diagnosis.",
    }
    (out_dir / "segments.card.json").write_text(json.dumps(card, indent=1), encoding="utf-8")
    print(f"wrote {onnx_path} and segments.card.json", flush=True)
    return card


def export_onnx(model, size: int, path: Path, torch) -> None:
    model = model.cpu().eval()
    dummy = torch.zeros(1, 1, size, size)
    options = dict(input_names=["image"], output_names=["masks"], opset_version=17,
                   dynamic_axes={"image": {0: "batch"}, "masks": {0: "batch"}})
    try:
        torch.onnx.export(model, dummy, str(path), dynamo=False, **options)
    except TypeError:                          # older PyTorch without the dynamo switch
        torch.onnx.export(model, dummy, str(path), **options)


def main(argv: list[str] | None = None) -> int:
    args = apply_smoke(build_parser().parse_args(argv))
    train(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
