import asyncio
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("SPRITEKILN_DATA", tempfile.mkdtemp(prefix="spritekiln_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import engine_export  # noqa: E402
from app.pixel import bg, pixelate, qa, sheet, split, tiles  # noqa: E402


def fake_pixel_art(k: int = 8) -> Image.Image:
    small = np.zeros((16, 16, 4), dtype=np.uint8)
    small[3:12, 4:13] = [200, 60, 50, 255]
    small[5:8, 7:10] = [250, 220, 120, 255]
    img = Image.fromarray(small, "RGBA").resize((16 * k, 16 * k), Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
    canvas.alpha_composite(img)
    return canvas


def test_grid_detection_recovers_block_size():
    k, _, _ = pixelate.estimate_block_size(fake_pixel_art(8))
    assert k == 8


def test_pixelate_exact_size_and_palette():
    out = pixelate.pixelate(fake_pixel_art(), 32, 32, colors=4)
    assert out.size == (32, 32)
    colors = {tuple(c) for c in np.asarray(out).reshape(-1, 4) if c[3] > 0}
    assert len(colors) <= 4


def test_chroma_remove_makes_background_transparent():
    out, used = bg.remove_background(fake_pixel_art(), method="chroma", mode="pixel")
    a = np.asarray(out)[..., 3]
    assert used == "chroma" and a[0, 0] == 0 and a[64, 64] == 255


def test_split_components_finds_separate_shapes():
    img = Image.new("RGBA", (100, 40), (0, 0, 0, 0))
    for x in (5, 40, 75):
        img.paste((255, 0, 0, 255), (x, 10, x + 15, 30))
    assert len(split.split_components(img, min_area=10)) == 3


def test_seamless_texture_reduces_edge_seam():
    ramp = np.tile(np.linspace(0, 255, 64, dtype=np.float32), (64, 1))
    src = np.stack([ramp, ramp, ramp, np.full_like(ramp, 255)], axis=2).astype(np.uint8)
    out = np.asarray(tiles.make_seamless(Image.fromarray(src))).astype(int)
    before = np.abs(src.astype(int)[:, 0] - src.astype(int)[:, -1]).mean()
    after = np.abs(out[:, 0] - out[:, -1]).mean()
    assert after < before * 0.2


def test_dual_grid_tileset_shape():
    fg = Image.new("RGBA", (16, 16), (0, 200, 0, 255))
    bgt = Image.new("RGBA", (16, 16), (150, 100, 50, 255))
    atlas, mapping = tiles.dual_grid_tileset(fg, bgt, 16)
    assert atlas.size == (64, 64) and len(mapping) == 16
    full = np.asarray(atlas.crop((48, 48, 64, 64)))  # index 15 = all corners foreground
    assert (full[..., 1] > 120).mean() > 0.95


def test_sheet_and_godot_resource():
    frames = [Image.new("RGBA", (8, 8), (i * 20, 0, 0, 255)) for i in range(6)]
    s, cols, rows = sheet.pack_sheet(frames)
    assert s.size == (8 * cols, 8 * rows)
    tres = sheet.godot_spriteframes("res://a.png", 8, 8, cols, 6, 10)
    assert tres.count('[sub_resource type="AtlasTexture"') == 6 and '"speed": 10.0' in tres


def _body(h: int = 30, w: int = 20) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([(64 - w) // 2, 34 - h, (64 + w) // 2, 34], fill=(200, 60, 50, 255))
    return img


def test_quality_gate_passes_real_motion_and_rejects_empty_or_frozen():
    moving = [_body(30 if i % 2 else 38) for i in range(8)]
    ok = qa.grade(moving)
    assert ok["ok"], ok
    assert ok["metrics"]["coverage_cv"] < 0.35

    empty = moving[:4] + [Image.new("RGBA", (64, 64), (0, 0, 0, 0)) for _ in range(4)]
    assert not qa.grade(empty)["ok"]

    frozen = [_body() for _ in range(8)]
    assert not qa.grade(frozen)["ok"]
    assert any("重复帧" in issue for issue in qa.grade(frozen)["issues"])


def test_engine_export_uses_absolute_frame_rects():
    asset = {"id": "ast_0123456789ab", "kind": "animation", "capability": "animate", "width": 16, "height": 16,
             "meta": {"frame_w": 16, "frame_h": 16, "cols": 4, "rows": 2, "count": 8, "fps": 10, "loop": True}}
    ase = engine_export.aseprite_json(asset)
    assert len(ase["frames"]) == 8
    assert ase["frames"][5]["frame"] == {"x": 16, "y": 16, "w": 16, "h": 16}
    assert ase["meta"]["frameTags"][0]["to"] == 7 and ase["meta"]["size"] == {"w": 64, "h": 32}
    pha = engine_export.phaser_atlas(asset)
    assert len(pha["animations"]["default"]) == 8 and pha["animations"]["default"][0].endswith("_000")
    files = engine_export.engine_files(asset, "animations/foo/sheet.png")
    assert set(files) == {"animations/foo/aseprite.json", "animations/foo/phaser.json"}


def test_tiled_tileset_json_for_dual_grid():
    asset = {"id": "ast_fedcba987654", "kind": "image", "capability": "tileset_gen", "width": 64, "height": 64,
             "meta": {"tileset": True, "tile_size": 16,
                      "mapping": [{"index": 0, "corners": {"tl": 0, "tr": 0, "bl": 0, "br": 0}}]}}
    tsj = engine_export.tiled_tileset(asset, "terrain.png")
    assert tsj["tilecount"] == 16 and tsj["columns"] == 4 and tsj["image"] == "terrain.png"
    assert tsj["tiles"][0]["properties"][0]["value"] == 0
    assert engine_export.tiled_tileset({"id": "x", "kind": "image", "width": 64, "height": 64, "meta": {}}) is None


@pytest.mark.parametrize("cap,params", [
    ("pixel_gen", {"template": "px_item_64", "prompt": "red potions"}),
    ("tileset_gen", {"foreground_prompt": "grass", "background_prompt": "dirt", "tile_size": 16}),
    ("animate", None),
    ("game_design", {"prompt": "cozy farming game"}),
])
def test_capabilities_offline(cap, params):
    from app import db
    from app.config import update_settings
    from app.jobs import manager

    update_settings({"routing": {"image": "mock", "image_edit": "mock", "video": "procedural", "llm": "rules",
                                 "threed": "mock", "bg": "chroma"}})

    async def run():
        await manager.start()
        p = params
        if p is None:
            base = await manager.submit("custom_size_pixel", {"prompt": "green slime", "width": 32, "height": 32}, None)
            base = await manager.wait(base["id"], 120)
            src = [a for a in base["result"] if db.get("assets", a)["role"] == "output"][0]
            p = {"source": src, "prompt": "jump", "frames": 8}
        job = await manager.submit(cap, p, None)
        return await manager.wait(job["id"], 120)

    job = asyncio.run(run())
    assert job["status"] == "succeeded", job.get("error")
    first = db.get("assets", job["result"][0])
    assert first is not None
    if cap == "animate":
        assert first["kind"] == "animation" and first["meta"]["count"] == 8
        assert first["meta"]["qa"]["ok"], first["meta"]["qa"]
        assert "aseprite" in first["meta"]["files"] and "phaser" in first["meta"]["files"]
        from app import export
        names = zipfile.ZipFile(io.BytesIO(export.export_zip(first["project_id"], [first["id"]]))).namelist()
        assert any(n.endswith("/aseprite.json") for n in names)
        assert any(n.endswith("/phaser.json") for n in names)
    if cap == "tileset_gen":
        from app import export
        data = export.export_zip(first["project_id"], [first["id"]])
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert any(n.endswith(".tsj") for n in names), names
