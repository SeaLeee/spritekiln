"""3D pipeline: (text →) concept / multi-view sheet → background removal → Pixal3D GLB → (browser) 8-direction
renders → pixelated directional sprites with one shared palette."""
from __future__ import annotations

import shutil

from PIL import Image, ImageOps

from .. import db, storage
from ..pixel.pixelate import has_alpha, trim
from . import Capability, Param, register
from .common import generate, pack_preview, remove_bg, seed_of, shared_palette, split_sheet, to_pixel
from .image_caps import PROVIDER, SEED

THREED = Param("threed_provider", "select", "3D 引擎", "auto",
               choices=[{"value": "auto", "label": "自动"}, {"value": "pixal3d", "label": "Pixal3D 本地 (PBR)"},
                        {"value": "mock", "label": "Billboard (测试)"}])
CONCEPT = ("Single 3D-ready game asset concept: {x}. Full object visible, front three-quarter view, neutral A-pose for "
           "characters, even soft studio lighting, no cast shadow, centered, isolated on plain pure white background, "
           "clean readable shapes.")


async def _to_3d(ctx, img: Image.Image, seed: int, quality: str, name: str, parents: list[str]) -> dict:
    prov = ctx.provider("threed")
    ctx.progress(0.35, f"{prov.label} 重建中（3090 低显存模式，约 4-8 分钟）")
    aid = db.new_id("ast")
    work = storage.project_dir(ctx.project_id) / aid
    glb = await prov.image_to_3d(img, work, seed=seed, quality=quality, ctx=ctx)
    final = storage.project_dir(ctx.project_id) / f"{aid}.glb"
    shutil.move(str(glb), final)
    preview = work / "input.png"
    meta = {"engine": prov.name, "seed": seed, "files": {"input": storage.rel(preview)} if preview.exists() else {},
            "size_mb": round(final.stat().st_size / 1024 / 1024, 2)}
    asset = storage.create_asset(ctx.project_id, kind="model3d", name=name, path=final, meta=meta, parents=parents,
                                 job_id=ctx.id, capability=ctx.job["capability"])
    return ctx.register(asset)


async def run_image_to_3d(ctx, p: dict) -> None:
    seed = seed_of(p)
    parents = []
    if p.get("source"):
        img = storage.load_image(p["source"])
        parents = [p["source"]]
    else:
        if not p.get("prompt"):
            raise ValueError("需要源图或描述")
        img = (await generate(ctx, CONCEPT.format(x=p["prompt"]), width=1024, height=1024, seed=seed, quality="detailed"))[0]
        concept = ctx.save_image(img, "3D 概念图", meta={"prompt": p["prompt"]})
        parents = [concept["id"]]
    if not has_alpha(img):
        img = await remove_bg(ctx, img, "hd", "auto")
    img = ImageOps.pad(trim(img), (1024, 1024), color=(0, 0, 0, 0))
    await _to_3d(ctx, img, seed, p["quality"], f"3D · {(p.get('prompt') or '模型')[:16]}", parents)


register(Capability(
    "image_to_3d", "单图转 3D", "threed",
    "图片或文字 → (概念图) → 抠图居中 → Pixal3D 生成带 PBR 贴图的 GLB。3090 采用 low-VRAM 分阶段加载 + SDPA。",
    [Param("source", "image", "源图 (可选)", None), Param("prompt", "longtext", "或文字描述", ""),
     Param("quality", "select", "精度", "standard", choices=[{"value": "standard", "label": "1024 (推荐 3090)"},
                                                            {"value": "ultimate", "label": "1536 (需关闭低显存)"}]),
     THREED, PROVIDER, SEED],
    run_image_to_3d, needs=["image", "threed", "bg"], aliases=["image-to-3d"], outputs="model3d", icon="cube"))


async def run_multiview_3d(ctx, p: dict) -> None:
    seed = seed_of(p)
    src = storage.load_image(p["source"]) if p.get("source") else None
    desc = p.get("prompt") or "the object in the reference image"
    prompt = (f"Orthographic multi-view reference sheet of {desc}: exactly 4 views in one row — front, right side, "
              f"back, left side. Same scale and identical design in every view, A-pose for characters, even lighting, "
              f"plain pure white background, evenly spaced, not touching.")
    sheet = (await generate(ctx, prompt, width=1536, height=640, seed=seed, refs=[src] if src else None, layout=(4, 1),
                            quality="detailed"))[0]
    raw = ctx.save_image(sheet, "多视角参考表", meta={"raw": True, "prompt": desc}, role="raw")
    rgba = await remove_bg(ctx, sheet, "hd", "auto")
    views = split_sheet(rgba, 4, (4, 1))
    names = ["front", "right", "back", "left"]
    view_ids = []
    for n, v in zip(names, views):
        view_ids.append(ctx.save_image(v, f"视图 · {n}", meta={"view": n}, parents=[raw["id"]])["id"])
    front = src if src is not None else views[0]
    if not has_alpha(front):
        front = await remove_bg(ctx, front, "hd", "auto")
    front = ImageOps.pad(trim(front), (1024, 1024), color=(0, 0, 0, 0))
    await _to_3d(ctx, front, seed, p["quality"], f"3D · {desc[:16]}", [raw["id"], *view_ids[:1]])


register(Capability(
    "multiview_3d", "多视角 → 3D", "threed",
    "先生成 4 视图一致参考表（正/右/背/左，用于审稿与贴图校对），再以正视图驱动 Pixal3D 重建；"
    "可替换为多图输入引擎（TRELLIS.2 / Hunyuan3D-2mv）。",
    [Param("source", "image", "参考图 (可选)", None), Param("prompt", "longtext", "描述", ""),
     Param("quality", "select", "精度", "standard", choices=["standard", "ultimate"]), THREED, PROVIDER, SEED],
    run_multiview_3d, needs=["image", "threed", "bg"], aliases=["multiview-3d"], outputs="model3d", icon="cubes"))


DIR8 = ["S", "SE", "E", "NE", "N", "NW", "W", "SW"]


async def run_render_sprites(ctx, p: dict) -> None:
    renders = [storage.load_image(a) for a in p["renders"]]
    pixel = p["mode"] == "pixel"
    size = int(p["size"])
    dirs = p.get("directions") or DIR8[: len(renders)]
    parts = [trim(r) for r in renders]
    # common scale so the character keeps one height across directions
    max_h = max(x.height for x in parts)
    max_w = max(x.width for x in parts)
    s = min((size - 2) / max_h, (size - 2) / max_w)
    outs = []
    palette = shared_palette(parts, int(p["colors"])) if pixel else None
    for x in parts:
        scaled = x.resize((max(1, round(x.width * s)), max(1, round(x.height * s))), Image.Resampling.LANCZOS)
        if pixel:
            outs.append(to_pixel(scaled, size, size, colors=int(p["colors"]), palette=palette, anchor="bottom",
                                 outline=p["outline"], padding=0))
        else:
            c = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            c.alpha_composite(scaled, ((size - scaled.width) // 2, size - scaled.height))
            outs.append(c)
    parents = [p["model"]] if p.get("model") else []
    for d, img in zip(dirs, outs):
        ctx.save_image(img, f"方向 {d}", meta={"direction": d, "pixel": pixel, "from_3d": True}, parents=parents)
    pack_preview(ctx, outs, "3D → 8 方向精灵表", {"directions": dirs, "pixel": pixel, "from_3d": True}, parents)


register(Capability(
    "render_sprites", "3D 渲染 → 方向精灵", "threed",
    "把 3D 模型在浏览器中按 8 个方向渲染的截图统一尺度、锁定共享调色板并像素化，得到严格一致的多方向精灵。",
    [Param("renders", "images", "渲染图 (按方向顺序)", [], required=True), Param("model", "image", "来源模型", None),
     Param("directions", "lines", "方向标签", DIR8), Param("mode", "select", "风格", "pixel", choices=["pixel", "hd"]),
     Param("size", "select", "尺寸", 64, choices=[32, 48, 64, 96, 128, 256]),
     Param("colors", "int", "颜色数", 24, min=4, max=64), Param("outline", "bool", "描边", True)],
    run_render_sprites, needs=[], aliases=["3d-to-sprites"], icon="rotate"))
