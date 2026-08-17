"""End-to-end boundary coverage for the opt-in V0 orchestration lane."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse


def _provider(*responses: LLMResponse) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=2_000)
    provider.chat_with_retry = AsyncMock(side_effect=responses)
    provider.chat_stream_with_retry = AsyncMock(side_effect=responses)
    return provider


@pytest.mark.asyncio
async def test_opt_in_orchestration_creates_session_owned_receipts(tmp_path) -> None:
    planner = LLMResponse(content="""{
      \"mode\": \"orchestrate\",
      \"nodes\": [
        {\"id\": \"facts\", \"actor\": \"subagent\", \"goal\": \"收集事实\", \"deliverable\": \"资料\", \"acceptance\": [\"两个来源\"], \"depends_on\": [], \"resource_claims\": []},
        {\"id\": \"risks\", \"actor\": \"subagent\", \"goal\": \"分析风险\", \"deliverable\": \"风险\", \"acceptance\": [\"列出风险\"], \"depends_on\": [], \"resource_claims\": []}
      ]
    }""")
    provider = _provider(planner, LLMResponse(content="综合结论"))
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        orchestration_enabled=True,
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)
    loop.subagents.run_inline = AsyncMock(side_effect=["事实结果", "风险结果"])

    outbound = await loop.process_direct(
        "请分别调研两家供应商并比较价格与交付风险",
        session_key="webui:one",
        channel="webui",
        chat_id="one",
    )

    assert outbound is not None
    assert outbound.content == "综合结论"
    assert loop.subagents.run_inline.await_count == 2
    assert [call.kwargs["tools"] for call in provider.chat_with_retry.await_args_list] == [[], []]
    session = loop.sessions.get_or_create("webui:one")
    harness = session.metadata["orchestration.v1"]["harness_v0"]
    assert harness["plans"][0]["status"] == "completed"
    assert {item["status"] for item in harness["receipts"]} == {"accepted"}
    assert session.metadata["orchestration.v1"]["task_frames"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_disabled_harness_keeps_candidate_request_on_existing_runner(tmp_path) -> None:
    provider = _provider(LLMResponse(content="正常 Runner 回答"))
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        orchestration_enabled=False,
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.subagents.run_inline = AsyncMock()

    outbound = await loop.process_direct(
        "请分别调研两家供应商并比较价格与交付风险",
        session_key="webui:one",
        channel="webui",
        chat_id="one",
    )

    assert outbound is not None
    assert outbound.content == "正常 Runner 回答"
    assert loop.subagents.run_inline.await_count == 0
    assert provider.chat_with_retry.await_count == 1


@pytest.mark.asyncio
async def test_cancelled_orchestration_stops_plan_and_cancels_frame(tmp_path) -> None:
    planner = LLMResponse(content="""{
      \"mode\": \"orchestrate\",
      \"nodes\": [
        {\"id\": \"facts\", \"actor\": \"subagent\", \"goal\": \"收集事实\", \"deliverable\": \"资料\", \"acceptance\": [\"两个来源\"], \"depends_on\": [], \"resource_claims\": []},
        {\"id\": \"risks\", \"actor\": \"subagent\", \"goal\": \"分析风险\", \"deliverable\": \"风险\", \"acceptance\": [\"列出风险\"], \"depends_on\": [], \"resource_claims\": []}
      ]
    }""")
    provider = _provider(planner)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        orchestration_enabled=True,
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)
    started = asyncio.Event()

    async def wait_for_worker(**_kwargs):
        started.set()
        await asyncio.Event().wait()

    loop.subagents.run_inline = AsyncMock(side_effect=wait_for_worker)
    task = asyncio.create_task(loop.process_direct(
        "请分别调研两家供应商并比较价格与交付风险",
        session_key="webui:one",
        channel="webui",
        chat_id="one",
    ))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    session = loop.sessions.get_or_create("webui:one")
    harness = session.metadata["orchestration.v1"]["harness_v0"]
    assert harness["plans"][0]["status"] == "stopped"
    assert session.metadata["orchestration.v1"]["task_frames"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_observe_only_orchestration_records_decision_without_state(tmp_path) -> None:
    """Shadow mode runs the planner but creates no frame/plan/worker."""
    planner = LLMResponse(content="""{
      "mode": "orchestrate",
      "nodes": [
        {"id": "facts", "actor": "subagent", "goal": "收集事实", "deliverable": "资料", "acceptance": ["两个来源"], "depends_on": [], "resource_claims": []},
        {"id": "risks", "actor": "subagent", "goal": "分析风险", "deliverable": "风险", "acceptance": ["列出风险"], "depends_on": [], "resource_claims": []}
      ]
    }""")
    provider = _provider(planner, LLMResponse(content="正常 Runner 回答"))
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        orchestration_observe=True,
        orchestration_enabled=False,
    )
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.subagents.run_inline = AsyncMock()

    outbound = await loop.process_direct(
        "请分别调研两家供应商并比较价格与交付风险",
        session_key="webui:one",
        channel="webui",
        chat_id="one",
    )

    # Shadow mode: planner consumed one model call, but the turn still runs on
    # the existing Runner (second model call) and no worker is spawned.
    assert outbound is not None
    assert outbound.content == "正常 Runner 回答"
    assert loop.subagents.run_inline.await_count == 0
    assert provider.chat_with_retry.await_count == 2
    session = loop.sessions.get_or_create("webui:one")
    assert "orchestration.v1" not in session.metadata
    assert "task_frames" not in session.metadata
