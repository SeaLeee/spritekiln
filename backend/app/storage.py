"""Asset storage on local disk + DB rows."""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from . import db
from .config import DATA_DIR, PROJECTS_DIR


def project_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def docs_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR).as_posix()


def abs_path(rel_path: str) -> Path:
    p = (DATA_DIR / rel_path).resolve()
    if DATA_DIR not in p.parents and p != DATA_DIR:
        raise ValueError("path escapes data dir")
    return p


def url_for(rel_path: str | None) -> str | None:
    return f"/files/{rel_path}" if rel_path else None


def _placement(project_id: str, parents: list[str]) -> tuple[float, float]:
    if parents:
        parent = db.get("assets", parents[0])
        if parent:
            i = db.query("SELECT COUNT(*) AS n FROM assets WHERE project_id=? AND parents LIKE ?",
                         (project_id, f'%"{parents[0]}"%'))[0]["n"]
            return parent["x"] + 340 + (i % 4) * 175, parent["y"] + (i // 4) * 210
    n = db.query("SELECT COUNT(*) AS n FROM assets WHERE project_id=? AND parents='[]'", (project_id,))[0]["n"]
    return 0.0, n * 460.0


def create_asset(project_id: str, *, kind: str, name: str, path: Path, width: int = 0, height: int = 0,
                 meta: dict[str, Any] | None = None, parents: list[str] | None = None, job_id: str | None = None,
                 capability: str | None = None, role: str = "output", x: float | None = None,
                 y: float | None = None) -> dict[str, Any]:
    parents = [p for p in (parents or []) if p]
    if x is None or y is None:
        x, y = _placement(project_id, parents)
    row = db.insert("assets", {
        "id": path.stem if path.stem.startswith("ast_") else db.new_id("ast"),
        "project_id": project_id, "kind": kind, "name": name, "path": rel(path), "width": width,
        "height": height, "meta": meta or {}, "parents": parents, "job_id": job_id,
        "capability": capability, "x": x, "y": y, "favorite": 0, "tags": [], "role": role,
        "created_at": db.now(),
    })
    db.update("projects", project_id, {"updated_at": db.now()})
    return row


def save_image(project_id: str, img: Image.Image, *, name: str, kind: str = "image", meta: dict | None = None,
               parents: list[str] | None = None, job_id: str | None = None, capability: str | None = None,
               role: str = "output", x: float | None = None, y: float | None = None) -> dict[str, Any]:
    aid = db.new_id("ast")
    path = project_dir(project_id) / f"{aid}.png"
    img.save(path, optimize=True)
    return create_asset(project_id, kind=kind, name=name, path=path, width=img.width, height=img.height, meta=meta,
                        parents=parents, job_id=job_id, capability=capability, role=role, x=x, y=y)


def save_bytes(project_id: str, data: bytes, ext: str, *, name: str, kind: str, meta: dict | None = None,
               parents: list[str] | None = None, job_id: str | None = None, capability: str | None = None,
               role: str = "output") -> dict[str, Any]:
    aid = db.new_id("ast")
    path = project_dir(project_id) / f"{aid}.{ext.lstrip('.')}"
    path.write_bytes(data)
    w = h = 0
    if kind == "image":
        try:
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
        except Exception:  # noqa: BLE001
            pass
    return create_asset(project_id, kind=kind, name=name, path=path, width=w, height=h, meta=meta, parents=parents,
                        job_id=job_id, capability=capability, role=role)


def copy_file(project_id: str, src: Path, *, name: str, kind: str, meta: dict | None = None,
              parents: list[str] | None = None, job_id: str | None = None, capability: str | None = None) -> dict:
    aid = db.new_id("ast")
    path = project_dir(project_id) / f"{aid}{src.suffix}"
    shutil.copyfile(src, path)
    return create_asset(project_id, kind=kind, name=name, path=path, meta=meta, parents=parents, job_id=job_id,
                        capability=capability)


def asset_file(asset: dict[str, Any]) -> Path:
    return abs_path(asset["path"])


def load_image(asset_id: str) -> Image.Image:
    asset = db.get("assets", asset_id)
    if not asset:
        raise KeyError(f"asset not found: {asset_id}")
    if asset["kind"] == "animation" and asset["meta"].get("frames"):
        return Image.open(abs_path(asset["meta"]["frames"][0])).convert("RGBA")
    return Image.open(asset_file(asset)).convert("RGBA")


def load_frames(asset_id: str) -> list[Image.Image]:
    asset = db.get("assets", asset_id)
    if not asset:
        raise KeyError(asset_id)
    frames = asset["meta"].get("frames")
    if frames:
        return [Image.open(abs_path(f)).convert("RGBA") for f in frames]
    return [Image.open(asset_file(asset)).convert("RGBA")]


def serialize(asset: dict[str, Any]) -> dict[str, Any]:
    out = dict(asset)
    out["url"] = url_for(asset.get("path"))
    meta = dict(asset.get("meta") or {})
    files = meta.get("files") or {}
    meta["file_urls"] = {k: url_for(v) for k, v in files.items()}
    if isinstance(meta.get("frames"), list):
        meta["frame_urls"] = [url_for(f) for f in meta["frames"]]
    out["meta"] = meta
    return out


def delete_asset(asset_id: str) -> None:
    asset = db.get("assets", asset_id)
    if not asset:
        return
    try:
        p = asset_file(asset)
        if p.exists():
            p.unlink()
        extra_dir = p.with_suffix("")
        if extra_dir.is_dir():
            shutil.rmtree(extra_dir, ignore_errors=True)
    except ValueError:
        pass
    db.delete("assets", asset_id)
