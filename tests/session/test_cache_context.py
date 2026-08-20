from nanobot.session.cache_context import (
    CACHE_CONTEXT_METADATA_KEY,
    CacheContextState,
    advance_context_epoch,
    read_cache_context_state,
    write_cache_context_state,
)


def test_cache_context_state_round_trips_as_one_bounded_metadata_record() -> None:
    metadata: dict[str, object] = {"unrelated": "keep"}
    state = CacheContextState(
        context_epoch=2,
        last_context_fingerprint="context",
        last_tool_surface_fingerprint="tools",
        last_runtime_cache_domain="openai:responses:gpt-5.6",
        last_provider="openai",
        last_model="gpt-5.6",
        last_mutation_reason="CACHE_DOMAIN_CHANGED",
    )

    write_cache_context_state(metadata, state)
    restored = read_cache_context_state(metadata)

    assert restored == state
    assert metadata["unrelated"] == "keep"
    assert set(metadata[CACHE_CONTEXT_METADATA_KEY]) == {
        "context_epoch",
        "last_context_fingerprint",
        "last_tool_surface_fingerprint",
        "last_runtime_cache_domain",
        "last_provider",
        "last_model",
        "last_mutation_reason",
    }


def test_context_epoch_advances_only_for_prefix_rewrite() -> None:
    state = CacheContextState(context_epoch=4)

    assert advance_context_epoch(state, ("MODEL_RUNTIME_CHANGED",)) == state
    advanced = advance_context_epoch(state, ("HISTORY_SNIPPED",))

    assert advanced.context_epoch == 5
    assert advanced.last_mutation_reason == "HISTORY_SNIPPED"


def test_cache_context_state_recovers_from_malformed_metadata() -> None:
    metadata = {
        CACHE_CONTEXT_METADATA_KEY: {
            "context_epoch": -1,
            "last_model": 123,
            "last_mutation_reason": None,
        }
    }

    assert read_cache_context_state(metadata) == CacheContextState()
