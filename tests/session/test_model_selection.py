"""Unit tests for session model selection data structures and helpers (T01-01..03)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from nanobot.session.model_selection import (
    CHANNEL_MODEL_PRESET_MESSAGE_META,
    SESSION_MODEL_PRESET_METADATA_KEY,
    ModelSelectionDecision,
    ModelSelectionSource,
    channel_model_preset_from_message_metadata,
    clear_session_model_preset,
)


class TestModelSelectionSource:
    def test_members_and_values(self) -> None:
        assert ModelSelectionSource.SESSION.value == "session"
        assert ModelSelectionSource.CHANNEL.value == "channel"
        assert ModelSelectionSource.GLOBAL.value == "global"

    def test_is_str_enum(self) -> None:
        assert isinstance(ModelSelectionSource.SESSION, str)
        assert ModelSelectionSource("session") is ModelSelectionSource.SESSION
        assert ModelSelectionSource("channel") is ModelSelectionSource.CHANNEL
        assert ModelSelectionSource("global") is ModelSelectionSource.GLOBAL


class TestModelSelectionDecision:
    def test_fields_and_defaults(self) -> None:
        decision = ModelSelectionDecision(
            preset="qwen",
            source=ModelSelectionSource.SESSION,
        )
        assert decision.preset == "qwen"
        assert decision.source is ModelSelectionSource.SESSION
        assert decision.channel_default is None

    def test_channel_default_roundtrip(self) -> None:
        decision = ModelSelectionDecision(
            preset="sol",
            source=ModelSelectionSource.CHANNEL,
            channel_default="sol",
        )
        assert decision.channel_default == "sol"

    def test_none_preset_for_plain_global(self) -> None:
        decision = ModelSelectionDecision(
            preset=None,
            source=ModelSelectionSource.GLOBAL,
        )
        assert decision.preset is None

    def test_frozen_rejects_mutation(self) -> None:
        decision = ModelSelectionDecision(
            preset="qwen",
            source=ModelSelectionSource.GLOBAL,
        )
        with pytest.raises(FrozenInstanceError):
            decision.preset = "sol"  # type: ignore[misc]


class TestChannelModelPresetFromMessageMetadata:
    def test_returns_stripped_value(self) -> None:
        metadata = {CHANNEL_MODEL_PRESET_MESSAGE_META: "  qwen  "}
        assert channel_model_preset_from_message_metadata(metadata) == "qwen"

    def test_missing_key_returns_none(self) -> None:
        assert channel_model_preset_from_message_metadata({}) is None

    def test_none_value_returns_none(self) -> None:
        metadata = {CHANNEL_MODEL_PRESET_MESSAGE_META: None}
        assert channel_model_preset_from_message_metadata(metadata) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_value_returns_none(self, value: str) -> None:
        metadata = {CHANNEL_MODEL_PRESET_MESSAGE_META: value}
        assert channel_model_preset_from_message_metadata(metadata) is None

    @pytest.mark.parametrize("value", [7, {"nested": True}, ["a"]])
    def test_non_string_value_returns_none(self, value: object) -> None:
        metadata = {CHANNEL_MODEL_PRESET_MESSAGE_META: value}
        assert channel_model_preset_from_message_metadata(metadata) is None

    @pytest.mark.parametrize("metadata", [None, "not-a-mapping", ["not", "a", "mapping"]])
    def test_non_mapping_returns_none(self, metadata: object) -> None:
        assert channel_model_preset_from_message_metadata(metadata) is None

    def test_preserves_unrelated_metadata(self) -> None:
        metadata = {"message_id": "m1", CHANNEL_MODEL_PRESET_MESSAGE_META: "qwen"}
        assert channel_model_preset_from_message_metadata(metadata) == "qwen"
        assert metadata["message_id"] == "m1"


class TestClearSessionModelPreset:
    def test_removes_key_and_reports(self) -> None:
        metadata: dict[str, object] = {
            SESSION_MODEL_PRESET_METADATA_KEY: "sol",
            "title": "t",
        }
        assert clear_session_model_preset(metadata) is True
        assert SESSION_MODEL_PRESET_METADATA_KEY not in metadata
        assert metadata == {"title": "t"}

    def test_idempotent(self) -> None:
        metadata: dict[str, object] = {SESSION_MODEL_PRESET_METADATA_KEY: "sol"}
        assert clear_session_model_preset(metadata) is True
        assert clear_session_model_preset(metadata) is False
        assert SESSION_MODEL_PRESET_METADATA_KEY not in metadata

    def test_missing_key_returns_false(self) -> None:
        assert clear_session_model_preset({}) is False
