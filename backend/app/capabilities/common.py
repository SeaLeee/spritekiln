"""Shared steps used by capabilities."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from PIL import Image

from .. import db, engine_export, storage
from ..pixel import bg as bgmod
from ..pixel import sheet as sheetmod
from ..pixel.pixelate import extract_palette, pixelate, trim
from ..pixel.split import split_components, split_grid

ASPECTS = {"1:1": (1024, 1024), "4:3": (1152, 864), "3:4": (864, 1152), "16:9": (1344, 768), "9:16": (768, 1344),
           "2:1": (1408, 704), "1:2": (704, 1408), "3:2": (1216, 816), "2:3": (816, 1216), "21:9": (1536, 640)}


def seed_of(params: dict) -> int:
    s = params.get("seed")
    return random.randint(0, 2 ** 31 - 1) if s in (None, -1, "") else int(s)


def size_for(aspect: str, resolution: str = "1K") -> tuple[int, int]:
    w, h = ASPECTS.get(aspect, (1024, 1024))
    if resolution == "2K":
        w, h = w * 2, h * 2
    return w, h


async def generate(ctx, prompt: str, *, width: int, height: int, n: int = 1, seed: int | None = None,
                   refs: list[Image.Image] | None = None, quality: str = "standard", transparent: bool = False,
                   layout: tuple[int, int] | None = None, kind: str = "image") -> list[Image.Image]:
    prov = ctx.provider(kind)
    ctx.progress(0.06, f"{prov.label} 生成中…")
    ctx.check()
    imgs = await prov.generate(prompt, width=width, height=height, n=n, seed=seed, refs=refs or None,
                               quality=quality, transparent=transparent, layout=layout, ctx=ctx)
    ctx.check()
    return imgs


async def remove_bg(ctx, img: Image.Image, mode: str = "hd", method: str = "auto", color: str | None = None,
                    preserve_translucency: bool = False) -> Image.Image:
    if method == "none":
        return img.convert("RGBA")
    if method == "auto":
        method = ctx.provider_name("bg") or "auto"
        if method not in ("birefnet", "chroma"):
            method = "auto"
    out, _ = await ctx.blocking(bgmod.remove_background, img, method if method in ("birefnet", "chroma") else "auto",
                                mode, color, 42.0, preserve_translucency)
    return out


def split_sheet(img: Image.Image, count: int, layout: tuple[int, int]) -> list[Image.Image]:
    """Split an rgba sheet into `count` parts, preferring connected components, falling back to the grid."""
    merge = max(2, img.width // 160)
    parts = [p for p, _ in split_components(img, min_area=max(64, img.width * img.height // 4000), merge_distance=merge)]
    if count <= 1:
        if parts:
            # keep the largest component group (whole image trimmed)
            return [trim(img)]
        return [img]
    if len(parts) == count:
        return parts
    if count <= len(parts) <= count * 2:
        # model drew extra figures: keep every intact one rather than slicing figures with grid cells
        return parts
    cells = [trim(c) for c in split_grid(img, layout[0], layout[1])]
    cells = [c for c in cells if c.getbbox()]
    if len(parts) > count and len(cells) >= count:
        return cells[:count]
    if len(parts) >= count:
        parts.sort(key=lambda p: p.width * p.height, reverse=True)
        return parts[:count]
    return cells[:count] if len(cells) >= len(parts) else parts


def shared_palette(images: list[Image.Image], colors: int) -> list[tuple[int, int, int]]:
    if not images:
        return []
    w = sum(i.width for i in images)
    h = max(i.height for i in images)
    strip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = 0
    for i in images:
        strip.alpha_composite(i.convert("RGBA"), (x, 0))
        x += i.width
    return extract_palette(strip, colors)


def to_pixel(img: Image.Image, w: int, h: int, *, colors: int, palette=None, anchor: str = "center",
             outline: bool = False, padding: int = 1) -> Image.Image:
    return pixelate(img, w, h, colors=colors, palette=palette, anchor=anchor, outline=outline, padding=padding)


def pack_preview(ctx, assets_imgs: list[Image.Image], name: str, meta: dict, parents: list[str], scale: int = 1) -> dict:
    sheet, cols, rows = sheetmod.pack_sheet(assets_imgs, cols=min(len(assets_imgs), 4), spacing=2 * scale)
    return ctx.save_image(sheet, name, kind="image", meta={**meta, "pack": True, "cols": cols, "rows": rows},
                          parents=parents, role="pack")


def save_animation(ctx, frames: list[Image.Image], *, name: str, fps: int, loop: bool, meta: dict,
                   parents: list[str], pixel: bool) -> dict[str, Any]:
    """Persist frames + sheet + gif + webp + Godot SpriteFrames, return the animation asset."""
    aid = db.new_id("ast")
    base = storage.project_dir(ctx.project_id)
    folder = base / aid
    folder.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    for i, f in enumerate(frames):
        p = folder / f"frame_{i:03d}.png"
        f.save(p)
        frame_paths.append(storage.rel(p))
    sheet, cols, rows = sheetmod.pack_sheet(frames)
    sheet_p = folder / "sheet.png"
    sheet.save(sheet_p)
    gif_p = base / f"{aid}.gif"
    scale = max(1, 256 // max(frames[0].width, frames[0].height)) if pixel else 1
    sheetmod.save_gif(frames, gif_p, fps, loop, scale=scale)
    webp_p = folder / "anim.webp"
    sheetmod.save_webp(frames, webp_p, fps, loop)
    fw, fh = frames[0].size
    tres = sheetmod.godot_spriteframes(f"res://{ctx.project_id}/{aid}_sheet.png", fw, fh, cols, len(frames), fps, loop)
    tres_p = folder / "spriteframes.tres"
    tres_p.write_text(tres, encoding="utf-8")
    duration_ms = int(round(1000 / max(1, fps)))
    info = {
        "frame_w": fw, "frame_h": fh, "cols": cols, "rows": rows, "count": len(frames), "fps": fps, "loop": loop,
        # absolute frame rectangles so engines never guess a grid (same layout as Aseprite JSON)
        "frames": [{"index": i, "x": (i % cols) * fw, "y": (i // cols) * fh, "w": fw, "h": fh,
                    "duration_ms": duration_ms} for i in range(len(frames))],
        "duration_ms": duration_ms, "pivot": {"x": 0.5, "y": 1.0},
    }
    (folder / "sheet.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    full_meta = {**meta, **info, "pixel": pixel, "frames": frame_paths, "providers": ctx.providers,
                 "files": {"sheet": storage.rel(sheet_p), "gif": storage.rel(gif_p), "webp": storage.rel(webp_p),
                           "tres": storage.rel(tres_p), "json": storage.rel(folder / "sheet.json")}}
    export_view = {"id": aid, "kind": "animation", "capability": ctx.job["capability"], "width": fw, "height": fh,
                   "meta": full_meta}
    for key, doc in (("aseprite", engine_export.aseprite_json(export_view)),
                     ("phaser", engine_export.phaser_atlas(export_view))):
        if doc:
            p = folder / f"{key}.json"
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            full_meta["files"][key] = storage.rel(p)
    asset = storage.create_asset(ctx.project_id, kind="animation", name=name, path=gif_p, width=fw, height=fh,
                                 meta=full_meta, parents=parents, job_id=ctx.id, capability=ctx.job["capability"])
    ctx.register(asset)
    return asset


def asset_meta(asset_id: str) -> dict:
    a = db.get("assets", asset_id)
    return (a or {}).get("meta") or {}


def image_param(name: str, label: str, required: bool = True, help: str = ""):
    from . import Param
    return Param(name, "image", label, required=required, help=help)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
