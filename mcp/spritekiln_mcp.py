#!/usr/bin/env python3
"""SpriteKiln MCP server (stdio, JSON-RPC 2.0, standard library only).

Register in Claude Code:   claude mcp add spritekiln -- python <path>/mcp/spritekiln_mcp.py
Generic MCP config:        {"command": "python", "args": ["<path>/mcp/spritekiln_mcp.py"],
                            "env": {"SPRITEKILN_URL": "http://127.0.0.1:7788"}}
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("SPRITEKILN_URL", "http://127.0.0.1:7788").rstrip("/")
DATA_DIR = Path(os.environ.get("SPRITEKILN_DATA", Path(__file__).resolve().parents[1] / "data"))
PROTOCOL = "2024-11-05"


def http(method: str, path: str, body=None, raw=False, headers=None, timeout=120):
    data = None
    headers = dict(headers or {})
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:600]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"SpriteKiln 未运行 ({BASE}): {e.reason}. 请先执行 start.ps1") from e
    return payload if raw else (json.loads(payload) if payload else None)


def upload(project: str, path: str) -> str:
    p = Path(path)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{p.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return http("POST", f"/api/projects/{project}/assets", body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})["id"]


def inbox() -> str:
    for p in http("GET", "/api/projects"):
        if p["kind"] == "inbox":
            return p["id"]
    return http("POST", "/api/projects", {"name": "收件箱 (Agent/API)", "kind": "inbox"})["id"]


def slim_asset(a: dict) -> dict:
    m = a.get("meta") or {}
    out = {"id": a["id"], "name": a["name"], "kind": a["kind"], "role": a["role"], "width": a["width"],
           "height": a["height"], "pixel": bool(m.get("pixel")), "url": BASE + (a.get("url") or ""),
           "file": str((DATA_DIR / a["path"]).resolve())}
    for k in ("fps", "count", "frame_w", "frame_h", "direction", "tile_size", "prompt"):
        if k in m:
            out[k] = m[k]
    if m.get("file_urls"):
        out["files"] = {k: BASE + v for k, v in m["file_urls"].items() if v}
    return out


def wait(job_id: str, timeout: float) -> dict:
    t0 = time.time()
    while True:
        job = http("GET", f"/api/jobs/{job_id}")
        if job["status"] in ("succeeded", "failed", "canceled") or time.time() - t0 > timeout:
            return job
        time.sleep(2)


def job_result(job: dict, include_raw: bool = False) -> dict:
    assets = [slim_asset(a) for a in job.get("assets", []) if include_raw or a["role"] in ("output", "pack")]
    return {"job_id": job["id"], "status": job["status"], "progress": job["progress"], "message": job.get("message"),
            "error": job.get("error"), "providers": job.get("providers"), "project_id": job["project_id"],
            "cost_usd": job.get("cost_usd"), "assets": assets, "canvas": f"{BASE}/studio/{job['project_id']}"}


def thumbs(job: dict, limit: int = 4) -> list[dict]:
    out = []
    for a in job.get("assets", []):
        if a["role"] not in ("output", "pack") or a["kind"] != "image" or len(out) >= limit:
            continue
        try:
            small = a["width"] and a["width"] <= 128
            path = (f"/api/assets/{a['id']}/download?fmt=png&scale={max(2, 256 // max(1, a['width']))}" if small
                    else f"/api/assets/{a['id']}/download")
            out.append({"type": "image", "data": base64.b64encode(http("GET", path, raw=True)).decode(),
                        "mimeType": "image/png"})
        except Exception:  # noqa: BLE001
            pass
    return out


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, **({"required": required} if required else {})}


TOOLS = [
    {"name": "health", "description": "检查 SpriteKiln 服务与各本地/云端引擎状态（生图、动画、3D、LLM、抠图）。",
     "inputSchema": _obj({})},
    {"name": "list_capabilities", "description": "列出全部素材能力（像素/高清/角色/动画/地图/UI/编辑/3D/策划）及简介。",
     "inputSchema": _obj({"module": {"type": "string"}})},
    {"name": "describe_capability", "description": "查看某个能力的完整参数 schema（类型、默认值、可选值）。运行前先调用。",
     "inputSchema": _obj({"capability": {"type": "string"}}, ["capability"])},
    {"name": "run_capability",
     "description": "提交一个素材任务并（默认）等待完成，返回最终产物（本地文件路径 + 缩略图）。图片参数可传 asset id 或本地文件路径。"
                    "本地 GPU 任务较慢：Z-Image≈1min，动画≈4min，3D≈7min；超时后用 get_job 恢复，不要重复提交。",
     "inputSchema": _obj({"capability": {"type": "string"}, "params": {"type": "object"},
                          "project_id": {"type": "string"}, "wait": {"type": "boolean", "default": True},
                          "timeout_s": {"type": "number", "default": 900}}, ["capability", "params"])},
    {"name": "get_job", "description": "查询/恢复任务（wait=true 时继续等待）。",
     "inputSchema": _obj({"job_id": {"type": "string"}, "wait": {"type": "boolean"}, "timeout_s": {"type": "number"}},
                         ["job_id"])},
    {"name": "list_projects", "description": "列出项目（每个项目一张画布）。", "inputSchema": _obj({})},
    {"name": "create_project", "description": "新建项目。", "inputSchema": _obj({"name": {"type": "string"}}, ["name"])},
    {"name": "list_assets", "description": "列出项目素材（默认只含最终产物）。",
     "inputSchema": _obj({"project_id": {"type": "string"}, "include_raw": {"type": "boolean"}}, ["project_id"])},
    {"name": "upload_image", "description": "上传本地图片为项目素材，返回 asset id。",
     "inputSchema": _obj({"path": {"type": "string"}, "project_id": {"type": "string"}}, ["path"])},
    {"name": "export_godot",
     "description": "把项目素材写入 Godot 4 项目 res://assets/spritekiln/（PNG、Sprite Sheet、SpriteFrames .tres、"
                    "AnimatedSprite2D .tscn、game-assets.json）。之后可用 Godot MCP 实例化 sprite.tscn。",
     "inputSchema": _obj({"project_id": {"type": "string"}, "godot_project": {"type": "string"},
                          "asset_ids": {"type": "array", "items": {"type": "string"}}}, ["project_id"])},
    {"name": "agent_chat", "description": "把自然语言需求交给 SpriteKiln 内置 Agent 规划并执行（可多步串联）。",
     "inputSchema": _obj({"message": {"type": "string"}, "project_id": {"type": "string"},
                          "attachments": {"type": "array", "items": {"type": "string"}}}, ["message"])},
]


def _find_cap(cid: str) -> dict | None:
    caps = http("GET", "/api/capabilities")["capabilities"]
    return next((x for x in caps if x["id"] == cid or cid in x["aliases"]), None)


def call(name: str, args: dict) -> list[dict]:
    def text(obj) -> list[dict]:
        return [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)}]

    if name == "health":
        h = http("GET", "/api/health")
        return text({"routes": h["routes"],
                     "providers": {k: {n: f"{'OK' if v['ok'] else 'X'} {v.get('detail', '')}" for n, v in p.items()}
                                   for k, p in h["providers"].items()}})
    if name == "list_capabilities":
        caps = http("GET", "/api/capabilities")["capabilities"]
        return text([{"id": c["id"], "module": c["module"], "name": c["name"], "description": c["description"]}
                     for c in caps if not args.get("module") or c["module"] == args["module"]])
    if name == "describe_capability":
        return text(_find_cap(args["capability"]) or f"unknown capability {args['capability']}")
    if name == "run_capability":
        c = _find_cap(args["capability"])
        if not c:
            raise RuntimeError(f"unknown capability {args['capability']}")
        project = args.get("project_id") or inbox()
        params = dict(args.get("params") or {})
        types = {p["name"]: p["type"] for p in c["params"]}
        for k, v in list(params.items()):
            if types.get(k) == "image" and isinstance(v, str) and not v.startswith("ast_") and Path(v).exists():
                params[k] = upload(project, v)
            elif types.get(k) == "images" and isinstance(v, list):
                params[k] = [upload(project, x) if isinstance(x, str) and not x.startswith("ast_") and Path(x).exists()
                             else x for x in v]
        job = http("POST", f"/api/capabilities/{c['id']}/run", {"project_id": project, "params": params, "source": "mcp"})
        if args.get("wait", True):
            job = wait(job["id"], float(args.get("timeout_s", 900)))
        return text(job_result(job)) + (thumbs(job) if job["status"] == "succeeded" else [])
    if name == "get_job":
        job = wait(args["job_id"], float(args.get("timeout_s", 600))) if args.get("wait") else \
            http("GET", f"/api/jobs/{args['job_id']}")
        return text(job_result(job)) + (thumbs(job) if job["status"] == "succeeded" else [])
    if name == "list_projects":
        return text([{"id": p["id"], "name": p["name"], "assets": p.get("asset_count")} for p in http("GET", "/api/projects")])
    if name == "create_project":
        return text(http("POST", "/api/projects", {"name": args["name"]}))
    if name == "list_assets":
        rows = http("GET", f"/api/projects/{args['project_id']}/assets")
        return text([slim_asset(a) for a in rows if args.get("include_raw") or a["role"] in ("output", "pack")])
    if name == "upload_image":
        return text({"asset_id": upload(args.get("project_id") or inbox(), args["path"])})
    if name == "export_godot":
        return text(http("POST", f"/api/projects/{args['project_id']}/export",
                         {"target": "godot", "asset_ids": args.get("asset_ids"), "godot_project": args.get("godot_project")}))
    if name == "agent_chat":
        res = http("POST", "/api/agent/chat", {"project_id": args.get("project_id"), "message": args["message"],
                                                "attachments": args.get("attachments") or []}, timeout=600)
        return text({"reply": res["message"]["content"], "plan": res["plan"], "job_ids": res["job_ids"],
                     "thread_id": res["thread_id"]})
    raise RuntimeError(f"unknown tool {name}")


def handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method", "")
    if mid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "spritekiln", "version": "1.0.0"},
                  "instructions": "Local game-asset studio. Call health, then describe_capability before run_capability."}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            result = {"content": call(p["name"], p.get("arguments") or {}), "isError": False}
        except Exception as exc:  # noqa: BLE001
            result = {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            out.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()


if __name__ == "__main__":
    main()
