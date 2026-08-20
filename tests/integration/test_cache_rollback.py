"""QA: Feature-flag rollback and legacy compatibility guarantees."""

from pathlib import Path

from nanobot.agent.context import ContextBuilder


def _builder(tmp_path: Path) -> ContextBuilder:
    return ContextBuilder(tmp_path / "workspace")


def test_feature_flags_default_to_off_for_rollback() -> None:
    from nanobot.config.schema import AgentDefaults

    experimental = AgentDefaults().experimental

    assert experimental.context_frame_enabled is False
    assert experimental.provider_cache_plan_enabled is False


def test_frame_path_does_not_change_session_history_format(tmp_path: Path) -> None:
    """The frame-based construction preserves the legacy message shape."""
    builder = _builder(tmp_path)
    history = [
        {"role": "user", "content": "第一轮"},
        {"role": "assistant", "content": "回复"},
    ]

    messages = builder.build_messages(history, "继续")

    assert messages[0] == {"role": "system", "content": messages[0]["content"]}
    assert messages[1] == {"role": "user", "content": "第一轮"}
    assert messages[2] == {"role": "assistant", "content": "回复"}
    assert messages[3] == {"role": "user", "content": "继续"}
    # system 仍是一个字符串，不改变 provider wire 结构
    assert isinstance(messages[0]["content"], str)


def test_no_provider_cache_fields_without_cache_plan(tmp_path: Path) -> None:
    """Default (no CachePlan) must not emit OpenAI-only cache kwargs."""
    builder = _builder(tmp_path)
    messages = builder.build_messages([], "hi")

    serialized = str(messages)
    assert "prompt_cache_key" not in serialized
    assert "prompt_cache_breakpoint" not in serialized
