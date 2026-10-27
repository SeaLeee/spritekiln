"""Kiln Agent: natural language → capability plan (LLM with JSON output, or rule router fallback) → chained jobs."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .. import capabilities, db
from ..jobs import manager
from ..providers import get_provider, resolve

SYSTEM = """你是 SpriteKiln 的游戏素材制作 Agent。根据用户需求，从能力目录中选择最少、最合适的能力，组成执行计划。
规则：
- 先定“素材契约”：像素还是高清、尺寸、数量、是否透明、是否需要动画。
- 能用一个能力就不要串联；需要串联时，后一步的图片参数写 "$prev"（上一步第一张产出）或 "$stepN"（第 N 步第一张产出）。
- 用户附带的素材 id 以 ast_ 开头，可直接作为图片参数。
- 提示词用简单自然语言（可中文），不要堆关键词。
- 只输出 JSON：{"reply": "给用户的简短中文说明", "plan": [{"capability": "<id>", "params": {...}, "why": "..."}]}
- 如果只是聊天/咨询，plan 为空数组。
能力目录：
"""


def catalog_text() -> str:
    lines = []
    for c in capabilities.REGISTRY.values():
        ps = ", ".join(f"{p.name}:{p.type}" + (f"={p.default}" if p.default not in (None, "", [], -1) else "")
                       for p in c.params if not p.advanced and p.name not in ("provider", "seed"))
        lines.append(f"- {c.id}（{c.name}）：{c.description} 参数[{ps}]")
    return "\n".join(lines)


RULES: list[tuple[list[str], str]] = [
    (["关键帧", "keyframe"], "keyframes_animate"),
    (["动画", "animation", "animate", "走路", "行走", "跑步", "待机", "攻击动作", "跳跃", "walk", "idle", "run cycle"], "animate"),
    (["视频", "video", "过场"], "video_gen"),
    (["8方向", "八方向", "多方向", "转面", "turnaround", "四方向", "multi-view", "8个方向", "8direction"], "character_multi_view"),
    (["多视角3d", "多视角 3d", "multiview"], "multiview_3d"),
    (["3d", "三维", "模型", "glb"], "image_to_3d"),
    (["地块", "tileset", "瓦片"], "tileset_gen"),
    (["等角", "isometric", "45度"], "isometric_tile"),
    (["横版", "视差", "parallax", "side-scroll"], "side_scrolling_map"),
    (["纹理", "texture", "材质"], "texture_gen"),
    (["ui", "按钮", "界面", "hud", "菜单", "血条"], "ui_gen"),
    (["去背景", "抠图", "透明背景", "remove background"], "remove_background"),
    (["像素化", "pixelate", "转像素"], "pixelate"),
    (["变体", "升级", "variant", "upgrade"], "asset_variants"),
    (["克隆", "同风格", "clone"], "asset_clone"),
    (["拆分", "切图", "split"], "split_components"),
    (["策划", "玩法", "设计文档", "gdd", "数值", "关卡设计", "系统设计"], "game_design"),
    (["修改", "编辑", "换成", "改成", "edit"], "image_edit"),
    (["高清", "hd", "立绘", "插画"], "hd_gen"),
    (["场景", "背景", "建筑", "scene", "background"], "pixel_universal"),
]
TEMPLATE_RULES = [(["武器", "剑", "weapon", "sword"], "px_weapon_64"), (["食物", "food"], "px_food_64"),
                  (["图标", "icon"], "px_icon_32"), (["怪", "monster", "enemy", "史莱姆"], "px_monster_64"),
                  (["动物", "宠物", "animal", "pet"], "px_animal_64"), (["建筑", "building", "房子"], "px_building_128"),
                  (["道具", "item", "物品", "prop"], "px_item_64"), (["头像", "portrait"], "px_portrait_96")]


def _pick(words: list[str], text: str) -> bool:
    return any(w in text for w in words)


ACTION_WORDS = ["做", "生成", "画", "来", "给我", "制作", "创建", "make", "create", "generate", "draw", "design", "写"]


def _actionable(message: str) -> bool:
    text = re.sub(r"\s+", "", message.lower())
    return _pick(ACTION_WORDS, text) or any(_pick(w, text) for w, _ in RULES)


def rule_plan(message: str, attachments: list[str]) -> tuple[str, list[dict]]:
    text = re.sub(r"\s+", "", message.lower())
    cap = None
    for words, cid in RULES:
        if _pick(words, text):
            cap = cid
            break
    needs_source = {"animate", "remove_background", "pixelate", "asset_variants", "asset_clone", "split_components",
                    "image_edit"}
    src = attachments[0] if attachments else None
    plan: list[dict] = []
    if cap in needs_source and not src:
        # generate a base sprite first, then chain
        plan.append({"capability": "custom_size_pixel", "params": {"prompt": message, "width": 64, "height": 64},
                     "why": "先生成一个定稿素材"})
        src = "$prev"
    if cap is None:
        template = next((t for words, t in TEMPLATE_RULES if _pick(words, text)), "px_char_64")
        cap = "pixel_gen"
        params: dict[str, Any] = {"template": template, "prompt": message}
    elif cap == "pixel_gen":
        params = {"prompt": message}
    elif cap in ("animate",):
        params = {"source": src, "prompt": message}
    elif cap == "keyframes_animate":
        params = {"keyframes": attachments, "prompt": message}
    elif cap == "video_gen":
        params = {"first_frame": src, "prompt": message}
    elif cap in ("character_multi_view", "image_to_3d", "multiview_3d"):
        params = {"source": src, "prompt": message}
    elif cap in ("remove_background", "pixelate", "split_components"):
        params = {"source": src}
    elif cap == "asset_variants":
        params = {"source": src}
    elif cap == "asset_clone":
        params = {"reference": src}
    elif cap == "image_edit":
        params = {"source": src, "prompt": message}
    elif cap == "tileset_gen":
        params = {"foreground_prompt": message}
    elif cap == "game_design":
        params = {"prompt": message}
    else:
        params = {"prompt": message}
    params = {k: v for k, v in params.items() if v is not None}
    plan.append({"capability": cap, "params": params, "why": "关键词路由"})
    names = " → ".join(capabilities.get(s["capability"]).name for s in plan)
    return f"（规则路由）将执行：{names}", plan


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def plan_for(message: str, attachments: list[str], history: list[dict]) -> tuple[str, list[dict], str]:
    llm_name = await resolve("llm")
    llm = get_provider("llm", llm_name)
    if llm_name != "rules":
        msgs = [{"role": "system", "content": SYSTEM + catalog_text()}]
        msgs += [{"role": m["role"], "content": m["content"]} for m in history[-8:] if m["role"] in ("user", "assistant")]
        att = f"\n附带素材: {', '.join(attachments)}" if attachments else ""
        msgs.append({"role": "user", "content": message + att})
        try:
            # Reasoning models occasionally answer in prose despite json_mode; one retry is
            # cheaper than dropping straight to the keyword router.
            data = None
            for _ in range(2):
                raw = await llm.chat(msgs, temperature=0.2, json_mode=True, max_tokens=1500)
                data = _extract_json(raw)
                if data is not None:
                    break
            if data is not None:
                plan = [s for s in data.get("plan", []) if s.get("capability") in capabilities.REGISTRY
                        or s.get("capability") in capabilities.ALIASES]
                if plan or not _actionable(message):
                    return data.get("reply", "") or raw[:400], plan, llm_name
            reply, plan = rule_plan(message, attachments)
            return f"（{llm.label} 未给出可执行计划，已用规则路由）\n{reply}", plan, "rules"
        except Exception as exc:  # noqa: BLE001
            reply, plan = rule_plan(message, attachments)
            return f"大模型不可用（{type(exc).__name__}），已切换规则路由。\n{reply}", plan, "rules"
    reply, plan = rule_plan(message, attachments)
    return reply, plan, "rules"


def _first_output(job: dict) -> str | None:
    ids = job.get("result") or []
    if not ids:
        return None
    rows = [db.get("assets", i) for i in ids]
    outs = [r for r in rows if r and r.get("role") == "output"]
    return (outs or [r for r in rows if r])[0]["id"]


def _substitute(value: Any, outputs: list[str | None]) -> Any:
    if isinstance(value, str):
        if value == "$prev":
            return outputs[-1] if outputs else None
        m = re.fullmatch(r"\$step(\d+)", value)
        if m:
            i = int(m.group(1)) - 1
            return outputs[i] if 0 <= i < len(outputs) else None
        return value
    if isinstance(value, list):
        return [_substitute(v, outputs) for v in value]
    return value


async def run_plan(plan: list[dict], project_id: str, thread_id: str | None = None, source: str = "agent") -> list[str]:
    """Submit step 1 now; later steps run in the background as soon as their inputs exist."""
    if not plan:
        return []
    first = plan[0]
    job = await manager.submit(first["capability"], _substitute(first.get("params", {}), []), project_id, source)
    job_ids = [job["id"]]
    if len(plan) > 1:
        asyncio.get_running_loop().create_task(_continue(plan, job, project_id, thread_id, source))
    return job_ids


async def _continue(plan: list[dict], first_job: dict, project_id: str, thread_id: str | None, source: str) -> None:
    outputs: list[str | None] = []
    job = first_job
    for i, step in enumerate(plan):
        if i > 0:
            params = {k: _substitute(v, outputs) for k, v in step.get("params", {}).items()}
            job = await manager.submit(step["capability"], params, project_id, source)
            if thread_id:
                add_message(thread_id, project_id, "assistant", f"▶ 第 {i + 1} 步：{capabilities.get(step['capability']).name}",
                            {"job_ids": [job["id"]]})
        done = await manager.wait(job["id"])
        if done["status"] != "succeeded":
            if thread_id:
                add_message(thread_id, project_id, "assistant", f"✖ 第 {i + 1} 步失败：{done.get('error')}", {})
            return
        outputs.append(_first_output(done))


def add_message(thread_id: str, project_id: str | None, role: str, content: str, data: dict | None = None) -> dict:
    return db.insert("messages", {"id": db.new_id("msg"), "thread_id": thread_id, "project_id": project_id, "role": role,
                                  "content": content, "data": data or {}, "created_at": db.now()})


def history(thread_id: str) -> list[dict]:
    return db.query("SELECT * FROM messages WHERE thread_id=? ORDER BY created_at", (thread_id,))


async def chat(project_id: str, thread_id: str | None, message: str, attachments: list[str], execute: bool = True) -> dict:
    thread_id = thread_id or db.new_id("thr")
    hist = history(thread_id)
    add_message(thread_id, project_id, "user", message, {"attachments": attachments})
    reply, plan, llm_name = await plan_for(message, attachments, hist)
    job_ids: list[str] = []
    error = None
    if execute and plan:
        try:
            job_ids = await run_plan(plan, project_id, thread_id)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
    text = reply or "好的。"
    if error:
        text += f"\n\n执行失败：{error}"
    msg = add_message(thread_id, project_id, "assistant", text, {"plan": plan, "job_ids": job_ids, "llm": llm_name})
    return {"thread_id": thread_id, "message": msg, "plan": plan, "job_ids": job_ids, "llm": llm_name}
