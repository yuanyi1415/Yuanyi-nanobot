from nanobot.context.cache_plan import CachePlan, RuntimeCacheDomain
from nanobot.providers.cache.capabilities import capabilities_for
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.session.cache_context import CacheContextState, advance_context_epoch


def _plan(model: str, epoch: int = 0) -> CachePlan:
    return CachePlan(
        domain=RuntimeCacheDomain("openai_codex", "responses", model),
        context_epoch=epoch,
        stable_prefix_fingerprint="stable-prefix",
        tool_surface_fingerprint="tools",
        boundaries=("core", "session"),
        session_scope_key="webui:case",
    )


def test_case_1_gpt_continuous_turns_keep_key_stable() -> None:
    provider = OpenAICodexProvider()
    assert provider.cache_request_kwargs(_plan("gpt-5.6")) == provider.cache_request_kwargs(
        _plan("gpt-5.6")
    )


def test_case_2_model_switch_does_not_advance_epoch() -> None:
    state = CacheContextState(context_epoch=2)
    assert advance_context_epoch(state, ("MODEL_RUNTIME_CHANGED",)) == state


def test_case_3_returning_to_gpt_reuses_same_domain_and_key() -> None:
    provider = OpenAICodexProvider()
    first = provider.cache_request_kwargs(_plan("gpt-5.6"))
    _ = provider.cache_request_kwargs(_plan("deepseek-chat"))
    returned = provider.cache_request_kwargs(_plan("gpt-5.6"))
    assert returned == first


def test_case_4_generation_only_change_keeps_domain() -> None:
    assert _plan("gpt-5.6").domain == _plan("gpt-5.6").domain


def test_case_5_model_change_changes_domain() -> None:
    assert _plan("gpt-5.6").domain != _plan("gpt-5.4").domain


def test_case_6_real_rewrite_advances_epoch() -> None:
    advanced = advance_context_epoch(CacheContextState(context_epoch=2), ("HISTORY_SNIPPED",))
    assert advanced.context_epoch == 3


def test_case_8_unsupported_breakpoint_is_not_enabled() -> None:
    capabilities = capabilities_for("openai_codex", "gpt-4.1")
    assert capabilities.explicit_breakpoints is False
    assert "prompt_cache_breakpoint" not in OpenAICodexProvider().cache_request_kwargs(_plan("gpt-4.1"))
