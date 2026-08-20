"""固定的 Cache 优化前 Replay A-G 基线。

这些用例只记录当前模型可见 Context 的行为，不预设尚未实现的 CachePlan/Epoch 语义。
后续改造必须在同一组输入下比较消息内容、顺序和稳定前缀。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.runtime_context import RuntimeContextBlock


@dataclass(frozen=True)
class ReplayTurn:
    provider: str
    model: str
    preset: str
    context_window_tokens: int
    user_message: str


REPLAY_TURNS = {
    "same_model": (
        ReplayTurn("deepseek", "deepseek-chat", "deep", 64_000, "第一轮"),
        ReplayTurn("deepseek", "deepseek-chat", "deep", 64_000, "第二轮"),
        ReplayTurn("deepseek", "deepseek-chat", "deep", 64_000, "第三轮"),
    ),
    "cross_provider": (
        ReplayTurn("deepseek", "deepseek-chat", "deep", 64_000, "DeepSeek 输入"),
        ReplayTurn("openai", "gpt-4.1", "gpt", 128_000, "GPT 输入"),
    ),
    "switch_back": (
        ReplayTurn("deepseek", "deepseek-chat", "deep", 64_000, "DeepSeek 首次"),
        ReplayTurn("openai", "gpt-4.1", "gpt", 128_000, "GPT 中间"),
        ReplayTurn("deepseek", "deepseek-chat", "deep", 64_000, "DeepSeek 切回"),
    ),
    "same_provider_different_model": (
        ReplayTurn("openai", "gpt-4.1", "gpt-fast", 128_000, "大模型"),
        ReplayTurn("openai", "gpt-4o-mini", "gpt-small", 32_000, "小模型"),
    ),
    "same_provider_model_different_preset": (
        ReplayTurn("openai", "gpt-4.1", "balanced", 128_000, "平衡 preset"),
        ReplayTurn("openai", "gpt-4.1", "cheap", 128_000, "低成本 preset"),
    ),
}


def _builder(tmp_path: Path) -> ContextBuilder:
    return ContextBuilder(tmp_path / "workspace")


def _turn_messages(
    builder: ContextBuilder,
    history: list[dict[str, str]],
    user_message: str,
) -> list[dict]:
    return builder.build_messages(
        history,
        user_message,
        channel="integration",
        session_key="replay:baseline",
        include_memory=False,
        include_memory_recent_history=False,
    )


def test_replay_a_same_model_keeps_stable_system_prefix(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    history: list[dict[str, str]] = []
    systems: list[str] = []

    for turn in REPLAY_TURNS["same_model"]:
        messages = _turn_messages(builder, history, turn.user_message)
        systems.append(messages[0]["content"])
        history.extend([
            {"role": "user", "content": turn.user_message},
            {"role": "assistant", "content": f"{turn.model} response"},
        ])

    assert systems[0] == systems[1] == systems[2]
    assert [item["content"] for item in history] == [
        "第一轮", "deepseek-chat response", "第二轮", "deepseek-chat response",
        "第三轮", "deepseek-chat response",
    ]


def test_replay_b_tool_loop_appends_results_without_rewriting_history(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    history = [
        {"role": "user", "content": "读取文件"},
        {"role": "assistant", "content": "调用 read_file"},
        {"role": "tool", "content": "文件内容"},
    ]
    before = [dict(message) for message in history]

    messages = _turn_messages(builder, history, "继续分析")

    assert messages[1:-1] == before
    assert messages[-1] == {"role": "user", "content": "继续分析"}


def test_replay_c_cross_provider_preserves_one_history_shape(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    history = [{"role": "user", "content": "共同历史"}]
    deepseek = _turn_messages(builder, history, REPLAY_TURNS["cross_provider"][0].user_message)
    openai = _turn_messages(builder, history, REPLAY_TURNS["cross_provider"][1].user_message)

    assert deepseek[0]["content"] == openai[0]["content"]
    assert deepseek[1]["role"] == openai[1]["role"] == "user"
    assert deepseek[1]["content"].startswith("共同历史\n\n")
    assert openai[1]["content"].startswith("共同历史\n\n")
    assert deepseek[1]["content"] != openai[1]["content"]


def test_replay_d_switch_back_reuses_same_context_shape(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    history = [{"role": "user", "content": "稳定前缀"}]
    first = _turn_messages(builder, history, REPLAY_TURNS["switch_back"][0].user_message)
    _ = _turn_messages(builder, history, REPLAY_TURNS["switch_back"][1].user_message)
    switched_back = _turn_messages(builder, history, REPLAY_TURNS["switch_back"][2].user_message)

    assert switched_back[0]["content"] == first[0]["content"]
    assert switched_back[1]["role"] == first[1]["role"] == "user"
    assert switched_back[1]["content"].startswith("稳定前缀\n\n")
    assert first[1]["content"].startswith("稳定前缀\n\n")


@pytest.mark.parametrize(
    "replay_name",
    ["same_provider_different_model", "same_provider_model_different_preset"],
)
def test_replay_e_f_model_selection_changes_do_not_change_base_context(
    tmp_path: Path,
    replay_name: str,
) -> None:
    builder = _builder(tmp_path)
    history = [{"role": "user", "content": "固定历史"}]
    turns = REPLAY_TURNS[replay_name]
    messages = [_turn_messages(builder, history, turn.user_message) for turn in turns]

    assert messages[0][0]["content"] == messages[1][0]["content"]
    assert messages[0][1]["role"] == messages[1][1]["role"] == "user"
    assert messages[0][1]["content"].startswith("固定历史\n\n")
    assert messages[1][1]["content"].startswith("固定历史\n\n")


def test_replay_g_context_window_change_keeps_input_messages_before_governance(
    tmp_path: Path,
) -> None:
    builder = _builder(tmp_path)
    history = [{"role": "user", "content": "长历史"}]
    large = _turn_messages(builder, history, "大窗口请求")
    small = _turn_messages(builder, history, "小窗口请求")

    assert large[0]["content"] == small[0]["content"]
    assert large[1]["role"] == small[1]["role"] == "user"
    assert large[1]["content"].startswith("长历史\n\n")
    assert small[1]["content"].startswith("长历史\n\n")
    assert large[-1]["role"] == small[-1]["role"] == "user"


def test_replay_runtime_context_stays_at_dynamic_user_tail(tmp_path: Path) -> None:
    builder = _builder(tmp_path)
    messages = builder.build_messages(
        [],
        "用户请求",
        include_memory=False,
        include_memory_recent_history=False,
        runtime_context_blocks=[
            RuntimeContextBlock(source="replay", content="动态运行时信息"),
        ],
    )

    content = messages[-1]["content"]
    assert content.index("用户请求") < content.index("动态运行时信息")


def test_replay_h_unprojected_skill_change_is_visible_in_current_baseline(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    builder = ContextBuilder(workspace)
    before = builder.build_system_prompt(
        include_memory=False,
        include_memory_recent_history=False,
    )
    skill = workspace / "skills" / "unused"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: unused\ndescription: Unused replay skill.\n---\n\n# Unused\n",
        encoding="utf-8",
    )

    after = builder.build_system_prompt(
        include_memory=False,
        include_memory_recent_history=False,
    )

    assert before != after
    assert "unused" in after


class _ReplayTool:
    def __init__(self, name: str):
        self.name = name

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.name,
                "parameters": {"type": "object", "properties": {}},
            },
        }


def test_replay_i_unprojected_mcp_tool_changes_baseline_surface() -> None:
    registry = ToolRegistry()
    registry.register(_ReplayTool("read_file"))
    before = registry.get_definitions()
    registry.register(_ReplayTool("mcp_unused"))

    after = registry.get_definitions()

    assert [item["function"]["name"] for item in before] == ["read_file"]
    assert [item["function"]["name"] for item in after] == ["read_file", "mcp_unused"]


class _ReplayProvider(LLMProvider):
    def __init__(self, response: LLMResponse):
        super().__init__()
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get_default_model(self) -> str:
        return "replay-model"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(dict(kwargs))
        return self.response


@pytest.mark.asyncio
async def test_replay_j_fallback_records_actual_provider_and_model() -> None:
    primary = _ReplayProvider(
        LLMResponse(content="primary unavailable", finish_reason="error", error_kind="server_error")
    )
    fallback = _ReplayProvider(LLMResponse(content="fallback result"))
    preset = ModelPresetConfig(model="qwen-replay", provider="qwen")
    observer = MagicMock()
    provider = FallbackProvider(
        primary=primary,
        fallback_presets=[preset],
        provider_factory=lambda _: fallback,
        fallback_model_observer=observer,
    )

    result = await provider.chat(messages=[{"role": "user", "content": "replay"}], model="deepseek-replay")

    assert result.content == "fallback result"
    assert primary.calls[0]["model"] == "deepseek-replay"
    assert fallback.calls[0]["model"] == "qwen-replay"
    observer.assert_called_once_with("qwen-replay")
