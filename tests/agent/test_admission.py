"""Regression coverage for the Slice 3 continuation admission gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.admission import assess_admission, runtime_context_for_anchor
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse, ProviderConversationState


def _task_frames(*frames: tuple[str, str]) -> dict[str, object]:
    return {
        "orchestration.v1": {
            "task_frames": [
                {"id": task_id, "goal": goal, "status": "ready"}
                for task_id, goal in frames
            ]
        }
    }


def test_non_continuation_keeps_existing_path() -> None:
    decision = assess_admission("帮我写一封邮件", {})
    assert decision.action == "pass"
    assert decision.reason == "not_continuation"


def test_single_task_frame_admits_and_adds_current_turn_context() -> None:
    decision = assess_admission("继续", _task_frames(("task-1", "整理调研结论")))
    assert decision.action == "continue"
    assert decision.reason == "single_task_frame"
    assert decision.anchor is not None
    block = runtime_context_for_anchor(decision.anchor)
    assert block is not None
    assert block.source == "admission_gate"
    assert "task-1" in block.content
    assert "整理调研结论" in block.content


def test_active_sustained_goal_is_an_unambiguous_continuation_anchor() -> None:
    decision = assess_admission(
        "继续吧",
        {"goal_state": {"status": "active", "objective": "完成切片三开发"}},
    )
    assert decision.action == "continue"
    assert decision.reason == "active_goal"
    assert decision.anchor is None


def test_multiple_task_frames_require_selection() -> None:
    decision = assess_admission(
        "按这个办",
        _task_frames(("task-1", "准备方案"), ("task-2", "运行回归")),
    )
    assert decision.action == "clarify"
    assert decision.reason == "multiple_task_frames"
    assert decision.candidate_count == 2
    assert decision.clarification is not None
    assert "准备方案" in decision.clarification
    assert "运行回归" in decision.clarification


def test_continuation_without_anchor_requires_clarification() -> None:
    decision = assess_admission("继续", {})
    assert decision.action == "clarify"
    assert decision.reason == "no_task_anchor"


def test_experimental_config_defaults_and_aliases() -> None:
    assert Config().agents.defaults.experimental.admission_gate is False
    assert Config().agents.defaults.experimental.observe_admission is False
    config = Config(agents={"defaults": {"experimental": {
        "admissionGate": True,
        "observeAdmission": True,
    }}})
    assert config.agents.defaults.experimental.admission_gate is True
    assert config.agents.defaults.experimental.observe_admission is True


@pytest.mark.asyncio
async def test_gate_short_circuits_runner_and_persists_a_complete_turn(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="should not run", usage={}))
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        admission_gate=True,
    )
    session = loop.sessions.get_or_create("cli:c1")
    session.provider_state = ProviderConversationState(
        kind="openai_responses",
        provider="openai:test",
        model="test-model",
        version=1,
        payload={"items": []},
    )

    result = await loop._process_message(InboundMessage(
        channel="cli", sender_id="user", chat_id="c1", content="继续"
    ))

    assert result is not None
    assert "明确任务" in result.content
    provider.chat_with_retry.assert_not_awaited()
    assert [(message["role"], message["content"]) for message in session.messages] == [
        ("user", "继续"),
        ("assistant", result.content),
    ]
    assert session.provider_state is None
    assert "_pending_user_turn" not in session.metadata


@pytest.mark.asyncio
async def test_gate_off_keeps_a_continuation_on_the_existing_runner_path(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="runner answer", usage={}))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")

    result = await loop._process_message(InboundMessage(
        channel="cli", sender_id="user", chat_id="c1", content="继续"
    ))

    assert result is not None
    assert result.content == "runner answer"
    provider.chat_with_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_marks_ephemeral_clarification_like_the_standard_path(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="should not run", usage={}))
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        admission_gate=True,
    )

    result = await loop.process_direct("继续", session_key="cli:c1", ephemeral=True)

    assert result is not None
    assert result.metadata["_stop_reason"] == "admission_clarify"
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_anchor_reaches_runner_as_runtime_context(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="continued", usage={}))
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        admission_gate=True,
    )
    session = loop.sessions.get_or_create("cli:c1")
    session.metadata.update(_task_frames(("task-1", "整理调研结论")))

    result = await loop._process_message(InboundMessage(
        channel="cli", sender_id="user", chat_id="c1", content="继续"
    ))

    assert result is not None
    assert result.content == "continued"
    request = provider.chat_with_retry.await_args.kwargs["messages"]
    assert "Task anchor selected by the session admission gate" in str(request)
    assert "整理调研结论" in str(request)
