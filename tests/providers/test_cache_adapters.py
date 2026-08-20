from nanobot.context.cache_plan import CachePlan, RuntimeCacheDomain
from nanobot.providers.cache.capabilities import CacheCapabilities, capabilities_for
from nanobot.providers.cache.dashscope import QwenCacheAdapter
from nanobot.providers.cache.deepseek import DeepSeekCacheAdapter
from nanobot.providers.cache.openai import OpenAICacheAdapter
from nanobot.providers.cache.zhipu import GLMCacheAdapter
from nanobot.providers.openai_codex_provider import OpenAICodexProvider


def _plan() -> CachePlan:
    return CachePlan(
        domain=RuntimeCacheDomain("openai_codex", "responses", "gpt-5.6"),
        context_epoch=2,
        stable_prefix_fingerprint="stable",
        tool_surface_fingerprint="tools",
        boundaries=("core",),
        session_scope_key="webui:one",
    )


def test_capabilities_are_model_aware_and_conservative() -> None:
    assert capabilities_for("deepseek", "deepseek-v4-flash") == CacheCapabilities(
        implicit_prefix=True,
        cache_read_metrics=True,
        cache_miss_metrics=True,
    )
    gpt56 = capabilities_for("openai_codex", "gpt-5.6")
    assert gpt56.explicit_breakpoints is False
    assert gpt56.cache_write_metrics is True
    assert capabilities_for("openai_codex", "gpt-4.1").cache_write_metrics is False


def test_deepseek_adapter_maps_read_and_miss_usage() -> None:
    telemetry = DeepSeekCacheAdapter.telemetry(
        model="deepseek-chat",
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "cached_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        },
    )

    assert telemetry.cache_read_tokens == 80
    assert telemetry.cache_miss_tokens == 20


def test_qwen_capabilities_are_implicit_and_do_not_use_explicit_marker() -> None:
    caps = capabilities_for("dashscope", "qwen-max")
    assert caps.implicit_prefix is True
    assert caps.explicit_breakpoints is False


def test_glm_capabilities_are_implicit_without_openai_only_fields() -> None:
    caps = capabilities_for("zhipu", "glm-4")
    assert caps.implicit_prefix is True
    assert caps.stable_cache_key is False


def test_qwen_adapter_maps_cached_usage() -> None:
    telemetry = QwenCacheAdapter.telemetry(
        model="qwen-max",
        usage={"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 60},
    )
    assert telemetry.provider == "dashscope"
    assert telemetry.cache_read_tokens == 60
    assert telemetry.cache_write_tokens is None


def test_glm_adapter_maps_cached_usage_without_openai_fields() -> None:
    telemetry = GLMCacheAdapter.telemetry(
        model="glm-4",
        usage={"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 55},
    )
    assert telemetry.provider == "zhipu"
    assert telemetry.cache_read_tokens == 55


def test_openai_adapter_maps_supported_usage_and_keeps_write_unknown() -> None:
    telemetry = OpenAICacheAdapter.telemetry(
        model="gpt-4.1",
        usage={"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 80},
    )

    assert telemetry.cache_read_tokens == 80
    assert telemetry.cache_write_tokens is None


def test_codex_adapter_scope_is_stable_without_message_content() -> None:
    provider = OpenAICodexProvider()

    first = provider.cache_request_kwargs(_plan())
    second = provider.cache_request_kwargs(_plan())

    assert first == second
    assert len(first["prompt_cache_key"]) == 64
    assert "webui:one" not in first["prompt_cache_key"]
