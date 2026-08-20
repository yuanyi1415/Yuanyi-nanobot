"""Model-level cache capability declarations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheCapabilities:
    implicit_prefix: bool = False
    explicit_breakpoints: bool = False
    stable_cache_key: bool = False
    cache_read_metrics: bool = False
    cache_write_metrics: bool = False
    cache_miss_metrics: bool = False


def capabilities_for(provider: str, model: str) -> CacheCapabilities:
    """Resolve conservative capabilities by provider family and model."""
    provider_name = provider.lower()
    model_name = model.lower()
    if provider_name == "deepseek":
        return CacheCapabilities(
            implicit_prefix=True,
            cache_read_metrics=True,
            cache_miss_metrics=True,
        )
    if provider_name in {"openai", "openai_codex"}:
        return CacheCapabilities(
            implicit_prefix=True,
            explicit_breakpoints=False,
            stable_cache_key=True,
            cache_read_metrics=True,
            cache_write_metrics="gpt-5.6" in model_name,
        )
    if provider_name == "dashscope":
        return CacheCapabilities(
            implicit_prefix=True,
            explicit_breakpoints=False,
            cache_read_metrics=True,
        )
    if provider_name == "zhipu":
        return CacheCapabilities(
            implicit_prefix=True,
            explicit_breakpoints=False,
            cache_read_metrics=True,
        )
    return CacheCapabilities()
