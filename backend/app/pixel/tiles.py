"""Tiles & maps: seamless textures, dual-grid terrain atlases, isometric tiles, parallax helpers."""
from __future__ import annotations

import numpy as np
from PIL import Image


def _smooth_weight(n: int) -> np.ndarray:
    x = np.linspace(0, 1, n, endpoint=False) + 0.5 / n
    w = 1 - np.abs(2 * x - 1)  # 0 at edges, 1 at centre
    return np.clip(w * 1.6 - 0.3, 0, 1) ** 1.2


def make_seamless(img: Image.Image, axis: str = "both") -> Image.Image:
    """Offset-and-blend: centre stays original, edges come from the half-shifted copy (which wraps)."""
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    h, w = arr.shape[:2]
    if axis in ("x", "both"):
        shifted = np.roll(arr, w // 2, axis=1)
        m = _smooth_weight(w)[None, :, None]
        arr = arr * m + shifted * (1 - m)
    if axis in ("y", "both"):
        shifted = np.roll(arr, h // 2, axis=0)
        m = _smooth_weight(h)[:, None, None]
        arr = arr * m + shifted * (1 - m)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


def tile_preview(tile: Image.Image, nx: int = 3, ny: int = 3) -> Image.Image:
    out = Image.new("RGBA", (tile.width * nx, tile.height * ny))
    for y in range(ny):
        for x in range(nx):
            out.paste(tile, (x * tile.width, y * tile.height))
    return out


def _value_noise(size: int, cells: int, rng: np.random.Generator) -> np.ndarray:
    grid = rng.random((cells + 1, cells + 1))
    xs = np.linspace(0, cells, size, endpoint=False)
    i = xs.astype(int)
    f = xs - i
    f = f * f * (3 - 2 * f)
    a = grid[np.ix_(i, i)]
    b = grid[np.ix_(i, i + 1)]
    c = grid[np.ix_(i + 1, i)]
    d = grid[np.ix_(i + 1, i + 1)]
    fx, fy = f[None, :], f[:, None]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def dual_grid_tileset(fg: Image.Image, bg: Image.Image | None, tile: int = 64, seed: int = 7,
                      roughness: float = 0.22, edge_shade: bool = True) -> tuple[Image.Image, list[dict]]:
    """16-tile corner-based (dual-grid / marching-squares) terrain atlas, 4×4.

    Tile index = TL*1 + TR*2 + BL*4 + BR*8 where a set bit means the corner is foreground terrain.
    Edges cross the tile border exactly at the midpoint so every tile pairs seamlessly with its neighbours.
    """
    fg_t = fg.convert("RGBA").resize((tile, tile), Image.Resampling.NEAREST)
    bg_t = bg.convert("RGBA").resize((tile, tile), Image.Resampling.NEAREST) if bg is not None else None
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:tile, 0:tile].astype(np.float32)
    u, v = (xx + 0.5) / tile, (yy + 0.5) / tile
    window = np.sin(np.pi * u) * np.sin(np.pi * v)
    atlas = Image.new("RGBA", (tile * 4, tile * 4), (0, 0, 0, 0))
    fg_a = np.asarray(fg_t).astype(np.float32)
    bg_a = np.asarray(bg_t).astype(np.float32) if bg_t is not None else None
    mapping = []
    for idx in range(16):
        tl, tr, bl, br = idx & 1, (idx >> 1) & 1, (idx >> 2) & 1, (idx >> 3) & 1
        field = tl * (1 - u) * (1 - v) + tr * u * (1 - v) + bl * (1 - u) * v + br * u * v
        noise = _value_noise(tile, 4, rng) - 0.5
        field = field + noise * roughness * 2 * window
        mask = field >= 0.5
        out = np.zeros((tile, tile, 4), dtype=np.float32)
        if bg_a is not None:
            out[:] = bg_a
        out[mask] = fg_a[mask]
        if edge_shade and 0 < idx < 15:
            m = mask.astype(np.uint8)
            p = np.pad(m, 1, mode="edge")
            border = (m == 1) & ((p[:-2, 1:-1] == 0) | (p[2:, 1:-1] == 0) | (p[1:-1, :-2] == 0) | (p[1:-1, 2:] == 0))
            out[border, :3] *= 0.72
        if bg_a is None:
            out[~mask] = 0
        r, c = divmod(idx, 4)
        atlas.paste(Image.fromarray(out.astype(np.uint8), "RGBA"), (c * tile, r * tile))
        mapping.append({"index": idx, "col": c, "row": r, "corners": {"tl": tl, "tr": tr, "bl": bl, "br": br}})
    return atlas, mapping


def _affine_face(tex: np.ndarray, out: np.ndarray, origin, ax, ay, shade: float) -> None:
    """Paint texture onto parallelogram origin + s*ax + t*ay (s,t in [0,1]) using inverse mapping."""
    th, tw = tex.shape[:2]
    h, w = out.shape[:2]
    m = np.array([[ax[0], ay[0]], [ax[1], ay[1]]], dtype=np.float64)
    inv = np.linalg.inv(m)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    px, py = xx + 0.5 - origin[0], yy + 0.5 - origin[1]
    s = inv[0, 0] * px + inv[0, 1] * py
    t = inv[1, 0] * px + inv[1, 1] * py
    inside = (s >= 0) & (s < 1) & (t >= 0) & (t < 1)
    sx = np.clip((s * tw).astype(int), 0, tw - 1)
    sy = np.clip((t * th).astype(int), 0, th - 1)
    col = tex[sy, sx].astype(np.float32)
    col[..., :3] *= shade
    out[inside] = col[inside]


def isometric_tile(texture: Image.Image, width: int = 128, block_height: int = 0,
                   side_texture: Image.Image | None = None) -> Image.Image:
    """2:1 isometric diamond (128×64 by default) optionally extruded into a block."""
    tex = np.asarray(texture.convert("RGBA"))
    side = np.asarray((side_texture or texture).convert("RGBA"))
    half_w, half_h = width / 2, width / 4
    h = int(round(width / 2 + block_height))
    out = np.zeros((h, width, 4), dtype=np.float32)
    if block_height > 0:
        _affine_face(side, out, (0, half_h), (half_w, half_h), (0, block_height), 0.78)
        _affine_face(side, out, (half_w, 2 * half_h), (half_w, -half_h), (0, block_height), 0.58)
    _affine_face(tex, out, (half_w, 0), (half_w, half_h), (-half_w, half_h), 1.0)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def isometric_preview(tile: Image.Image, n: int = 4, width: int = 128) -> Image.Image:
    half_w, half_h = width // 2, width // 4
    W = n * width
    H = n * half_h * 2 + tile.height
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for gy in range(n):
        for gx in range(n):
            x = (gx - gy) * half_w + W // 2 - half_w
            y = (gx + gy) * half_h
            out.alpha_composite(tile, (x, y))
    return out
