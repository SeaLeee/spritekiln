"""Export: ZIP asset pack with manifest, and direct write-back into a Godot 4 project (res://)."""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from . import db, engine_export, storage
from .config import get_settings
from .pixel import sheet as sheetmod


def _slug(text: str) -> str:
    s = re.sub(r"[^\w-]+", "_", text, flags=re.ASCII).strip("_").lower()
    return s[:40] or "asset"


def _assets(project_id: str, asset_ids: list[str] | None) -> list[dict]:
    if asset_ids:
        rows = [db.get("assets", a) for a in asset_ids]
        return [r for r in rows if r]
    return db.query("SELECT * FROM assets WHERE project_id=? AND role IN ('output','pack') ORDER BY created_at",
                    (project_id,))


def _files_for(asset: dict) -> list[tuple[str, Path]]:
    """(relative export path, source file) for an asset."""
    stem = _slug(asset["name"])
    if stem == "asset" or not re.search(r"[a-z]{2}", stem):
        stem = f"{asset.get('capability') or asset['kind']}_{stem}".strip("_")
    base = f"{asset['kind']}s/{stem}_{asset['id'][-6:]}"
    main = storage.asset_file(asset)
    out = []
    if asset["kind"] == "animation":
        files = asset["meta"].get("files", {})
        for key, name in (("sheet", "sheet.png"), ("gif", "preview.gif"), ("webp", "anim.webp"), ("json", "sheet.json")):
            if files.get(key):
                out.append((f"{base}/{name}", storage.abs_path(files[key])))
        for i, f in enumerate(asset["meta"].get("frames", [])):
            out.append((f"{base}/frames/frame_{i:03d}.png", storage.abs_path(f)))
    else:
        out.append((f"{base}{main.suffix}", main))
        mapping = main.parent / f"{asset['id']}_mapping.json"
        if mapping.exists():
            out.append((f"{base}_mapping.json", mapping))
    return out


def manifest(assets: list[dict]) -> dict[str, Any]:
    items = []
    for a in assets:
        m = a.get("meta") or {}
        files = _files_for(a)
        paths = [p for p, _ in files]
        if files:
            paths += list(engine_export.engine_files(a, files[0][0]))
        item = {"id": a["id"], "name": a["name"], "kind": a["kind"], "width": a["width"], "height": a["height"],
                "pixel": bool(m.get("pixel")), "files": paths}
        for k in ("fps", "frame_w", "frame_h", "cols", "rows", "count", "loop", "direction", "tile_size", "mapping",
                  "diamond", "layer", "parallax"):
            if k in m:
                item[k] = m[k]
        items.append(item)
    return {"generator": "SpriteKiln", "version": 1, "assets": items}


def export_zip(project_id: str, asset_ids: list[str] | None = None) -> bytes:
    assets = _assets(project_id, asset_ids)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for a in assets:
            files = _files_for(a)
            for rel, src in files:
                if src.exists():
                    z.write(src, rel)
            if files:
                for rel, doc in engine_export.engine_files(a, files[0][0]).items():
                    z.writestr(rel, json.dumps(doc, ensure_ascii=False, indent=2))
            if a["kind"] == "animation":
                m = a["meta"]
                base = _files_for(a)[0][0].rsplit("/", 1)[0]
                tres = sheetmod.godot_spriteframes(f"res://{base}/sheet.png", m["frame_w"], m["frame_h"], m["cols"],
                                                   m["count"], m["fps"], m.get("loop", True))
                z.writestr(f"{base}/spriteframes.tres", tres)
        z.writestr("game-assets.json", json.dumps(manifest(assets), ensure_ascii=False, indent=2))
    return buf.getvalue()


def export_godot(project_id: str, asset_ids: list[str] | None, godot_project: str | None = None,
                 asset_dir: str | None = None) -> dict[str, Any]:
    cfg = get_settings()["godot"]
    root = Path(godot_project or cfg.get("project_path") or "")
    if not (root / "project.godot").exists():
        raise ValueError(f"不是 Godot 项目目录（缺少 project.godot）: {root}")
    project = db.get("projects", project_id) or {"name": "spritekiln"}
    pslug = _slug(project["name"])
    if pslug == "asset" or not re.search(r"[a-z]{2}", pslug):
        pslug = f"project_{project_id[-6:]}"
    sub = f"{(asset_dir or cfg.get('asset_dir') or 'assets/spritekiln').strip('/')}/{pslug}"
    dest = root / sub
    dest.mkdir(parents=True, exist_ok=True)
    assets = _assets(project_id, asset_ids)
    written: list[dict[str, Any]] = []
    for a in assets:
        files = []
        for rel, src in _files_for(a):
            if not src.exists() or rel.endswith(".gif"):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            files.append(f"res://{sub}/{rel}")
        entry: dict[str, Any] = {"id": a["id"], "name": a["name"], "kind": a["kind"], "files": files}
        if a["kind"] == "animation":
            m = a["meta"]
            base = _files_for(a)[0][0].rsplit("/", 1)[0]
            sheet_res = f"res://{sub}/{base}/sheet.png"
            tres_res = f"res://{sub}/{base}/spriteframes.tres"
            (dest / base / "spriteframes.tres").write_text(
                sheetmod.godot_spriteframes(sheet_res, m["frame_w"], m["frame_h"], m["cols"], m["count"], m["fps"],
                                            m.get("loop", True)), encoding="utf-8")
            (dest / base / "sprite.tscn").write_text(sheetmod.godot_animated_scene(tres_res, _slug(a["name"]).title()),
                                                     encoding="utf-8")
            entry.update({"sprite_frames": tres_res, "scene": f"res://{sub}/{base}/sprite.tscn"})
        written.append(entry)
    (dest / "game-assets.json").write_text(json.dumps({**manifest(assets), "godot": written}, ensure_ascii=False,
                                                      indent=2), encoding="utf-8")
    _ensure_pixel_filter(root)
    return {"godot_project": str(root), "res_dir": f"res://{sub}", "assets": written}


def _ensure_pixel_filter(root: Path) -> None:
    """Default texture filter = Nearest so pixel art stays crisp (only added if the key is absent)."""
    pg = root / "project.godot"
    text = pg.read_text(encoding="utf-8")
    if "textures/canvas_textures/default_texture_filter" in text:
        return
    if "[rendering]" in text:
        text = text.replace("[rendering]", "[rendering]\n\ntextures/canvas_textures/default_texture_filter=0", 1)
    else:
        text += "\n[rendering]\n\ntextures/canvas_textures/default_texture_filter=0\n"
    pg.write_text(text, encoding="utf-8")
