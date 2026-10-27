"""Editing & post-processing: background removal, pixelate, universal edit, one-click variants, split, palette swap."""
from __future__ import annotations

import numpy as np
from PIL import Image

from .. import db, storage
from ..pixel.pixelate import extract_palette, pixelate, quantize
from ..pixel.split import split_components
from . import Capability, Param, register
from .common import remove_bg, seed_of, shared_palette
from .image_caps import PROVIDER, SEED


def _src_meta(aid: str) -> dict:
    a = db.get("assets", aid) or {}
    return {"pixel": bool((a.get("meta") or {}).get("pixel")), "width": a.get("width", 0), "height": a.get("height", 0),
            "kind": a.get("kind")}


# ------------------------------------------------------------------ remove background
async def run_remove_bg(ctx, p: dict) -> None:
    src = db.get("assets", p["source"])
    if src and src["kind"] == "animation":
        from .common import save_animation
        frames = storage.load_frames(p["source"])
        out = [await remove_bg(ctx, f, p["mode"], p["method"], p.get("color") or None, p["preserve_translucency"])
               for f in frames]
        m = src["meta"]
        save_animation(ctx, out, name=f"{src['name']} · 去背景", fps=m.get("fps", 8), loop=m.get("loop", True),
                       meta={"bg_removed": True}, parents=[src["id"]], pixel=p["mode"] == "pixel")
        return
    img = storage.load_image(p["source"])
    out = await remove_bg(ctx, img, p["mode"], p["method"], p.get("color") or None, p["preserve_translucency"])
    ctx.save_image(out, f"{(src or {}).get('name', '素材')} · 去背景",
                   meta={"pixel": p["mode"] == "pixel", "bg_removed": True})


register(Capability(
    "remove_background", "去背景", "edit",
    "静态图或动画逐帧去背景。标准=纯色键控+洪水填充(精确、零显存)；高级=BiRefNet 神经抠图(复杂背景)。",
    [Param("source", "image", "图片/动画", None, required=True),
     Param("mode", "select", "模式", "hd", choices=[{"value": "hd", "label": "高清 (保留软边)"},
                                                   {"value": "pixel", "label": "像素 (二值 alpha)"}]),
     Param("method", "select", "档位", "auto", choices=[{"value": "auto", "label": "自动"},
                                                       {"value": "chroma", "label": "标准"},
                                                       {"value": "birefnet", "label": "高级 BiRefNet"}]),
     Param("color", "color", "背景色 (留空自动)", ""),
     Param("preserve_translucency", "bool", "保留半透明", False, advanced=True)],
    run_remove_bg, needs=["bg"], aliases=["remove-background"], icon="eraser"))


# ------------------------------------------------------------------ pixelate
async def run_pixelate(ctx, p: dict) -> None:
    img = storage.load_image(p["source"])
    palette = None
    if p.get("palette_from"):
        palette = extract_palette(storage.load_image(p["palette_from"]), int(p["colors"]))
    w, h = int(p["width"]), int(p["height"])
    if p["keep_ratio"]:
        s = min(w / img.width, h / img.height)
        w, h = max(4, round(img.width * s)), max(4, round(img.height * s))
    out = pixelate(img, w, h, colors=int(p["colors"]), palette=palette, outline=p["outline"],
                   detect_grid=p["detect_grid"], dither=p["dither"], trim_alpha=False)
    ctx.save_image(out, f"像素化 {w}x{h}", meta={"pixel": True, "palette": extract_palette(out, int(p["colors"]))})


register(Capability(
    "pixelate", "像素化", "edit",
    "把任意图转为干净像素画：自动检测“伪像素”网格并按块中值还原、调色板量化、孤立像素清理，可锁定参考调色板。",
    [Param("source", "image", "源图", None, required=True), Param("width", "int", "宽", 64, min=8, max=1024),
     Param("height", "int", "高", 64, min=8, max=1024), Param("keep_ratio", "bool", "保持比例", True),
     Param("colors", "int", "颜色数", 24, min=2, max=128), Param("detect_grid", "bool", "伪像素网格检测", True),
     Param("palette_from", "image", "锁定调色板来源 (可选)", None), Param("outline", "bool", "描边", False),
     Param("dither", "bool", "抖动", False, advanced=True)],
    run_pixelate, needs=[], aliases=["pixelate-run"], icon="grid"))


# ------------------------------------------------------------------ universal image edit
async def run_image_edit(ctx, p: dict) -> None:
    src_info = _src_meta(p["source"])
    img = storage.load_image(p["source"])
    mask = storage.load_image(p["mask"]) if p.get("mask") else None
    refs = [storage.load_image(a) for a in p.get("references") or []]
    prov = ctx.provider("image_edit")
    ctx.progress(0.1, f"{prov.label} 编辑中…")
    pixel = src_info["pixel"] or p["mode"] == "pixel"
    work = img
    if pixel and max(img.size) < 512:
        k = max(1, 1024 // max(img.size))
        work = img.resize((img.width * k, img.height * k), Image.Resampling.NEAREST)
        if mask is not None:
            mask = mask.resize(work.size, Image.Resampling.NEAREST)
    flat = Image.new("RGBA", work.size, (255, 255, 255, 255))
    flat.alpha_composite(work.convert("RGBA"))
    outs = await prov.edit(flat, p["prompt"], refs=refs, mask=mask, strength=float(p["strength"]),
                           seed=seed_of(p), ctx=ctx)
    for i, o in enumerate(outs):
        if img.mode == "RGBA" and np.asarray(img.getchannel("A")).min() < 250:
            o = await remove_bg(ctx, o, "pixel" if pixel else "hd", "auto")
        if pixel:
            palette = extract_palette(img, 32) if p["keep_palette"] else None
            o = pixelate(o, img.width, img.height, colors=32, palette=palette, detect_grid=True)
        ctx.save_image(o, f"编辑 · {p['prompt'][:16]}", meta={"pixel": pixel, "prompt": p["prompt"]})


register(Capability(
    "image_edit", "万能编辑", "edit",
    "用一句话修改图片（换色、加装备、改表情…），可加遮罩局部重绘与多张参考；像素图自动放大编辑再还原尺寸与调色板。",
    [Param("source", "image", "源图", None, required=True), Param("prompt", "longtext", "修改要求", "", required=True),
     Param("mask", "image", "遮罩 (白=修改区域，可选)", None), Param("references", "images", "参考图", []),
     Param("mode", "select", "模式", "auto", choices=["auto", "pixel", "hd"]),
     Param("strength", "float", "重绘强度 (本地 img2img)", 0.6, min=0.1, max=1.0),
     Param("keep_palette", "bool", "像素：锁定原调色板", True), PROVIDER, SEED],
    run_image_edit, needs=["image_edit", "bg"], aliases=["image-edit"], icon="pencil"))


# ------------------------------------------------------------------ one-click upgrade / variants
async def run_variants(ctx, p: dict) -> None:
    src_info = _src_meta(p["source"])
    img = storage.load_image(p["source"])
    prompts = p["prompts"] or [f"variant {i + 1}" for i in range(3)]
    prov = ctx.provider("image_edit")
    pixel = src_info["pixel"]
    k = max(1, 1024 // max(img.size)) if pixel else 1
    work = img.resize((img.width * k, img.height * k), Image.Resampling.NEAREST) if k > 1 else img
    flat = Image.new("RGBA", work.size, (255, 255, 255, 255))
    flat.alpha_composite(work.convert("RGBA"))
    palette = extract_palette(img, 32) if pixel else None
    for i, line in enumerate(prompts):
        ctx.progress(0.1 + 0.8 * i / len(prompts), f"变体 {i + 1}/{len(prompts)}: {line[:20]}")
        prompt = (f"Keep the same object, framing, size, camera angle, outline and art style. Only change: {line}. "
                  f"Plain white background.")
        out = (await prov.edit(flat, prompt, strength=float(p["strength"]), seed=seed_of(p) + i, ctx=ctx))[0]
        out = await remove_bg(ctx, out, "pixel" if pixel else "hd", "auto")
        if pixel:
            out = pixelate(out, img.width, img.height, colors=32, palette=palette if p["lock_palette"] else None)
        ctx.save_image(out, f"变体 {i + 1} · {line[:14]}", meta={"pixel": pixel, "variant_prompt": line, "level": i + 1})


register(Capability(
    "asset_variants", "一键升级 / 变体", "edit",
    "同一素材生成多级升级或多个同尺寸同风格变体（每行一个改动），保持构图、尺寸与锚点一致。",
    [Param("source", "image", "源素材", None, required=True),
     Param("prompts", "lines", "每行一个改动", ["铁质版本", "黄金镶嵌版本", "传说级发光版本"]),
     Param("strength", "float", "改动强度 (本地)", 0.55, min=0.1, max=1.0),
     Param("lock_palette", "bool", "像素：锁定调色板", False), PROVIDER, SEED],
    run_variants, needs=["image_edit", "bg"], aliases=["one-click-upgrade", "one_click_upgrade"], icon="layers"))


# ------------------------------------------------------------------ split components
async def run_split(ctx, p: dict) -> None:
    img = storage.load_image(p["source"])
    if np.asarray(img.getchannel("A")).min() >= 250:
        img = await remove_bg(ctx, img, "hd", "chroma")
    parts = split_components(img, min_area=int(p["min_area"]), merge_distance=int(p["merge_distance"]))
    for i, (part, box) in enumerate(parts):
        ctx.save_image(part, f"组件 #{i + 1}", meta={"box": box, "pixel": _src_meta(p["source"])["pixel"]})


register(Capability(
    "split_components", "拆分组件", "edit",
    "把一张图集里互不相连的图案拆成独立透明 PNG（记录原始位置），本地零成本。",
    [Param("source", "image", "图集", None, required=True), Param("min_area", "int", "最小面积(px²)", 24, min=1),
     Param("merge_distance", "int", "合并距离(px)", 2, min=0, max=32)],
    run_split, needs=[], aliases=["split-components"], icon="scissors"))


# ------------------------------------------------------------------ palette swap (recolor)
async def run_palette_swap(ctx, p: dict) -> None:
    img = storage.load_image(p["source"])
    target = storage.load_image(p["palette_from"])
    n = int(p["colors"])
    src_pal = extract_palette(img, n)
    dst_pal = extract_palette(target, n)

    def lum(c):
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

    src_sorted = sorted(src_pal, key=lum)
    dst_sorted = sorted(dst_pal, key=lum)
    mapping = {s: dst_sorted[min(len(dst_sorted) - 1, int(i * len(dst_sorted) / len(src_sorted)))]
               for i, s in enumerate(src_sorted)}
    q = quantize(img, palette=src_pal)
    arr = np.asarray(q).copy()
    for s, d in mapping.items():
        m = (arr[..., 0] == s[0]) & (arr[..., 1] == s[1]) & (arr[..., 2] == s[2]) & (arr[..., 3] > 0)
        arr[m, :3] = d
    ctx.save_image(Image.fromarray(arr, "RGBA"), "换色", meta={"pixel": True, "palette": dst_sorted})


register(Capability(
    "palette_swap", "调色板换色", "edit",
    "按亮度映射把素材换成另一张图的调色板，用于批量做皮肤 / 阵营色 / 季节色。",
    [Param("source", "image", "源素材", None, required=True), Param("palette_from", "image", "目标调色板来源", None, required=True),
     Param("colors", "int", "颜色数", 16, min=2, max=64)],
    run_palette_swap, needs=[], icon="palette"))
