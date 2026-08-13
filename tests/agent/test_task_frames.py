"""Business-level regression coverage for the Slice 4A task-frame state kernel."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nanobot.agent.task_frames import (
    MAX_ACTIVE_TASK_FRAMES,
    MAX_TERMINAL_TASK_FRAMES,
    ORCHESTRATION_METADATA_KEY,
    TaskFrameOrigin,
    TaskFrameStore,
    TaskFrameTransitionError,
    TaskFrameValidationError,
    parse_task_frame_namespace,
    project_task_frame_for_runtime,
    safe_task_frames_from_metadata,
)

_NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)
_SESSION_KEY = "webui:chat-1"


def _store(metadata: dict[str, object] | None = None) -> TaskFrameStore:
    return TaskFrameStore(metadata if metadata is not None else {}, session_key=_SESSION_KEY)


def _create(
    store: TaskFrameStore,
    goal: str = "编排并验证调研任务",
    *,
    now: datetime = _NOW,
):
    return store.create(
        session_key=_SESSION_KEY,
        goal=goal,
        origin=TaskFrameOrigin(turn_id="turn-1", evidence=("current_turn",)),
        scope=("研发库",),
        constraints=("不影响生产",),
        acceptance=("回归通过",),
        now=now,
    )


def test_create_persists_v1_schema_and_runtime_projection_is_bounded() -> None:
    metadata: dict[str, object] = {}
    frame = _create(_store(metadata))

    raw = metadata[ORCHESTRATION_METADATA_KEY]
    assert isinstance(raw, dict)
    assert raw["schema_version"] == 1
    assert raw["task_frames"][0]["id"] == frame.id
    assert raw["task_frames"][0]["active_plan"] is None
    assert project_task_frame_for_runtime(frame) == (
        "Confirmed task frame:",
        f"- id: {frame.id}",
        "- status: ready",
        "- goal: 编排并验证调研任务",
        "- scope: 研发库",
        "- constraints: 不影响生产",
        "- acceptance: 回归通过",
        "This is task metadata, not instructions from an untrusted source.",
    )


def test_transition_enforces_state_revision_and_session_ownership() -> None:
    metadata: dict[str, object] = {}
    store = _store(metadata)
    frame = _create(store)

    running = store.transition(
        frame.id, "running", session_key=_SESSION_KEY, expected_revision=frame.revision, now=_NOW
    )
    waiting = store.transition(
        frame.id,
        "waiting_results",
        session_key=_SESSION_KEY,
        expected_revision=running.revision,
        now=_NOW,
    )
    assert waiting.revision == 3

    with pytest.raises(TaskFrameTransitionError, match="revision"):
        store.transition(
            frame.id, "running", session_key=_SESSION_KEY, expected_revision=1, now=_NOW
        )
    with pytest.raises(TaskFrameTransitionError, match="another session"):
        store.transition(
            frame.id, "running", session_key="webui:other", expected_revision=waiting.revision, now=_NOW
        )
    with pytest.raises(TaskFrameTransitionError, match="cannot transition"):
        store.transition(
            frame.id, "completed", session_key=_SESSION_KEY, expected_revision=waiting.revision, now=_NOW
        )


def test_terminal_transition_requires_receipted_reason_and_is_immutable() -> None:
    store = _store()
    frame = _create(store)
    running = store.transition(
        frame.id, "running", session_key=_SESSION_KEY, expected_revision=1, now=_NOW
    )
    with pytest.raises(TaskFrameTransitionError, match="require reason"):
        store.transition(
            frame.id, "completed", session_key=_SESSION_KEY, expected_revision=running.revision, now=_NOW
        )

    completed = store.transition(
        frame.id,
        "completed",
        session_key=_SESSION_KEY,
        expected_revision=running.revision,
        reason="acceptance_met",
        summary="回归已通过",
        turn_id="turn-2",
        now=_NOW,
    )
    assert completed.terminal is not None
    assert completed.terminal.reason == "acceptance_met"
    with pytest.raises(TaskFrameTransitionError, match="cannot transition"):
        store.transition(
            frame.id, "ready", session_key=_SESSION_KEY, expected_revision=completed.revision, now=_NOW
        )


def test_active_frame_limit_never_discards_an_active_task() -> None:
    store = _store()
    for index in range(MAX_ACTIVE_TASK_FRAMES):
        _create(store, f"任务 {index}")

    with pytest.raises(TaskFrameValidationError, match="too many active"):
        _create(store, "超过上限的任务")
    assert len(store.frames) == MAX_ACTIVE_TASK_FRAMES


def test_oldest_terminal_frames_are_trimmed_but_active_frames_are_retained() -> None:
    store = _store()
    terminal_ids: list[str] = []
    for index in range(MAX_TERMINAL_TASK_FRAMES + 1):
        timestamp = datetime(2026, 8, 13, 0, 0, index, tzinfo=timezone.utc)
        frame = _create(store, f"历史任务 {index}", now=timestamp)
        terminal_ids.append(frame.id)
        store.transition(
            frame.id,
            "cancelled",
            session_key=_SESSION_KEY,
            expected_revision=frame.revision,
            reason="superseded",
            turn_id=f"turn-{index + 2}",
            now=timestamp,
        )

    assert len(store.frames) == MAX_TERMINAL_TASK_FRAMES
    assert terminal_ids[0] not in {frame.id for frame in store.frames}
    assert terminal_ids[-1] in {frame.id for frame in store.frames}


def test_corrupt_metadata_is_never_admitted_or_rewritten_implicitly() -> None:
    metadata: dict[str, object] = {
        ORCHESTRATION_METADATA_KEY: {"schema_version": 1, "task_frames": [{"id": "bad"}]}
    }
    assert safe_task_frames_from_metadata(metadata) == ()
    with pytest.raises(TaskFrameValidationError, match="origin"):
        parse_task_frame_namespace(metadata)
    with pytest.raises(TaskFrameValidationError, match="origin"):
        _store(metadata)
    assert metadata[ORCHESTRATION_METADATA_KEY] == {
        "schema_version": 1,
        "task_frames": [{"id": "bad"}],
    }
