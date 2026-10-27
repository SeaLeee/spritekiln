"""Deterministic quality gate for generated animation frames.

Inspired by the take gates in `agent-sprite-forge` and the frame gate in `sprite-gen`, but deliberately
explainable and model-free: every number comes from alpha geometry, not from another AI call. The gate
answers one question — *would this sequence be usable in a game?* — and only rejects the failures that
are mechanically detectable:

* empty / near-empty frames (background keyed the sprite away)
* the subject pumping in size (inconsistent scale)
* long runs of duplicated frames (a frozen "animation")

Centre drift is measured and reported but **not** a failure: a jump, lunge or attack is supposed to move
inside the frame. A gate that rejects intended motion is worse than no gate (it burns a retake and teaches
the user to ignore the warning). Art quality, identity and motion semantics still need human/agent review.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

LEVELS = {
    "standard": {"coverage_cv": 0.35, "bbox_cv": 0.30, "duplicate": 0.35},
    "strict": {"coverage_cv": 0.22, "bbox_cv": 0.18, "duplicate": 0.20},
}
MIN_COVERAGE = 0.003
ALPHA_THRESHOLD = 16
# mean absolute RGB difference *over the subject* on a 32×32 thumbnail; exactly frozen frames score 0
DUPLICATE_DIFF = 0.5


def _frame_stats(frame: Image.Image) -> dict:
    rgba = frame.convert("RGBA")
    a = np.asarray(rgba.getchannel("A"))
    mask = a > ALPHA_THRESHOLD
    coverage = float(mask.mean())
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return {"coverage": 0.0, "w": 0.0, "h": 0.0, "cx": 0.5, "cy": 0.5, "empty": True}
    w, h = rgba.size
    return {
        "coverage": coverage,
        "w": (xs.max() - xs.min() + 1) / w,
        "h": (ys.max() - ys.min() + 1) / h,
        "cx": (xs.max() + xs.min() + 1) / 2 / w,
        "cy": (ys.max() + ys.min() + 1) / 2 / h,
        "empty": coverage < MIN_COVERAGE,
    }


def _thumb(frame: Image.Image) -> np.ndarray:
    return np.asarray(frame.convert("RGBA").resize((32, 32), Image.Resampling.BOX), dtype=np.float32)


def _difference(a: np.ndarray, b: np.ndarray) -> float:
    """Mean RGB difference restricted to the subject, so a 60×60 sprite on a 512² canvas stays sensitive."""
    mask = (a[..., 3] > 8) | (b[..., 3] > 8)
    if not mask.any():
        return 0.0
    return float(np.abs(a[..., :3] - b[..., :3])[mask].mean())


def _cv(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = float(np.mean(values))
    return float(np.std(values) / mean) if mean > 1e-6 else 0.0


def frame_metrics(frames: list[Image.Image]) -> dict:
    if not frames:
        return {"count": 0, "empty_ratio": 1.0, "coverage_cv": 1.0, "bbox_cv": 1.0,
                "center_jitter": 1.0, "duplicate_ratio": 1.0, "coverage_mean": 0.0}
    stats = [_frame_stats(f) for f in frames]
    duplicates = 0
    thumbs = [_thumb(f) for f in frames]
    for a, b in zip(thumbs, thumbs[1:]):
        if _difference(a, b) < DUPLICATE_DIFF:
            duplicates += 1
    jitter = [float(np.hypot(s["cx"] - 0.5, s["cy"] - 0.5)) for s in stats if not s["empty"]]
    widths = [s["w"] for s in stats if not s["empty"]]
    heights = [s["h"] for s in stats if not s["empty"]]
    return {
        "count": len(frames),
        "empty_ratio": round(sum(1 for s in stats if s["empty"]) / len(stats), 4),
        "coverage_mean": round(float(np.mean([s["coverage"] for s in stats])), 4),
        "coverage_cv": round(_cv([s["coverage"] for s in stats if not s["empty"]]), 4),
        "bbox_cv": round(max(_cv(widths), _cv(heights)), 4),
        "center_jitter": round(float(np.mean(jitter)) if jitter else 1.0, 4),
        "duplicate_ratio": round(duplicates / max(1, len(frames) - 1), 4),
    }


def grade(frames: list[Image.Image], level: str = "standard") -> dict:
    """Return {ok, score, issues[], metrics{}}. ``level`` is "off" | "standard" | "strict"."""
    if level == "off":
        return {"level": "off", "ok": True, "score": 1.0, "issues": [], "metrics": frame_metrics(frames)}
    limits = LEVELS.get(level, LEVELS["standard"])
    m = frame_metrics(frames)
    issues: list[str] = []
    if m["empty_ratio"] > 0:
        issues.append(f"{round(m['empty_ratio'] * m['count'])} 帧接近全透明")
    if m["coverage_mean"] < MIN_COVERAGE:
        issues.append("主体覆盖率过低")
    if m["coverage_cv"] > limits["coverage_cv"]:
        issues.append(f"主体面积波动过大 ({m['coverage_cv']:.2f} > {limits['coverage_cv']:.2f})")
    if m["bbox_cv"] > limits["bbox_cv"]:
        issues.append(f"主体尺寸不稳定 ({m['bbox_cv']:.2f} > {limits['bbox_cv']:.2f})")
    if m["duplicate_ratio"] > limits["duplicate"]:
        issues.append(f"重复帧过多，动作可能冻结 ({m['duplicate_ratio']:.2f} > {limits['duplicate']:.2f})")
    penalty = (m["empty_ratio"] * 2 + m["coverage_cv"] * 0.8 + m["bbox_cv"] * 0.6
               + m["center_jitter"] * 2 + m["duplicate_ratio"] * 0.8)
    return {
        "level": level,
        "ok": not issues,
        "score": round(max(0.0, 1.0 - penalty), 4),
        "issues": issues,
        "metrics": m,
    }
