"""Integration tests for the skill-guidance lane + observability (FR-1/FR-4/FR-5).

Covers the loop-side lane decision, observability logging (channel=observability),
auto-bind injection through ``build_messages``, ``$skill`` precedence, and the
feature-flag-off zero-change contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop, TurnContext, TurnKind
from nanobot.agent.skills import SkillsLoader
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config


def _write_skill(
    base: Path,
    name: str,
    *,
    metadata_json: dict | None = None,
    body: str = "# Skill\n",
) -> None:
    skill_dir = base / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    if metadata_json is not None:
        payload = json.dumps({"nanobot": metadata_json}, separators=(",", ":"))
        lines.append(f"metadata: {payload}")
    lines.extend(["---", "", body])
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


def _make_loop(tmp_path: Path, **kwargs: object) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        **kwargs,
    )
    # Isolate from the repository's bundled skills so recall only sees the
    # workspace skills this test writes.
    empty_builtin = tmp_path / ".empty-builtin"
    empty_builtin.mkdir(exist_ok=True)
    loop.context.skills = SkillsLoader(tmp_path, builtin_skills_dir=empty_builtin)
    return loop


def _user_turn(loop: AgentLoop, content: str, *, kind: TurnKind = TurnKind.USER) -> TurnContext:
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="c1", content=content)
    return TurnContext(
        msg=msg,
        session_key="cli:c1",
        turn_id="turn-1",
        runtime=loop.llm_runtime(),
        kind=kind,
        delivery=loop.turn_delivery_factory.create(msg, "cli:c1"),
    )


def _with_session(ctx: TurnContext) -> TurnContext:
    ctx.session = SimpleNamespace(
        key="cli:c1",
        metadata={},
        policy=SimpleNamespace(persist=True, log_content=True),
    )
    return ctx


# ---------------------------------------------------------------------------
# FR-5: flags off -> zero new behavior
# ---------------------------------------------------------------------------


def test_flags_off_no_recall_no_logs_no_injection(tmp_path: Path) -> None:
    """With both flags off, no recall runs, no observability log, no injection."""
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    loop = _make_loop(tmp_path)
    assert loop.observe_lane is False
    assert loop.skill_auto_bind is False

    # A recall that would raise proves it is never invoked when flags are off.
    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("recall_skill_candidates must not run with flags off")

    loop.context.skills.recall_skill_candidates = _explode  # type: ignore[method-assign]

    logs: list[str] = []
    sink_id = logger.add(logs.append, level="INFO", format="{message}")
    try:
        messages = loop._build_initial_messages(_with_session(_user_turn(loop, "open a github pr")))
    finally:
        logger.remove(sink_id)

    assert messages[0]["role"] == "system"
    assert "### Skill: github" not in messages[0]["content"]
    assert not any("skill_lane" in line for line in logs)


# ---------------------------------------------------------------------------
# FR-4: auto bind injection + explicit $skill precedence
# ---------------------------------------------------------------------------


def test_skill_auto_bind_injects_high_confidence_skill(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    loop = _make_loop(tmp_path, skill_auto_bind=True)

    messages = loop._build_initial_messages(_with_session(_user_turn(loop, "open a github pr")))
    assert "### Skill: github" in messages[0]["content"]


def test_explicit_skill_precedes_auto_bind_in_context(tmp_path: Path) -> None:
    """$skill references come first; auto bindings append at the tail (FR-4)."""
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    _write_skill(tmp_path / "skills", "beta", metadata_json={"description": "beta helper"})

    builder = ContextBuilder(tmp_path)
    seen: list[list[str]] = []
    original = builder.build_system_prompt

    def _spy(**kwargs: object) -> str:
        seen.append(list(kwargs.get("active_skill_names") or []))
        return original(**kwargs)

    builder.build_system_prompt = _spy  # type: ignore[method-assign]
    builder.build_messages(
        [],
        "use $beta for github work",
        auto_bind_skill_names=["github"],
    )
    assert seen == [["beta", "github"]]


def test_auto_bind_does_not_duplicate_explicit_skill(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    builder = ContextBuilder(tmp_path)
    seen: list[list[str]] = []
    original = builder.build_system_prompt

    def _spy(**kwargs: object) -> str:
        seen.append(list(kwargs.get("active_skill_names") or []))
        return original(**kwargs)

    builder.build_system_prompt = _spy  # type: ignore[method-assign]
    builder.build_messages([], "use $github", auto_bind_skill_names=["github"])
    assert seen == [["github"]]


def test_auto_bind_disabled_flag_means_no_injection(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    # observe only: recall runs (for the log) but nothing is injected.
    loop = _make_loop(tmp_path, observe_lane=True, skill_auto_bind=False)
    messages = loop._build_initial_messages(_with_session(_user_turn(loop, "open a github pr")))
    assert "### Skill: github" not in messages[0]["content"]


# ---------------------------------------------------------------------------
# FR-1: lane decision + observability logging
# ---------------------------------------------------------------------------


def test_observe_lane_emits_structured_log(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    loop = _make_loop(tmp_path, observe_lane=True, skill_auto_bind=True)

    logs: list[str] = []
    sink_id = logger.add(logs.append, level="INFO", format="{extra[channel]}|{message}")
    try:
        loop._observe_lane(
            _user_turn(loop, "open a github pr"),
            loop._decide_skill_lane(_user_turn(loop, "open a github pr")),
        )
    finally:
        logger.remove(sink_id)

    assert logs, "expected an observability log line"
    line = logs[0]
    assert line.startswith("observability|skill_lane ")
    assert "lane=skill" in line
    assert "candidates=github" in line
    assert "bound=github" in line
    assert "bound_token_estimate=" in line
    assert "recall_elapsed_ms=" in line
    assert "reason=high_confidence" in line
    assert "open a github pr" not in line


def test_observe_lane_fast_no_binding(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, observe_lane=True)
    decision = loop._decide_skill_lane(_user_turn(loop, "hello, how are you?"))
    assert decision.lane == "fast"
    assert decision.explicit == ()
    assert decision.candidates == ()
    assert decision.bound == ()
    assert decision.reason == "none"
    assert decision.recall_elapsed_ms >= 0


def test_observe_lane_system_turn_is_other(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, observe_lane=True)
    decision = loop._decide_skill_lane(
        _user_turn(loop, "internal system payload", kind=TurnKind.SYSTEM)
    )
    assert decision.lane == "other"
    assert decision.candidates == ()


def test_observe_lane_explicit_skill_is_skill_lane(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    loop = _make_loop(tmp_path, observe_lane=True)
    decision = loop._decide_skill_lane(_user_turn(loop, "use $github"))
    assert decision.lane == "skill"
    assert decision.explicit == ("github",)
    assert decision.bound == ()


def test_observe_lane_ambiguous_candidates_recorded_not_bound(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    _write_skill(tmp_path / "skills", "git", metadata_json={"description": "git workflows"})
    loop = _make_loop(tmp_path, observe_lane=True, skill_auto_bind=True)
    decision = loop._decide_skill_lane(_user_turn(loop, "git and github both here"))
    assert decision.lane == "fast"  # no binding -> fast path, but candidates recorded
    assert set(decision.candidates) == {"github", "git"}
    assert decision.bound == ()
    assert decision.reason == "ambiguous_multi_candidate"


def test_observe_lane_never_logs_message_body(tmp_path: Path) -> None:
    """Observability remains useful without retaining user-provided content."""
    loop = _make_loop(tmp_path, observe_lane=True)
    ctx = _user_turn(loop, "sensitive secret content")
    ctx.session = SimpleNamespace(policy=SimpleNamespace(log_content=False))

    logs: list[str] = []
    sink_id = logger.add(logs.append, level="INFO", format="{message}")
    try:
        loop._observe_lane(ctx, loop._decide_skill_lane(ctx))
    finally:
        logger.remove(sink_id)

    assert logs
    assert "sensitive secret content" not in logs[0]


def test_observe_lane_records_context_loaded_after_auto_binding(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    loop = _make_loop(tmp_path, observe_lane=True, skill_auto_bind=True)
    logs: list[str] = []
    sink_id = logger.add(logs.append, level="INFO", format="{message}")
    try:
        loop._build_initial_messages(_with_session(_user_turn(loop, "open a github pr")))
    finally:
        logger.remove(sink_id)

    assert any("skill_lane event=decision" in line for line in logs)
    assert any("skill_lane event=context_loaded" in line and "skills=github" in line for line in logs)


def test_flags_off_produce_no_observability_log(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    _write_skill(tmp_path / "skills", "github", metadata_json={"description": "github prs"})
    loop = _make_loop(tmp_path)
    logs: list[str] = []
    sink_id = logger.add(logs.append, level="INFO", format="{message}")
    try:
        loop._build_initial_messages(_with_session(_user_turn(loop, "open a github pr")))
    finally:
        logger.remove(sink_id)
    assert not any("skill_lane" in line for line in logs)


# ---------------------------------------------------------------------------
# Config wiring
# ---------------------------------------------------------------------------


def test_experimental_config_defaults() -> None:
    config = Config()
    experimental = config.agents.defaults.experimental
    assert experimental.observe_lane is False
    assert experimental.skill_auto_bind is False
    assert experimental.skill_auto_bind_max_count == 2
    assert experimental.skill_auto_bind_token_budget == 2000


def test_experimental_config_camel_case_aliases() -> None:
    config = Config(
        agents={
            "defaults": {
                "experimental": {
                    "observeLane": True,
                    "skillAutoBind": True,
                    "skillAutoBindMaxCount": 3,
                    "skillAutoBindTokenBudget": 1000,
                }
            }
        }
    )
    experimental = config.agents.defaults.experimental
    assert experimental.observe_lane is True
    assert experimental.skill_auto_bind is True
    assert experimental.skill_auto_bind_max_count == 3
    assert experimental.skill_auto_bind_token_budget == 1000
