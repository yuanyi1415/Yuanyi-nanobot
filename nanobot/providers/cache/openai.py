"""OpenAI prompt cache adapter helpers."""

from __future__ import annotations

from nanobot.context.cache_plan import CachePlan
from nanobot.context.telemetry import CacheTelemetry


class OpenAICacheAdapter:
    """Map OpenAI cached usage without changing generic Context semantics."""

    provider = "openai"

    @staticmethod
    def telemetry(
        *,
        model: str,
        usage: dict[str, int],
        model_preset: str | None = None,
        selection_source: str | None = None,
        runtime_cache_domain: str | None = None,
        context_epoch: int | None = None,
        prompt_cache_key: str | None = None,
    ) -> CacheTelemetry:
        return CacheTelemetry(
            provider="openai",
            model=model,
            model_preset=model_preset,
            selection_source=selection_source,
            runtime_cache_domain=runtime_cache_domain,
            context_epoch=context_epoch,
            prompt_cache_key=prompt_cache_key,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cache_read_tokens=usage.get("cached_tokens", usage.get("cache_read_tokens")),
            cache_write_tokens=usage.get("cache_write_tokens"),
        )

    @staticmethod
    def request_kwargs(plan: CachePlan) -> dict[str, str]:
        """Return only provider-neutral stable scope data for an adapter."""
        return {
            "cache_scope": f"{plan.session_scope_key}:{plan.domain.key}:{plan.context_epoch}"
        }
