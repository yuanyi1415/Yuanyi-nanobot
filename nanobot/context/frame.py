"""Immutable, provider-neutral context contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast


class ContextStability(StrEnum):
    """Ordering from least-changing to most-changing context content."""

    CORE = "core"
    SESSION = "session"
    TASK = "task"
    HISTORY = "history"
    TURN = "turn"


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """One named block in a model-visible context frame."""

    key: str
    stability: ContextStability
    role: str
    content: object
    cacheable: bool = True

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("context block key must not be empty")
        if not self.role:
            raise ValueError("context block role must not be empty")


@dataclass(frozen=True, slots=True)
class ContextFrame:
    """A complete provider-neutral description of one model-visible turn."""

    blocks: tuple[ContextBlock, ...]
    history: tuple[dict[str, Any], ...]
    current_message: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolSurface:
    """The exact tool definitions projected to the current model turn."""

    names: tuple[str, ...]
    definitions: tuple[dict[str, Any], ...]
    fingerprint: str

    @classmethod
    def from_definitions(cls, definitions: Sequence[Mapping[str, Any]]) -> ToolSurface:
        """Build a surface and fingerprint from provider-neutral tool schemas."""
        from nanobot.context.fingerprint import tool_surface_fingerprint

        copied = tuple(dict(definition) for definition in definitions)
        names: list[str] = []
        for definition in copied:
            function = definition.get("function")
            if isinstance(function, Mapping):
                name = cast(Mapping[str, object], function).get("name")
            else:
                name = definition.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("tool definition name must be a non-empty string")
            names.append(name)
        return cls(
            names=tuple(names),
            definitions=copied,
            fingerprint=tool_surface_fingerprint(copied),
        )

    def __post_init__(self) -> None:
        if len(self.names) != len(self.definitions):
            raise ValueError("tool names and definitions must have the same length")
        if any(not name for name in self.names):
            raise ValueError("tool names must not be empty")
        if not self.fingerprint:
            raise ValueError("tool surface fingerprint must not be empty")
