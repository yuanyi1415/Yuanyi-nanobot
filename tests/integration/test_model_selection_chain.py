"""INT001 end-to-end model-selection and provider-state verification."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import (
    ChannelInstanceSpec,
    ChannelManagementSpec,
    ChannelSetupSpec,
)
from nanobot.channels.manager import ChannelManager
from nanobot.channels.plugin import ChannelPlugin
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.factory import ProviderSnapshot
from nanobot.session.model_selection import (
    CHANNEL_MODEL_PRESET_MESSAGE_META,
    SESSION_MODEL_PRESET_METADATA_KEY,
)


class RecordingProvider(LLMProvider):
    def __init__(self, provider_name: str) -> None:
        super().__init__()
        self.provider_name = provider_name
        self.generation = GenerationSettings(max_tokens=256, temperature=0.1)
        self.models: list[str | None] = []
        self.contexts: list[ProviderCallContext | None] = []

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.models.append(model)
        self.contexts.append(kwargs.get("provider_context"))
        return LLMResponse(content=f"{self.provider_name}:{model}")

    def get_default_model(self) -> str:
        return self.provider_name


class StatefulProvider(RecordingProvider):
    def can_resume_conversation_state(self, state, model=None) -> bool:
        return state.provider == self.provider_name and state.model == model

    async def chat_with_context(self, *, provider_context, **kwargs) -> LLMResponse:
        self.models.append(kwargs.get("model"))
        self.contexts.append(provider_context)
        return LLMResponse(
            content=f"{self.provider_name}:{kwargs.get('model')}",
            provider_state=ProviderConversationState(
                kind="test",
                provider=self.provider_name,
                model=kwargs.get("model") or "",
                version=1,
                payload={"provider": self.provider_name},
            ),
        )


def _make_loop(tmp_path, *, stateful: bool = False):
    provider_type = StatefulProvider if stateful else RecordingProvider
    global_provider = provider_type("global-provider")
    channel_provider = provider_type("channel-provider")
    session_provider = provider_type("session-provider")
    other_provider = provider_type("other-provider")
    presets = {
        "global": ModelPresetConfig(model="global-model", context_window_tokens=8_000),
        "channel": ModelPresetConfig(model="channel-model", context_window_tokens=8_000),
        "session": ModelPresetConfig(model="session-model", context_window_tokens=8_000),
        "other": ModelPresetConfig(model="other-model", context_window_tokens=8_000),
    }
    providers = {
        "global": global_provider,
        "channel": channel_provider,
        "session": session_provider,
        "other": other_provider,
    }

    def load_preset(name: str) -> ProviderSnapshot:
        preset = presets[name]
        return ProviderSnapshot(
            provider=providers[name],
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        )

    loop = AgentLoop(
        bus=MessageBus(),
        provider=global_provider,
        workspace=tmp_path,
        model="global-model",
        context_window_tokens=8_000,
        model_presets=presets,
        preset_snapshot_loader=load_preset,
    )
    loop.schedule_background = lambda coro: coro.close()  # type: ignore[method-assign]
    return loop, providers


def _message(channel: str, chat_id: str, *, sender_id: str = "user", content: str = "hi"):
    return InboundMessage(
        channel=channel,
        sender_id=sender_id,
        chat_id=chat_id,
        content=content,
    )


async def _turn(loop: AgentLoop, msg: InboundMessage):
    outbound = await loop._process_message(msg)
    assert outbound is not None
    return outbound


class _IntegrationChannel(BaseChannel):
    name = "integration"
    display_name = "Integration"

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        raise AssertionError("integration test channel must not send")

    async def send_delta(self, chat_id, delta, metadata=None, **kwargs) -> None:
        raise AssertionError("integration test channel must not stream")


class _IntegrationMultiChannel(_IntegrationChannel):
    name = "integrationmulti"
    display_name = "IntegrationMulti"


def _instance_specs(section: object, *, enabled_only: bool = True):
    values = section.get("instances", []) if isinstance(section, dict) else []
    return [
        ChannelInstanceSpec(instance_id=item["id"], config=item)
        for item in values
        if not enabled_only or item.get("enabled", False)
    ]


def _plugin(monkeypatch, *, multi: bool = False) -> None:
    name = "integrationmulti" if multi else "integration"
    channel_cls = _IntegrationMultiChannel if multi else _IntegrationChannel
    management = (
        ChannelManagementSpec(
            multi_instance=True,
            instance_specs=_instance_specs,
            update_instance_config=lambda section, values, *, instance_id="default": values,
            runtime_name=lambda channel_name, instance_id: (
                channel_name if instance_id == "default" else f"{channel_name}.{instance_id}"
            ),
        )
        if multi
        else ChannelManagementSpec()
    )
    plugin = ChannelPlugin(
        name=name,
        display_name=channel_cls.display_name,
        runtime=f"{__name__}:{channel_cls.__name__}",
        setup=ChannelSetupSpec(fields={}),
        management=management,
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda enabled_names=None: {name: plugin},
    )


def _config(*, enabled: bool, preset: str | None) -> Config:
    section: dict[str, Any] = {"enabled": enabled, "allowFrom": ["*"]}
    if preset is not None:
        section["modelPreset"] = preset
    return Config.model_validate({
        "channels": {"websocket": {"enabled": False}, "integration": section}
    })


@pytest.mark.asyncio
async def test_priority_matrix_uses_real_inbound_to_turn_chain(tmp_path, monkeypatch) -> None:
    loop, providers = _make_loop(tmp_path)
    _plugin(monkeypatch)
    manager = ChannelManager(_config(enabled=True, preset="channel"), loop.bus)
    channel = manager.channels["integration"]

    # Channel -> global, then Session -> channel, then Session -> global fallback.
    await channel._handle_message("alice", "chat-global", "hello")
    msg = await loop.bus.consume_inbound()
    assert (await _turn(loop, msg)).content == "channel-provider:channel-model"

    loop.set_session_model_preset("integration:chat-session", "session")
    await channel._handle_message("alice", "chat-session", "hello")
    msg = await loop.bus.consume_inbound()
    assert (await _turn(loop, msg)).content == "session-provider:session-model"

    stale = loop.sessions.get_or_create("integration:chat-fallback")
    stale.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "deleted"
    loop.sessions.save(stale)
    await channel._handle_message("alice", "chat-fallback", "hello")
    msg = await loop.bus.consume_inbound()
    assert (await _turn(loop, msg)).content == "channel-provider:channel-model"

    # Removing the channel metadata exercises the unchanged global-default path.
    msg = _message("webui", "global-only")
    assert (await _turn(loop, msg)).content == "global-provider:global-model"
    assert providers["global"].models == ["global-model"]


@pytest.mark.asyncio
async def test_webui_and_im_session_overrides_are_isolated(tmp_path) -> None:
    loop, providers = _make_loop(tmp_path)
    loop.set_session_model_preset("webui:one", "session")
    loop.set_session_model_preset("im:user-a", "other")

    assert (await _turn(loop, _message("webui", "one"))).content == "session-provider:session-model"
    assert (await _turn(loop, _message("webui", "two"))).content == "global-provider:global-model"
    assert (await _turn(loop, _message("im", "user-a"))).content == "other-provider:other-model"
    assert (await _turn(loop, _message("im", "group-1"))).content == "global-provider:global-model"
    assert providers["session"].models == ["session-model"]
    assert providers["other"].models == ["other-model"]
    assert providers["global"].models == ["global-model", "global-model"]


@pytest.mark.asyncio
async def test_channel_instances_and_inbound_metadata_are_isolated(tmp_path, monkeypatch) -> None:
    loop, providers = _make_loop(tmp_path)
    _plugin(monkeypatch)
    _plugin(monkeypatch, multi=True)
    config = Config.model_validate({
        "channels": {
            "websocket": {"enabled": False},
            "integrationmulti": {
                "enabled": True,
                "instances": [
                    {
                        "id": "default",
                        "enabled": True,
                        "allowFrom": ["*"],
                        "modelPreset": "channel",
                    },
                    {
                        "id": "work",
                        "enabled": True,
                        "allowFrom": ["*"],
                        "modelPreset": "other",
                    },
                ],
            },
        }
    })
    manager = ChannelManager(config, loop.bus)

    await manager.channels["integrationmulti"]._handle_message("u", "a", "x")
    msg_a = await loop.bus.consume_inbound()
    await manager.channels["integrationmulti.work"]._handle_message("u", "b", "x")
    msg_b = await loop.bus.consume_inbound()
    assert msg_a.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "channel"
    assert msg_b.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "other"
    assert (await _turn(loop, msg_a)).content == "channel-provider:channel-model"
    assert (await _turn(loop, msg_b)).content == "other-provider:other-model"
    assert providers["channel"].models == ["channel-model"]
    assert providers["other"].models == ["other-model"]


@pytest.mark.asyncio
async def test_removed_session_and_channel_presets_fall_back_safely(tmp_path) -> None:
    loop, providers = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("im:stale")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "missing-session"
    loop.sessions.save(session)

    msg = _message("im", "stale")
    msg.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] = "missing-channel"
    assert (await _turn(loop, msg)).content == "global-provider:global-model"
    reloaded = loop.sessions.get_or_create("im:stale")
    assert SESSION_MODEL_PRESET_METADATA_KEY not in reloaded.metadata
    assert providers["global"].models == ["global-model"]


@pytest.mark.asyncio
async def test_cross_provider_switch_discards_incompatible_conversation_state(tmp_path) -> None:
    loop, providers = _make_loop(tmp_path, stateful=True)
    key = "webui:conversation"
    loop.set_session_model_preset(key, "session")
    first = await _turn(loop, _message("webui", "conversation"))
    assert first.content == "session-provider:session-model"

    loop.set_session_model_preset(key, "other")
    second = await _turn(loop, _message("webui", "conversation", content="switch"))
    assert second.content == "other-provider:other-model"
    context = providers["other"].contexts[-1]
    assert context is None or context.conversation_state is None
    assert loop.sessions.get_or_create(key).provider_state is not None
    assert loop.sessions.get_or_create(key).provider_state.provider == "other-provider"


@pytest.mark.asyncio
async def test_channel_hot_rebuild_changes_following_inbound_turn(tmp_path, monkeypatch) -> None:
    loop, providers = _make_loop(tmp_path)
    _plugin(monkeypatch)
    initial = _config(enabled=False, preset="channel")
    updated = _config(enabled=True, preset="other")
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: updated)
    manager = ChannelManager(initial, loop.bus)

    result = await manager.apply_channel_feature_action("enable", "integration")
    assert result["handled"] is True
    await manager.channels["integration"]._handle_message("u", "rebuilt", "after")
    msg = await loop.bus.consume_inbound()
    assert msg.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "other"
    assert (await _turn(loop, msg)).content == "other-provider:other-model"
    assert providers["channel"].models == []
    assert providers["other"].models == ["other-model"]
