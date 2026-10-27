"""Game-design agent capability: LLM drafts / revises Markdown design documents stored with the project."""
from __future__ import annotations

import re
from datetime import datetime

from .. import storage
from . import Capability, Param, register

SYSTEM = """你是资深独立游戏策划（Game Designer）。输出结构化的 Markdown 设计文档，内容务实可执行，适合一人/小团队。
文档包含：一句话概念、目标玩家、核心循环(用列表)、核心系统、关卡/内容规划、数值与成长要点、美术风格与素材清单
(按 角色/道具/地图/UI/动画 分组，并给出建议尺寸，如 64x64 像素角色)、技术实现建议(Godot 4)、MVP 范围与里程碑、风险。
只输出 Markdown，不要额外解释。"""

DOC_TYPES = {
    "gdd": "完整游戏设计文档 (GDD)",
    "core_loop": "核心玩法循环与系统设计",
    "asset_list": "美术素材清单（可直接交给素材生成 Agent 执行）",
    "balance": "数值与经济平衡方案",
    "level": "关卡与内容规划",
    "critique": "对现有设计的批判性评审与改进建议",
}


def slug(text: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text).strip("-")
    return s[:40] or "doc"


async def run_game_design(ctx, p: dict) -> None:
    llm = ctx.provider("llm")
    ctx.progress(0.1, f"{llm.label} 撰写中…")
    docs = storage.docs_dir(ctx.project_id)
    context = ""
    if p.get("include_existing"):
        for f in sorted(docs.glob("*.md"))[-3:]:
            context += f"\n\n--- 现有文档 {f.name} ---\n" + f.read_text(encoding="utf-8")[:4000]
    user = f"文档类型：{DOC_TYPES[p['doc_type']]}\n需求：{p['prompt']}{context}"
    md = await llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                        temperature=0.6, max_tokens=4096)
    if llm.name == "rules":
        md = _fallback_doc(p)
    name = f"{datetime.now():%Y%m%d-%H%M}-{p['doc_type']}-{slug(p['prompt'][:20])}.md"
    path = docs / name
    path.write_text(md, encoding="utf-8")
    a = storage.create_asset(ctx.project_id, kind="doc", name=f"策划 · {DOC_TYPES[p['doc_type']]}", path=path,
                             meta={"doc_type": p["doc_type"], "llm": llm.name, "chars": len(md)}, job_id=ctx.id,
                             capability="game_design")
    ctx.register(a)


def _fallback_doc(p: dict) -> str:
    idea = p["prompt"]
    return f"""# {idea[:30]}

> 离线模板生成（未连接大模型）。在 设置 → 模型服务 配置 Ollama / OpenAI 兼容接口后可获得完整策划文档。

## 一句话概念
{idea}

## 核心循环
- 探索 → 收集资源 → 养成/建造 → 解锁新区域 → 再探索

## 美术素材清单
| 类别 | 内容 | 建议规格 | SpriteKiln 能力 |
|---|---|---|---|
| 主角 | 主角 + 4 方向 | 64×64 像素 | pixel_gen → character_multi_view → animate |
| 敌人 | 3 种基础怪 | 64×64 像素 | pixel_gen(px_monster_64) |
| 道具 | 16 个物品图标 | 32×32 像素 | pixel_gen(px_icon_32) |
| 地图 | 草地/泥土地块 | 32px dual-grid | tileset_gen |
| UI | 血条、按钮、背包面板 | 高清/像素 | ui_gen |
| 动画 | 待机/行走/攻击 | 8-16 帧 | animate / keyframes_animate |

## MVP 范围
1. 单场景可玩原型（Godot 4）
2. 主角移动与一种交互
3. 一个敌人与一种战斗反馈
"""


register(Capability(
    "game_design", "策划 Agent", "design",
    "规划核心玩法、系统、数值与素材清单，生成持久化的 Markdown 设计文档（可勾选参考已有文档迭代）。",
    [Param("prompt", "longtext", "游戏想法 / 修改要求", "", required=True),
     Param("doc_type", "select", "文档类型", "gdd", choices=[{"value": k, "label": v} for k, v in DOC_TYPES.items()]),
     Param("include_existing", "bool", "参考项目已有文档", True),
     Param("llm_provider", "select", "大模型", "auto", choices=["auto", "llm_local", "openai", "ark", "minimax", "rules"])],
    run_game_design, needs=["llm"], aliases=["game-design"], outputs="doc", icon="book"))
