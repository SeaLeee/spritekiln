"""Pixel-art processing: grid detection, block downsampling, palette quantisation, outline and cleanup."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def has_alpha(img: Image.Image) -> bool:
    if img.mode != "RGBA":
        return False
    a = np.asarray(img.getchannel("A"))
    return bool((a < 250).mean() > 0.01)


def alpha_bbox(img: Image.Image, thr: int = 8) -> tuple[int, int, int, int] | None:
    a = np.asarray(img.convert("RGBA").getchannel("A"))
    ys, xs = np.where(a > thr)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def trim(img: Image.Image, margin: int = 0) -> Image.Image:
    box = alpha_bbox(img)
    if not box:
        return img
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - margin), max(0, y0 - margin), min(img.width, x1 + margin), min(img.height, y1 + margin)))


def fit_canvas(img: Image.Image, width: int, height: int, padding: int = 0, anchor: str = "center",
               resample=Image.Resampling.LANCZOS, upscale: bool = True) -> Image.Image:
    img = img.convert("RGBA")
    aw, ah = max(1, width - 2 * padding), max(1, height - 2 * padding)
    scale = min(aw / img.width, ah / img.height)
    if not upscale:
        scale = min(scale, 1.0)
    nw, nh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    if (nw, nh) != img.size:
        img = img.resize((nw, nh), resample)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    x = (width - nw) // 2
    y = height - padding - nh if anchor == "bottom" else (height - nh) // 2
    canvas.alpha_composite(img, (x, max(0, y)))
    return canvas


def _edge_profile(lum: np.ndarray, axis: int) -> np.ndarray:
    d = np.abs(np.diff(lum, axis=axis))
    d[d < 12] = 0
    return d.sum(axis=1 - axis) if axis == 1 else d.sum(axis=1)


def estimate_block_size(img: Image.Image, max_k: int = 48) -> tuple[int, int, int]:
    """Detect the size of 'fake' pixels in an upscaled/AI pixel-art image. Returns (k, offset_x, offset_y)."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    col = np.abs(np.diff(lum, axis=1))
    row = np.abs(np.diff(lum, axis=0))
    col[col < 12] = 0
    row[row < 12] = 0
    cp = col.sum(axis=0)
    rp = row.sum(axis=1)
    tot_c, tot_r = cp.sum(), rp.sum()
    if tot_c <= 0 or tot_r <= 0:
        return 1, 0, 0

    def best(profile: np.ndarray, total: float, k: int) -> tuple[float, int]:
        scores = []
        for o in range(k):
            # edge at diff index i sits between pixel i and i+1 -> boundary at i+1
            idx = np.arange(o - 1, len(profile), k)
            idx = idx[(idx >= 0) & (idx < len(profile))]
            win = profile[idx].sum()
            # tolerate +-1 jitter from resampling
            for j in (idx - 1, idx + 1):
                j = j[(j >= 0) & (j < len(profile))]
                win += 0.5 * profile[j].sum()
            scores.append(win / total)
        o = int(np.argmax(scores))
        return float(scores[o]), o

    chosen = (1, 0, 0)
    limit = min(max_k, img.width // 8, img.height // 8)
    for k in range(2, max(2, limit) + 1):
        sx, ox = best(cp, tot_c, k)
        sy, oy = best(rp, tot_r, k)
        if min(sx, sy) >= 0.82:
            chosen = (k, ox, oy)
    return chosen


def downsample_blocks(img: Image.Image, k: int, ox: int = 0, oy: int = 0) -> Image.Image:
    """Collapse k×k fake pixels into one real pixel using the block median (robust to blur/JPEG noise)."""
    arr = np.asarray(img.convert("RGBA"))
    h, w = arr.shape[:2]
    ox, oy = ox % k, oy % k
    nx, ny = (w - ox) // k, (h - oy) // k
    if nx < 1 or ny < 1:
        return img.convert("RGBA")
    crop = arr[oy:oy + ny * k, ox:ox + nx * k]
    blocks = crop.reshape(ny, k, nx, k, 4).transpose(0, 2, 1, 3, 4).reshape(ny, nx, k * k, 4)
    m = max(1, k // 4)
    inner = crop.reshape(ny, k, nx, k, 4)[:, m:k - m or k, :, m:k - m or k, :]
    inner = inner.transpose(0, 2, 1, 3, 4).reshape(ny, nx, -1, 4)
    out = np.median(inner if inner.shape[2] else blocks, axis=2).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def extract_palette(img: Image.Image, colors: int = 16) -> list[tuple[int, int, int]]:
    rgba = img.convert("RGBA")
    a = np.asarray(rgba.getchannel("A"))
    rgb = np.asarray(rgba.convert("RGB"))
    px = rgb[a > 127]
    if len(px) == 0:
        return [(0, 0, 0)]
    sample = Image.fromarray(px.reshape(1, -1, 3), "RGB")
    q = sample.quantize(colors=max(2, min(256, colors)), method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: 3 * len(q.getcolors() or [])] if q.getcolors() else q.getpalette()[:3 * colors]
    return [tuple(pal[i:i + 3]) for i in range(0, len(pal), 3)]  # type: ignore[misc]


def quantize(img: Image.Image, colors: int = 24, palette: list[tuple[int, int, int]] | None = None,
             alpha_threshold: int = 128, dither: bool = False) -> Image.Image:
    rgba = img.convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"))
    rgb = rgba.convert("RGB")
    dith = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    if palette:
        pal_img = Image.new("P", (1, 1))
        flat = [c for rgbc in palette for c in rgbc]
        flat += flat[:3] * (256 - len(palette))
        pal_img.putpalette(flat[:768])
        q = rgb.quantize(palette=pal_img, dither=dith)
    else:
        opaque = alpha > alpha_threshold
        if opaque.any():
            pal = extract_palette(rgba, colors)
            return quantize(rgba, palette=pal, alpha_threshold=alpha_threshold, dither=dither)
        q = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=dith)
    out = np.asarray(q.convert("RGBA")).copy()
    out[..., 3] = np.where(alpha > alpha_threshold, 255, 0)
    out[out[..., 3] == 0] = 0
    return Image.fromarray(out, "RGBA")


def clean_orphans(img: Image.Image) -> Image.Image:
    """Remove isolated single opaque pixels and fill single transparent holes."""
    arr = np.asarray(img.convert("RGBA")).copy()
    a = arr[..., 3] > 0
    p = np.pad(a, 1)
    n = sum(np.roll(np.roll(p, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)[1:-1, 1:-1]
    arr[a & (n == 0)] = 0
    holes = (~a) & (n >= 7)
    if holes.any():
        rgb = arr[..., :3].astype(np.int32)
        pr = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode="edge")
        right = pr[1:-1, 2:]
        arr[holes, :3] = right[holes].astype(np.uint8)
        arr[holes, 3] = 255
    return Image.fromarray(arr, "RGBA")


def add_outline(img: Image.Image, color: tuple[int, int, int] | None = None) -> Image.Image:
    arr = np.asarray(img.convert("RGBA")).copy()
    a = arr[..., 3] > 0
    if not a.any():
        return img
    if color is None:
        rgb = arr[..., :3][a].astype(np.int32)
        darkest = rgb[np.argmin(rgb.sum(axis=1))]
        color = tuple(int(c * 0.6) for c in darkest)  # type: ignore[assignment]
    p = np.pad(a, 1)
    neigh = p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    edge = neigh & ~a
    arr[edge, :3] = color
    arr[edge, 3] = 255
    return Image.fromarray(arr, "RGBA")


def pixelate(img: Image.Image, width: int | None = None, height: int | None = None, *, colors: int = 24,
             palette: list[tuple[int, int, int]] | None = None, outline: bool = False, padding: int = 0,
             anchor: str = "center", detect_grid: bool = True, dither: bool = False,
             trim_alpha: bool = True) -> Image.Image:
    """Turn any (AI-generated) image into crisp, game-ready pixel art at an exact size."""
    img = img.convert("RGBA")
    if detect_grid:
        k, ox, oy = estimate_block_size(img)
        if k >= 2:
            img = downsample_blocks(img, k, ox, oy)
    if trim_alpha and has_alpha(img):
        img = trim(img)
    if width and height:
        content = img
        if content.width <= width - 2 * padding and content.height <= height - 2 * padding:
            img = fit_canvas(content, width, height, padding, anchor, upscale=False)
        else:
            # premultiplied box filter keeps colours honest when shrinking
            img = fit_canvas(content, width, height, padding, anchor, resample=Image.Resampling.BOX)
    img = quantize(img, colors=colors, palette=palette, dither=dither)
    img = clean_orphans(img)
    if outline:
        img = add_outline(img)
    return img


def upscale(img: Image.Image, factor: int) -> Image.Image:
    return img.resize((img.width * factor, img.height * factor), Image.Resampling.NEAREST)


def soften(img: Image.Image, radius: float = 0.6) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))
