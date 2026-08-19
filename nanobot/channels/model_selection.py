"""Host-level parsing of Channel Instance Default model presets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

# Persisted Host field name. It lives at the Channel Instance level
# (``channels.<name>.modelPreset`` for single-instance channels,
# ``channels.<name>.instances[].modelPreset`` for multi-instance channels)
# and is read from the raw config before plugin DTO conversion so plugins
# never need to declare it.
CHANNEL_MODEL_PRESET_CONFIG_FIELD = "modelPreset"

# The literal ``default`` means "inherit the global default"; the settings
# layer deletes the override instead of persisting this string, and parsing
# here treats it the same way so stale values never become presets.
_DEFAULT_INHERIT_VALUE = "default"


def channel_model_preset_from_config(config: object) -> str | None:
    """Read the Host-level ``modelPreset`` field from a raw channel config.

    Compatible inputs:

    - plain ``dict`` with the camelCase ``modelPreset`` key;
    - Pydantic / DTO objects exposing ``model_dump(mode="json", by_alias=True)``;
    - missing key, ``None``, blank strings, and the literal ``default``.

    Every unusable value normalizes to ``None``, which means "inherit the
    Global Default".
    """
    if config is None:
        return None
    if hasattr(config, "model_dump"):
        # Pydantic v2 / DTO surface; ``Any`` mirrors ``contracts._config_mapping``.
        dto = cast(Any, config)
        dumped = dto.model_dump(mode="json", by_alias=True)
        if not isinstance(dumped, dict):
            return None
        config = dumped
    if not isinstance(config, Mapping):
        return None
    values = cast(Mapping[object, object], config)
    raw = values.get(CHANNEL_MODEL_PRESET_CONFIG_FIELD)
    if not isinstance(raw, str):
        return None
    preset = raw.strip()
    if not preset or preset == _DEFAULT_INHERIT_VALUE:
        return None
    return preset
