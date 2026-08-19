"""Channel Instance Default runtime binding tests (T02-03..07)."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import (
    ChannelInstanceSpec,
    ChannelManagementSpec,
    ChannelSetupSpec,
)
from nanobot.channels.manager import ChannelManager
from nanobot.channels.plugin import ChannelPlugin
from nanobot.config.schema import Config
from nanobot.session.model_selection import CHANNEL_MODEL_PRESET_MESSAGE_META


class _DummyChannel(BaseChannel):
    name = "dummy"
    display_name = "Dummy"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        raise AssertionError("send should not be called")

    async def send_delta(self, chat_id, delta, metadata=None, **kwargs) -> None:
        return None


class _PresetChannel(BaseChannel):
    name = "preset"
    display_name = "Preset"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def start(self):
        self._running = True
        self.started.set()
        await self.stopped.wait()

    async def stop(self):
        self._running = False
        self.stopped.set()

    async def send(self, msg):  # pragma: no cover - not used by these tests
        raise AssertionError("send should not be called")


class _PresetMultiChannel(_PresetChannel):
    name = "presetmulti"
    display_name = "PresetMulti"


def _multi_instance_specs(section, *, enabled_only=True):
    instances = section.get("instances", []) if isinstance(section, dict) else []
    return [
        ChannelInstanceSpec(instance_id=item["id"], config=item)
        for item in instances
        if not enabled_only or item.get("enabled", False)
    ]


def _plugin(channel_cls: type[BaseChannel], *, multi_instance: bool = False) -> ChannelPlugin:
    runtime_attr = f"_runtime_{channel_cls.display_name.lower()}"
    globals()[runtime_attr] = channel_cls
    setup = ChannelSetupSpec(fields={}) if multi_instance else None
    management = (
        ChannelManagementSpec(
            multi_instance=True,
            instance_specs=_multi_instance_specs,
            update_instance_config=lambda section, values, *, instance_id="default": values,
            runtime_name=lambda name, instance_id: (
                name if instance_id == "default" else f"{name}.{instance_id}"
            ),
        )
        if multi_instance
        else ChannelManagementSpec()
    )
    return ChannelPlugin(
        name=channel_cls.name,
        display_name=channel_cls.display_name,
        runtime=f"{__name__}:{runtime_attr}",
        setup=setup,
        management=management,
    )


def _stub_registry(monkeypatch, *plugins: ChannelPlugin) -> None:
    by_name = {plugin.name: plugin for plugin in plugins}
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda enabled_names=None: {
            name: plugin
            for name, plugin in by_name.items()
            if enabled_names is None or name in enabled_names
        },
    )


class TestBaseChannelDefaultModelPreset:
    def test_default_model_preset_defaults_to_none(self) -> None:
        channel = _DummyChannel({}, MessageBus())
        assert channel.default_model_preset is None

    @pytest.mark.asyncio
    async def test_handle_message_injects_channel_default_metadata(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel({"allowFrom": ["*"]}, bus)
        channel.default_model_preset = "qwen"

        await channel._handle_message(
            sender_id="alice", chat_id="chat1", content="hi"
        )

        msg = await bus.consume_inbound()
        assert msg.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "qwen"
        assert msg.content == "hi"

    @pytest.mark.asyncio
    async def test_handle_message_skips_injection_without_default(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel({"allowFrom": ["*"]}, bus)

        await channel._handle_message(
            sender_id="alice", chat_id="chat1", content="hi"
        )

        msg = await bus.consume_inbound()
        assert CHANNEL_MODEL_PRESET_MESSAGE_META not in msg.metadata

    @pytest.mark.asyncio
    async def test_handle_message_does_not_mutate_caller_metadata(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel({"allowFrom": ["*"]}, bus)
        channel.default_model_preset = "sol"
        metadata = {"message_id": "m1"}

        await channel._handle_message(
            sender_id="alice", chat_id="chat1", content="hi", metadata=metadata
        )

        assert metadata == {"message_id": "m1"}
        msg = await bus.consume_inbound()
        assert msg.metadata["message_id"] == "m1"
        assert msg.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "sol"

    @pytest.mark.asyncio
    async def test_handle_message_injects_with_streaming_flag(self) -> None:
        bus = MessageBus()
        channel = _DummyChannel({"allowFrom": ["*"], "streaming": True}, bus)
        channel.default_model_preset = "qwen"

        await channel._handle_message(
            sender_id="alice", chat_id="chat1", content="hi"
        )

        msg = await bus.consume_inbound()
        assert msg.metadata["_wants_stream"] is True
        assert msg.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "qwen"


class TestChannelManagerBindsDefaultModelPreset:
    def test_init_binds_default_model_preset_from_raw_config(self, monkeypatch) -> None:
        config = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": True, "modelPreset": "qwen"},
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetChannel))

        manager = ChannelManager(config, MessageBus())

        assert manager.channels["preset"].default_model_preset == "qwen"

    def test_init_defaults_to_none_when_model_preset_omitted(self, monkeypatch) -> None:
        config = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": True},
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetChannel))

        manager = ChannelManager(config, MessageBus())

        assert manager.channels["preset"].default_model_preset is None

    def test_init_normalizes_default_sentinel_to_none(self, monkeypatch) -> None:
        config = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": True, "modelPreset": "default"},
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetChannel))

        manager = ChannelManager(config, MessageBus())

        assert manager.channels["preset"].default_model_preset is None

    def test_multi_instance_defaults_are_isolated(self, monkeypatch) -> None:
        config = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "presetmulti": {
                    "enabled": True,
                    "instances": [
                        {"id": "default", "enabled": True, "modelPreset": "sol"},
                        {"id": "work", "enabled": True, "modelPreset": "qwen"},
                        {"id": "personal", "enabled": True},
                    ],
                },
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetMultiChannel, multi_instance=True))

        manager = ChannelManager(config, MessageBus())

        assert manager.channels["presetmulti"].default_model_preset == "sol"
        assert manager.channels["presetmulti.work"].default_model_preset == "qwen"
        assert manager.channels["presetmulti.personal"].default_model_preset is None

    @pytest.mark.asyncio
    async def test_manager_built_channel_injects_preset_into_inbound(
        self, monkeypatch
    ) -> None:
        config = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {
                    "enabled": True,
                    "modelPreset": "qwen",
                    "allowFrom": ["*"],
                },
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetChannel))
        bus = MessageBus()

        manager = ChannelManager(config, bus)
        channel = manager.channels["preset"]

        await channel._handle_message(sender_id="alice", chat_id="chat1", content="hi")

        msg = await bus.consume_inbound()
        assert msg.metadata[CHANNEL_MODEL_PRESET_MESSAGE_META] == "qwen"


class TestChannelManagerHotRebuild:
    @pytest.mark.asyncio
    async def test_hot_rebuild_applies_new_model_preset(self, monkeypatch) -> None:
        initial = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": False, "modelPreset": "qwen"},
            }
        })
        updated = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": True, "modelPreset": "sol"},
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetChannel))
        monkeypatch.setattr("nanobot.config.loader.load_config", lambda: updated)

        manager = ChannelManager(initial, MessageBus())
        assert "preset" not in manager.channels

        result = await manager.apply_channel_feature_action("enable", "preset")

        assert result["handled"] is True
        assert manager.channels["preset"].default_model_preset == "sol"

    @pytest.mark.asyncio
    async def test_hot_rebuild_normalizes_removed_model_preset(self, monkeypatch) -> None:
        initial = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": False, "modelPreset": "qwen"},
            }
        })
        updated = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "preset": {"enabled": True},
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetChannel))
        monkeypatch.setattr("nanobot.config.loader.load_config", lambda: updated)

        manager = ChannelManager(initial, MessageBus())

        await manager.apply_channel_feature_action("enable", "preset")

        assert manager.channels["preset"].default_model_preset is None

    @pytest.mark.asyncio
    async def test_hot_rebuild_multi_instance_keeps_isolated_defaults(
        self, monkeypatch
    ) -> None:
        initial = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "presetmulti": {"enabled": False, "instances": []},
            }
        })
        updated = Config.model_validate({
            "channels": {
                "websocket": {"enabled": False},
                "presetmulti": {
                    "enabled": True,
                    "instances": [
                        {"id": "default", "enabled": True, "modelPreset": "sol"},
                        {"id": "work", "enabled": True, "modelPreset": "qwen"},
                    ],
                },
            }
        })
        _stub_registry(monkeypatch, _plugin(_PresetMultiChannel, multi_instance=True))
        monkeypatch.setattr("nanobot.config.loader.load_config", lambda: updated)

        manager = ChannelManager(initial, MessageBus())

        default_result = await manager.apply_channel_feature_action(
            "enable", "presetmulti"
        )
        work_result = await manager.apply_channel_feature_action(
            "enable", "presetmulti", "work"
        )

        assert default_result["handled"] is True
        assert work_result["handled"] is True
        assert manager.channels["presetmulti"].default_model_preset == "sol"
        assert manager.channels["presetmulti.work"].default_model_preset == "qwen"
