"""Strict planner boundary coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.execution_planner import plan_execution, should_consider_orchestration
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(provider: MagicMock) -> LLMRuntime:
    provider.generation = GenerationSettings(max_tokens=4_096)
    return LLMRuntime.capture(provider, "test-model", context_window_tokens=16_000)


def test_candidate_gate_keeps_ordinary_work_out_of_planner() -> None:
    assert should_consider_orchestration("帮我写一封邮件") is False
    assert should_consider_orchestration("请分别调研两家供应商并比较价格与交付风险") is True


@pytest.mark.asyncio
async def test_invalid_planner_output_fails_closed_to_runner() -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="not json"))

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别调研两家供应商并比较价格与交付风险",
        history=[],
    )

    assert decision.mode == "direct"
    assert decision.reason == "planner_invalid_output"
    call = provider.chat_with_retry.await_args
    assert call.kwargs["tools"] == []
    assert call.kwargs["max_tokens"] == 2_048
    assert call.kwargs["temperature"] == 0
    assert call.kwargs["reasoning_effort"] == "low"
    provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_truncated_planner_output_is_never_repaired_or_executed() -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content='{"mode":"orchestrate","nodes":[]}',
        finish_reason="length",
    ))

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别调研两家供应商并比较价格与交付风险",
        history=[],
    )

    assert decision.mode == "direct"
    assert decision.reason == "planner_unusable_response"


@pytest.mark.asyncio
async def test_explicit_split_prefers_orchestration_without_forcing_it() -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content='{"mode": "direct"}')
    )

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别分析模块甲和模块乙，并比较它们的职责差异",
        history=[],
    )

    assert decision.mode == "direct"
    prompt = provider.chat_with_retry.await_args.args[0][0]["content"]
    assert "Prefer mode=orchestrate" in prompt
    assert "final comparison or synthesis" in prompt
    assert "Independent read-only work uses [] by default" in prompt
    assert "exclusive:<stable-resource-id>" in prompt
    assert "web search or viewing context are not resource_claims" in prompt


@pytest.mark.asyncio
async def test_planner_accepts_only_subagent_dag() -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="""{
      \"mode\": \"orchestrate\",
      \"nodes\": [
        {\"id\": \"facts\", \"actor\": \"subagent\", \"goal\": \"收集事实\", \"deliverable\": \"资料\", \"acceptance\": [\"两个来源\"], \"depends_on\": [], \"resource_claims\": []},
        {\"id\": \"risks\", \"actor\": \"subagent\", \"goal\": \"分析风险\", \"deliverable\": \"风险\", \"acceptance\": [\"列出风险\"], \"depends_on\": [\"facts\"], \"resource_claims\": []}
      ]
    }"""))

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别调研两家供应商并比较价格与交付风险",
        history=[],
    )

    assert decision.mode == "orchestrate"
    assert [node.id for node in decision.nodes] == ["facts", "risks"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resource_claim", ["web search", "exclusive:"])
async def test_planner_rejects_nonexclusive_resource_claims(resource_claim: str) -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="""{
      "mode": "orchestrate",
      "nodes": [
        {"id": "facts", "actor": "subagent", "goal": "收集事实", "deliverable": "资料", "acceptance": ["两个来源"], "depends_on": [], "resource_claims": ["%s"]},
        {"id": "risks", "actor": "subagent", "goal": "分析风险", "deliverable": "风险", "acceptance": ["列出风险"], "depends_on": [], "resource_claims": []}
      ]
    }""" % resource_claim))

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别调研两家供应商并比较价格与交付风险",
        history=[],
    )

    assert decision.mode == "direct"
    assert decision.reason == "planner_invalid_output"


@pytest.mark.asyncio
async def test_planner_accepts_specific_exclusive_resource_claims() -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="""{
      "mode": "orchestrate",
      "nodes": [
        {"id": "write_a", "actor": "subagent", "goal": "写入报告", "deliverable": "报告", "acceptance": ["保存"], "depends_on": [], "resource_claims": ["exclusive:workspace:file:report.md"]},
        {"id": "write_b", "actor": "subagent", "goal": "检查报告", "deliverable": "检查结果", "acceptance": ["完成检查"], "depends_on": [], "resource_claims": ["exclusive:workspace:file:report.md"]}
      ]
    }"""))

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别编写报告并检查报告的内容与格式",
        history=[],
    )

    assert decision.mode == "orchestrate"
    assert all(node.resource_claims == ("exclusive:workspace:file:report.md",) for node in decision.nodes)


@pytest.mark.asyncio
async def test_planner_repairs_common_json_wrapping_without_another_model_call() -> None:
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="""```json
    {mode: orchestrate, nodes: [
      {id: facts, actor: subagent, goal: 收集事实, deliverable: 资料,
       acceptance: [两个来源], depends_on: [], resource_claims: []},
      {id: risks, actor: subagent, goal: 分析风险, deliverable: 风险,
       acceptance: [列出风险], depends_on: [facts], resource_claims: []}
    ]}
    ```"""))

    decision = await plan_execution(
        provider=provider,
        runtime=_runtime(provider),
        user_text="请分别调研两家供应商并比较价格与交付风险",
        history=[],
    )

    assert decision.mode == "orchestrate"
    assert [node.id for node in decision.nodes] == ["facts", "risks"]
    provider.chat_with_retry.assert_awaited_once()
