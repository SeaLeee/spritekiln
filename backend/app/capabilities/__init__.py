"""Capability registry. A capability = one public workflow (like meowa's /api/workflows/<id>/run).

The param schema drives: the web form, REST validation, the CLI (kiln_api.py) and the MCP tool schema.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class Param:
    name: str
    type: str  # text | longtext | int | float | bool | select | image | images | color | lines
    label: str
    default: Any = None
    choices: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    help: str = ""
    required: bool = False
    show_if: dict[str, Any] | None = None
    advanced: bool = False


@dataclass
class Capability:
    id: str
    name: str
    module: str
    description: str
    params: list[Param]
    run: Callable[[Any, dict[str, Any]], Awaitable[None]]
    needs: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    outputs: str = "image"
    icon: str = "sparkles"
    hint: str = ""

    def schema(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("run")
        return d


REGISTRY: dict[str, Capability] = {}
ALIASES: dict[str, str] = {}

MODULES = {
    "pixel": {"name": "像素美术", "desc": "像素角色、道具、素材包"},
    "hd": {"name": "高清美术", "desc": "高清角色、道具、素材包、通用生成"},
    "edit": {"name": "编辑与后处理", "desc": "去背景、像素化、万能编辑、变体、拆分"},
    "character": {"name": "角色", "desc": "多方向角色、立绘"},
    "ui": {"name": "游戏 UI", "desc": "HUD、菜单、按钮与图标"},
    "map": {"name": "游戏地图", "desc": "无缝纹理、地块、等角、横版视差"},
    "animation": {"name": "动画", "desc": "帧动画、关键帧、视频"},
    "threed": {"name": "3D 管线", "desc": "单图/多视角 → 3D 模型 → 8 方向精灵"},
    "design": {"name": "策划 Agent", "desc": "玩法、系统与设计文档"},
}


def register(cap: Capability) -> Capability:
    REGISTRY[cap.id] = cap
    for a in cap.aliases:
        ALIASES[a] = cap.id
    return cap


def get(cap_id: str) -> Capability:
    cid = ALIASES.get(cap_id, cap_id)
    if cid not in REGISTRY:
        raise KeyError(f"未知能力: {cap_id}")
    return REGISTRY[cid]


def _coerce(p: Param, v: Any) -> Any:
    if v is None or v == "":
        return p.default
    t = p.type
    if t == "int":
        v = int(float(v))
    elif t == "float":
        v = float(v)
    elif t == "bool":
        v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
    elif t in ("images", "lines"):
        if isinstance(v, str):
            v = [x.strip() for x in v.replace("\r", "").split("\n" if t == "lines" else ",") if x.strip()]
        v = list(v)
    elif t == "select" and p.choices:
        values = [c["value"] if isinstance(c, dict) else c for c in p.choices]
        if v not in values:
            # tolerate numbers sent as strings
            match = [x for x in values if str(x) == str(v)]
            if not match:
                raise ValueError(f"参数 {p.name} 取值 {v!r} 不在 {values}")
            v = match[0]
    if t in ("int", "float"):
        if p.min is not None and v < p.min:
            v = type(v)(p.min)
        if p.max is not None and v > p.max:
            v = type(v)(p.max)
    return v


def validate(cap: Capability, params: dict[str, Any]) -> dict[str, Any]:
    params = dict(params or {})
    out: dict[str, Any] = {}
    for p in cap.params:
        out[p.name] = _coerce(p, params.pop(p.name, None))
        if p.required and out[p.name] in (None, "", []):
            raise ValueError(f"缺少必填参数: {p.name} ({p.label})")
    # pass-through provider overrides
    for k in ("provider", "video_provider", "threed_provider", "llm_provider", "bg_method"):
        if k in params and k not in out:
            out[k] = params[k]
    return out


def catalog() -> list[dict[str, Any]]:
    return [c.schema() for c in REGISTRY.values()]


# import capability modules for registration side-effects
from . import image_caps, edit_caps, map_caps, anim_caps, threed_caps, design_caps  # noqa: E402,F401
