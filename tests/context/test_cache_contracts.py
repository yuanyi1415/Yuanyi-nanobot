"""Unit tests for the provider-neutral Context/Cache contracts."""

from dataclasses import FrozenInstanceError

import pytest

from nanobot.context import (
    CACHE_DOMAIN_CHANGED,
    MODEL_RUNTIME_CHANGED,
    CachePlan,
    CachePlanner,
    CacheTelemetry,
    ContextBlock,
    ContextFrame,
    ContextStability,
    RuntimeCacheDomain,
    ToolSurface,
    context_fingerprint,
    deterministic_json,
    diagnose_cache_transition,
    tool_surface_fingerprint,
)


def test_context_frame_and_blocks_are_frozen() -> None:
    block = ContextBlock("identity", ContextStability.CORE, "system", "stable")
    frame = ContextFrame((block,), (), {"role": "user", "content": "hello"})

    with pytest.raises(FrozenInstanceError):
        block.key = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        frame.blocks = ()  # type: ignore[misc]

    assert frame.blocks[0].stability is ContextStability.CORE


def test_context_block_rejects_empty_identity_fields() -> None:
    with pytest.raises(ValueError, match="key"):
        ContextBlock("", ContextStability.CORE, "system", "content")
    with pytest.raises(ValueError, match="role"):
        ContextBlock("identity", ContextStability.CORE, "", "content")


def test_deterministic_json_is_order_independent_and_redacts_secrets() -> None:
    left = {"b": 2, "a": {"apiKey": "secret-value", "content": "same"}}
    right = {"a": {"content": "same", "apiKey": "different"}, "b": 2}

    assert deterministic_json(left) == deterministic_json(right)
    assert "secret-value" not in deterministic_json(left)
    assert "different" not in deterministic_json(right)
    assert context_fingerprint(left) == context_fingerprint(right)


def test_tool_surface_fingerprint_is_stable_for_equal_definitions() -> None:
    definitions = [
        {"function": {"name": "read_file", "parameters": {"type": "object"}}},
    ]

    surface = ToolSurface.from_definitions(definitions)

    assert surface.fingerprint == tool_surface_fingerprint(list(surface.definitions))
    assert surface.names == ("read_file",)


def test_tool_surface_rejects_mismatched_names_and_definitions() -> None:
    with pytest.raises(ValueError, match="same length"):
        ToolSurface(("read_file",), (), "fingerprint")


def test_runtime_cache_domain_is_not_a_preset_or_snapshot_signature() -> None:
    domain = RuntimeCacheDomain("openai", "responses", "gpt-5.6")

    assert domain.key == "openai:responses:gpt-5.6"
    assert "api" not in domain.key


def test_cache_planner_uses_frozen_runtime_and_frame_content() -> None:
    from nanobot.providers.base import GenerationSettings, LLMProvider
    from nanobot.utils.llm_runtime import LLMRuntime

    class Provider(LLMProvider):
        def get_default_model(self) -> str:
            return "model"

        async def chat(self, **kwargs):
            raise AssertionError(kwargs)

    runtime = LLMRuntime(
        provider=Provider(),
        model="model",
        generation=GenerationSettings(),
        context_window_tokens=32_000,
    )
    frame = ContextFrame(
        blocks=(ContextBlock("core", ContextStability.CORE, "system", "stable"),),
        history=(),
        current_message={"role": "user", "content": "turn"},
    )
    surface = ToolSurface.from_definitions([])

    plan = CachePlanner().plan(
        frame=frame,
        runtime=runtime,
        session_key="webui:one",
        context_epoch=3,
        tool_surface=surface,
    )

    assert plan.domain.model == "model"
    assert plan.context_epoch == 3
    assert plan.boundaries == ("core",)


def test_cache_transition_reports_runtime_and_domain_independently() -> None:
    domain = RuntimeCacheDomain("openai", "responses", "gpt-5.6")

    assert diagnose_cache_transition(
        previous_provider="openai",
        previous_model="gpt-4.1",
        previous_domain="openai:chat:gpt-4.1",
        provider="openai",
        model="gpt-5.6",
        domain=domain,
    ) == (MODEL_RUNTIME_CHANGED, CACHE_DOMAIN_CHANGED)


def test_cache_plan_preserves_epoch_and_fingerprints() -> None:
    domain = RuntimeCacheDomain("deepseek", "chat", "deepseek-chat")
    plan = CachePlan(
        domain=domain,
        context_epoch=2,
        stable_prefix_fingerprint="stable",
        tool_surface_fingerprint="tools",
        boundaries=("core", "session"),
        session_scope_key="webui:one",
    )

    assert plan.context_epoch == 2
    assert plan.boundaries == ("core", "session")


def test_cache_feature_flags_are_off_by_default_and_independent() -> None:
    from nanobot.config.schema import AgentDefaults

    experimental = AgentDefaults().experimental

    assert experimental.context_frame_enabled is False
    assert experimental.provider_cache_plan_enabled is False
    assert AgentDefaults.model_validate({
        "experimental": {
            "contextFrameEnabled": True,
            "providerCachePlanEnabled": True,
        }
    }).experimental.provider_cache_plan_enabled is True


def test_cache_telemetry_keeps_unsupported_metrics_unknown() -> None:
    telemetry = CacheTelemetry(
        provider="qwen",
        model="qwen-max",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=80,
        cache_write_tokens=None,
        cache_miss_tokens=None,
    )

    assert telemetry.cache_read_tokens == 80
    assert telemetry.cache_write_tokens is None
    assert telemetry.cache_miss_tokens is None


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (lambda: RuntimeCacheDomain("", "route", "model"), "domain fields"),
        (lambda: CachePlan(RuntimeCacheDomain("p", "r", "m"), -1, "s", "t", (), "session"), "epoch"),
        (lambda: CacheTelemetry("", "model"), "provider"),
        (lambda: CacheTelemetry("provider", "model", cache_read_rate=2), "rate"),
    ],
)
def test_contracts_reject_invalid_values(factory, value: str) -> None:
    with pytest.raises(ValueError, match=value):
        factory()
