"""Provider-neutral cache telemetry contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheTelemetry:
    """One request's cache metrics; unsupported values remain ``None``."""

    provider: str
    model: str
    model_preset: str | None = None
    selection_source: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_miss_tokens: int | None = None
    cache_read_rate: float | None = None
    runtime_cache_domain: str | None = None
    context_epoch: int | None = None
    prompt_cache_key: str | None = None
    stable_prefix_fingerprint: str | None = None
    tool_surface_fingerprint: str | None = None
    mutation_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider or not self.model:
            raise ValueError("telemetry provider and model must not be empty")
        for field_name in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "cache_miss_tokens",
            "context_epoch",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must not be negative")
        if self.cache_read_rate is not None and not 0 <= self.cache_read_rate <= 1:
            raise ValueError("cache read rate must be between 0 and 1")
