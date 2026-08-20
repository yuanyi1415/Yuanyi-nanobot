from unittest.mock import MagicMock

from nanobot.agent.context_governance import (
    GOVERNANCE_HISTORY_SNIPPED,
    GOVERNANCE_MALFORMED_REPAIRED,
    GOVERNANCE_NONE,
    ContextGovernanceConfig,
    ContextGovernor,
)


def _config() -> ContextGovernanceConfig:
    return ContextGovernanceConfig(
        provider=MagicMock(),
        model="test-model",
        tools=MagicMock(),
        workspace=None,
        session_key="test:session",
        max_tool_result_chars=100,
    )


def test_governance_reports_none_without_message_rewrite() -> None:
    governor = ContextGovernor()
    messages = [{"role": "user", "content": "hello"}]

    assert governor.prepare_for_model(_config(), messages, set()) == messages
    assert governor.last_diagnostics == (GOVERNANCE_NONE,)
    assert governor.rewrites_prefix(governor.last_diagnostics) is False


def test_governance_reports_malformed_repair_without_prefix_rewrite() -> None:
    governor = ContextGovernor()
    messages = [{"role": "assistant", "content": "[Previous assistant message omitted.]"}]

    result = governor.prepare_for_model(_config(), messages, set())

    assert result == []
    assert governor.last_diagnostics == (GOVERNANCE_MALFORMED_REPAIRED,)
    assert governor.rewrites_prefix(governor.last_diagnostics) is False


def test_governance_rewrite_diagnostic_is_epoch_relevant() -> None:
    governor = ContextGovernor()

    assert governor.rewrites_prefix((GOVERNANCE_HISTORY_SNIPPED,)) is True
