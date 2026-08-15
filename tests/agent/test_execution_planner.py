"""Strict planner boundary coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.execution_planner import plan_execution, should_consider_orchestration
from nanobot.providers.base import LLMResponse
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(provider: MagicMock) -> LLMRuntime:
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
    assert provider.chat_with_retry.await_args.kwargs["tools"] == []


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
