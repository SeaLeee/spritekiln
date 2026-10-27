"""SpriteKiln HTTP API (FastAPI)."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from . import agent, capabilities, db, export, storage
from .capabilities import templates as T
from .config import DATA_DIR, ROOT, WEB_DIST, public_settings, update_settings
from .jobs import ensure_default_project, manager
from .providers import all_health, resolve
from .providers.comfyui import list_workflows

app = FastAPI(title="SpriteKiln 像素窑", version="1.0.0",
              description="本地化 AI 游戏素材工作台：像素/高清素材、动画关键帧、地图、UI、3D 管线、Skill + Agent + MCP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def _startup() -> None:
    db.conn()
    await manager.start()


class ProjectIn(BaseModel):
    name: str = "未命名项目"
    kind: str = "general"
    description: str = ""
    style: dict[str, Any] = {}


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    style: dict[str, Any] | None = None
    viewport: dict[str, Any] | None = None


class AssetPatch(BaseModel):
    name: str | None = None
    x: float | None = None
    y: float | None = None
    favorite: bool | None = None
    tags: list[str] | None = None


class RunIn(BaseModel):
    project_id: str | None = None
    params: dict[str, Any] = {}
    source: str = "web"
    wait: bool = False


class ChatIn(BaseModel):
    project_id: str | None = None
    thread_id: str | None = None
    message: str
    attachments: list[str] = []
    execute: bool = True


class ExportIn(BaseModel):
    asset_ids: list[str] | None = None
    target: str = "zip"  # zip | godot
    godot_project: str | None = None
    asset_dir: str | None = None


def _404(what: str):
    raise HTTPException(404, f"{what} not found")


def _job_out(job: dict) -> dict:
    job = dict(job)
    job["assets"] = [storage.serialize(a) for a in (db.get("assets", i) for i in job.get("result") or []) if a]
    return job


# ------------------------------------------------------------------ system
@app.get("/api/health")
async def health(force: bool = False):
    providers = await all_health(force)
    routes = {k: await resolve(k) for k in ("image", "image_edit", "video", "llm", "threed", "bg")}
    return {"ok": True, "providers": providers, "routes": routes, "data_dir": str(DATA_DIR)}


@app.get("/api/system")
async def system_info():
    """Local paths + build state, so the Skill page can print correct copy-paste commands."""
    return {"name": "SpriteKiln", "version": app.version, "root": str(ROOT), "data_dir": str(DATA_DIR),
            "skill_dir": str(ROOT / "skills" / "spritekiln-game-assets"),
            "frontend_built": WEB_DIST.exists()}


@app.get("/api/settings")
async def get_settings_api():
    return public_settings()


@app.put("/api/settings")
async def put_settings(patch: dict[str, Any]):
    update_settings(patch)
    from .providers import _health_cache
    _health_cache.clear()
    return public_settings()


@app.get("/api/capabilities")
async def list_capabilities():
    return {"modules": capabilities.MODULES, "capabilities": capabilities.catalog()}


@app.get("/api/templates")
async def list_templates():
    return {"pixel": T.PIXEL_TEMPLATES, "hd": T.HD_TEMPLATES}


@app.get("/api/comfy/workflows")
async def comfy_workflows():
    return list_workflows()


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
async def list_projects():
    rows = db.query("""SELECT p.*, (SELECT COUNT(*) FROM assets a WHERE a.project_id=p.id AND a.role!='raw') AS asset_count,
                       (SELECT a.path FROM assets a WHERE a.project_id=p.id AND a.kind='image' AND a.role='output'
                        ORDER BY a.created_at DESC LIMIT 1) AS cover
                       FROM projects p ORDER BY updated_at DESC""")
    for r in rows:
        r["cover_url"] = storage.url_for(r.pop("cover", None))
    return rows


@app.post("/api/projects")
async def create_project(body: ProjectIn):
    return db.insert("projects", {"id": db.new_id("prj"), "name": body.name, "kind": body.kind,
                                  "description": body.description, "style": body.style, "viewport": {},
                                  "created_at": db.now(), "updated_at": db.now()})


@app.get("/api/projects/{pid}")
async def get_project(pid: str):
    return db.get("projects", pid) or _404("project")


@app.patch("/api/projects/{pid}")
async def patch_project(pid: str, body: ProjectPatch):
    vals = {k: v for k, v in body.model_dump().items() if v is not None}
    vals["updated_at"] = db.now()
    return db.update("projects", pid, vals) or _404("project")


@app.delete("/api/projects/{pid}")
async def delete_project(pid: str):
    for a in db.query("SELECT id FROM assets WHERE project_id=?", (pid,)):
        storage.delete_asset(a["id"])
    db.delete("projects", pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/assets")
async def project_assets(pid: str, include_raw: bool = True):
    sql = "SELECT * FROM assets WHERE project_id=?" + ("" if include_raw else " AND role!='raw'") + " ORDER BY created_at"
    return [storage.serialize(a) for a in db.query(sql, (pid,))]


@app.post("/api/projects/{pid}/assets")
async def upload_asset(pid: str, file: UploadFile = File(...), name: str = Form(""), x: float | None = Form(None),
                       y: float | None = Form(None), role: str = Form("input"), pixel: bool = Form(False)):
    if not db.get("projects", pid):
        _404("project")
    data = await file.read()
    suffix = Path(file.filename or "upload.png").suffix.lower() or ".png"
    kind = "image" if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp") else "model3d" if suffix in (".glb", ".gltf") \
        else "video" if suffix in (".mp4", ".webm") else "file"
    if kind == "image":
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        a = storage.save_image(pid, img, name=name or file.filename or "上传", kind="image", role=role,
                               meta={"uploaded": True, "pixel": pixel or (img.width <= 256 and img.height <= 256)}, x=x, y=y)
    else:
        a = storage.save_bytes(pid, data, suffix, name=name or file.filename or "上传", kind=kind, role=role,
                               meta={"uploaded": True})
    return storage.serialize(a)


@app.get("/api/projects/{pid}/docs")
async def list_docs(pid: str):
    d = storage.docs_dir(pid)
    return [{"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime} for f in sorted(d.glob("*.md"))]


@app.get("/api/projects/{pid}/docs/{name}")
async def read_doc(pid: str, name: str):
    f = storage.docs_dir(pid) / Path(name).name
    if not f.exists():
        _404("doc")
    return {"name": f.name, "content": f.read_text(encoding="utf-8")}


@app.put("/api/projects/{pid}/docs/{name}")
async def write_doc(pid: str, name: str, body: dict[str, str]):
    f = storage.docs_dir(pid) / Path(name).name
    f.write_text(body.get("content", ""), encoding="utf-8")
    return {"ok": True, "name": f.name}


@app.post("/api/projects/{pid}/export")
async def export_project(pid: str, body: ExportIn):
    if body.target == "godot":
        try:
            return await asyncio.to_thread(export.export_godot, pid, body.asset_ids, body.godot_project, body.asset_dir)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    data = await asyncio.to_thread(export.export_zip, pid, body.asset_ids)
    proj = db.get("projects", pid) or {"name": "assets"}
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=spritekiln_{pid[-6:]}.zip",
                             "X-Project-Name": json.dumps(proj["name"])})


# ------------------------------------------------------------------ assets
@app.get("/api/assets/{aid}")
async def get_asset(aid: str):
    a = db.get("assets", aid) or _404("asset")
    return storage.serialize(a)


@app.patch("/api/assets/{aid}")
async def patch_asset(aid: str, body: AssetPatch):
    vals = {k: v for k, v in body.model_dump().items() if v is not None}
    if "favorite" in vals:
        vals["favorite"] = int(vals["favorite"])
    a = db.update("assets", aid, vals) or _404("asset")
    return storage.serialize(a)


@app.delete("/api/assets/{aid}")
async def delete_asset(aid: str):
    storage.delete_asset(aid)
    return {"ok": True}


@app.get("/api/assets/{aid}/download")
async def download_asset(aid: str, fmt: str = "file", scale: int = 1):
    a = db.get("assets", aid) or _404("asset")
    if fmt == "file":
        p = storage.asset_file(a)
        return FileResponse(p, filename=f"{a['name']}{p.suffix}")
    if fmt in ("sheet", "webp", "tres", "json", "aseprite", "phaser") and a["kind"] == "animation":
        p = storage.abs_path(a["meta"]["files"][fmt])
        return FileResponse(p, filename=f"{a['name']}_{p.name}")
    if fmt == "png" and scale > 1:
        img = storage.load_image(aid).resize((a["width"] * scale, a["height"] * scale), Image.Resampling.NEAREST)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png",
                        headers={"Content-Disposition": f"attachment; filename=asset_x{scale}.png"})
    if fmt == "zip":
        data = export.export_zip(a["project_id"], [aid])
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename={aid}.zip"})
    raise HTTPException(400, "unsupported format")


# ------------------------------------------------------------------ jobs / capabilities
async def _run(cap_id: str, body: RunIn):
    try:
        job = await manager.submit(cap_id, body.params, body.project_id, body.source)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.wait:
        job = await manager.wait(job["id"], timeout=3600)
    return _job_out(job)


@app.post("/api/capabilities/{cap_id}/run")
async def run_capability(cap_id: str, body: RunIn):
    return await _run(cap_id, body)


@app.post("/api/workflows/{cap_id}/run")
async def run_workflow_compat(cap_id: str, body: RunIn):
    """meowa-compatible route shape."""
    return await _run(cap_id, body)


@app.get("/api/jobs")
async def list_jobs(project_id: str | None = None, status: str | None = None, limit: int = 100):
    sql, args = "SELECT * FROM jobs WHERE 1=1", []
    if project_id:
        sql += " AND project_id=?"
        args.append(project_id)
    if status == "active":
        sql += " AND status IN ('queued','running')"
    elif status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [_job_out(j) for j in db.query(sql, args)]


@app.get("/api/jobs/{jid}")
async def get_job(jid: str):
    return _job_out(db.get("jobs", jid) or _404("job"))


@app.post("/api/jobs/{jid}/cancel")
async def cancel_job(jid: str):
    return _job_out(await manager.cancel(jid) or _404("job"))


@app.post("/api/jobs/{jid}/retry")
async def retry_job(jid: str):
    return _job_out(await manager.retry(jid))


@app.get("/api/events")
async def events(request: Request):
    q = manager.subscribe()

    async def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            manager.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ agent
@app.post("/api/agent/chat")
async def agent_chat(body: ChatIn):
    pid = body.project_id or ensure_default_project()
    return await agent.chat(pid, body.thread_id, body.message, body.attachments, body.execute)


@app.get("/api/agent/threads/{tid}")
async def agent_thread(tid: str):
    return agent.history(tid)


@app.get("/api/agent/threads")
async def agent_threads(project_id: str):
    return db.query("""SELECT thread_id, MIN(created_at) AS created_at, MAX(created_at) AS updated_at, COUNT(*) AS n,
                       (SELECT content FROM messages m2 WHERE m2.thread_id=m.thread_id AND role='user'
                        ORDER BY created_at LIMIT 1) AS title
                       FROM messages m WHERE project_id=? GROUP BY thread_id ORDER BY updated_at DESC""", (project_id,))


@app.get("/api/stats")
async def stats():
    from .providers.util import spent_today
    j = db.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    return {"jobs": {r["status"]: r["n"] for r in j}, "spent_today_usd": round(spent_today(), 4),
            "assets": db.query("SELECT COUNT(*) AS n FROM assets")[0]["n"],
            "projects": db.query("SELECT COUNT(*) AS n FROM projects")[0]["n"]}


# ------------------------------------------------------------------ static
app.mount("/files", StaticFiles(directory=str(DATA_DIR)), name="files")
SKILL_DIR = Path(__file__).resolve().parents[2] / "skills"
if SKILL_DIR.exists():
    app.mount("/skills", StaticFiles(directory=str(SKILL_DIR)), name="skills")

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="web-assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        f = WEB_DIST / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
else:
    @app.get("/")
    async def root():
        return JSONResponse({"name": "SpriteKiln API", "docs": "/docs", "hint": "前端未构建：cd web && npm run build"})
