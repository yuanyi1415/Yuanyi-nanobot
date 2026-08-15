"""Validated, session-owned V0 execution plans and result receipts.

This is a state kernel.  It deliberately does not choose plans, call models,
or start workers; the loop/coordinator owns those actions.  Keeping this layer
deterministic makes result routing and cancellation independently testable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, MutableMapping, cast
from uuid import uuid4

from nanobot.agent.task_frames import ORCHESTRATION_METADATA_KEY, TASK_FRAMES_METADATA_KEY

HARNESS_METADATA_KEY = "harness_v0"
HARNESS_SCHEMA_VERSION = 1
MAX_PLANS = 8
MAX_NODES_PER_PLAN = 12
MAX_GRAPH_DEPTH = 4
MAX_RECEIPTS = 48
MAX_NAMESPACE_BYTES = 24 * 1024

NodeActor = Literal["parent", "subagent"]
PlanStatus = Literal["ready", "running", "completed", "blocked", "stopped", "superseded"]
ReceiptStatus = Literal["issued", "accepted", "rejected", "cancelled"]


class OrchestrationValidationError(ValueError):
    """Raised when a persisted plan or receipt is malformed or unsafe."""


class ReceiptMismatchError(OrchestrationValidationError):
    """Raised when a result does not belong to the receipt being consumed."""


@dataclass(frozen=True)
class PlanNode:
    id: str
    actor: NodeActor
    goal: str
    deliverable: str
    acceptance: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    resource_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    id: str
    frame_id: str
    frame_revision: int
    status: PlanStatus
    nodes: tuple[PlanNode, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RouteReceipt:
    parent_session_key: str
    frame_id: str
    frame_revision: int
    plan_id: str
    node_id: str
    task_id: str
    status: ReceiptStatus
    issued_at: str
    expires_at: str
    result_ref: str | None = None


def new_plan(
    *,
    frame_id: str,
    frame_revision: int,
    nodes: tuple[PlanNode, ...],
    now: datetime | None = None,
) -> ExecutionPlan:
    timestamp = _timestamp(now)
    plan = ExecutionPlan(
        id=f"plan_{uuid4().hex}",
        frame_id=frame_id,
        frame_revision=frame_revision,
        status="ready",
        nodes=nodes,
        created_at=timestamp,
        updated_at=timestamp,
    )
    validate_plan(plan)
    return plan


def new_receipt(
    *,
    parent_session_key: str,
    plan: ExecutionPlan,
    node_id: str,
    task_id: str,
    expires_at: str,
    now: datetime | None = None,
) -> RouteReceipt:
    if not any(node.id == node_id for node in plan.nodes):
        raise OrchestrationValidationError("receipt node does not belong to plan")
    _require_text(parent_session_key, "parent_session_key", 300)
    _require_text(task_id, "task_id", 200)
    _require_text(expires_at, "expires_at", 80)
    return RouteReceipt(
        parent_session_key=parent_session_key,
        frame_id=plan.frame_id,
        frame_revision=plan.frame_revision,
        plan_id=plan.id,
        node_id=node_id,
        task_id=task_id,
        status="issued",
        issued_at=_timestamp(now),
        expires_at=expires_at,
    )


def validate_plan(plan: ExecutionPlan, *, max_nodes: int = MAX_NODES_PER_PLAN) -> None:
    _require_text(plan.id, "plan.id", 200)
    _require_text(plan.frame_id, "plan.frame_id", 200)
    _require_positive_int(plan.frame_revision, "plan.frame_revision")
    if plan.status not in {"ready", "running", "completed", "blocked", "stopped", "superseded"}:
        raise OrchestrationValidationError("plan.status is invalid")
    if not plan.nodes or len(plan.nodes) > max_nodes:
        raise OrchestrationValidationError("plan nodes must be a non-empty bounded list")
    _require_text(plan.created_at, "plan.created_at", 80)
    _require_text(plan.updated_at, "plan.updated_at", 80)
    ids: set[str] = set()
    node_map: dict[str, PlanNode] = {}
    for node in plan.nodes:
        _validate_node(node)
        if node.id in ids:
            raise OrchestrationValidationError("plan node ids must be unique")
        ids.add(node.id)
        node_map[node.id] = node
    for node in plan.nodes:
        for dependency in node.depends_on:
            if dependency == node.id or dependency not in node_map:
                raise OrchestrationValidationError("plan dependency is invalid")
    _validate_graph_depth(node_map)


class OrchestrationStore:
    """Transactional owner of plans and receipts in one session metadata mapping."""

    def __init__(self, metadata: MutableMapping[str, Any], *, session_key: str) -> None:
        _require_text(session_key, "session_key", 300)
        self._metadata = metadata
        self._session_key = session_key
        self._plans, self._receipts = self._load()

    @property
    def plans(self) -> tuple[ExecutionPlan, ...]:
        return self._plans

    @property
    def receipts(self) -> tuple[RouteReceipt, ...]:
        return self._receipts

    def add_plan(self, plan: ExecutionPlan, *, session_key: str) -> None:
        self._require_session(session_key)
        validate_plan(plan)
        if any(item.id == plan.id for item in self._plans):
            raise OrchestrationValidationError("plan already exists")
        if len(self._plans) >= MAX_PLANS:
            raise OrchestrationValidationError("too many plans retained in session")
        self._replace((*self._plans, plan), self._receipts)

    def transition_plan(
        self,
        plan_id: str,
        to_status: PlanStatus,
        *,
        session_key: str,
        now: datetime | None = None,
    ) -> ExecutionPlan:
        self._require_session(session_key)
        index, plan = self._find_plan(plan_id)
        allowed: dict[PlanStatus, set[PlanStatus]] = {
            "ready": {"running", "stopped", "blocked"},
            "running": {"completed", "blocked", "stopped", "superseded"},
            "blocked": {"stopped", "superseded"},
            "completed": set(),
            "stopped": set(),
            "superseded": set(),
        }
        if to_status not in allowed[plan.status]:
            raise OrchestrationValidationError("plan transition is invalid")
        updated = replace(plan, status=to_status, updated_at=_timestamp(now))
        plans = list(self._plans)
        plans[index] = updated
        receipts = self._receipts
        if to_status in {"blocked", "stopped", "superseded"}:
            receipts = tuple(
                replace(receipt, status="cancelled")
                if receipt.plan_id == plan.id and receipt.status == "issued"
                else receipt
                for receipt in receipts
            )
        self._replace(tuple(plans), receipts)
        return updated

    def issue_receipt(self, receipt: RouteReceipt, *, session_key: str) -> None:
        self._require_session(session_key)
        _validate_receipt(receipt)
        plan = self._plan_for_receipt(receipt)
        if plan.status not in {"ready", "running"}:
            raise OrchestrationValidationError("cannot issue receipt for inactive plan")
        if any(item.task_id == receipt.task_id for item in self._receipts):
            raise OrchestrationValidationError("task receipt already exists")
        if len(self._receipts) >= MAX_RECEIPTS:
            raise OrchestrationValidationError("too many receipts retained in session")
        self._replace(self._plans, (*self._receipts, receipt))

    def consume_receipt(
        self,
        *,
        parent_session_key: str,
        frame_id: str,
        frame_revision: int,
        plan_id: str,
        node_id: str,
        task_id: str,
        result_ref: str,
        now: datetime | None = None,
    ) -> RouteReceipt:
        self._require_session(parent_session_key)
        index, receipt = self._find_receipt(task_id)
        expected = (parent_session_key, frame_id, frame_revision, plan_id, node_id, task_id)
        actual = (
            receipt.parent_session_key,
            receipt.frame_id,
            receipt.frame_revision,
            receipt.plan_id,
            receipt.node_id,
            receipt.task_id,
        )
        if receipt.status != "issued" or actual != expected:
            raise ReceiptMismatchError("result does not match an active route receipt")
        if receipt.expires_at < _timestamp(now):
            raise ReceiptMismatchError("route receipt has expired")
        _require_text(result_ref, "result_ref", 500)
        accepted = replace(receipt, status="accepted", result_ref=result_ref)
        receipts = list(self._receipts)
        receipts[index] = accepted
        self._replace(self._plans, tuple(receipts))
        return accepted

    def reject_receipt(self, task_id: str, *, session_key: str) -> RouteReceipt:
        self._require_session(session_key)
        index, receipt = self._find_receipt(task_id)
        if receipt.status != "issued":
            raise OrchestrationValidationError("receipt is no longer pending")
        rejected = replace(receipt, status="rejected")
        receipts = list(self._receipts)
        receipts[index] = rejected
        self._replace(self._plans, tuple(receipts))
        return rejected

    def _load(self) -> tuple[tuple[ExecutionPlan, ...], tuple[RouteReceipt, ...]]:
        raw_namespace = self._metadata.get(ORCHESTRATION_METADATA_KEY)
        if raw_namespace is None:
            return (), ()
        if not isinstance(raw_namespace, dict):
            raise OrchestrationValidationError("orchestration namespace must be an object")
        raw_harness = cast(dict[str, Any], raw_namespace).get(HARNESS_METADATA_KEY)
        if raw_harness is None:
            return (), ()
        if not isinstance(raw_harness, dict):
            raise OrchestrationValidationError("harness metadata must be an object")
        harness = cast(dict[str, Any], raw_harness)
        if harness.get("schema_version") != HARNESS_SCHEMA_VERSION:
            raise OrchestrationValidationError("unsupported harness schema_version")
        raw_plans = harness.get("plans")
        raw_receipts = harness.get("receipts")
        if not isinstance(raw_plans, list) or not isinstance(raw_receipts, list):
            raise OrchestrationValidationError("harness plans and receipts must be lists")
        plans = tuple(_plan_from_data(item) for item in cast(list[object], raw_plans))
        receipts = tuple(_receipt_from_data(item) for item in cast(list[object], raw_receipts))
        if len(plans) > MAX_PLANS or len(receipts) > MAX_RECEIPTS:
            raise OrchestrationValidationError("harness metadata exceeds retained limits")
        for plan in plans:
            validate_plan(plan)
        for receipt in receipts:
            _validate_receipt(receipt)
            if not any(plan.id == receipt.plan_id for plan in plans):
                raise OrchestrationValidationError("receipt plan does not exist")
        return plans, receipts

    def _replace(self, plans: tuple[ExecutionPlan, ...], receipts: tuple[RouteReceipt, ...]) -> None:
        for plan in plans:
            validate_plan(plan)
        for receipt in receipts:
            _validate_receipt(receipt)
        raw = self._metadata.get(ORCHESTRATION_METADATA_KEY)
        namespace: dict[str, Any] = (
            dict(cast(dict[str, Any], raw))
            if isinstance(raw, dict)
            else {"schema_version": 1, TASK_FRAMES_METADATA_KEY: []}
        )
        namespace.setdefault("schema_version", 1)
        namespace.setdefault(TASK_FRAMES_METADATA_KEY, [])
        namespace[HARNESS_METADATA_KEY] = {
            "schema_version": HARNESS_SCHEMA_VERSION,
            "plans": [_plan_to_data(plan) for plan in plans],
            "receipts": [_receipt_to_data(receipt) for receipt in receipts],
        }
        serialized = json.dumps(namespace, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if len(serialized.encode("utf-8")) > MAX_NAMESPACE_BYTES:
            raise OrchestrationValidationError("orchestration namespace exceeds its size limit")
        self._metadata[ORCHESTRATION_METADATA_KEY] = json.loads(serialized)
        self._plans = plans
        self._receipts = receipts

    def _require_session(self, session_key: str) -> None:
        if session_key != self._session_key:
            raise ReceiptMismatchError("orchestration mutation belongs to another session")

    def _find_plan(self, plan_id: str) -> tuple[int, ExecutionPlan]:
        for index, plan in enumerate(self._plans):
            if plan.id == plan_id:
                return index, plan
        raise OrchestrationValidationError("plan does not exist")

    def _find_receipt(self, task_id: str) -> tuple[int, RouteReceipt]:
        for index, receipt in enumerate(self._receipts):
            if receipt.task_id == task_id:
                return index, receipt
        raise ReceiptMismatchError("route receipt does not exist")

    def _plan_for_receipt(self, receipt: RouteReceipt) -> ExecutionPlan:
        _, plan = self._find_plan(receipt.plan_id)
        if (
            plan.frame_id != receipt.frame_id
            or plan.frame_revision != receipt.frame_revision
            or not any(node.id == receipt.node_id for node in plan.nodes)
        ):
            raise OrchestrationValidationError("receipt does not belong to plan")
        return plan


def _validate_node(node: PlanNode) -> None:
    _require_text(node.id, "node.id", 120)
    if node.actor not in {"parent", "subagent"}:
        raise OrchestrationValidationError("node.actor is invalid")
    _require_text(node.goal, "node.goal", 800)
    _require_text(node.deliverable, "node.deliverable", 500)
    _validate_texts(node.acceptance, "node.acceptance", minimum=1)
    _validate_texts(node.depends_on, "node.depends_on")
    _validate_texts(node.resource_claims, "node.resource_claims")


def _validate_receipt(receipt: RouteReceipt) -> None:
    _require_text(receipt.parent_session_key, "receipt.parent_session_key", 300)
    _require_text(receipt.frame_id, "receipt.frame_id", 200)
    _require_positive_int(receipt.frame_revision, "receipt.frame_revision")
    _require_text(receipt.plan_id, "receipt.plan_id", 200)
    _require_text(receipt.node_id, "receipt.node_id", 120)
    _require_text(receipt.task_id, "receipt.task_id", 200)
    if receipt.status not in {"issued", "accepted", "rejected", "cancelled"}:
        raise OrchestrationValidationError("receipt.status is invalid")
    _require_text(receipt.issued_at, "receipt.issued_at", 80)
    _require_text(receipt.expires_at, "receipt.expires_at", 80)
    if receipt.result_ref is not None:
        _require_text(receipt.result_ref, "receipt.result_ref", 500)


def _validate_graph_depth(nodes: Mapping[str, PlanNode]) -> None:
    visiting: set[str] = set()
    visited: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id in visiting:
            raise OrchestrationValidationError("plan graph contains a cycle")
        if node_id in visited:
            return visited[node_id]
        visiting.add(node_id)
        node = nodes[node_id]
        value = 1 + max((depth(dep) for dep in node.depends_on), default=0)
        visiting.remove(node_id)
        visited[node_id] = value
        return value

    if any(depth(node_id) > MAX_GRAPH_DEPTH for node_id in nodes):
        raise OrchestrationValidationError("plan graph exceeds maximum depth")


def _plan_to_data(plan: ExecutionPlan) -> dict[str, Any]:
    data = asdict(plan)
    data["nodes"] = [asdict(node) for node in plan.nodes]
    return data


def _receipt_to_data(receipt: RouteReceipt) -> dict[str, Any]:
    return asdict(receipt)


def _plan_from_data(value: object) -> ExecutionPlan:
    if not isinstance(value, dict):
        raise OrchestrationValidationError("plan must be an object")
    raw = cast(dict[str, Any], value)
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        raise OrchestrationValidationError("plan nodes must be a list")
    node_values = cast(list[object], nodes)
    return ExecutionPlan(
        id=_text(raw, "id", 200),
        frame_id=_text(raw, "frame_id", 200),
        frame_revision=_positive(raw, "frame_revision"),
        status=cast(PlanStatus, _text(raw, "status", 40)),
        nodes=tuple(_node_from_data(item) for item in node_values),
        created_at=_text(raw, "created_at", 80),
        updated_at=_text(raw, "updated_at", 80),
    )


def _node_from_data(value: object) -> PlanNode:
    if not isinstance(value, dict):
        raise OrchestrationValidationError("plan node must be an object")
    raw = cast(dict[str, Any], value)
    return PlanNode(
        id=_text(raw, "id", 120),
        actor=cast(NodeActor, _text(raw, "actor", 20)),
        goal=_text(raw, "goal", 800),
        deliverable=_text(raw, "deliverable", 500),
        acceptance=_texts(raw.get("acceptance"), "acceptance", minimum=1),
        depends_on=_texts(raw.get("depends_on"), "depends_on"),
        resource_claims=_texts(raw.get("resource_claims"), "resource_claims"),
    )


def _receipt_from_data(value: object) -> RouteReceipt:
    if not isinstance(value, dict):
        raise OrchestrationValidationError("receipt must be an object")
    raw = cast(dict[str, Any], value)
    result_ref = raw.get("result_ref")
    if result_ref is not None and not isinstance(result_ref, str):
        raise OrchestrationValidationError("receipt result_ref must be text or null")
    return RouteReceipt(
        parent_session_key=_text(raw, "parent_session_key", 300),
        frame_id=_text(raw, "frame_id", 200),
        frame_revision=_positive(raw, "frame_revision"),
        plan_id=_text(raw, "plan_id", 200),
        node_id=_text(raw, "node_id", 120),
        task_id=_text(raw, "task_id", 200),
        status=cast(ReceiptStatus, _text(raw, "status", 20)),
        issued_at=_text(raw, "issued_at", 80),
        expires_at=_text(raw, "expires_at", 80),
        result_ref=result_ref,
    )


def _text(data: Mapping[str, Any], name: str, limit: int) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise OrchestrationValidationError(f"{name} must be text")
    _require_text(value, name, limit)
    return value


def _positive(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    _require_positive_int(value, name)
    return cast(int, value)


def _texts(value: object, name: str, *, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise OrchestrationValidationError(f"{name} must be a list")
    values = tuple(cast(list[object], value))
    _validate_texts(values, name, minimum=minimum)
    return cast(tuple[str, ...], values)


def _validate_texts(values: tuple[str, ...] | tuple[object, ...], name: str, *, minimum: int = 0) -> None:
    if len(values) < minimum or len(values) > 8:
        raise OrchestrationValidationError(f"{name} must be a bounded text list")
    for value in values:
        _require_text(value, name, 500)


def _require_text(value: object, name: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise OrchestrationValidationError(f"{name} must be non-empty text within its limit")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OrchestrationValidationError(f"{name} must be an integer >= 1")


def _timestamp(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
