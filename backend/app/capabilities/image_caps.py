"""Still-image generation capabilities: pixel presets, pixel universal, custom size, HD presets, general,
multi-view characters, UI sheets and asset cloning."""
from __future__ import annotations

from PIL import Image, ImageOps

from .. import db, storage
from ..pixel.pixelate import estimate_block_size, downsample_blocks, pixelate, trim, upscale
from ..pixel.split import split_grid
from . import Capability, Param, register
from . import templates as T
from .common import (generate, pack_preview, remove_bg, seed_of, shared_palette, size_for, split_sheet, to_pixel)

PROVIDER = Param("provider", "select", "生图模型", "auto",
                 choices=[{"value": "auto", "label": "自动 (本地优先)"}, {"value": "comfyui", "label": "本地 ComfyUI · Z-Image"},
                          {"value": "openai", "label": "GPT Image"}, {"value": "ark", "label": "Seedream"},
                          {"value": "minimax", "label": "MiniMax image-01"}, {"value": "mock", "label": "离线程序化"}])
SEED = Param("seed", "int", "种子 (-1 随机)", -1, advanced=True)
QUALITY = Param("quality", "select", "质量", "standard", choices=[{"value": "standard", "label": "普通"},
                                                                  {"value": "detailed", "label": "精细"},
                                                                  {"value": "ultimate", "label": "极致"}])
BG = Param("remove_bg", "select", "抠图档位", "auto", choices=[{"value": "auto", "label": "自动"},
                                                               {"value": "chroma", "label": "标准 (纯色键控)"},
                                                               {"value": "birefnet", "label": "高级 (BiRefNet)"},
                                                               {"value": "none", "label": "不抠图"}])


def _refs(params: dict, *keys: str) -> list[Image.Image]:
    out = []
    for k in keys:
        v = params.get(k)
        for aid in (v if isinstance(v, list) else [v] if v else []):
            out.append(storage.load_image(aid))
    return out


# ------------------------------------------------------------------ pixel preset
async def run_pixel_gen(ctx, p: dict) -> None:
    t = T.find(p["template"])
    seed = seed_of(p)
    prompt = T.sheet_prompt(p["prompt"], t, T.PIXEL_STYLE + (", " + p["style"] if p.get("style") else ""))
    if p.get("direction"):
        prompt += f" Facing direction: {p['direction']}."
    refs = _refs(p, "reference")
    if refs:
        prompt += " Match the character design / art style of the reference image."
    w, h = size_for("1:1" if t["layout"][0] == t["layout"][1] else "16:9" if t["layout"][0] > t["layout"][1] else "9:16")
    sheet = (await generate(ctx, prompt, width=w, height=h, seed=seed, refs=refs, quality=p["quality"],
                            layout=tuple(t["layout"])))[0]
    ctx.progress(0.55, "抠图 / 拆分素材")
    rgba = await remove_bg(ctx, sheet, "pixel", p["remove_bg"] if p["remove_bg"] != "none" else "auto")
    parts = split_sheet(rgba, t["count"], tuple(t["layout"]))
    colors = int(p.get("colors") or t["colors"])
    ctx.progress(0.75, "完美像素化 (网格检测 + 共享调色板)")
    # detect fake-pixel grid on the full sheet so every part shares the same pixel scale
    k, _, _ = estimate_block_size(sheet)
    palette = shared_palette(parts, colors)
    outs = []
    for i, part in enumerate(parts):
        img = to_pixel(part, t["w"], t["h"], colors=colors, palette=palette, anchor=t["anchor"],
                       outline=p.get("outline", False))
        outs.append(img)
    meta = {"pixel": True, "template": t["id"], "prompt": p["prompt"], "seed": seed, "palette": palette,
            "grid_detected": k}
    raw = ctx.save_image(sheet, f"原始生成 · {t['name']}", meta={**meta, "raw": True}, role="raw")
    for i, img in enumerate(outs):
        ctx.save_image(img, f"{t['name']} #{i + 1}", meta={**meta, "index": i}, parents=[raw["id"]])
    if len(outs) > 1:
        pack_preview(ctx, outs, f"{t['name']} 素材包", meta, [raw["id"]])


register(Capability(
    "pixel_gen", "像素模板生成", "pixel",
    "按模板生成像素素材包：精确尺寸、数量与风格，自动抠图、拆分、完美像素化并共享调色板保证整组一致。",
    [Param("template", "select", "模板", "px_char_64", choices=T.choices("pixel")),
     Param("prompt", "longtext", "描述整组素材", "", required=True,
           help="描述整组：主题、材质、需要放在一起的物件类别，而不是单个物件"),
     Param("reference", "image", "参考图 (可选)", None, help="角色/风格一致性参考"),
     Param("direction", "text", "朝向 (可选)", "", advanced=True),
     Param("style", "text", "额外风格", "", advanced=True),
     Param("colors", "int", "调色板颜色数 (0=模板默认)", 0, min=0, max=64, advanced=True),
     Param("outline", "bool", "加 1px 描边", False, advanced=True),
     BG, QUALITY, PROVIDER, SEED],
    run_pixel_gen, needs=["image", "bg"], aliases=["pixel-gen", "pixel_gen_template"], icon="grid",
    hint="模板决定素材包版式；最好描述整组素材。"))


# ------------------------------------------------------------------ pixel universal (万能生成)
async def run_pixel_universal(ctx, p: dict) -> None:
    seed = seed_of(p)
    view = "top-down overhead game view" if p["view"] == "top-down" else "game view"
    prompt = f"{p['prompt']}. {view}, pixel art, crisp pixels, limited palette, no text."
    w, h = size_for(p["aspect_ratio"])
    img = (await generate(ctx, prompt, width=w, height=h, seed=seed, refs=_refs(p, "reference"), quality=p["quality"]))[0]
    ctx.progress(0.6, "网格检测与像素化")
    target_long = int(p["pixel_size"])
    scale = target_long / max(img.width, img.height)
    tw, th = max(8, round(img.width * scale)), max(8, round(img.height * scale))
    k, ox, oy = estimate_block_size(img)
    base = downsample_blocks(img, k, ox, oy) if k >= 2 else img
    if p["remove_bg"] != "none":
        base = await remove_bg(ctx, base, "pixel", p["remove_bg"])
    out = pixelate(base, tw, th, colors=int(p["colors"]), detect_grid=False, trim_alpha=False)
    raw = ctx.save_image(img, "原始生成", meta={"raw": True, "prompt": p["prompt"]}, role="raw")
    ctx.save_image(out, p["prompt"][:24] or "像素图", meta={"pixel": True, "prompt": p["prompt"], "seed": seed,
                                                           "grid_detected": k}, parents=[raw["id"]])


register(Capability(
    "pixel_universal", "像素万能生成", "pixel",
    "自由画布的像素生成：场景、插画、建筑升级、HD 转像素再创作；支持俯视。尺寸由长边像素数决定。",
    [Param("prompt", "longtext", "描述", "", required=True),
     Param("aspect_ratio", "select", "画幅", "4:3", choices=["4:3", "3:4", "2:1", "1:2", "3:2", "2:3", "1:1", "16:9"]),
     Param("view", "select", "视角", "standard", choices=[{"value": "standard", "label": "标准"},
                                                         {"value": "top-down", "label": "俯视"}]),
     Param("pixel_size", "select", "长边像素", 256, choices=[128, 192, 256, 320, 384, 512]),
     Param("colors", "int", "颜色数", 32, min=4, max=64),
     Param("reference", "image", "参考图 (可选)", None),
     Param("remove_bg", "select", "抠图", "none", choices=["none", "auto", "chroma", "birefnet"]),
     QUALITY, PROVIDER, SEED],
    run_pixel_universal, needs=["image", "bg"], aliases=["pixel-universal-gen", "large_pixel_gen"], icon="image"))


# ------------------------------------------------------------------ custom size pixel (精确像素)
async def run_custom_size(ctx, p: dict) -> None:
    seed = seed_of(p)
    w, h = int(p["width"]), int(p["height"])
    aspect = "1:1" if abs(w - h) < min(w, h) * 0.25 else ("16:9" if w > h else "9:16")
    prompt = (f"A single game asset: {p['prompt']}. Fill the frame, centered, isolated on plain pure white background. "
              f"{T.PIXEL_STYLE}. Keep the design minimal, express details with simple color blocks.")
    refs = _refs(p, "reference")
    W, H = size_for(aspect)
    img = (await generate(ctx, prompt, width=W, height=H, seed=seed, refs=refs, quality=p["quality"]))[0]
    rgba = await remove_bg(ctx, img, "pixel", p["remove_bg"])
    out = to_pixel(trim(rgba), w, h, colors=int(p["colors"]), anchor=p["anchor"], outline=p["outline"],
                   padding=0 if p["fill"] else 1)
    raw = ctx.save_image(img, "原始生成", meta={"raw": True}, role="raw")
    ctx.save_image(out, f"{p['prompt'][:20]} {w}x{h}", meta={"pixel": True, "prompt": p["prompt"], "seed": seed},
                   parents=[raw["id"]])


register(Capability(
    "custom_size_pixel", "精确像素生成", "pixel",
    "单个物件，任意宽高的精确像素尺寸；也可把一张参考图重绘为指定尺寸像素画。",
    [Param("prompt", "longtext", "物件描述", "", required=True), Param("width", "int", "宽(px)", 48, min=8, max=512),
     Param("height", "int", "高(px)", 48, min=8, max=512), Param("colors", "int", "颜色数", 20, min=4, max=64),
     Param("anchor", "select", "对齐", "center", choices=["center", "bottom"]),
     Param("fill", "bool", "撑满画布", True), Param("outline", "bool", "1px 描边", False),
     Param("reference", "image", "参考图 (可选)", None), BG, QUALITY, PROVIDER, SEED],
    run_custom_size, needs=["image", "bg"], aliases=["custom-size-pixel-gen", "one_click_pixelate"], icon="ruler"))


# ------------------------------------------------------------------ HD presets
async def run_hd_gen(ctx, p: dict) -> None:
    t = T.find(p["template"])
    seed = seed_of(p)
    prompt = T.sheet_prompt(p["prompt"], t, T.HD_STYLE + (", " + p["style"] if p.get("style") else ""))
    refs = _refs(p, "reference")
    if refs:
        prompt += " Keep the identity and art style of the reference image."
    w, h = size_for("1:1", p["resolution"])
    sheet = (await generate(ctx, prompt, width=w, height=h, seed=seed, refs=refs, quality=p["quality"],
                            layout=tuple(t["layout"])))[0]
    raw = ctx.save_image(sheet, f"原始 · {t['name']}", meta={"raw": True, "prompt": p["prompt"]}, role="raw")
    if p["remove_bg"] == "none":
        parts = [sheet.convert("RGBA")] if t["count"] == 1 else split_grid(sheet.convert("RGBA"), *t["layout"])
    else:
        ctx.progress(0.55, "抠图 / 拆分")
        rgba = await remove_bg(ctx, sheet, "hd", p["remove_bg"])
        parts = split_sheet(rgba, t["count"], tuple(t["layout"]))
    meta = {"pixel": False, "template": t["id"], "prompt": p["prompt"], "seed": seed}
    for i, part in enumerate(parts):
        ctx.save_image(part, f"{t['name']} #{i + 1}", meta={**meta, "index": i}, parents=[raw["id"]])


register(Capability(
    "hd_gen", "高清模板生成", "hd",
    "高清角色 (2×2)、素材包 (4×4)、图标 (3×3)：自动抠图与组件拆分，可选参考图保持一致性。",
    [Param("template", "select", "模板", "hd_char_2x2", choices=T.choices("hd")),
     Param("prompt", "longtext", "描述整组素材", "", required=True), Param("reference", "image", "参考图 (可选)", None),
     Param("resolution", "select", "分辨率", "1K", choices=["1K", "2K"]), Param("style", "text", "额外风格", "", advanced=True),
     BG, QUALITY, PROVIDER, SEED],
    run_hd_gen, needs=["image", "bg"], aliases=["hd-gen"], icon="sparkles"))


# ------------------------------------------------------------------ general generation
async def run_general(ctx, p: dict) -> None:
    seed = seed_of(p)
    w, h = size_for(p["aspect_ratio"], p["resolution"])
    refs = _refs(p, "references")
    imgs = await generate(ctx, p["prompt"], width=w, height=h, n=int(p["count"]), seed=seed, refs=refs,
                          quality=p["quality"], transparent=p["remove_bg"] != "none")
    for i, img in enumerate(imgs):
        if p["remove_bg"] != "none":
            img = await remove_bg(ctx, img, "hd", p["remove_bg"])
        ctx.save_image(img, f"{p['prompt'][:20]} #{i + 1}", meta={"prompt": p["prompt"], "seed": seed + i,
                                                                   "pixel": False})


register(Capability(
    "general_image", "通用生成", "hd",
    "最自由的直连生图：提示词 + 可选参考图决定内容、风格、数量与构图（角色、UI、背景、九宫格道具都可）。",
    [Param("prompt", "longtext", "提示词", "", required=True, help="用简单自然语言描述，不要堆砌关键词"),
     Param("references", "images", "参考图 (可多张)", []),
     Param("aspect_ratio", "select", "画幅", "1:1", choices=["1:1", "3:4", "4:3", "9:16", "16:9", "21:9"]),
     Param("resolution", "select", "分辨率", "1K", choices=["1K", "2K"]),
     Param("count", "int", "张数", 1, min=1, max=4),
     Param("remove_bg", "select", "去背景", "none", choices=["none", "auto", "chroma", "birefnet"]),
     QUALITY, PROVIDER, SEED],
    run_general, needs=["image", "bg"], aliases=["general-image", "image-2.5", "nano-banana"], icon="wand"))


# ------------------------------------------------------------------ multi-view character
DIRS5 = ["S", "SE", "E", "NE", "N"]
DIR_NAMES = {"S": "正面", "SE": "右前", "E": "右侧", "NE": "右后", "N": "背面", "SW": "左前", "W": "左侧", "NW": "左后"}


async def run_multi_view(ctx, p: dict) -> None:
    seed = seed_of(p)
    pixel = p["mode"] == "pixel"
    src = storage.load_image(p["source"]) if p.get("source") else None
    desc = p.get("prompt") or "the character in the reference image"
    style = T.PIXEL_STYLE if pixel else T.HD_STYLE
    prompt = (f"Character turnaround sheet of {desc}. The SAME character shown 5 times in a single row, left to right: "
              f"front view, front three-quarter view facing right, right side profile view, back three-quarter view "
              f"facing right, back view. Full body, identical proportions, outfit and colors in every view, evenly "
              f"spaced, not touching, plain pure white background. {p.get('extra') or ''} {style}")
    prov = ctx.provider("image")
    if src is not None and not prov.supports_refs:
        # img2img fallback: tile the source 5× and let the model re-pose each copy
        cell = ImageOps.contain(src.convert("RGBA"), (300, 600))
        canvas = Image.new("RGBA", (1600, 640), (255, 255, 255, 255))
        for i in range(5):
            canvas.alpha_composite(cell, (i * 320 + (320 - cell.width) // 2, 640 - cell.height - 20))
        sheet = (await prov.edit(canvas, prompt, strength=0.72, seed=seed, width=1600, height=640, ctx=ctx))[0]
    else:
        sheet = (await generate(ctx, prompt, width=1536, height=640, seed=seed, refs=[src] if src else None,
                                quality=p["quality"], layout=(5, 1)))[0]
    raw = ctx.save_image(sheet, "转面原图", meta={"raw": True}, role="raw")
    ctx.progress(0.6, "拆分五视图并镜像补全八方向")
    rgba = await remove_bg(ctx, sheet, p["mode"], "auto")
    parts = split_sheet(rgba, 5, (5, 1))
    while len(parts) < 5:
        parts.append(parts[-1] if parts else rgba)
    views = dict(zip(DIRS5, parts[:5]))
    views["SW"] = ImageOps.mirror(views["SE"])
    views["W"] = ImageOps.mirror(views["E"])
    views["NW"] = ImageOps.mirror(views["NE"])
    order = ["S", "SE", "E", "NE", "N", "NW", "W", "SW"]
    size = int(p["size"])
    outs = []
    if pixel:
        palette = shared_palette(parts, 24)
        # normalise scale: same height for every view
        for d in order:
            outs.append(to_pixel(views[d], size, size, colors=24, palette=palette, anchor="bottom"))
    else:
        for d in order:
            outs.append(ImageOps.pad(trim(views[d]), (size * 4, size * 4), color=(0, 0, 0, 0), centering=(0.5, 1.0)))
    for d, img in zip(order, outs):
        ctx.save_image(img, f"{DIR_NAMES[d]} ({d})", meta={"direction": d, "pixel": pixel, "seed": seed,
                                                           "mirrored": d in ("SW", "W", "NW")}, parents=[raw["id"]])
    pack_preview(ctx, outs, "八方向角色表", {"directions": order, "pixel": pixel}, [raw["id"]])


register(Capability(
    "character_multi_view", "多方向角色", "character",
    "从描述或已有角色图生成 8 方向角色表（5 视图生成 + 左右镜像）。需要严格一致可走 3D 管线渲染 8 方向。",
    [Param("source", "image", "角色图 (可选)", None), Param("prompt", "longtext", "角色描述", ""),
     Param("mode", "select", "风格", "pixel", choices=[{"value": "pixel", "label": "像素"}, {"value": "hd", "label": "高清"}]),
     Param("size", "select", "单格尺寸(px)", 64, choices=[32, 48, 64, 96, 128]),
     Param("extra", "text", "动作/姿态约束", "", advanced=True), QUALITY, PROVIDER, SEED],
    run_multi_view, needs=["image", "bg"], aliases=["character-multi-view"], icon="rotate"))


# ------------------------------------------------------------------ UI sheet
async def run_ui_gen(ctx, p: dict) -> None:
    from ..pixel.split import split_components
    seed = seed_of(p)
    pixel = p["mode"] == "pixel"
    prompt = (f"Game UI kit sprite sheet: {p['prompt']}. Separate UI elements (buttons, panels, frames, bars, icons) "
              f"laid out on a grid with clear empty space between every element, flat front view, plain pure white "
              f"background, no mockup, no text labels. {T.PIXEL_STYLE if pixel else T.HD_STYLE}")
    w, h = size_for(p["aspect_ratio"], p["resolution"])
    sheet = (await generate(ctx, prompt, width=w, height=h, seed=seed, refs=_refs(p, "reference"), quality=p["quality"],
                            layout=(3, 3)))[0]
    ctx.progress(0.55, "抠图并识别组件")
    rgba = await remove_bg(ctx, sheet, p["mode"], p["remove_bg"])
    if pixel:
        k, ox, oy = estimate_block_size(sheet)
        if k >= 2:
            rgba = downsample_blocks(rgba, k, ox, oy)
            rgba = pixelate(rgba, colors=32, detect_grid=False, trim_alpha=False)
    agg = ctx.save_image(rgba, f"UI 图集 · {p['prompt'][:16]}", meta={"pixel": pixel, "prompt": p["prompt"], "seed": seed})
    parts = split_components(rgba, min_area=max(16, rgba.width * rgba.height // 3000),
                             merge_distance=2 if pixel else max(4, rgba.width // 128))
    comps = []
    for i, (img, box) in enumerate(parts):
        comps.append({"index": i, "box": box})
        ctx.save_image(img, f"UI 组件 #{i + 1}", meta={"box": box, "pixel": pixel}, parents=[agg["id"]])
    db.update("assets", agg["id"], {"meta": {**agg["meta"], "components": comps}})


register(Capability(
    "ui_gen", "游戏 UI", "ui",
    "生成 HUD / 菜单 / 按钮 / 图标图集，自动去背景 + 组件分割，返回图集与每个组件。",
    [Param("prompt", "longtext", "UI 描述", "", required=True),
     Param("mode", "select", "风格", "hd", choices=[{"value": "hd", "label": "高清"}, {"value": "pixel", "label": "像素"}]),
     Param("aspect_ratio", "select", "画幅", "1:1", choices=["1:1", "4:3", "16:9"]),
     Param("resolution", "select", "分辨率", "1K", choices=["1K", "2K"]), Param("reference", "image", "风格参考", None),
     BG, QUALITY, PROVIDER, SEED],
    run_ui_gen, needs=["image", "bg"], aliases=["ui-gen", "general_ui_gen", "ui-agent"], outputs="images", icon="layout"))


# ------------------------------------------------------------------ asset clone
async def run_asset_clone(ctx, p: dict) -> None:
    seed = seed_of(p)
    n = int(p["clone_count"])
    side = int(n ** 0.5)
    ref = storage.load_image(p["reference"])
    pixel = p["mode"] == "pixel"
    prompt = p.get("prompt") or (f"Create {n} new game assets in exactly the same art style, palette, outline weight, "
                                 f"scale and rendering as the reference, arranged in a {side} by {side} grid, each "
                                 f"isolated on plain pure white background with empty space between them.")
    sheet = (await generate(ctx, prompt, width=1024, height=1024, seed=seed, refs=[ref], quality=p["quality"],
                            layout=(side, side)))[0]
    raw = ctx.save_image(sheet, f"克隆图集 ×{n}", meta={"raw": True, "prompt": prompt}, role="raw")
    rgba = await remove_bg(ctx, sheet, p["mode"], p["remove_bg"])
    parts = split_sheet(rgba, n, (side, side))
    if pixel:
        src_asset = db.get("assets", p["reference"]) or {"width": 64, "height": 64}
        w, h = (src_asset["width"], src_asset["height"]) if src_asset["width"] <= 256 else (64, 64)
        palette = shared_palette([ref, *parts], 24)
        parts = [to_pixel(x, w, h, colors=24, palette=palette) for x in parts]
    for i, part in enumerate(parts):
        ctx.save_image(part, f"克隆 #{i + 1}", meta={"pixel": pixel, "index": i}, parents=[raw["id"], p["reference"]])


register(Capability(
    "asset_clone", "素材克隆", "edit",
    "以一张参考素材为风格，克隆 1/4/9/16/25/36 个同风格新素材（网格），像素模式会锁定参考调色板。",
    [Param("reference", "image", "参考素材", None, required=True),
     Param("clone_count", "select", "数量", 4, choices=[1, 4, 9, 16, 25, 36]),
     Param("prompt", "longtext", "完整提示词 (可选，留空用内置)", ""),
     Param("mode", "select", "模式", "pixel", choices=["pixel", "hd"]), BG, QUALITY, PROVIDER, SEED],
    run_asset_clone, needs=["image", "bg"], aliases=["asset-clone"], icon="copy"))
