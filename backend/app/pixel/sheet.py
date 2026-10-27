"""Sprite sheets, GIF/WebP export, frame alignment and Godot SpriteFrames resources."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from .pixelate import alpha_bbox


def union_bbox(frames: list[Image.Image]) -> tuple[int, int, int, int] | None:
    boxes = [b for b in (alpha_bbox(f) for f in frames) if b]
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def crop_frames(frames: list[Image.Image], margin: int = 1) -> list[Image.Image]:
    """Crop every frame with the same union box so the sprite anchor stays stable."""
    box = union_bbox(frames)
    if not box:
        return frames
    w, h = frames[0].size
    x0, y0, x1, y1 = box
    box = (max(0, x0 - margin), max(0, y0 - margin), min(w, x1 + margin), min(h, y1 + margin))
    return [f.crop(box) for f in frames]


def pack_sheet(frames: list[Image.Image], cols: int | None = None, spacing: int = 0) -> tuple[Image.Image, int, int]:
    n = len(frames)
    if not cols:
        cols = min(n, 8) if n <= 8 else int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols))
    fw, fh = frames[0].size
    sheet = Image.new("RGBA", (cols * fw + (cols - 1) * spacing, rows * fh + (rows - 1) * spacing), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        sheet.alpha_composite(f.convert("RGBA"), (c * (fw + spacing), r * (fh + spacing)))
    return sheet, cols, rows


def split_sheet(sheet: Image.Image, cols: int, rows: int, count: int | None = None) -> list[Image.Image]:
    fw, fh = sheet.width // cols, sheet.height // rows
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append(sheet.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)))
    return out[:count] if count else out


def save_gif(frames: list[Image.Image], path: Path, fps: float, loop: bool = True, scale: int = 1) -> None:
    out = []
    for f in frames:
        f = f.convert("RGBA")
        if scale > 1:
            f = f.resize((f.width * scale, f.height * scale), Image.Resampling.NEAREST)
        a = np.asarray(f)
        rgb = Image.fromarray(a[..., :3])
        p = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pa = np.asarray(p).copy()
        pa[a[..., 3] < 128] = 255
        pal = p.getpalette()[:765] + [0, 0, 0]
        q = Image.fromarray(pa, "P")
        q.putpalette(pal)
        q.info["transparency"] = 255
        out.append(q)
    duration = int(round(1000 / max(1, fps)))
    out[0].save(path, save_all=True, append_images=out[1:], duration=duration, loop=0 if loop else 1,
                disposal=2, transparency=255, optimize=False)


def save_webp(frames: list[Image.Image], path: Path, fps: float, loop: bool = True) -> None:
    duration = int(round(1000 / max(1, fps)))
    frames = [f.convert("RGBA") for f in frames]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, loop=0 if loop else 1,
                   lossless=True)


def godot_spriteframes(texture_res_path: str, frame_w: int, frame_h: int, cols: int, count: int, fps: float,
                       loop: bool = True, anim_name: str = "default") -> str:
    lines = [f'[gd_resource type="SpriteFrames" load_steps={count + 2} format=3]', "",
             f'[ext_resource type="Texture2D" path="{texture_res_path}" id="1_sheet"]', ""]
    for i in range(count):
        r, c = divmod(i, cols)
        lines += [f'[sub_resource type="AtlasTexture" id="AtlasTexture_{i}"]', 'atlas = ExtResource("1_sheet")',
                  f"region = Rect2({c * frame_w}, {r * frame_h}, {frame_w}, {frame_h})", ""]
    frames = ",\n".join('{\n"duration": 1.0,\n"texture": SubResource("AtlasTexture_%d")\n}' % i for i in range(count))
    lines += ["[resource]", "animations = [{", f'"frames": [{frames}],', f'"loop": {"true" if loop else "false"},',
              f'"name": &"{anim_name}",', f'"speed": {float(fps)}', "}]", ""]
    return "\n".join(lines)


def godot_animated_scene(spriteframes_res_path: str, node_name: str = "Sprite") -> str:
    return "\n".join([
        '[gd_scene load_steps=2 format=3]', "",
        f'[ext_resource type="SpriteFrames" path="{spriteframes_res_path}" id="1_frames"]', "",
        f'[node name="{node_name}" type="AnimatedSprite2D"]',
        'texture_filter = 1', 'sprite_frames = ExtResource("1_frames")', 'autoplay = "default"', "",
    ])
