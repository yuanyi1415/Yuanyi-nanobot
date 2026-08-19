"""Session-scoped model preset metadata."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

# Session.metadata is public SDK data, so internal selectors use a reserved namespace.
SESSION_MODEL_PRESET_METADATA_KEY = "_nanobot_model_preset"

# Runtime-only inbound metadata: the Channel Instance Default preset chosen for
# the turn that produced this message. Set by the channel runtime, not part of
# the user-editable message metadata protocol.
CHANNEL_MODEL_PRESET_MESSAGE_META = "_nanobot_channel_model_preset"


class ModelSelectionSource(str, Enum):
    """Where the effective model preset for a turn came from."""

    SESSION = "session"
    CHANNEL = "channel"
    GLOBAL = "global"


@dataclass(frozen=True)
class ModelSelectionDecision:
    """One turn's model selection outcome.

    Attributes:
        preset: The effective preset name that produced the runtime; ``None``
            when the effective runtime carries no named preset (plain global).
        source: Priority layer that won: SESSION > CHANNEL > GLOBAL.
        channel_default: The raw Channel Instance Default read from the inbound
            message metadata, when the message came from a channel (may be a
            stale value whose preset was removed).
    """

    preset: str | None
    source: ModelSelectionSource
    channel_default: str | None = None


def model_preset_from_metadata(metadata: object) -> str | None:
    """Read the canonical session preset name from persisted metadata."""
    if not isinstance(metadata, Mapping):
        return None
    typed_metadata = cast(Mapping[object, object], metadata)
    if SESSION_MODEL_PRESET_METADATA_KEY not in typed_metadata:
        return None
    value = typed_metadata[SESSION_MODEL_PRESET_METADATA_KEY]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("session model preset must be a non-empty string")
    return value.strip()


def channel_model_preset_from_message_metadata(metadata: object) -> str | None:
    """Read the Channel Instance Default preset from inbound message metadata.

    Unlike :func:`model_preset_from_metadata`, this reader is lenient: the key
    is runtime-internal data injected by the channel runtime, so missing,
    non-string, or blank values simply mean "no channel default" and let the
    resolution fall back to the global default instead of failing the turn.
    """
    if not isinstance(metadata, Mapping):
        return None
    typed_metadata = cast(Mapping[object, object], metadata)
    value = typed_metadata.get(CHANNEL_MODEL_PRESET_MESSAGE_META)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def clear_session_model_preset(metadata: MutableMapping[str, Any]) -> bool:
    """Remove the Session Override preset key, returning True when removed.

    Idempotent: calling again on metadata without the key is a no-op and
    returns False.
    """
    if SESSION_MODEL_PRESET_METADATA_KEY not in metadata:
        return False
    del metadata[SESSION_MODEL_PRESET_METADATA_KEY]
    return True
