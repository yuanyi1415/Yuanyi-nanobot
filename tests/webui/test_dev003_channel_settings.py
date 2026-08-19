from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from websockets.datastructures import Headers

from nanobot.channels.base import BaseChannel
from nanobot.channels.contracts import ChannelFieldSpec, ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.webui.http_utils import http_json_response
from nanobot.webui.settings_routes import WebUISettingsRouter
from nanobot.webui.settings_services import WebUISettingsServices


class _SettingsChannel(BaseChannel):
    name = "settings_test"
    display_name = "Settings test"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg) -> None:
        return None


_PLUGIN = ChannelPlugin(
    name="settings_test",
    display_name="Settings test",
    runtime=f"{__name__}:_SettingsChannel",
    setup=ChannelSetupSpec(fields={"token": ChannelFieldSpec(kind="secret")}),
)


def _router(config_path: Path) -> WebUISettingsRouter:
    return WebUISettingsRouter(
        settings=WebUISettingsServices.create(config_path),
        bus=SimpleNamespace(),
        logger=SimpleNamespace(exception=lambda *_args: None),
        check_api_token=lambda _request: True,
        parse_query=lambda _path: {},
        json_response=http_json_response,
        error_response=lambda status, message: http_json_response({"error": message}, status=status),
        runtime_surface="browser",
        runtime_capabilities={},
    )


def _request(values: dict[str, object], *, enable: bool = False) -> SimpleNamespace:
    request = SimpleNamespace(path="/api/settings/channels/configure", headers=Headers())
    request._nanobot_webui_mutation_request = True
    request._nanobot_webui_mutation_payload = {
        "name": "settings_test",
        "instance_id": "default",
        "enable": enable,
        "values": values,
    }
    return request


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[WebUISettingsRouter, Path]:
    path = tmp_path / "config.json"
    save_config(
        Config(
            model_presets={"fast": ModelPresetConfig(model="fast-model")},
            channels={"settings_test": {"enabled": True, "token": "secret"}},
        ),
        path,
    )
    monkeypatch.setattr("nanobot.webui.settings_routes.load_channel_plugin", lambda _name: _PLUGIN)
    return _router(path), path


def test_t03_01_host_model_preset_is_saved_without_setup_field(monkeypatch, tmp_path) -> None:
    router, path = _setup(monkeypatch, tmp_path)

    assert router._save_channel_config_values(
        "settings_test", {"channels.settings_test.modelPreset": "fast"}
    ) == ["channels.settings_test.modelPreset"]
    assert load_config(path).channels.settings_test["modelPreset"] == "fast"


def test_t03_02_and_t03_04_invalid_preset_is_rejected_without_write(monkeypatch, tmp_path) -> None:
    router, path = _setup(monkeypatch, tmp_path)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="existing model preset") as error:
        router._save_channel_config_values(
            "settings_test", {"channels.settings_test.modelPreset": "missing"}
        )

    assert error.value.status == 400
    assert path.read_text(encoding="utf-8") == before


def test_t03_03_default_and_empty_remove_override(monkeypatch, tmp_path) -> None:
    router, path = _setup(monkeypatch, tmp_path)
    router._save_channel_config_values(
        "settings_test", {"channels.settings_test.modelPreset": "fast"}
    )

    for value in ("default", "", None):
        router._save_channel_config_values(
            "settings_test", {"channels.settings_test.modelPreset": value}
        )
        assert "modelPreset" not in load_config(path).channels.settings_test


@pytest.mark.asyncio
async def test_t03_05_enabled_channel_uses_existing_hot_rebuild(monkeypatch, tmp_path) -> None:
    router, path = _setup(monkeypatch, tmp_path)
    calls: list[tuple[str, str, str | None]] = []
    router._nanobot_features_action = lambda *_args, **_kwargs: {"features": []}
    router._channel_feature_action = lambda action, name, instance_id: calls.append(
        (action, name, instance_id)
    ) or {"handled": True, "ok": True, "requires_restart": False}

    response = await router.dispatch(None, _request({"channels.settings_test.modelPreset": "fast"}, enable=True), "/api/settings/channels/configure")

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body)["saved"] is True
    assert calls == [("enable", "settings_test", "default")]
    assert load_config(path).channels.settings_test["modelPreset"] == "fast"


def test_t03_09_model_preset_is_not_sent_to_validator(monkeypatch, tmp_path) -> None:
    router, _path = _setup(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def validate(name, values, *, instance_id):
        captured.update(name=name, values=values, instance_id=instance_id)
        return {"status": "configured"}

    monkeypatch.setattr("nanobot.webui.settings_routes.validate_channel_config", validate)
    request = _request({
        "channels.settings_test.modelPreset": "fast",
        "channels.settings_test.token": "secret",
    })
    request._nanobot_webui_mutation_payload["enable"] = False

    response = asyncio.run(router._handle_settings_channel_validate(request))

    assert response.status_code == 200
    assert captured["values"] == {"channels.settings_test.token": "secret"}
