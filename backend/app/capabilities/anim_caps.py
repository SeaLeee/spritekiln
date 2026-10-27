"""Animation: sprite frame animation from a still (video model → frames → key-out → re-pixelate with locked
palette → aligned sprite sheet), keyframe-controlled animation (first/last-frame interpolation chained), video."""
from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image

from .. import db, storage
from ..pixel import qa
from ..pixel.bg import chroma_remove
from ..pixel.pixelate import extract_palette, has_alpha, pixelate, quantize
from . import Capability, Param, register
from .common import remove_bg, save_animation, seed_of
from .image_caps import SEED

VIDEO = Param("video_provider", "select", "动画模型", "auto",
              choices=[{"value": "auto", "label": "自动 (本地优先)"},
                       {"value": "comfyui", "label": "本地 ComfyUI (MiniMax H3 / Wan2.2)"},
                       {"value": "ark", "label": "Seedance"}, {"value": "minimax", "label": "MiniMax Hailuo"},
                       {"value": "procedural", "label": "程序化 (零显存/即时)"}])
KEYS = [(0, 255, 0), (255, 0, 255), (0, 128, 255), (255, 255, 255)]


def choose_key(img: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(img.convert("RGBA"))
    px = arr[arr[..., 3] > 127][:, :3].astype(np.float32)
    if len(px) == 0:
        return KEYS[0]
    px = px[:: max(1, len(px) // 4000)]
    best, best_d = KEYS[0], -1.0
    for k in KEYS[:3]:
        d = float(np.sqrt(((px - np.array(k)) ** 2).sum(axis=1)).min())
        if d > best_d:
            best, best_d = k, d
    return best


class Stage:
    """Places a sprite on a solid key-colour canvas sized for the video model and maps frames back."""

    def __init__(self, src: Image.Image, pixel: bool, pad: tuple[int, int, int, int], target: int = 512):
        self.src = src.convert("RGBA")
        self.pixel = pixel
        t, r, b, l = pad
        self.logical = (self.src.width + l + r, self.src.height + t + b)
        self.offset = (l, t)
        scale = target / max(self.logical)
        self.k = max(1, math.floor(scale)) if pixel else scale
        cw, ch = round(self.logical[0] * self.k), round(self.logical[1] * self.k)
        self.size = (int(math.ceil(cw / 32) * 32), int(math.ceil(ch / 32) * 32))
        self.inner = (cw, ch)
        self.key = choose_key(self.src)

    def canvas(self, img: Image.Image | None = None) -> Image.Image:
        img = (img or self.src).convert("RGBA")
        logical = Image.new("RGBA", self.logical, (0, 0, 0, 0))
        logical.alpha_composite(img, self.offset)
        big = logical.resize(self.inner, Image.Resampling.NEAREST if self.pixel else Image.Resampling.LANCZOS)
        out = Image.new("RGBA", self.size, (*self.key, 255))
        out.alpha_composite(big, (0, 0))
        return out.convert("RGB")

    def restore(self, frame: Image.Image, palette, colors: int) -> Image.Image:
        f = frame.convert("RGBA").resize(self.size, Image.Resampling.LANCZOS).crop((0, 0, *self.inner))
        f = chroma_remove(f, self.key, tolerance=95, flood=True, soft=not self.pixel)
        if self.pixel:
            return pixelate(f, self.logical[0], self.logical[1], colors=colors, palette=palette, detect_grid=False,
                            trim_alpha=False)
        return f.resize(self.logical, Image.Resampling.LANCZOS)


def _pad(src: Image.Image, p: dict) -> tuple[int, int, int, int]:
    if p.get("padding", -1) >= 0:
        v = int(p["padding"])
        return v, v, v, v
    w, h = src.size
    return int(h * 0.3), int(w * 0.3), max(1, int(h * 0.04)), int(w * 0.3)


def _motion_prompt(action: str, loop: bool, key) -> str:
    color = {(0, 255, 0): "pure green", (255, 0, 255): "pure magenta", (0, 128, 255): "pure blue"}.get(tuple(key), "solid")
    s = (f"{action}. The character performs the action in place, full body always visible, static locked camera, "
         f"no zoom, no camera movement, flat {color} background stays unchanged, 2D game sprite animation.")
    if loop:
        s += " Seamless loop: the last pose returns exactly to the first pose."
    return s


async def _frames_from_provider(ctx, stage: Stage | None, src: Image.Image, prompt: str, *, last: Image.Image | None,
                                n: int, fps: int, seed: int) -> list[Image.Image]:
    prov = ctx.provider("video")
    ctx.progress(0.08, f"{prov.label} 生成动作…")
    if prov.name == "procedural" or stage is None:
        return await prov.animate(src, prompt, last=last, num_frames=n, fps=fps, seed=seed, ctx=ctx)
    first = stage.canvas()
    last_c = stage.canvas(last) if last is not None else None
    return await prov.animate(first, prompt, last=last_c, num_frames=n, fps=fps, width=stage.size[0],
                              height=stage.size[1], seed=seed, ctx=ctx)


async def run_animate(ctx, p: dict) -> None:
    asset = db.get("assets", p["source"]) or {}
    src = storage.load_image(p["source"])
    pixel = p["mode"] == "pixel" or (p["mode"] == "auto" and bool((asset.get("meta") or {}).get("pixel")))
    if not has_alpha(src):
        src = await remove_bg(ctx, src, "pixel" if pixel else "hd", "auto")
    last = storage.load_image(p["last_frame"]) if p.get("last_frame") else None
    n, fps, seed = int(p["frames"]), int(p["fps"]), seed_of(p)
    prov_name = ctx.provider_name("video")
    stage = None if prov_name == "procedural" else Stage(src, pixel, _pad(src, p), int(p["resolution"]))
    key = stage.key if stage else KEYS[0]
    prompt = _motion_prompt(p["prompt"], p["loop"], key)
    loop_last = src if (p["loop"] and last is None) else last
    colors = int(p["colors"])
    palette = extract_palette(src, colors) if pixel else None
    # Geometry metrics need real alpha; with keep-background there is nothing to measure.
    gate = p.get("quality_gate") or "standard"
    if p["remove_bg"] == "none":
        gate = "off"
    retakes = max(0, int(p.get("retakes") or 0)) if gate != "off" else 0
    best: tuple[float, list[Image.Image], dict] | None = None
    reports: list[dict] = []
    for attempt in range(retakes + 1):
        ctx.check()
        # each retry asks for the property that most often breaks a take; seed changes too
        attempt_prompt = prompt if attempt == 0 else prompt + (
            " Keep the whole character inside the frame, at the same size and position as the first pose.")
        raw = await _frames_from_provider(ctx, stage, src, attempt_prompt, last=loop_last,
                                          n=n + (1 if p["loop"] else 0), fps=fps, seed=seed + attempt * 10_007)
        if p["loop"] and len(raw) > n:
            raw = raw[:n]  # drop the duplicated closing frame
        ctx.progress(0.85, "逐帧抠图 / 锁定调色板像素化 / 对齐")
        if stage is not None:
            frames = [stage.restore(f, palette, colors) for f in raw]
        else:
            frames = [quantize(f, palette=palette) if pixel else f for f in raw]
        if p["remove_bg"] == "none" and stage is not None:
            frames = [Image.alpha_composite(Image.new("RGBA", f.size, (*key, 255)), f) for f in frames]
        report = qa.grade(frames, gate)
        report["attempt"] = attempt + 1
        reports.append(report)
        if best is None or report["score"] > best[0]:
            best = (report["score"], frames, report)
        if report["ok"] or attempt == retakes:
            break
        ctx.progress(0.9, f"质量门控未通过（{report['issues'][0] if report['issues'] else '未知'}），"
                          f"重拍 {attempt + 1}/{retakes}")
    assert best is not None
    _, frames, report = best
    save_animation(ctx, frames, name=f"动画 · {p['prompt'][:18]}", fps=fps, loop=p["loop"],
                   meta={"prompt": p["prompt"], "seed": seed, "source": p["source"], "motion_provider": prov_name,
                         "qa": report, "qa_attempts": reports},
                   parents=[p["source"]], pixel=pixel)


register(Capability(
    "animate", "帧动画", "animation",
    "从一张定稿素材生成精灵帧动画：视频模型生成动作 → 逐帧键控抠图 → 锁定源调色板重像素化 → 锚点对齐 → "
    "Sprite Sheet / GIF / WebP / Godot SpriteFrames。",
    [Param("source", "image", "定稿素材", None, required=True),
     Param("prompt", "longtext", "动作描述", "idle breathing animation", required=True, help="例：walk cycle to the right / 挥剑攻击 / 跳跃"),
     Param("frames", "select", "帧数", 16, choices=[8, 12, 16, 24, 32]),
     Param("fps", "select", "帧率", 12, choices=[6, 8, 10, 12, 16, 24]),
     Param("loop", "bool", "循环动画", True), Param("last_frame", "image", "尾帧 (可选)", None),
     Param("mode", "select", "风格", "auto", choices=[{"value": "auto", "label": "跟随源素材"},
                                                     {"value": "pixel", "label": "像素"}, {"value": "hd", "label": "高清"}]),
     Param("colors", "int", "像素颜色数", 32, min=4, max=64, advanced=True),
     Param("resolution", "select", "生成分辨率", 512, choices=[384, 512, 640, 768], advanced=True),
     Param("padding", "int", "四周留白(px, -1=自动)", -1, min=-1, max=320, advanced=True),
     Param("remove_bg", "select", "去背景", "auto", choices=["auto", "none"], advanced=True),
     Param("quality_gate", "select", "质量门控", "standard",
           choices=[{"value": "off", "label": "关闭"}, {"value": "standard", "label": "标准"},
                    {"value": "strict", "label": "严格"}], advanced=True,
           help="检查空帧/面积波动/尺寸漂移/锚点漂移/重复帧；不通过时自动重拍"),
     Param("retakes", "int", "未通过重拍次数", 1, min=0, max=2, advanced=True,
           help="每次重拍都会换 seed，并追加“保持在画面内、尺寸位置一致”的提示"), VIDEO, SEED],
    run_animate, needs=["video", "bg"], aliases=["meowa-animation", "meowa_animation", "animate-run"],
    outputs="animation", icon="film", hint="先定稿静态素材再做动画；像素动画建议 ≤128×128。"))


async def run_keyframes(ctx, p: dict) -> None:
    keys = [storage.load_image(a) for a in p["keyframes"]]
    if len(keys) < 2:
        raise ValueError("至少需要 2 张关键帧")
    first_asset = db.get("assets", p["keyframes"][0]) or {}
    pixel = p["mode"] == "pixel" or (p["mode"] == "auto" and bool((first_asset.get("meta") or {}).get("pixel")))
    keys = [k if has_alpha(k) else await remove_bg(ctx, k, "pixel" if pixel else "hd", "auto") for k in keys]
    w = max(k.width for k in keys)
    h = max(k.height for k in keys)
    norm = []
    for k in keys:
        c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        c.alpha_composite(k, ((w - k.width) // 2, h - k.height))
        norm.append(c)
    if p["loop"]:
        norm.append(norm[0])
    seg_prompts = p.get("segment_prompts") or []
    per = int(p["frames_per_segment"])
    fps, seed = int(p["fps"]), seed_of(p)
    prov_name = ctx.provider_name("video")
    stage = None if prov_name == "procedural" else Stage(norm[0], pixel, _pad(norm[0], {"padding": p["padding"]}),
                                                         int(p["resolution"]))
    colors = 32
    palette = extract_palette(norm[0], colors) if pixel else None
    frames: list[Image.Image] = []
    segments = len(norm) - 1
    for i in range(segments):
        ctx.progress(0.05 + 0.8 * i / segments, f"关键帧段 {i + 1}/{segments}")
        action = seg_prompts[i] if i < len(seg_prompts) else (p.get("prompt") or "smooth motion between the two poses")
        prompt = _motion_prompt(action, False, stage.key if stage else KEYS[0]) + \
            " The animation starts exactly at the first frame pose and ends exactly at the last frame pose."
        raw = await _frames_from_provider(ctx, stage, norm[i], prompt, last=norm[i + 1], n=per + 1, fps=fps, seed=seed + i)
        seg = [stage.restore(f, palette, colors) for f in raw] if stage else \
            [quantize(f, palette=palette) if pixel else f for f in raw]
        frames.extend(seg[:-1] if i < segments - 1 or p["loop"] else seg)
    save_animation(ctx, frames, name=f"关键帧动画 · {len(keys)} 关键帧", fps=fps, loop=p["loop"],
                   meta={"keyframes": p["keyframes"], "segment_prompts": seg_prompts, "motion_provider": prov_name},
                   parents=list(p["keyframes"]), pixel=pixel)


register(Capability(
    "keyframes_animate", "关键帧动画", "animation",
    "用 2-6 张关键姿势控制复杂动作：相邻关键帧两两做首尾帧插值（FL2V），拼接为连续帧并统一调色板与锚点。",
    [Param("keyframes", "images", "关键帧 (按顺序)", [], required=True),
     Param("segment_prompts", "lines", "每段动作说明 (每行一段, 可选)", []),
     Param("prompt", "text", "通用动作说明", "smooth natural motion"),
     Param("frames_per_segment", "select", "每段帧数", 6, choices=[3, 4, 6, 8, 12]),
     Param("fps", "select", "帧率", 12, choices=[6, 8, 10, 12, 16, 24]), Param("loop", "bool", "回到首帧循环", True),
     Param("mode", "select", "风格", "auto", choices=["auto", "pixel", "hd"]),
     Param("resolution", "select", "生成分辨率", 512, choices=[384, 512, 640, 768], advanced=True),
     Param("padding", "int", "留白(px, -1=自动)", -1, min=-1, max=320, advanced=True), VIDEO, SEED],
    run_keyframes, needs=["video", "bg"], aliases=["keyframes-run", "keyframes"], outputs="animation", icon="keyframes"))


async def run_video(ctx, p: dict) -> None:
    import av
    src = storage.load_image(p["first_frame"])
    last = storage.load_image(p["last_frame"]) if p.get("last_frame") else None
    prov = ctx.provider("video")
    w, h = (int(x) for x in p["size"].split("x"))
    fps = int(p["fps"])
    n = int(float(p["seconds"]) * fps)
    first = Image.new("RGB", src.size, (255, 255, 255))
    first.paste(src.convert("RGBA"), mask=src.convert("RGBA").getchannel("A"))
    frames = await prov.animate(first.resize((w, h)), p["prompt"], last=last.convert("RGB").resize((w, h)) if last else None,
                                num_frames=n, fps=fps, width=w, height=h, seed=seed_of(p), ctx=ctx)
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as out:
        stream = out.add_stream("h264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        for f in frames:
            bgf = Image.new("RGB", f.size, (255, 255, 255))
            bgf.paste(f.convert("RGBA"), mask=f.convert("RGBA").getchannel("A"))
            for pkt in stream.encode(av.VideoFrame.from_image(bgf.resize((w, h)))):
                out.mux(pkt)
        for pkt in stream.encode():
            out.mux(pkt)
    a = storage.save_bytes(ctx.project_id, buf.getvalue(), "mp4", name=f"视频 · {p['prompt'][:18]}", kind="video",
                           meta={"prompt": p["prompt"], "fps": fps, "frame_count": len(frames)},
                           parents=[x for x in (p["first_frame"], p.get("last_frame")) if x], job_id=ctx.id,
                           capability="video_gen")
    ctx.register(a)


register(Capability(
    "video_gen", "短视频", "animation",
    "首帧（可选尾帧）→ 短视频 mp4，用于过场/宣传或无法用帧动画表现的运动。",
    [Param("first_frame", "image", "首帧", None, required=True), Param("last_frame", "image", "尾帧 (可选)", None),
     Param("prompt", "longtext", "画面运动描述", "", required=True),
     Param("seconds", "select", "时长(s)", 3, choices=[2, 3, 4, 5, 6]), Param("fps", "select", "帧率", 16, choices=[8, 12, 16, 24]),
     Param("size", "select", "尺寸", "768x432", choices=["512x512", "768x432", "432x768", "1024x576"]), VIDEO, SEED],
    run_video, needs=["video"], aliases=["video-run", "seedance_generator"], outputs="video", icon="video"))
