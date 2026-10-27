"""Offline providers: procedural image generator, procedural animator, rule-based LLM, billboard 3D.

They make the whole pipeline runnable without GPU / API keys (demo, CI, and fallback), and they emit
"fake pixel art" (upscaled blocks) so the pixel pipeline exercises its grid-detection path.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .base import ImageProvider, LLMProvider, ThreeDProvider, VideoProvider

COLOR_WORDS = {
    "red": (214, 64, 69), "红": (214, 64, 69), "blue": (64, 112, 214), "蓝": (64, 112, 214),
    "green": (72, 168, 96), "绿": (72, 168, 96), "yellow": (236, 196, 64), "黄": (236, 196, 64),
    "gold": (226, 176, 52), "金": (226, 176, 52), "purple": (146, 86, 198), "紫": (146, 86, 198),
    "pink": (232, 128, 170), "粉": (232, 128, 170), "orange": (232, 132, 52), "橙": (232, 132, 52),
    "white": (232, 232, 240), "白": (232, 232, 240), "black": (52, 48, 64), "黑": (52, 48, 64),
    "brown": (140, 92, 60), "棕": (140, 92, 60), "silver": (176, 184, 200), "银": (176, 184, 200),
    "ice": (150, 210, 240), "冰": (150, 210, 240), "fire": (240, 100, 40), "火": (240, 100, 40),
}
KINDS = [
    ("character", ["character", "hero", "knight", "girl", "boy", "warrior", "mage", "npc", "人", "角色", "勇者", "骑士", "女孩", "男孩", "法师", "猫娘"]),
    ("slime", ["slime", "monster", "blob", "enemy", "史莱姆", "怪", "敌人"]),
    ("sword", ["sword", "weapon", "blade", "axe", "spear", "剑", "武器", "刀", "斧"]),
    ("potion", ["potion", "bottle", "flask", "药水", "瓶"]),
    ("tree", ["tree", "plant", "bush", "树", "植物", "草丛"]),
    ("chest", ["chest", "box", "crate", "宝箱", "箱"]),
    ("tile", ["texture", "tile", "ground", "grass", "dirt", "stone", "地面", "纹理", "草地", "泥土", "石"]),
    ("ui", ["ui", "button", "hud", "panel", "icon", "按钮", "界面", "面板", "图标"]),
    ("scene", ["scene", "background", "landscape", "map", "场景", "背景", "地图", "风景"]),
]


def _seed(prompt: str, seed: int | None) -> int:
    h = int(hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8], 16)
    return h ^ (seed or 0)


def _palette(prompt: str, rng: random.Random) -> list[tuple[int, int, int]]:
    base = None
    low = prompt.lower()
    for word, col in COLOR_WORDS.items():
        if word in low:
            base = col
            break
    if base is None:
        hue = rng.random()
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.85)
        base = (int(r * 255), int(g * 255), int(b * 255))
    dark = tuple(int(c * 0.55) for c in base)
    light = tuple(min(255, int(c * 1.25 + 30)) for c in base)
    return [base, dark, light, (40, 34, 48), (246, 214, 180), (250, 250, 250)]  # type: ignore[list-item]


def _kind(prompt: str) -> str:
    low = prompt.lower()
    for kind, words in KINDS:
        if any(w in low for w in words):
            return kind
    return "gem"


def _draw_sprite(kind: str, pal, rng: random.Random, g: int = 32) -> Image.Image:
    """Draw a g×g sprite on transparent background."""
    im = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    base, dark, light, ink, skin, white = pal
    u = g / 32
    if kind == "character":
        d.rectangle([12 * u, 26 * u, 14 * u, 30 * u], fill=ink)
        d.rectangle([18 * u, 26 * u, 20 * u, 30 * u], fill=ink)
        d.rectangle([10 * u, 15 * u, 22 * u, 26 * u], fill=base, outline=dark)
        d.rectangle([8 * u, 16 * u, 10 * u, 23 * u], fill=skin)
        d.rectangle([22 * u, 16 * u, 24 * u, 23 * u], fill=skin)
        d.ellipse([10 * u, 4 * u, 22 * u, 16 * u], fill=skin, outline=ink)
        d.chord([9 * u, 2 * u, 23 * u, 12 * u], 180, 360, fill=dark)
        d.rectangle([13 * u, 9 * u, 14 * u, 11 * u], fill=ink)
        d.rectangle([18 * u, 9 * u, 19 * u, 11 * u], fill=ink)
        d.rectangle([12 * u, 19 * u, 20 * u, 20 * u], fill=light)
    elif kind == "slime":
        d.ellipse([5 * u, 12 * u, 27 * u, 30 * u], fill=base, outline=dark)
        d.ellipse([9 * u, 15 * u, 14 * u, 19 * u], fill=light)
        d.rectangle([12 * u, 20 * u, 13 * u, 23 * u], fill=ink)
        d.rectangle([19 * u, 20 * u, 20 * u, 23 * u], fill=ink)
    elif kind == "sword":
        d.polygon([(15 * u, 2 * u), (17 * u, 2 * u), (18 * u, 21 * u), (14 * u, 21 * u)], fill=(200, 210, 225), outline=ink)
        d.line([(16 * u, 4 * u), (16 * u, 20 * u)], fill=white)
        d.rectangle([10 * u, 21 * u, 22 * u, 23 * u], fill=base, outline=dark)
        d.rectangle([15 * u, 23 * u, 17 * u, 29 * u], fill=dark)
        d.ellipse([14 * u, 28 * u, 18 * u, 31 * u], fill=base)
    elif kind == "potion":
        d.rectangle([14 * u, 4 * u, 18 * u, 10 * u], fill=(210, 220, 230), outline=ink)
        d.rectangle([13 * u, 3 * u, 19 * u, 5 * u], fill=(150, 100, 60))
        d.ellipse([7 * u, 9 * u, 25 * u, 29 * u], fill=(220, 230, 240), outline=ink)
        d.ellipse([9 * u, 15 * u, 23 * u, 27 * u], fill=base)
        d.ellipse([11 * u, 16 * u, 14 * u, 19 * u], fill=white)
    elif kind == "tree":
        d.rectangle([14 * u, 20 * u, 18 * u, 30 * u], fill=(120, 80, 50), outline=ink)
        d.ellipse([5 * u, 3 * u, 27 * u, 23 * u], fill=(72, 160, 80), outline=(30, 80, 40))
        d.ellipse([9 * u, 6 * u, 16 * u, 12 * u], fill=(120, 200, 110))
    elif kind == "chest":
        d.rectangle([5 * u, 12 * u, 27 * u, 28 * u], fill=(150, 96, 50), outline=ink)
        d.rectangle([5 * u, 12 * u, 27 * u, 17 * u], fill=(176, 116, 64), outline=ink)
        d.rectangle([14 * u, 15 * u, 18 * u, 20 * u], fill=base, outline=dark)
    elif kind == "ui":
        d.rounded_rectangle([3 * u, 9 * u, 29 * u, 23 * u], radius=int(3 * u), fill=base, outline=dark, width=max(1, int(u)))
        d.rectangle([6 * u, 12 * u, 26 * u, 14 * u], fill=light)
    else:
        d.polygon([(16 * u, 3 * u), (27 * u, 13 * u), (16 * u, 29 * u), (5 * u, 13 * u)], fill=base, outline=dark)
        d.polygon([(16 * u, 3 * u), (21 * u, 13 * u), (16 * u, 29 * u), (11 * u, 13 * u)], fill=light)
    return im


def _texture(pal, rng: random.Random, g: int = 32) -> Image.Image:
    base, dark, light = pal[0], pal[1], pal[2]
    arr = np.zeros((g, g, 4), dtype=np.uint8)
    noise = np.random.default_rng(rng.randint(0, 10_000)).random((g, g))
    for y in range(g):
        for x in range(g):
            n = noise[y, x]
            c = dark if n < 0.18 else light if n > 0.86 else base
            arr[y, x] = (*c, 255)
    return Image.fromarray(arr, "RGBA")


def _scene(pal, rng: random.Random, w: int, h: int) -> Image.Image:
    im = Image.new("RGBA", (w, h), (150, 200, 240, 255))
    d = ImageDraw.Draw(im)
    for i in range(h // 2):
        t = i / (h / 2)
        d.line([(0, i), (w, i)], fill=(int(120 + 80 * t), int(170 + 50 * t), 235, 255))
    for k in range(3):
        base_y = h * (0.5 + 0.12 * k)
        col = tuple(int(c * (0.6 + 0.15 * k)) for c in pal[0])
        pts = [(0, h)]
        for x in range(0, w + 16, 16):
            pts.append((x, base_y + math.sin(x / (40 + 20 * k) + k) * 18 + rng.random() * 6))
        pts.append((w, h))
        d.polygon(pts, fill=(*col, 255))
    return im


class MockImageProvider(ImageProvider):
    name = "mock"
    label = "离线程序化生成 (Mock)"
    lane = "cpu"
    supports_refs = True
    supports_edit = True

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024, n: int = 1,
                       seed: int | None = None, refs=None, negative: str = "", quality: str = "standard",
                       transparent: bool = False, layout=None, ctx: Any = None) -> list[Image.Image]:
        out = []
        for i in range(n):
            rng = random.Random(_seed(prompt, (seed or 0) + i))
            pal = _palette(prompt, rng)
            kind = _kind(prompt)
            bg = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
            if kind == "scene":
                out.append(_scene(pal, rng, width, height).convert("RGBA"))
                continue
            canvas = Image.new("RGBA", (width, height), bg)
            if kind == "tile":
                tex = _texture(pal, rng, 32)
                out.append(tex.resize((width, height), Image.Resampling.NEAREST))
                continue
            cols, rows = layout or (1, 1)
            cw, ch = width // cols, height // rows
            g = 32
            for r in range(rows):
                for c in range(cols):
                    sub_rng = random.Random(rng.randint(0, 1 << 30))
                    sub_pal = _palette(prompt + str(r * cols + c) if cols * rows > 1 else prompt, sub_rng)
                    sprite = _draw_sprite(kind, sub_pal, sub_rng, g)
                    block = max(1, int(min(cw, ch) * 0.8) // g)
                    sprite = sprite.resize((g * block, g * block), Image.Resampling.NEAREST)
                    canvas.alpha_composite(sprite, (c * cw + (cw - sprite.width) // 2, r * ch + (ch - sprite.height) // 2))
            out.append(canvas)
        return out

    async def edit(self, image: Image.Image, prompt: str, *, refs=None, mask=None, strength: float = 0.65,
                   seed=None, width=None, height=None, ctx: Any = None) -> list[Image.Image]:
        rng = random.Random(_seed(prompt, seed))
        pal = _palette(prompt, rng)
        img = image.convert("RGBA")
        arr = np.asarray(img).astype(np.float32)
        tint = np.array(pal[0], dtype=np.float32)
        lum = arr[..., :3].mean(axis=2, keepdims=True) / 255.0
        mixed = arr[..., :3] * (1 - strength * 0.6) + tint * lum * strength * 0.6 * 1.3
        if mask is not None:
            m = (np.asarray(mask.convert("L").resize(img.size)) > 127)[..., None]
            mixed = np.where(m, mixed, arr[..., :3])
        arr[..., :3] = np.clip(mixed, 0, 255)
        out = Image.fromarray(arr.astype(np.uint8), "RGBA")
        if width and height and (width, height) != out.size:
            out = out.resize((width, height), Image.Resampling.NEAREST)
        return [out]


MOTIONS = {
    "idle": ["idle", "breath", "待机", "呼吸"], "walk": ["walk", "run", "走", "跑"],
    "attack": ["attack", "slash", "hit", "攻击", "挥", "砍"], "jump": ["jump", "跳"],
    "float": ["float", "hover", "漂浮", "悬浮", "fly", "飞"], "spin": ["spin", "rotate", "旋转"],
    "hurt": ["hurt", "damage", "受伤", "受击"], "bounce": ["bounce", "弹", "slime", "史莱姆"],
}


def detect_motion(prompt: str) -> str:
    low = prompt.lower()
    for motion, words in MOTIONS.items():
        if any(w in low for w in words):
            return motion
    return "idle"


def _place(src: Image.Image, size, dx=0.0, dy=0.0, sx=1.0, sy=1.0, angle=0.0, flash=0.0) -> Image.Image:
    w, h = size
    img = src
    nw, nh = max(1, int(round(src.width * sx))), max(1, int(round(src.height * sy)))
    if (nw, nh) != src.size:
        img = img.resize((nw, nh), Image.Resampling.NEAREST)
    if angle:
        img = img.rotate(angle, resample=Image.Resampling.NEAREST, expand=True)
    if flash > 0:
        a = np.asarray(img).astype(np.float32)
        a[..., :3] = a[..., :3] * (1 - flash) + 255 * flash
        img = Image.fromarray(a.astype(np.uint8), "RGBA")
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = int(round((w - img.width) / 2 + dx))
    y = int(round(h - img.height - (h - src.height) / 2 + dy))
    canvas.paste(img, (x, y), img)
    return canvas


class ProceduralVideoProvider(VideoProvider):
    """Deterministic transform-based animation (squash/stretch, bob, lunge...). Zero GPU, instant."""
    name = "procedural"
    label = "程序化动画 (本地零显存)"
    lane = "cpu"
    supports_last_frame = True

    async def animate(self, first: Image.Image, prompt: str, *, last=None, num_frames: int = 16, fps: int = 8,
                      width: int = 0, height: int = 0, seed=None, ctx: Any = None) -> list[Image.Image]:
        src = first.convert("RGBA")
        pad = max(4, src.height // 6)
        size = (src.width + 2 * pad, src.height + 2 * pad)
        motion = detect_motion(prompt)
        frames = []
        for i in range(num_frames):
            t = i / num_frames
            s = math.sin(2 * math.pi * t)
            c = math.cos(2 * math.pi * t)
            if motion == "idle":
                f = _place(src, size, dy=-pad + 0, sx=1 + 0.03 * s, sy=1 - 0.04 * s)
            elif motion == "walk":
                f = _place(src, size, dy=-pad - abs(s) * pad * 0.5, angle=4 * s)
            elif motion == "attack":
                lunge = max(0.0, math.sin(math.pi * min(1, t * 1.6)))
                f = _place(src, size, dx=lunge * pad * 0.9, dy=-pad, angle=-12 * lunge, sx=1 + 0.06 * lunge)
            elif motion == "jump":
                up = max(0.0, math.sin(math.pi * t))
                squash = 0.12 if t < 0.1 or t > 0.9 else 0
                f = _place(src, size, dy=-pad - up * pad * 0.95, sx=1 + squash, sy=1 - squash)
            elif motion == "float":
                f = _place(src, size, dy=-pad - (s + 1) * pad * 0.35)
            elif motion == "spin":
                f = _place(src, size, dy=-pad, sx=max(0.08, abs(c)))
            elif motion == "hurt":
                f = _place(src, size, dx=(pad * 0.3) * (1 if i % 2 else -1) * (1 - t), dy=-pad, flash=0.7 if i < 2 else 0)
            else:  # bounce
                f = _place(src, size, dy=-pad - abs(s) * pad * 0.6, sx=1 + 0.1 * c, sy=1 - 0.1 * c)
            frames.append(f)
        if last is not None:
            lst = _place(last.convert("RGBA"), size, dy=-pad)
            frames = [Image.blend(f, lst, i / max(1, num_frames - 1)) for i, f in enumerate(frames)]
        return frames


class RulesLLM(LLMProvider):
    """Template-based fallback so prompt optimisation / design docs still work with no LLM configured."""
    name = "rules"
    label = "规则模板 (无 LLM)"

    async def chat(self, messages, *, temperature: float = 0.4, json_mode: bool = False, max_tokens: int = 2048) -> str:
        last = messages[-1]["content"] if messages else ""
        if json_mode:
            return json.dumps({"reply": "（离线规则模式）已按关键词理解你的需求。", "items": []}, ensure_ascii=False)
        return f"（离线规则模式，未配置大模型）\n\n你的输入：{last[:500]}"


class MockThreeDProvider(ThreeDProvider):
    """Builds an extruded, textured billboard GLB from the image silhouette (for pipeline testing)."""
    name = "mock"
    label = "Billboard 3D (Mock)"
    lane = "cpu"

    async def image_to_3d(self, image: Image.Image, out_dir: Path, *, seed: int = 42, quality: str = "standard",
                          ctx: Any = None) -> Path:
        import trimesh
        img = image.convert("RGBA")
        w, h = img.size
        aspect = w / h
        hw, hh, d = 0.5 * aspect, 0.5, 0.04
        v = np.array([[-hw, -hh, d], [hw, -hh, d], [hw, hh, d], [-hw, hh, d],
                      [-hw, -hh, -d], [hw, -hh, -d], [hw, hh, -d], [-hw, hh, -d]])
        f = np.array([[0, 1, 2], [0, 2, 3], [5, 4, 7], [5, 7, 6]])
        uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [1, 0], [0, 0], [0, 1], [1, 1]])
        material = trimesh.visual.material.PBRMaterial(baseColorTexture=img, alphaMode="MASK", alphaCutoff=0.5,
                                                         doubleSided=True)
        mesh = trimesh.Trimesh(vertices=v, faces=f, visual=trimesh.visual.TextureVisuals(uv=uv, material=material),
                               process=False)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "model.glb"
        mesh.export(path)
        return path
