"""V0 orchestration state and receipt contract coverage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nanobot.agent.orchestration import (
    HARNESS_METADATA_KEY,
    OrchestrationStore,
    OrchestrationValidationError,
    PlanNode,
    ReceiptMismatchError,
    new_plan,
    new_receipt,
)
from nanobot.agent.task_frames import TaskFrameOrigin, TaskFrameStore

_NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)
_SESSION = "webui:chat-1"


def _plan(*, dependencies: tuple[str, ...] = ()):
    return new_plan(
        frame_id="tf_1",
        frame_revision=1,
        nodes=(
            PlanNode(
                id="research",
                actor="subagent",
                goal="收集事实",
                deliverable="来源清单",
                acceptance=("包含两个可核验来源",),
            ),
            PlanNode(
                id="synthesis",
                actor="parent",
                goal="形成结论",
                deliverable="结论",
                acceptance=("引用来源",),
                depends_on=dependencies,
            ),
        ),
        now=_NOW,
    )


def test_plan_and_receipt_are_session_owned_and_json_persisted() -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key=_SESSION)
    plan = _plan(dependencies=("research",))
    store.add_plan(plan, session_key=_SESSION)
    receipt = new_receipt(
        parent_session_key=_SESSION,
        plan=plan,
        node_id="research",
        task_id="worker-1",
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
        now=_NOW,
    )
    store.issue_receipt(receipt, session_key=_SESSION)

    raw = metadata["orchestration.v1"]
    assert raw[HARNESS_METADATA_KEY]["plans"][0]["id"] == plan.id
    assert raw[HARNESS_METADATA_KEY]["receipts"][0]["task_id"] == "worker-1"


def test_receipt_rejects_cross_session_and_old_revision_results() -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key=_SESSION)
    plan = _plan()
    store.add_plan(plan, session_key=_SESSION)
    store.issue_receipt(new_receipt(
        parent_session_key=_SESSION,
        plan=plan,
        node_id="research",
        task_id="worker-1",
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
        now=_NOW,
    ), session_key=_SESSION)

    with pytest.raises(ReceiptMismatchError):
        store.consume_receipt(
            parent_session_key="webui:other",
            frame_id="tf_1",
            frame_revision=1,
            plan_id=plan.id,
            node_id="research",
            task_id="worker-1",
            result_ref="artifact://result",
            now=_NOW,
        )
    with pytest.raises(ReceiptMismatchError):
        store.consume_receipt(
            parent_session_key=_SESSION,
            frame_id="tf_1",
            frame_revision=2,
            plan_id=plan.id,
            node_id="research",
            task_id="worker-1",
            result_ref="artifact://result",
            now=_NOW,
        )


def test_stop_plan_cancels_only_its_pending_receipts() -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key=_SESSION)
    plan = _plan()
    store.add_plan(plan, session_key=_SESSION)
    store.transition_plan(plan.id, "running", session_key=_SESSION, now=_NOW)
    store.issue_receipt(new_receipt(
        parent_session_key=_SESSION,
        plan=plan,
        node_id="research",
        task_id="worker-1",
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
        now=_NOW,
    ), session_key=_SESSION)

    stopped = store.transition_plan(plan.id, "stopped", session_key=_SESSION, now=_NOW)
    assert stopped.status == "stopped"
    assert store.receipts[0].status == "cancelled"


def test_blocking_plan_cancels_its_pending_receipts() -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key=_SESSION)
    plan = _plan()
    store.add_plan(plan, session_key=_SESSION)
    store.transition_plan(plan.id, "running", session_key=_SESSION, now=_NOW)
    store.issue_receipt(new_receipt(
        parent_session_key=_SESSION,
        plan=plan,
        node_id="research",
        task_id="worker-1",
        expires_at=(_NOW + timedelta(hours=1)).isoformat(),
        now=_NOW,
    ), session_key=_SESSION)

    store.transition_plan(plan.id, "blocked", session_key=_SESSION, now=_NOW)
    assert store.receipts[0].status == "cancelled"


def test_plan_rejects_cycles_and_invalid_dependencies() -> None:
    with pytest.raises(OrchestrationValidationError, match="dependency"):
        _plan(dependencies=("missing",))
    with pytest.raises(OrchestrationValidationError, match="cycle"):
        new_plan(
            frame_id="tf_1",
            frame_revision=1,
            nodes=(
                PlanNode("a", "parent", "A", "A", ("ok",), ("b",)),
                PlanNode("b", "subagent", "B", "B", ("ok",), ("a",)),
            ),
            now=_NOW,
        )


def test_task_frame_writes_preserve_harness_state() -> None:
    metadata: dict[str, object] = {}
    orchestration = OrchestrationStore(metadata, session_key=_SESSION)
    orchestration.add_plan(_plan(), session_key=_SESSION)
    frames = TaskFrameStore(metadata, session_key=_SESSION)
    frames.create(
        session_key=_SESSION,
        goal="继续任务",
        origin=TaskFrameOrigin(turn_id="turn-1", evidence=("current_turn",)),
        now=_NOW,
    )
    assert metadata["orchestration.v1"][HARNESS_METADATA_KEY]["plans"]
