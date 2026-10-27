"""Async job queue with resource lanes (gpu / cloud / cpu), persistence, cancel and SSE events."""
from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any, Callable

from PIL import Image

from . import db, storage
from .config import get_settings


class JobCanceled(Exception):
    pass


class JobContext:
    def __init__(self, manager: "JobManager", job: dict[str, Any]):
        self.manager = manager
        self.job = job
        self.id: str = job["id"]
        self.project_id: str = job["project_id"]
        self.params: dict[str, Any] = job["params"]
        self.providers: dict[str, str] = job["providers"] or {}
        self.assets: list[dict[str, Any]] = []
        self.cost_usd = 0.0
        self._cancel = manager.cancel_flags.setdefault(self.id, asyncio.Event())

    # ---- progress / cancel
    def progress(self, value: float, message: str = "") -> None:
        value = max(0.0, min(1.0, value))
        db.update("jobs", self.id, {"progress": value, "message": message})
        self.manager.publish({"type": "job", "job": self.manager.public_job(self.id)})

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCanceled()

    @property
    def canceled(self) -> bool:
        return self._cancel.is_set()

    def add_cost(self, usd: float) -> None:
        self.cost_usd += usd

    # ---- providers
    def provider(self, kind: str):
        from .providers import get_provider
        return get_provider(kind, self.providers.get(kind))

    def provider_name(self, kind: str) -> str:
        return self.providers.get(kind, "")

    # ---- assets
    def input_parents(self) -> list[str]:
        ids: list[str] = []
        for k, v in self.params.items():
            if isinstance(v, str) and v.startswith("ast_"):
                ids.append(v)
            elif isinstance(v, list):
                ids.extend(x for x in v if isinstance(x, str) and x.startswith("ast_"))
        return ids

    def save_image(self, img: Image.Image, name: str, *, kind: str = "image", meta: dict | None = None,
                   parents: list[str] | None = None, role: str = "output") -> dict[str, Any]:
        meta = dict(meta or {})
        meta.setdefault("providers", self.providers)
        asset = storage.save_image(self.project_id, img, name=name, kind=kind, meta=meta,
                                   parents=parents if parents is not None else self.input_parents(),
                                   job_id=self.id, capability=self.job["capability"], role=role)
        self.assets.append(asset)
        return asset

    def register(self, asset: dict[str, Any]) -> dict[str, Any]:
        self.assets.append(asset)
        return asset

    async def blocking(self, fn: Callable, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)


class JobManager:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lanes: dict[str, asyncio.Semaphore] = {}
        self.cancel_flags: dict[str, asyncio.Event] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.subscribers: set[asyncio.Queue] = set()

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        q = get_settings()["queue"]
        self.lanes = {name: asyncio.Semaphore(max(1, int(q.get(name, 1)))) for name in ("gpu", "cloud", "cpu")}
        for job in db.query("SELECT * FROM jobs WHERE status IN ('queued','running')"):
            if job["status"] == "running":
                db.update("jobs", job["id"], {"status": "failed", "error": "服务重启导致任务中断，可点击重试",
                                              "finished_at": db.now()})
            else:
                self._spawn(job["id"])

    # ---- events
    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def public_job(self, job_id: str) -> dict[str, Any] | None:
        job = db.get("jobs", job_id)
        return job

    # ---- submit / run
    async def submit(self, capability_id: str, params: dict[str, Any], project_id: str | None,
                     source: str = "web") -> dict[str, Any]:
        from . import capabilities
        from .providers import resolve_lane, resolve_providers

        cap = capabilities.get(capability_id)
        params = capabilities.validate(cap, params)
        if not project_id:
            project_id = ensure_default_project()
        providers = await resolve_providers(cap.needs, params)
        lane = resolve_lane(providers)
        job = db.insert("jobs", {
            "id": db.new_id("job"), "project_id": project_id, "capability": cap.id, "params": params,
            "status": "queued", "progress": 0, "message": "排队中", "lane": lane, "providers": providers,
            "result": [], "source": source, "created_at": db.now(),
        })
        self.publish({"type": "job", "job": job})
        self._spawn(job["id"])
        return job

    def _spawn(self, job_id: str) -> None:
        assert self.loop is not None
        self.tasks[job_id] = self.loop.create_task(self._run(job_id))

    async def _run(self, job_id: str) -> None:
        from . import capabilities

        job = db.get("jobs", job_id)
        if not job:
            return
        sem = self.lanes.get(job["lane"], self.lanes["cpu"])
        flag = self.cancel_flags.setdefault(job_id, asyncio.Event())
        async with sem:
            if flag.is_set():
                return
            job = db.update("jobs", job_id, {"status": "running", "started_at": db.now(), "message": "运行中"})
            self.publish({"type": "job", "job": job})
            ctx = JobContext(self, job)
            try:
                cap = capabilities.get(job["capability"])
                await cap.run(ctx, job["params"])
                ctx.check()
                job = db.update("jobs", job_id, {
                    "status": "succeeded", "progress": 1, "message": "完成",
                    "result": [a["id"] for a in ctx.assets], "cost_usd": ctx.cost_usd, "finished_at": db.now(),
                })
            except (JobCanceled, asyncio.CancelledError):
                job = db.update("jobs", job_id, {"status": "canceled", "message": "已取消",
                                                 "result": [a["id"] for a in ctx.assets], "finished_at": db.now()})
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                job = db.update("jobs", job_id, {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                                                 "message": "失败", "result": [a["id"] for a in ctx.assets],
                                                 "cost_usd": ctx.cost_usd, "finished_at": db.now()})
            finally:
                self.tasks.pop(job_id, None)
                self.cancel_flags.pop(job_id, None)
            self.publish({"type": "job", "job": job})
            if ctx.assets:
                self.publish({"type": "assets", "project_id": job["project_id"],
                              "assets": [storage.serialize(a) for a in ctx.assets]})

    async def cancel(self, job_id: str) -> dict[str, Any] | None:
        job = db.get("jobs", job_id)
        if not job:
            return None
        self.cancel_flags.setdefault(job_id, asyncio.Event()).set()
        if job["status"] == "queued":
            task = self.tasks.pop(job_id, None)
            if task:
                task.cancel()
            job = db.update("jobs", job_id, {"status": "canceled", "message": "已取消", "finished_at": db.now()})
            self.publish({"type": "job", "job": job})
        return job

    async def retry(self, job_id: str) -> dict[str, Any]:
        job = db.get("jobs", job_id)
        if not job:
            raise KeyError(job_id)
        return await self.submit(job["capability"], job["params"], job["project_id"], source=job["source"])

    async def wait(self, job_id: str, timeout: float | None = None) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout if timeout else None
        while True:
            job = db.get("jobs", job_id)
            if job and job["status"] in ("succeeded", "failed", "canceled"):
                return job
            if end and loop.time() > end:
                return job  # type: ignore[return-value]
            await asyncio.sleep(0.5)


def ensure_default_project() -> str:
    rows = db.query("SELECT id FROM projects WHERE kind='inbox' LIMIT 1")
    if rows:
        return rows[0]["id"]
    p = db.insert("projects", {"id": db.new_id("prj"), "name": "收件箱 (Agent/API)", "kind": "inbox",
                               "description": "Agent / API 未指定项目时的默认落盘位置", "style": {}, "viewport": {},
                               "created_at": db.now(), "updated_at": db.now()})
    return p["id"]


manager = JobManager()


def job_summary(job: dict[str, Any]) -> str:
    return json.dumps({k: job.get(k) for k in ("id", "capability", "status", "progress", "message")}, ensure_ascii=False)
