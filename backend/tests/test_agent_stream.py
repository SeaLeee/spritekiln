"""Streaming planner: OpenAI-compatible SSE parsing and agent.chat_stream event order (offline)."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SPRITEKILN_DATA", tempfile.mkdtemp(prefix="spritekiln_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import agent  # noqa: E402
from app.providers.util import parse_sse_line  # noqa: E402


def test_parse_sse_line_reads_reasoning_and_content():
    assert parse_sse_line('data: {"choices":[{"delta":{"reasoning_content":"先想"}}]}') == [("reasoning", "先想")]
    assert parse_sse_line('data: {"choices":[{"delta":{"reasoning":"再想"}}]}') == [("reasoning", "再想")]
    assert parse_sse_line('data: {"choices":[{"delta":{"content":"{\\"plan\\":[]}"}}]}') == [("content", '{"plan":[]}')]
    assert parse_sse_line('data: {"choices":[{"delta":{"role":"assistant"}}]}') == []
    assert parse_sse_line("data: [DONE]") == []
    assert parse_sse_line(": ping") == []
    assert parse_sse_line("data: not-json") == []


def test_parse_sse_line_handles_non_streamed_body():
    """A proxy that ignores stream:true answers with one plain completion body."""
    body = '{"choices":[{"message":{"reasoning_content":"想了","content":"{\\"plan\\":[]}"}}]}'
    assert parse_sse_line(body) == [("reasoning", "想了"), ("content", '{"plan":[]}')]


def test_chat_stream_with_rules_emits_plan_and_done(monkeypatch):
    async def fake_resolve(kind, override=None):
        return "rules"

    monkeypatch.setattr(agent, "resolve", fake_resolve)

    async def run():
        return [ev async for ev in agent.chat_stream(None, None, "做 4 个 64px 的森林小怪", [], execute=False)]

    events = asyncio.run(run())
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done"
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["llm"] == "rules"
    assert plan["plan"] and plan["plan"][0]["capability"] in ("pixel_gen", "custom_size_pixel")
    done = events[-1]
    assert done["thread_id"].startswith("thr_")
    assert done["error"] is None
    # The transcript is persisted, so reopening the thread shows the same reply.
    shown = [m for m in agent.history(done["thread_id"]) if m["role"] == "assistant"]
    assert shown and shown[-1]["content"] == done["message"]["content"]
