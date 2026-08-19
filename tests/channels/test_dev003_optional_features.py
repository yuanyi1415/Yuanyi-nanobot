from __future__ import annotations

from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import ChannelInstanceSpec, ChannelManagementSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.optional_features import optional_features_payload


class _PayloadChannel(BaseChannel):
    name = "payload_test"
    display_name = "Payload test"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg) -> None:
        return None


def test_t03_06_and_t03_08_single_payload_normalizes_deleted_preset(monkeypatch) -> None:
    plugin = ChannelPlugin(
        name="payload_test",
        display_name="Payload test",
        runtime=f"{__name__}:_PayloadChannel",
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {plugin.name: plugin})
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})
    config = Config(
        model_presets={"kept": ModelPresetConfig(model="kept-model")},
        channels={"payload_test": {"enabled": True, "modelPreset": "deleted"}},
    )

    feature = optional_features_payload(config=config)["features"][0]

    assert feature["model_preset"] is None


def test_t03_07_and_t03_08_multi_payload_is_instance_specific(monkeypatch) -> None:
    plugin = ChannelPlugin(
        name="payload_test",
        display_name="Payload test",
        runtime=f"{__name__}:_PayloadChannel",
        management=ChannelManagementSpec(
            multi_instance=True,
            instance_specs=lambda section, *, enabled_only=True: [
                ChannelInstanceSpec(item["id"], item)
                for item in section["instances"]
                if not enabled_only or item.get("enabled", False)
            ],
            update_instance_config=lambda section, values, *, instance_id="default": section,
            runtime_name=lambda name, instance_id: name if instance_id == "default" else f"{name}.{instance_id}",
        ),
    )
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {plugin.name: plugin})
    monkeypatch.setattr("nanobot.optional_features.optional_dependency_groups", lambda: {})
    config = Config(
        model_presets={"kept": ModelPresetConfig(model="kept-model")},
        channels={
            "payload_test": {
                "instances": [
                    {"id": "a", "enabled": True, "modelPreset": "kept"},
                    {"id": "b", "enabled": True, "modelPreset": "deleted"},
                ]
            }
        },
    )

    instances = optional_features_payload(config=config)["features"][0]["instances"]

    assert [(item["id"], item["model_preset"]) for item in instances] == [
        ("a", "kept"),
        ("b", None),
    ]
