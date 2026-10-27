"""Map capabilities: seamless textures, dual-grid tilesets, isometric tiles, side-scrolling parallax layers, self-loop."""
from __future__ import annotations

from PIL import Image

from .. import storage
from ..pixel import tiles
from ..pixel.pixelate import pixelate
from . import Capability, Param, register
from .common import generate, remove_bg, seed_of, write_json
from .image_caps import PROVIDER, QUALITY, SEED

TEXTURE_PROMPT = ("Seamless tileable top-down texture of {x}. Flat orthographic view straight from above, evenly "
                  "distributed detail, no objects, no perspective, no shadows, uniform lighting, fills the whole frame.")


async def _texture(ctx, prompt: str, *, pixel: bool, size: int, colors: int, seed: int, quality: str) -> Image.Image:
    img = (await generate(ctx, TEXTURE_PROMPT.format(x=prompt) + (" pixel art, limited palette." if pixel else ""),
                          width=1024, height=1024, seed=seed, quality=quality))[0]
    w, h = img.size
    crop = img.crop((w * 0.15, h * 0.15, w * 0.85, h * 0.85)).resize((max(size * 4, 256),) * 2, Image.Resampling.LANCZOS)
    seamless = tiles.make_seamless(crop)
    if pixel:
        return pixelate(seamless, size, size, colors=colors, detect_grid=False, trim_alpha=False)
    return seamless.resize((size, size), Image.Resampling.LANCZOS)


async def run_texture(ctx, p: dict) -> None:
    pixel = p["mode"] == "pixel"
    tex = await _texture(ctx, p["prompt"], pixel=pixel, size=int(p["size"]), colors=int(p["colors"]), seed=seed_of(p),
                         quality=p["quality"])
    # re-wrap after quantisation so edges stay continuous
    a = ctx.save_image(tex, f"纹理 · {p['prompt'][:16]}", meta={"pixel": pixel, "seamless": True, "texture": True})
    prev = tiles.tile_preview(tex, 3, 3)
    ctx.save_image(prev, "3×3 平铺预览", meta={"pixel": pixel, "preview": True}, parents=[a["id"]], role="preview")


register(Capability(
    "texture_gen", "无缝纹理", "map",
    "生成可平铺的地表/材质纹理（错位融合消缝），像素模式输出 16/32/64px 有限色纹理并附 3×3 平铺预览。",
    [Param("prompt", "text", "材质", "grass with small flowers", required=True),
     Param("mode", "select", "风格", "pixel", choices=["pixel", "hd"]),
     Param("size", "select", "尺寸", 64, choices=[16, 32, 64, 128, 256, 512]),
     Param("colors", "int", "颜色数(像素)", 12, min=2, max=64), QUALITY, PROVIDER, SEED],
    run_texture, needs=["image"], aliases=["texture-gen", "texture_gen_run"], icon="square"))


async def run_tileset(ctx, p: dict) -> None:
    size = int(p["tile_size"])
    pixel = p["mode"] == "pixel"
    seed = seed_of(p)

    async def get_tex(asset_key: str, prompt_key: str) -> Image.Image | None:
        if p.get(asset_key):
            return storage.load_image(p[asset_key])
        if p.get(prompt_key):
            return await _texture(ctx, p[prompt_key], pixel=pixel, size=size, colors=12, seed=seed, quality=p["quality"])
        return None

    fg = await get_tex("foreground", "foreground_prompt")
    if fg is None:
        raise ValueError("需要前景纹理（素材或描述）")
    bg = await get_tex("background", "background_prompt")
    ctx.progress(0.8, "生成 16 格角点地块图集")
    atlas, mapping = tiles.dual_grid_tileset(fg, bg, size, seed=seed % 10_000, roughness=float(p["roughness"]))
    a = ctx.save_image(atlas, f"地块图集 {size}px", meta={"pixel": pixel, "tileset": True, "tile_size": size,
                                                         "mapping": mapping, "layout": "dual-grid-4x4",
                                                         "bit_order": "TL=1,TR=2,BL=4,BR=8"})
    # demo map using the atlas
    import random
    rnd = random.Random(seed)
    W, H = 10, 7
    corners = [[1 if (rnd.random() < 0.55 and 1 < x < W and 1 < y < H) else 0 for x in range(W + 1)] for y in range(H + 1)]
    demo = Image.new("RGBA", (W * size, H * size))
    for y in range(H):
        for x in range(W):
            idx = corners[y][x] * 1 + corners[y][x + 1] * 2 + corners[y + 1][x] * 4 + corners[y + 1][x + 1] * 8
            r, c = divmod(idx, 4)
            demo.paste(atlas.crop((c * size, r * size, (c + 1) * size, (r + 1) * size)), (x * size, y * size))
    ctx.save_image(demo, "地块拼接示例", meta={"pixel": pixel, "preview": True}, parents=[a["id"]], role="preview")
    path = storage.project_dir(ctx.project_id) / f"{a['id']}_mapping.json"
    write_json(path, {"tile_size": size, "layout": "dual-grid 4x4", "tiles": mapping})


register(Capability(
    "tileset_gen", "地形地块 (Dual-Grid)", "map",
    "用前景/背景两种纹理生成 16 格角点(Marching Squares/Dual-Grid)地形图集 + 映射表 + 拼接示例，可直接用于 Godot TileMap。",
    [Param("foreground", "image", "前景纹理素材", None), Param("foreground_prompt", "text", "或前景描述", "lush grass"),
     Param("background", "image", "背景纹理素材", None), Param("background_prompt", "text", "或背景描述", "brown dirt"),
     Param("tile_size", "select", "格子尺寸", 32, choices=[16, 32, 48, 64]),
     Param("roughness", "float", "边缘起伏", 0.22, min=0, max=0.5),
     Param("mode", "select", "风格", "pixel", choices=["pixel", "hd"]), QUALITY, PROVIDER, SEED],
    run_tileset, needs=["image"], aliases=["tileset-gen"], icon="grid"))


async def run_isometric(ctx, p: dict) -> None:
    pixel = p["mode"] == "pixel"
    if p.get("texture"):
        tex = storage.load_image(p["texture"])
    else:
        tex = await _texture(ctx, p["prompt"] or "stone floor", pixel=pixel, size=64, colors=12, seed=seed_of(p),
                             quality=p["quality"])
    side = storage.load_image(p["side_texture"]) if p.get("side_texture") else None
    w = int(p["width"])
    tile = tiles.isometric_tile(tex, w, int(p["block_height"]), side)
    a = ctx.save_image(tile, f"等角地块 {w}px", meta={"pixel": pixel, "isometric": True, "diamond": [w, w // 2],
                                                   "block_height": int(p["block_height"]),
                                                   "neighbor_offsets": [[w // 2, w // 4], [-w // 2, w // 4]]})
    ctx.save_image(tiles.isometric_preview(tile, 4, w), "等角拼接预览", meta={"preview": True}, parents=[a["id"]],
                   role="preview")


register(Capability(
    "isometric_tile", "等角地块", "map",
    "把纹理投影为 2:1 等角菱形（默认 128×64，邻格偏移 (64,32)），可挤出为方块，附 4×4 拼接预览。",
    [Param("texture", "image", "顶面纹理 (可选)", None), Param("prompt", "text", "或材质描述", "mossy stone"),
     Param("side_texture", "image", "侧面纹理 (可选)", None),
     Param("width", "select", "菱形宽", 128, choices=[32, 64, 128, 256]),
     Param("block_height", "int", "方块高度(0=平面)", 32, min=0, max=256),
     Param("mode", "select", "风格", "pixel", choices=["pixel", "hd"]), QUALITY, PROVIDER, SEED],
    run_isometric, needs=["image"], aliases=["isometric-gen", "isometric-texture"], icon="box"))


async def run_side_scroll(ctx, p: dict) -> None:
    pixel = p["mode"] == "pixel"
    seed = seed_of(p)
    theme = p["prompt"]
    style = "pixel art, limited palette" if pixel else "painterly 2D game art"
    layers = [
        ("background", f"Distant background layer for a side-scrolling game: {theme}. Sky and far scenery only, wide "
                       f"panorama, no characters, {style}.", False),
        ("midground", f"Midground layer for a side-scrolling game: {theme}. Silhouettes of mid-distance scenery "
                      f"(trees, buildings, hills) along the bottom, top area empty plain white background, {style}.", True),
        ("foreground", f"Foreground layer for a side-scrolling game: {theme}. Near-camera ground strip, grass, rocks and "
                       f"plants only along the bottom edge, everything else plain white background, {style}.", True),
    ]
    outs = []
    for i, (name, prompt, transparent) in enumerate(layers):
        ctx.progress(0.05 + 0.3 * i, f"生成 {name}")
        img = (await generate(ctx, prompt, width=1536, height=640, seed=seed + i, quality=p["quality"]))[0]
        if p["loop"]:
            img = tiles.make_seamless(img, "x")
        if transparent:
            img = await remove_bg(ctx, img, "pixel" if pixel else "hd", "auto")
        if pixel:
            h = int(p["pixel_height"])
            img = pixelate(img, round(img.width * h / img.height), h, colors=32, detect_grid=True, trim_alpha=False)
        outs.append(ctx.save_image(img, f"视差层 · {name}", meta={"pixel": pixel, "layer": name, "parallax": [0.2, 0.5, 1.0][i],
                                                                  "loop_x": p["loop"]}))
    comp = storage.load_image(outs[0]["id"]).copy()
    for a in outs[1:]:
        comp.alpha_composite(storage.load_image(a["id"]).resize(comp.size, Image.Resampling.NEAREST))
    ctx.save_image(comp, "视差合成预览", meta={"preview": True, "pixel": pixel}, parents=[a["id"] for a in outs], role="preview")


register(Capability(
    "side_scrolling_map", "横版视差地图", "map",
    "分别生成远景/中景/前景三层（中前景自动透明），可水平无缝循环，附合成预览与视差速度建议。",
    [Param("prompt", "longtext", "场景主题", "enchanted forest at dusk", required=True),
     Param("mode", "select", "风格", "pixel", choices=["pixel", "hd"]),
     Param("pixel_height", "select", "像素高度", 180, choices=[144, 180, 216, 270, 360]),
     Param("loop", "bool", "水平无缝循环", True), QUALITY, PROVIDER, SEED],
    run_side_scroll, needs=["image", "bg"], aliases=["side-scrolling-map", "hd-side-scrolling-map"], icon="mountain"))


async def run_self_loop(ctx, p: dict) -> None:
    img = storage.load_image(p["source"])
    out = tiles.make_seamless(img, p["axis"])
    a = ctx.save_image(out, f"无缝循环 ({p['axis']})", meta={"seamless": p["axis"]})
    nx, ny = (3, 1) if p["axis"] == "x" else (1, 3) if p["axis"] == "y" else (2, 2)
    ctx.save_image(tiles.tile_preview(out, nx, ny), "循环预览", meta={"preview": True}, parents=[a["id"]], role="preview")


register(Capability(
    "self_loop", "图片自循环", "map",
    "让任意图片在水平/垂直/双向上首尾无缝衔接（背景卷轴、纹理）。",
    [Param("source", "image", "图片", None, required=True),
     Param("axis", "select", "方向", "x", choices=[{"value": "x", "label": "水平"}, {"value": "y", "label": "垂直"},
                                                   {"value": "both", "label": "双向纹理"}])],
    run_self_loop, needs=[], aliases=["self-loop"], icon="repeat"))
