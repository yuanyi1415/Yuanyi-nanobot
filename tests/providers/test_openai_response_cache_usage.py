from nanobot.providers.openai_responses.parsing import _usage_from_response_obj


def test_responses_usage_maps_cache_read_and_write_tokens() -> None:
    usage = _usage_from_response_obj({
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "input_tokens_details": {
                "cached_tokens": 80,
                "cache_write_tokens": 20,
            },
        }
    })

    assert usage["cache_read_tokens"] == 80
    assert usage["cache_write_tokens"] == 20


def test_responses_usage_keeps_explicit_zero_distinct_from_unknown() -> None:
    usage = _usage_from_response_obj({
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {
                "cached_tokens": 0,
                "cache_write_tokens": 0,
            },
        }
    })

    assert usage["cache_read_tokens"] == 0
    assert usage["cache_write_tokens"] == 0


def test_responses_usage_omits_unsupported_cache_fields() -> None:
    usage = _usage_from_response_obj({
        "usage": {"input_tokens": 100, "output_tokens": 20}
    })

    assert "cache_read_tokens" not in usage
    assert "cache_write_tokens" not in usage
