"""Versioned, bounded cache diagnostics stored in session metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast

from nanobot.agent.context_governance import PREFIX_REWRITE_DIAGNOSTICS

CACHE_CONTEXT_METADATA_KEY = "cache_context.v1"


@dataclass(frozen=True, slots=True)
class CacheContextState:
    context_epoch: int = 0
    last_context_fingerprint: str | None = None
    last_tool_surface_fingerprint: str | None = None
    last_runtime_cache_domain: str | None = None
    last_provider: str | None = None
    last_model: str | None = None
    last_mutation_reason: str = "NONE"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "context_epoch": self.context_epoch,
            "last_context_fingerprint": self.last_context_fingerprint,
            "last_tool_surface_fingerprint": self.last_tool_surface_fingerprint,
            "last_runtime_cache_domain": self.last_runtime_cache_domain,
            "last_provider": self.last_provider,
            "last_model": self.last_model,
            "last_mutation_reason": self.last_mutation_reason,
        }


def read_cache_context_state(metadata: Mapping[str, Any]) -> CacheContextState:
    """Read bounded cache state; malformed or legacy values fall back safely."""
    raw = metadata.get(CACHE_CONTEXT_METADATA_KEY)
    if not isinstance(raw, dict):
        return CacheContextState()
    data = cast(dict[str, object], raw)
    epoch = data.get("context_epoch", 0)
    reason = data.get("last_mutation_reason")
    return CacheContextState(
        context_epoch=epoch if isinstance(epoch, int) and epoch >= 0 else 0,
        last_context_fingerprint=_optional_text(data.get("last_context_fingerprint")),
        last_tool_surface_fingerprint=_optional_text(data.get("last_tool_surface_fingerprint")),
        last_runtime_cache_domain=_optional_text(data.get("last_runtime_cache_domain")),
        last_provider=_optional_text(data.get("last_provider")),
        last_model=_optional_text(data.get("last_model")),
        last_mutation_reason=reason if isinstance(reason, str) else "NONE",
    )


def advance_context_epoch(
    state: CacheContextState,
    governance_diagnostics: tuple[str, ...],
) -> CacheContextState:
    """Advance the epoch only when governance rewrites an existing prefix."""
    if not PREFIX_REWRITE_DIAGNOSTICS.intersection(governance_diagnostics):
        return state
    return CacheContextState(
        context_epoch=state.context_epoch + 1,
        last_context_fingerprint=state.last_context_fingerprint,
        last_tool_surface_fingerprint=state.last_tool_surface_fingerprint,
        last_runtime_cache_domain=state.last_runtime_cache_domain,
        last_provider=state.last_provider,
        last_model=state.last_model,
        last_mutation_reason=governance_diagnostics[-1] if governance_diagnostics else "NONE",
    )


def write_cache_context_state(metadata: dict[str, Any], state: CacheContextState) -> None:
    """Replace the single versioned state record without retaining per-turn history."""
    metadata[CACHE_CONTEXT_METADATA_KEY] = state.to_metadata()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
