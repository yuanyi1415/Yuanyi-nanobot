"""Provider-neutral cache planning contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nanobot.context.fingerprint import context_fingerprint

if TYPE_CHECKING:
    from nanobot.context.frame import ContextFrame, ToolSurface
    from nanobot.utils.llm_runtime import LLMRuntime


@dataclass(frozen=True, slots=True)
class RuntimeCacheDomain:
    """Stable cache identity for one provider route and model."""

    provider_family: str
    provider_route: str
    model: str

    def __post_init__(self) -> None:
        if not self.provider_family or not self.provider_route or not self.model:
            raise ValueError("runtime cache domain fields must not be empty")

    @property
    def key(self) -> str:
        return f"{self.provider_family}:{self.provider_route}:{self.model}"


@dataclass(frozen=True, slots=True)
class CachePlan:
    """Provider-neutral cache plan passed to a provider adapter later."""

    domain: RuntimeCacheDomain
    context_epoch: int
    stable_prefix_fingerprint: str
    tool_surface_fingerprint: str
    boundaries: tuple[str, ...]
    session_scope_key: str

    def __post_init__(self) -> None:
        if self.context_epoch < 0:
            raise ValueError("context epoch must not be negative")
        if not self.stable_prefix_fingerprint:
            raise ValueError("stable prefix fingerprint must not be empty")
        if not self.tool_surface_fingerprint:
            raise ValueError("tool surface fingerprint must not be empty")
        if not self.session_scope_key:
            raise ValueError("session scope key must not be empty")


MODEL_RUNTIME_CHANGED = "MODEL_RUNTIME_CHANGED"
CACHE_DOMAIN_CHANGED = "CACHE_DOMAIN_CHANGED"


class CachePlanner:
    """Create a provider-neutral plan from one already-frozen runtime."""

    def plan(
        self,
        *,
        frame: "ContextFrame",
        runtime: "LLMRuntime",
        session_key: str,
        context_epoch: int,
        tool_surface: "ToolSurface",
    ) -> CachePlan:
        provider = runtime.provider
        provider_family = type(provider).__name__.removesuffix("Provider").lower()
        provider_family = provider_family or type(provider).__name__.lower()
        provider_route = f"{type(provider).__module__}:{type(provider).__qualname__}"
        stable_blocks = [
            {
                "key": block.key,
                "stability": block.stability.value,
                "role": block.role,
                "content": block.content,
            }
            for block in frame.blocks
            if block.cacheable
        ]
        return CachePlan(
            domain=RuntimeCacheDomain(provider_family, provider_route, runtime.model),
            context_epoch=context_epoch,
            stable_prefix_fingerprint=context_fingerprint(stable_blocks),
            tool_surface_fingerprint=tool_surface.fingerprint,
            boundaries=tuple(block.key for block in frame.blocks if block.cacheable),
            session_scope_key=session_key,
        )


def diagnose_cache_transition(
    *,
    previous_provider: str | None,
    previous_model: str | None,
    previous_domain: str | None,
    provider: str,
    model: str,
    domain: RuntimeCacheDomain,
) -> tuple[str, ...]:
    """Report runtime and domain changes independently."""
    reasons: list[str] = []
    if previous_provider is not None and (previous_provider, previous_model) != (provider, model):
        reasons.append(MODEL_RUNTIME_CHANGED)
    if previous_domain is not None and previous_domain != domain.key:
        reasons.append(CACHE_DOMAIN_CHANGED)
    return tuple(reasons)
