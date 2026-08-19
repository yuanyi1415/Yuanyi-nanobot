"""Turn-level three-layer model selection tests (T01-04..07)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.providers.factory import ProviderSnapshot
from nanobot.session.model_selection import (
    CHANNEL_MODEL_PRESET_MESSAGE_META,
    SESSION_MODEL_PRESET_METADATA_KEY,
    ModelSelectionDecision,
    ModelSelectionSource,
    model_preset_from_metadata,
)


class RecordingProvider(LLMProvider):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.generation = GenerationSettings(max_tokens=256, temperature=0.1)
        self.calls: list[str | None] = []

    async def chat(self, messages, tools=None, model=None, **kwargs):
        await asyncio.sleep(0)
        self.calls.append(model)
        return LLMResponse(content=f"reply from {self.name}", finish_reason="stop")

    def get_default_model(self) -> str:
        return self.name


def _make_loop(tmp_path) -> tuple[AgentLoop, RecordingProvider, dict[str, RecordingProvider]]:
    base = RecordingProvider("base-model")
    channel = RecordingProvider("channel-model")
    session = RecordingProvider("session-model")
    presets = {
        "default": ModelPresetConfig(model="base-model", context_window_tokens=8_000),
        "channel-preset": ModelPresetConfig(model="channel-model", context_window_tokens=16_000),
        "session-preset": ModelPresetConfig(model="session-model", context_window_tokens=32_000),
    }
    providers = {"channel-preset": channel, "session-preset": session}

    def load_preset(name: str) -> ProviderSnapshot:
        if name == "default":
            return ProviderSnapshot(
                provider=base,
                model="base-model",
                context_window_tokens=8_000,
                signature=(name, "base-model"),
            )
        provider = providers[name]
        preset = presets[name]
        return ProviderSnapshot(
            provider=provider,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        )

    loop = AgentLoop(
        bus=MessageBus(),
        provider=base,
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=8_000,
        model_presets=presets,
        preset_snapshot_loader=load_preset,
    )
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    return loop, base, providers


def _msg(channel: str = "feishu", *, channel_default: str | None = None) -> InboundMessage:
    metadata: dict[str, Any] = {}
    if channel_default is not None:
        metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] = channel_default
    return InboundMessage(
        channel=channel,
        sender_id="user",
        chat_id="c1",
        content="hello",
        metadata=metadata,
    )


def _reloaded_session_override(loop: AgentLoop, session_key: str) -> str | None:
    loop.sessions.invalidate(session_key)
    return model_preset_from_metadata(loop.sessions.get_or_create(session_key).metadata)


# --- T01-04: three-layer priority ----------------------------------------------


def test_session_override_beats_channel_and_global(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")
    loop.set_session_model_preset(session.key, "session-preset")
    msg = _msg(channel_default="channel-preset")

    runtime, decision = loop.model_selection_for_turn(session, msg)

    assert isinstance(decision, ModelSelectionDecision)
    assert decision.source is ModelSelectionSource.SESSION
    assert decision.preset == "session-preset"
    assert decision.channel_default == "channel-preset"
    assert runtime.model == "session-model"
    assert runtime.model_preset == "session-preset"


def test_channel_default_used_without_session_override(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")

    runtime, decision = loop.model_selection_for_turn(session, _msg(channel_default="channel-preset"))

    assert decision.source is ModelSelectionSource.CHANNEL
    assert decision.preset == "channel-preset"
    assert decision.channel_default == "channel-preset"
    assert runtime.model == "channel-model"
    assert runtime.model_preset == "channel-preset"


def test_global_default_used_without_any_override(tmp_path) -> None:
    loop, base, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")

    runtime, decision = loop.model_selection_for_turn(session, _msg())

    assert decision.source is ModelSelectionSource.GLOBAL
    assert decision.preset is None
    assert decision.channel_default is None
    assert runtime.model == "base-model"
    assert runtime.model_preset is None
    assert runtime.provider is base


def test_channel_default_is_stripped_before_resolution(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")

    runtime, decision = loop.model_selection_for_turn(
        session,
        _msg(channel_default=" channel-preset "),
    )

    assert decision.source is ModelSelectionSource.CHANNEL
    assert decision.preset == "channel-preset"
    assert runtime.model == "channel-model"


def test_session_override_still_wins_over_removed_channel_default(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")
    loop.set_session_model_preset(session.key, "session-preset")

    runtime, decision = loop.model_selection_for_turn(
        session,
        _msg(channel_default="removed-channel-preset"),
    )

    assert decision.source is ModelSelectionSource.SESSION
    assert runtime.model == "session-model"


# --- T01-05: removed Session Override falls back --------------------------------


def test_removed_session_preset_clears_metadata_and_falls_to_channel(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "removed-preset"
    loop.sessions.save(session)

    runtime, decision = loop.model_selection_for_turn(
        session,
        _msg(channel_default="channel-preset"),
    )

    assert decision.source is ModelSelectionSource.CHANNEL
    assert runtime.model == "channel-model"
    assert _reloaded_session_override(loop, session.key) is None


def test_removed_session_preset_falls_to_global_without_channel_default(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "removed-preset"
    loop.sessions.save(session)

    runtime, decision = loop.model_selection_for_turn(session, _msg())

    assert decision.source is ModelSelectionSource.GLOBAL
    assert decision.preset is None
    assert runtime.model == "base-model"
    assert _reloaded_session_override(loop, session.key) is None


# --- T01-06: removed Channel Default falls back to global -----------------------


def test_removed_channel_preset_ignored_and_falls_to_global(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("feishu:c1")

    runtime, decision = loop.model_selection_for_turn(
        session,
        _msg(channel_default="removed-channel-preset"),
    )

    assert decision.source is ModelSelectionSource.GLOBAL
    assert decision.preset is None
    assert decision.channel_default == "removed-channel-preset"
    assert runtime.model == "base-model"
    assert _reloaded_session_override(loop, session.key) is None


# --- T01-07: runtime_for_session() compatibility --------------------------------


def test_runtime_for_session_keeps_session_global_semantics(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)

    plain = loop.sessions.get_or_create("feishu:plain")
    assert loop.runtime_for_session(plain).model == "base-model"

    overridden = loop.sessions.get_or_create("feishu:overridden")
    loop.set_session_model_preset(overridden.key, "session-preset")
    assert loop.runtime_for_session(overridden).model == "session-model"
    assert loop.runtime_for_session(overridden).model_preset == "session-preset"

    stale = loop.sessions.get_or_create("feishu:stale")
    stale.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "removed-preset"
    loop.sessions.save(stale)
    assert loop.runtime_for_session(stale).model == "base-model"
    assert _reloaded_session_override(loop, stale.key) is None


def test_runtime_for_session_recover_removed_false_raises(tmp_path) -> None:
    loop, _, _ = _make_loop(tmp_path)
    stale = loop.sessions.get_or_create("feishu:stale")
    stale.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "removed-preset"
    loop.sessions.save(stale)

    with pytest.raises(KeyError):
        loop.runtime_for_session(stale, recover_removed=False)


# --- Turn integration through the BUILD stage -----------------------------------


async def test_turn_uses_channel_default_through_build_stage(tmp_path) -> None:
    loop, _, providers = _make_loop(tmp_path)

    outbound = await loop._process_message(_msg(channel_default="channel-preset"))

    assert outbound is not None
    assert outbound.content == "reply from channel-model"
    assert providers["channel-preset"].calls == ["channel-model"]


async def test_turn_session_override_beats_channel_through_build_stage(tmp_path) -> None:
    loop, _, providers = _make_loop(tmp_path)
    loop.set_session_model_preset("feishu:c1", "session-preset")

    outbound = await loop._process_message(_msg(channel_default="channel-preset"))

    assert outbound is not None
    assert outbound.content == "reply from session-model"
    assert providers["session-preset"].calls == ["session-model"]
    assert providers["channel-preset"].calls == []


async def test_turn_without_override_keeps_global_through_build_stage(tmp_path) -> None:
    loop, base, _ = _make_loop(tmp_path)

    outbound = await loop._process_message(_msg())

    assert outbound is not None
    assert outbound.content == "reply from base-model"
    assert base.calls == ["base-model"]
