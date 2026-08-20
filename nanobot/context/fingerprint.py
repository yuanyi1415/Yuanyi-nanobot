"""Deterministic, non-sensitive fingerprints for context contracts."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any, cast

_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "password", "secret", "token")


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _normalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _normalize(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        items = cast(Mapping[object, object], value).items()
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else _normalize(item)
            for key, item in items
        }
    if isinstance(value, (list, tuple)):
        sequence = cast(Sequence[object], value)
        return [_normalize(item) for item in sequence]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def deterministic_json(value: Any) -> str:
    """Serialize a value deterministically while redacting sensitive fields."""
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def context_fingerprint(value: Any) -> str:
    """Return a stable SHA-256 fingerprint for a context-shaped value."""
    return hashlib.sha256(deterministic_json(value).encode("utf-8")).hexdigest()


def tool_surface_fingerprint(definitions: Sequence[Mapping[str, Any]]) -> str:
    """Return a stable fingerprint for projected tool definitions."""
    return context_fingerprint(list(definitions))
