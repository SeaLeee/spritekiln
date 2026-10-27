#!/usr/bin/env python3
"""SpriteKiln CLI runner for agents (Claude Code / Codex / any shell-capable agent).

Standard library only. Talks to the local SpriteKiln server (default http://127.0.0.1:7788,
override with SPRITEKILN_URL). Image parameters accept either an asset id (ast_...) or a local
file path, which is uploaded automatically.

  python kiln_api.py health
  python kiln_api.py capabilities [--module pixel]
  python kiln_api.py describe pixel_gen
  python kiln_api.py templates
  python kiln_api.py run pixel_gen --param template=px_char_64 --param "prompt=forest heroes" --output-dir ./out/heroes
  python kiln_api.py run animate --param source=./hero.png --param "prompt=walk cycle" --output-dir ./out/walk
  python kiln_api.py poll job_xxx --output-dir ./out/recovered
  python kiln_api.py projects | create-project NAME
  python kiln_api.py export-godot --project prj_xxx --godot D:/Games/MyGame [--assets ast_1,ast_2]
  python kiln_api.py export-zip --project prj_xxx --out pack.zip
  python kiln_api.py chat "做 4 个 64px 森林小怪" [--project prj_xxx]
  python kiln_api.py batch pack.json [--output-dir ./out/pack]
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

VERSION = "1.0.0"
BASE = os.environ.get("SPRITEKILN_URL", "http://127.0.0.1:7788").rstrip("/")
TERMINAL = {"succeeded", "failed", "canceled"}


def _req(method: str, path: str, body=None, headers=None, raw: bool = False, timeout: float = 120):
    data = None
    headers = dict(headers or {})
    if body is not None and not isinstance(body, (bytes, bytearray)):
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif body is not None:
        data = bytes(body)
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(f"HTTP {e.code} {path}: {detail[:800]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"无法连接 SpriteKiln ({BASE})：{e.reason}。请先运行 start.ps1 或 python backend/run.py")
    if raw:
        return payload
    return json.loads(payload.decode("utf-8")) if payload else None


def _upload(project: str, path: Path) -> str:
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n{path.stem}\r\n".encode(),
        f"--{boundary}--\r\n".encode(),
    ]
    res = _req("POST", f"/api/projects/{project}/assets", b"".join(parts),
               {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return res["id"]


def _default_project() -> str:
    for p in _req("GET", "/api/projects"):
        if p["kind"] == "inbox":
            return p["id"]
    return _req("POST", "/api/projects", {"name": "收件箱 (Agent/API)", "kind": "inbox"})["id"]


def _coerce(value: str):
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _resolve_images(params: dict, cap: dict, project: str) -> dict:
    types = {p["name"]: p["type"] for p in cap["params"]}
    out = dict(params)
    for k, v in params.items():
        t = types.get(k)
        if t == "image" and isinstance(v, str) and not v.startswith("ast_") and Path(v).exists():
            out[k] = _upload(project, Path(v))
        elif t in ("images",):
            vals = v if isinstance(v, list) else [x for x in str(v).split(",") if x]
            out[k] = [_upload(project, Path(x)) if not x.startswith("ast_") and Path(x).exists() else x for x in vals]
        elif t == "lines" and isinstance(v, str):
            out[k] = [x for x in v.split("|") if x]
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^\w-]+", "-", text, flags=re.ASCII).strip("-").lower()[:40] or "asset"


def _download(job: dict, output_dir: Path) -> list[dict]:
    """Save only final deliverables (role output/pack) + a sanitized final_outputs.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    finals = []
    for a in job.get("assets", []):
        if a["role"] not in ("output", "pack"):
            continue
        base = f"{_slug(a['name'])}_{a['id'][-6:]}"
        files = {}
        if a["kind"] == "animation":
            for fmt, name in (("file", "preview.gif"), ("sheet", "sheet.png"), ("webp", "anim.webp"),
                              ("tres", "spriteframes.tres"), ("json", "sheet.json"),
                              ("aseprite", "aseprite.json"), ("phaser", "phaser.json")):
                if fmt == "file" or a["meta"].get("file_urls", {}).get(fmt):
                    p = output_dir / base / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(_req("GET", f"/api/assets/{a['id']}/download?fmt={fmt}", raw=True, timeout=300))
                    files[fmt] = str(p)
        else:
            ext = Path(a["path"]).suffix
            p = output_dir / f"{base}{ext}"
            p.write_bytes(_req("GET", f"/api/assets/{a['id']}/download", raw=True, timeout=300))
            files["file"] = str(p)
        m = a.get("meta") or {}
        finals.append({"id": a["id"], "name": a["name"], "kind": a["kind"], "role": a["role"], "width": a["width"],
                       "height": a["height"], "pixel": bool(m.get("pixel")), "files": files,
                       **{k: m[k] for k in ("fps", "count", "frame_w", "frame_h", "cols", "rows", "direction",
                                            "tile_size", "palette") if k in m}})
    (output_dir / "final_outputs.json").write_text(json.dumps({"job_id": job["id"], "capability": job["capability"],
                                                               "final_outputs": finals}, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    return finals


def _wait(job_id: str, timeout: float) -> dict:
    t0 = time.time()
    last = ""
    while True:
        job = _req("GET", f"/api/jobs/{job_id}")
        line = f"[{job['status']}] {int(job['progress'] * 100):3d}% {job.get('message') or ''}"
        if line != last:
            print(line, file=sys.stderr, flush=True)
            last = line
        if job["status"] in TERMINAL:
            return job
        if time.time() - t0 > timeout:
            raise SystemExit(f"等待超时；任务仍在运行，稍后用 `poll {job_id}` 恢复，切勿重复提交")
        time.sleep(2)


def _find_cap(capability: str) -> dict:
    data = _req("GET", "/api/capabilities")
    cap = next((c for c in data["capabilities"] if c["id"] == capability or capability in c["aliases"]), None)
    if not cap:
        raise SystemExit(f"未知能力 {capability}；用 `capabilities` 查看目录")
    return cap


def cmd_run(a) -> None:
    cap = _find_cap(a.capability)
    params: dict = {}
    if a.params_json:
        params.update(json.loads(Path(a.params_json).read_text(encoding="utf-8")))
    for kv in a.param or []:
        k, _, v = kv.partition("=")
        params[k] = _coerce(v)
    project = a.project or _default_project()
    params = _resolve_images(params, cap, project)
    job = _req("POST", f"/api/capabilities/{cap['id']}/run", {"project_id": project, "params": params, "source": "cli"})
    print(json.dumps({"job_id": job["id"], "project_id": project, "lane": job["lane"], "providers": job["providers"]},
                     ensure_ascii=False))
    if a.no_wait:
        return
    job = _wait(job["id"], a.timeout)
    if job["status"] != "succeeded":
        raise SystemExit(f"任务 {job['status']}: {job.get('error')}")
    out = Path(a.output_dir or f"./outputs/{cap['id']}-{job['id'][-6:]}")
    finals = _download(job, out)
    print(json.dumps({"job_id": job["id"], "output_dir": str(out.resolve()), "final_outputs": len(finals),
                      "cost_usd": job.get("cost_usd", 0)}, ensure_ascii=False))


def cmd_batch(a) -> None:
    """Run a JSON manifest of capabilities sequentially (same shape as pixel-art-factory manifests).

    {"project": "prj_...", "output_dir": "./outputs/pack", "stop_on_error": false,
     "items": [{"capability": "pixel_gen", "params": {"template": "px_item_64", "prompt": "potion"}, "name": "potion"}]}
    """
    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    items = manifest.get("items") or []
    if not items:
        raise SystemExit("manifest 里没有 items")
    project = a.project or manifest.get("project") or _default_project()
    base = Path(a.output_dir or manifest.get("output_dir") or "./outputs/batch")
    stop = a.stop_on_error or bool(manifest.get("stop_on_error"))
    report: list[dict] = []
    for i, item in enumerate(items):
        cap_id = item.get("capability") or item.get("id")
        label = item.get("name") or f"{i:02d}-{cap_id}"
        entry: dict = {"index": i, "name": label, "capability": cap_id}
        try:
            cap = _find_cap(cap_id)
            params = _resolve_images(dict(item.get("params") or {}), cap, project)
            job = _req("POST", f"/api/capabilities/{cap['id']}/run",
                       {"project_id": project, "params": params, "source": "batch"})
            job = _wait(job["id"], a.timeout)
            if job["status"] != "succeeded":
                raise SystemExit(f"任务 {job['status']}: {job.get('error')}")
            out = base / _slug(label)
            finals = _download(job, out)
            entry.update({"status": "succeeded", "job_id": job["id"], "output_dir": str(out.resolve()),
                          "final_outputs": len(finals), "cost_usd": job.get("cost_usd", 0)})
        except (SystemExit, Exception) as exc:  # noqa: BLE001
            entry.update({"status": "failed", "error": str(exc)[:800]})
            if stop:
                report.append(entry)
                break
        report.append(entry)
        print(json.dumps(entry, ensure_ascii=False), file=sys.stderr, flush=True)
    base.mkdir(parents=True, exist_ok=True)
    summary = {"project_id": project, "items": len(items),
               "succeeded": sum(1 for r in report if r["status"] == "succeeded"),
               "failed": sum(1 for r in report if r["status"] == "failed"), "report": report}
    (base / "batch_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("project_id", "items", "succeeded", "failed")}, ensure_ascii=False))
    print(str((base / "batch_report.json").resolve()))
    if summary["failed"]:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(prog="kiln_api", description="SpriteKiln agent CLI")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    c = sub.add_parser("capabilities")
    c.add_argument("--module")
    d = sub.add_parser("describe")
    d.add_argument("capability")
    sub.add_parser("templates")
    r = sub.add_parser("run")
    r.add_argument("capability")
    r.add_argument("--param", action="append", help="key=value (repeatable); lines: a|b|c; images: p1,p2")
    r.add_argument("--params-json")
    r.add_argument("--project")
    r.add_argument("--output-dir")
    r.add_argument("--no-wait", action="store_true")
    r.add_argument("--timeout", type=float, default=3600)
    p = sub.add_parser("poll")
    p.add_argument("job_id")
    p.add_argument("--output-dir")
    p.add_argument("--timeout", type=float, default=3600)
    sub.add_parser("projects")
    cp = sub.add_parser("create-project")
    cp.add_argument("name")
    up = sub.add_parser("upload")
    up.add_argument("file")
    up.add_argument("--project")
    eg = sub.add_parser("export-godot")
    eg.add_argument("--project", required=True)
    eg.add_argument("--godot")
    eg.add_argument("--assets")
    ez = sub.add_parser("export-zip")
    ez.add_argument("--project", required=True)
    ez.add_argument("--out", default="spritekiln_assets.zip")
    ez.add_argument("--assets")
    ch = sub.add_parser("chat")
    ch.add_argument("message")
    ch.add_argument("--project")
    ch.add_argument("--attach", help="comma separated asset ids")
    b = sub.add_parser("batch", help="run a JSON manifest of capabilities sequentially")
    b.add_argument("manifest")
    b.add_argument("--project")
    b.add_argument("--output-dir")
    b.add_argument("--stop-on-error", action="store_true")
    b.add_argument("--timeout", type=float, default=3600)
    a = ap.parse_args()

    if a.cmd == "health":
        h = _req("GET", "/api/health")
        print(json.dumps({"routes": h["routes"], "providers": {k: {n: v["ok"] for n, v in p.items()}
                                                               for k, p in h["providers"].items()}}, ensure_ascii=False, indent=2))
    elif a.cmd == "capabilities":
        data = _req("GET", "/api/capabilities")
        for cap in data["capabilities"]:
            if a.module and cap["module"] != a.module:
                continue
            print(f"{cap['id']:22s} [{cap['module']}] {cap['name']} — {cap['description']}")
    elif a.cmd == "describe":
        data = _req("GET", "/api/capabilities")
        cap = next((x for x in data["capabilities"] if x["id"] == a.capability or a.capability in x["aliases"]), None)
        print(json.dumps(cap, ensure_ascii=False, indent=2) if cap else f"未知能力 {a.capability}")
    elif a.cmd == "templates":
        print(json.dumps(_req("GET", "/api/templates"), ensure_ascii=False, indent=2))
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "batch":
        cmd_batch(a)
    elif a.cmd == "poll":
        job = _wait(a.job_id, a.timeout)
        if job["status"] == "succeeded":
            out = Path(a.output_dir or f"./outputs/{job['capability']}-{job['id'][-6:]}")
            _download(job, out)
            print(json.dumps({"job_id": job["id"], "output_dir": str(out.resolve())}, ensure_ascii=False))
        else:
            print(json.dumps({"job_id": job["id"], "status": job["status"], "error": job.get("error")}, ensure_ascii=False))
    elif a.cmd == "projects":
        for p in _req("GET", "/api/projects"):
            print(f"{p['id']}  {p['name']}  ({p.get('asset_count', 0)} assets)")
    elif a.cmd == "create-project":
        print(_req("POST", "/api/projects", {"name": a.name})["id"])
    elif a.cmd == "upload":
        print(_upload(a.project or _default_project(), Path(a.file)))
    elif a.cmd == "export-godot":
        ids = a.assets.split(",") if a.assets else None
        print(json.dumps(_req("POST", f"/api/projects/{a.project}/export",
                              {"target": "godot", "asset_ids": ids, "godot_project": a.godot}), ensure_ascii=False, indent=2))
    elif a.cmd == "export-zip":
        ids = a.assets.split(",") if a.assets else None
        Path(a.out).write_bytes(_req("POST", f"/api/projects/{a.project}/export", {"target": "zip", "asset_ids": ids},
                                     raw=True, timeout=600))
        print(Path(a.out).resolve())
    elif a.cmd == "chat":
        res = _req("POST", "/api/agent/chat", {"project_id": a.project, "message": a.message,
                                                "attachments": a.attach.split(",") if a.attach else []}, timeout=600)
        print(res["message"]["content"])
        print(json.dumps({"thread_id": res["thread_id"], "job_ids": res["job_ids"], "plan": res["plan"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
