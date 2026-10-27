"""Engine-facing metadata exporters: Aseprite JSON, Phaser/Pixi atlas, Tiled tileset.

These formats share one idea taken from `sprite-gen` / `agent-sprite-forge` / `pixel-art-factory`:
an engine should sample *absolute frame rectangles* from a manifest instead of guessing a grid.
The files are written next to the image inside the ZIP, so relative paths stay valid:

    animations/<slug>/aseprite.json   -> "sheet.png"
    animations/<slug>/phaser.json     -> "sheet.png"
    images/<slug>/tileset.tsj         -> "<slug>.png"

Only formats are emitted whose source data exists (animation meta / tileset meta); nothing is faked.
"""
from __future__ import annotations

from typing import Any


def _stem(asset: dict) -> str:
    return f"{asset.get('capability') or asset['kind']}_{asset['id'][-6:]}"


def frame_layout(meta: dict) -> list[dict[str, int]]:
    count = int(meta.get("count") or 0)
    fw, fh, cols = int(meta.get("frame_w") or 0), int(meta.get("frame_h") or 0), int(meta.get("cols") or 0)
    if not (count and fw and fh and cols):
        return []
    return [
        {"index": i, "x": (i % cols) * fw, "y": (i // cols) * fh, "w": fw, "h": fh}
        for i in range(count)
    ]


def _animation(asset: dict) -> tuple[dict, list[dict[str, int]]] | None:
    meta = asset.get("meta") or {}
    frames = frame_layout(meta)
    if not frames:
        return None
    return meta, frames


def aseprite_json(asset: dict) -> dict | None:
    """Aseprite 'array' JSON (also read by Phaser, PixiJS and Flame)."""
    got = _animation(asset)
    if not got:
        return None
    meta, rects = got
    fps = float(meta.get("fps") or 12)
    duration = int(round(1000 / max(1.0, fps)))
    cols = int(meta.get("cols") or 1)
    rows = int(meta.get("rows") or 1)
    fw, fh = int(meta["frame_w"]), int(meta["frame_h"])
    frames = [{
        "filename": "sheet.png",
        "frame": {"x": r["x"], "y": r["y"], "w": fw, "h": fh},
        "rotated": False,
        "trimmed": False,
        "spriteSourceSize": {"x": 0, "y": 0, "w": fw, "h": fh},
        "sourceSize": {"w": fw, "h": fh},
        "duration": duration,
    } for r in rects]
    return {
        "frames": frames,
        "meta": {
            "app": "SpriteKiln",
            "version": "1.1",
            "image": "sheet.png",
            "format": "RGBA8888",
            "size": {"w": cols * fw, "h": rows * fh},
            "scale": "1",
            "frameTags": [{"name": "default", "from": 0, "to": len(rects) - 1, "direction": "forward",
                           "repeat": "1" if meta.get("loop", True) else "0"}],
            "layers": [{"name": "sprite", "opacity": 255, "blendMode": "normal"}],
            "slices": [],
            "pivot": {"x": 0.5, "y": 1.0},
        },
    }


def phaser_atlas(asset: dict) -> dict | None:
    """Phaser 3 / PixiJS 'JSON Hash' texture atlas with an `animations` map."""
    got = _animation(asset)
    if not got:
        return None
    meta, rects = got
    fw, fh = int(meta["frame_w"]), int(meta["frame_h"])
    stem = _stem(asset)
    names = [f"{stem}_{i:03d}" for i in range(len(rects))]
    frames = {
        name: {
            "frame": {"x": r["x"], "y": r["y"], "w": fw, "h": fh},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": fw, "h": fh},
            "sourceSize": {"w": fw, "h": fh},
        }
        for name, r in zip(names, rects)
    }
    return {
        "frames": frames,
        "animations": {"default": names},
        "meta": {
            "app": "SpriteKiln",
            "version": "1.1",
            "image": "sheet.png",
            "format": "RGBA8888",
            "size": {"w": int(meta.get("cols") or 1) * fw, "h": int(meta.get("rows") or 1) * fh},
            "scale": "1",
        },
    }


def tiled_tileset(asset: dict, image_name: str | None = None) -> dict | None:
    """Tiled 1.10 JSON tileset (.tsj) for dual-grid terrain atlases and isometric tiles."""
    meta = asset.get("meta") or {}
    width, height = int(asset.get("width") or 0), int(asset.get("height") or 0)
    if not (width and height):
        return None
    tile_w = int(meta.get("tile_size") or (meta.get("diamond") or [0])[0] or 0)
    tile_h = int(meta.get("tile_size") or (meta.get("diamond") or [0, 0])[1] // 2 or 0)
    if not meta.get("tileset") and not meta.get("isometric") and not tile_w:
        return None
    if meta.get("isometric"):
        tile_h = int(meta.get("diamond", [tile_w, tile_w // 2])[1])
    if not tile_w or not tile_h:
        return None
    columns = max(1, width // tile_w)
    rows = max(1, height // tile_h)
    tilecount = columns * rows
    tiles = []
    for item in meta.get("mapping") or []:
        props = [{"name": "corner_mask", "type": "int", "value": int(item.get("index", 0))}]
        corners = item.get("corners") or {}
        for key, label in (("tl", "corner_tl"), ("tr", "corner_tr"), ("bl", "corner_bl"), ("br", "corner_br")):
            if key in corners:
                props.append({"name": label, "type": "bool", "value": bool(corners[key])})
        tiles.append({"id": int(item.get("index", len(tiles))), "properties": props})
    out: dict[str, Any] = {
        "type": "tileset",
        "version": "1.10",
        "tiledversion": "1.10.2",
        "name": f"spritekiln_{asset['id'][-6:]}",
        "tilewidth": tile_w,
        "tileheight": tile_h,
        "tilecount": tilecount,
        "columns": columns,
        "spacing": 0,
        "margin": 0,
        "image": image_name or f"{_stem(asset)}.png",
        "imagewidth": width,
        "imageheight": height,
    }
    if meta.get("isometric"):
        out["tileoffset"] = {"x": 0, "y": tile_h // 2}
        out["properties"] = [{"name": "grid", "type": "string", "value": "isometric-2:1"}]
    if tiles:
        out["tiles"] = tiles
    return out


def engine_files(asset: dict, image_path: str) -> dict[str, dict]:
    """Map export-relative path → JSON document for one asset.

    ``image_path`` is the asset's main path inside the export. Animations pass their folder
    (files are written beside ``sheet.png``); still images pass the image itself and get a
    sibling ``.tsj`` tileset.
    """
    if asset["kind"] == "animation":
        folder = image_path.rsplit("/", 1)[0]
        out: dict[str, dict] = {}
        ase = aseprite_json(asset)
        pha = phaser_atlas(asset)
        if ase:
            out[f"{folder}/aseprite.json"] = ase
        if pha:
            out[f"{folder}/phaser.json"] = pha
        return out
    tsj = tiled_tileset(asset, image_path.rsplit("/", 1)[-1])
    if not tsj:
        return {}
    return {f"{image_path.rsplit('.', 1)[0]}.tsj": tsj}
