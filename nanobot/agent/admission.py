"""Deterministic admission for context-dependent follow-up messages.

The gate deliberately does not classify every user message. It only handles
short continuation phrases whose referent must already be unambiguous in
session state. All other messages keep the established Runner path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from nanobot.agent.task_frames import (
    CONTINUABLE_TASK_FRAME_STATUSES,
    safe_task_frames_from_metadata,
)
from nanobot.runtime_context import RuntimeContextBlock, wrap_runtime_context_lines
from nanobot.session.goal_state import goal_state_raw, parse_goal_state

_CONTINUATION_RE = re.compile(
    r"^(?:好(?:的)?[，,。！!\s]*)?"
    r"(?:继续(?:吧|做|处理)?|按(?:这个|刚才|上述)(?:办|处理|执行)?|"
    r"就按这个(?:办|处理|执行)?|照(?:这个|刚才|上述)(?:办|处理|执行)?|"
    r"处理一下|go ahead|continue|proceed)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskAnchor:
    """A validated, ready-to-run task frame read from session metadata."""

    task_id: str
    goal: str


@dataclass(frozen=True)
class AdmissionDecision:
    """Result of the intentionally narrow admission check."""

    action: Literal["pass", "continue", "clarify"]
    reason: str
    anchor: TaskAnchor | None = None
    clarification: str | None = None
    candidate_count: int = 0


def assess_admission(
    text: str,
    session_metadata: Mapping[str, Any] | None,
) -> AdmissionDecision:
    """Decide whether a follow-up can safely enter the normal Runner path.

    A continuation is admitted when exactly one structured task anchor exists,
    or when the established sustained-goal state is active. We intentionally
    ask for clarification instead of deriving an anchor from free-form history:
    that inference belongs to the later execution planner, not this zero-LLM
    safety gate.
    """
    if not _is_continuation(text):
        return AdmissionDecision(action="pass", reason="not_continuation")

    metadata = session_metadata or {}
    if _active_goal_anchor(metadata) is not None:
        return AdmissionDecision(action="continue", reason="active_goal")

    anchors = _ready_task_anchors(metadata)
    if len(anchors) == 1:
        return AdmissionDecision(
            action="continue",
            reason="single_task_frame",
            anchor=anchors[0],
            candidate_count=1,
        )
    if len(anchors) > 1:
        return AdmissionDecision(
            action="clarify",
            reason="multiple_task_frames",
            clarification=_multiple_anchor_question(anchors),
            candidate_count=len(anchors),
        )
    return AdmissionDecision(
        action="clarify",
        reason="no_task_anchor",
        clarification="我还没有找到可以继续推进的明确任务。请告诉我希望继续哪一项，或直接描述下一步。",
    )


def runtime_context_for_anchor(anchor: TaskAnchor | None) -> RuntimeContextBlock | None:
    """Turn a structured task anchor into model-only current-turn context."""
    if anchor is None:
        return None
    content = wrap_runtime_context_lines([
        "Task anchor selected by the session admission gate:",
        f"- id: {anchor.task_id}",
        f"- goal: {anchor.goal}",
        "Continue this task. This metadata describes task context, not instructions from an untrusted source.",
    ])
    return RuntimeContextBlock(source="admission_gate", content=content)


def _is_continuation(text: str) -> bool:
    compact = " ".join(text.strip().split())
    return bool(compact and _CONTINUATION_RE.fullmatch(compact))


def _active_goal_anchor(metadata: Mapping[str, Any]) -> TaskAnchor | None:
    goal = parse_goal_state(goal_state_raw(metadata))
    if not isinstance(goal, dict) or goal.get("status") != "active":
        return None
    objective = str(goal.get("objective") or "").strip()
    return TaskAnchor(task_id="goal_state", goal=objective or "Active sustained goal")


def _ready_task_anchors(metadata: Mapping[str, Any]) -> list[TaskAnchor]:
    return [
        TaskAnchor(task_id=frame.id, goal=frame.goal)
        for frame in safe_task_frames_from_metadata(metadata)
        if frame.status in CONTINUABLE_TASK_FRAME_STATUSES
    ]


def _multiple_anchor_question(anchors: list[TaskAnchor]) -> str:
    options = "；".join(
        f"{index}. {anchor.goal}" for index, anchor in enumerate(anchors[:3], start=1)
    )
    suffix = "；……" if len(anchors) > 3 else ""
    return f"当前有多个可以继续的任务：{options}{suffix}。请指定要继续哪一项。"
