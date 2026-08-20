"""GLM / Zhipu prompt cache adapter."""

from __future__ import annotations

from nanobot.context.telemetry import CacheTelemetry


class GLMCacheAdapter:
    """GLM auto-caches stable prefixes; it does not inherit OpenAI-only cache fields."""

    provider = "zhipu"

    @staticmethod
    def telemetry(
        *,
        model: str,
        usage: dict[str, int],
        model_preset: str | None = None,
        selection_source: str | None = None,
        runtime_cache_domain: str | None = None,
        context_epoch: int | None = None,
    ) -> CacheTelemetry:
        return CacheTelemetry(
            provider="zhipu",
            model=model,
            model_preset=model_preset,
            selection_source=selection_source,
            runtime_cache_domain=runtime_cache_domain,
            context_epoch=context_epoch,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cache_read_tokens=usage.get("cached_tokens", usage.get("cache_read_tokens")),
        )
