"""Controlled execution of a validated V0 subagent plan."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from nanobot.agent.orchestration import (
    ExecutionPlan,
    OrchestrationStore,
    PlanNode,
    RouteReceipt,
    new_receipt,
)
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.utils.llm_runtime import LLMRuntime

PersistState = Callable[[], None]


@dataclass(frozen=True)
class WorkerResult:
    node_id: str
    receipt: RouteReceipt
    content: str


@dataclass(frozen=True)
class CoordinatorResult:
    status: str
    workers: tuple[WorkerResult, ...]
    error: str | None = None


class OrchestrationCoordinator:
    """Runs only the current plan; it does not consume the message bus."""

    def __init__(self, *, max_parallel_workers: int, result_context_chars: int) -> None:
        self.max_parallel_workers = max(1, max_parallel_workers)
        self.result_context_chars = max(1_000, result_context_chars)

    async def execute(
        self,
        *,
        plan: ExecutionPlan,
        store: OrchestrationStore,
        subagents: SubagentManager,
        runtime: LLMRuntime,
        session_key: str,
        origin_channel: str,
        origin_chat_id: str,
        origin_message_id: str | None,
        workspace: Path,
        user_task: str,
        persist_state: PersistState,
    ) -> CoordinatorResult:
        store.transition_plan(plan.id, "running", session_key=session_key)
        persist_state()
        completed: set[str] = set()
        remaining = {node.id: node for node in plan.nodes}
        workers: list[WorkerResult] = []
        try:
            while remaining:
                ready = [
                    node for node in remaining.values()
                    if all(dependency in completed for dependency in node.depends_on)
                ]
                if not ready:
                    store.transition_plan(plan.id, "blocked", session_key=session_key)
                    persist_state()
                    return CoordinatorResult("blocked", tuple(workers), "plan dependencies cannot advance")
                batch = _select_parallel_batch(ready, self.max_parallel_workers)
                receipts = [
                    self._issue_receipt(store, plan, node.id, session_key, persist_state)
                    for node in batch
                ]
                results = await asyncio.gather(*(
                    subagents.run_inline(
                        task=_worker_task(user_task, node.goal, node.deliverable, node.acceptance),
                        label=node.id,
                        origin_channel=origin_channel,
                        origin_chat_id=origin_chat_id,
                        session_key=session_key,
                        origin_message_id=origin_message_id,
                        runtime=runtime,
                        task_id=receipt.task_id,
                        execution_owner_key=receipt.task_id,
                    )
                    for node, receipt in zip(batch, receipts, strict=True)
                ))
                for node, receipt, content in zip(batch, receipts, results, strict=True):
                    if is_tool_error_result(content):
                        store.reject_receipt(receipt.task_id, session_key=session_key)
                        store.transition_plan(plan.id, "stopped", session_key=session_key)
                        persist_state()
                        return CoordinatorResult("blocked", tuple(workers), str(content))
                    result_text = str(content)
                    result_ref = _persist_worker_result(
                        workspace=workspace,
                        session_key=session_key,
                        plan_id=plan.id,
                        task_id=receipt.task_id,
                        content=result_text,
                    )
                    accepted = store.consume_receipt(
                        parent_session_key=session_key,
                        frame_id=plan.frame_id,
                        frame_revision=plan.frame_revision,
                        plan_id=plan.id,
                        node_id=node.id,
                        task_id=receipt.task_id,
                        result_ref=result_ref,
                    )
                    persist_state()
                    workers.append(WorkerResult(node.id, accepted, result_text))
                    completed.add(node.id)
                    del remaining[node.id]
            return CoordinatorResult("completed", tuple(workers))
        except asyncio.CancelledError:
            store.transition_plan(plan.id, "stopped", session_key=session_key)
            persist_state()
            raise
        except Exception as exc:
            store.transition_plan(plan.id, "blocked", session_key=session_key)
            persist_state()
            return CoordinatorResult("blocked", tuple(workers), str(exc))

    def _issue_receipt(
        self,
        store: OrchestrationStore,
        plan: ExecutionPlan,
        node_id: str,
        session_key: str,
        persist_state: PersistState,
    ) -> RouteReceipt:
        receipt = new_receipt(
            parent_session_key=session_key,
            plan=plan,
            node_id=node_id,
            task_id=f"orch_{uuid4().hex}",
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )
        store.issue_receipt(receipt, session_key=session_key)
        persist_state()
        return receipt


def _select_parallel_batch(nodes: list[PlanNode], limit: int) -> list[PlanNode]:
    selected: list[PlanNode] = []
    claims: set[str] = set()
    for node in nodes:
        node_claims = set(node.resource_claims)
        if claims.intersection(node_claims):
            continue
        selected.append(node)
        claims.update(node_claims)
        if len(selected) == limit:
            break
    return selected or nodes[:1]


def _worker_task(user_task: str, goal: str, deliverable: str, acceptance: tuple[str, ...]) -> str:
    checks = "\n".join(f"- {item}" for item in acceptance)
    return (
        "Complete only this delegated work item. Do not create or delegate further subagents. "
        "Use available tools only when needed and report evidence, limits, and the requested deliverable.\n\n"
        f"Parent request:\n{user_task}\n\nWork item:\n{goal}\n"
        f"Expected deliverable: {deliverable}\nAcceptance checks:\n{checks}"
    )


def _persist_worker_result(
    *,
    workspace: Path,
    session_key: str,
    plan_id: str,
    task_id: str,
    content: str,
) -> str:
    """Persist content privately; session state retains only a stable reference."""
    bucket = hashlib.sha256(session_key.encode("utf-8")).hexdigest()[:24]
    root = (workspace / "memory" / "orchestration-results" / bucket / plan_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{task_id}.txt"
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{task_id}.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return f"orchestration-result://{bucket}/{plan_id}/{task_id}"
