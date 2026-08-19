"""Unit tests for Host-level channel modelPreset config parsing (T02-01..02)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from nanobot.channels.model_selection import (
    CHANNEL_MODEL_PRESET_CONFIG_FIELD,
    channel_model_preset_from_config,
)


class _InstanceDto(BaseModel):
    """A plugin-style DTO that keeps ``modelPreset`` under its alias."""

    model_config = ConfigDict(populate_by_name=True)

    model_preset: str | None = Field(default=None, alias="modelPreset")
    token: str | None = None


class _WeirdDto:
    """A DTO whose dump is not a mapping; must normalize to None."""

    def model_dump(self, **kwargs: object) -> str:
        return "not-a-mapping"


class TestChannelModelPresetFromConfig:
    def test_returns_stripped_value(self) -> None:
        config = {CHANNEL_MODEL_PRESET_CONFIG_FIELD: "  qwen  "}
        assert channel_model_preset_from_config(config) == "qwen"

    def test_missing_key_returns_none(self) -> None:
        assert channel_model_preset_from_config({"enabled": True}) is None

    def test_empty_dict_returns_none(self) -> None:
        assert channel_model_preset_from_config({}) is None

    def test_none_value_returns_none(self) -> None:
        config = {CHANNEL_MODEL_PRESET_CONFIG_FIELD: None}
        assert channel_model_preset_from_config(config) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_value_returns_none(self, value: str) -> None:
        config = {CHANNEL_MODEL_PRESET_CONFIG_FIELD: value}
        assert channel_model_preset_from_config(config) is None

    @pytest.mark.parametrize("value", ["default", " default "])
    def test_default_value_returns_none(self, value: str) -> None:
        config = {CHANNEL_MODEL_PRESET_CONFIG_FIELD: value}
        assert channel_model_preset_from_config(config) is None

    @pytest.mark.parametrize("value", [7, False, {"nested": True}, ["a"]])
    def test_non_string_value_returns_none(self, value: object) -> None:
        config = {CHANNEL_MODEL_PRESET_CONFIG_FIELD: value}
        assert channel_model_preset_from_config(config) is None

    @pytest.mark.parametrize("config", [None, "not-a-mapping", ["not", "a", "mapping"]])
    def test_non_mapping_returns_none(self, config: object) -> None:
        assert channel_model_preset_from_config(config) is None

    def test_preserves_unrelated_keys(self) -> None:
        config = {"enabled": True, "token": "t", CHANNEL_MODEL_PRESET_CONFIG_FIELD: "qwen"}
        assert channel_model_preset_from_config(config) == "qwen"

    def test_does_not_read_snake_case_alias(self) -> None:
        assert channel_model_preset_from_config({"model_preset": "qwen"}) is None


class TestChannelModelPresetFromConfigDto:
    def test_dto_dump_is_parsed(self) -> None:
        dto = _InstanceDto(modelPreset="sol")
        assert channel_model_preset_from_config(dto) == "sol"

    def test_dto_without_preset_returns_none(self) -> None:
        assert channel_model_preset_from_config(_InstanceDto()) is None

    def test_dto_default_value_returns_none(self) -> None:
        dto = _InstanceDto(modelPreset="default")
        assert channel_model_preset_from_config(dto) is None

    def test_dto_non_mapping_dump_returns_none(self) -> None:
        assert channel_model_preset_from_config(_WeirdDto()) is None
