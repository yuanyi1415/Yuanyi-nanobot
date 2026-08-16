"""Coordinator execution preserves bounded concurrency and receipt ownership."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from nanobot.agent.orchestration import OrchestrationStore, PlanNode, new_plan
from nanobot.agent.orchestration_coordinator import OrchestrationCoordinator
from nanobot.agent.tools.base import ToolResult
from nanobot.utils.llm_runtime import LLMRuntime


class _Subagents:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run_inline(self, **kwargs):
        self.calls.append(kwargs)
        return f"result:{kwargs['label']}"


class _GatedSubagents(_Subagents):
    def __init__(self) -> None:
        super().__init__()
        self.started: set[str] = set()
        self.first_started = asyncio.Event()
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()
        self.max_active = 0

    async def run_inline(self, **kwargs):
        label = kwargs["label"]
        self.calls.append(kwargs)
        self.started.add(label)
        self.first_started.set()
        self.max_active = max(self.max_active, len(self.started))
        if len(self.started) == 2:
            self.all_started.set()
        await self.release.wait()
        self.started.remove(label)
        return f"result:{label}"


def _runtime() -> LLMRuntime:
    provider = MagicMock()
    return LLMRuntime.capture(provider, "test", context_window_tokens=8_000)


@pytest.mark.asyncio
async def test_coordinator_persists_receipts_and_respects_dependencies(tmp_path) -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key="webui:one")
    plan = new_plan(
        frame_id="tf_1",
        frame_revision=2,
        nodes=(
            PlanNode("facts", "subagent", "事实", "资料", ("来源",)),
            PlanNode("risks", "subagent", "风险", "结论", ("风险",), ("facts",)),
        ),
    )
    store.add_plan(plan, session_key="webui:one")
    subagents = _Subagents()
    saves = 0

    def persist() -> None:
        nonlocal saves
        saves += 1

    outcome = await OrchestrationCoordinator(
        max_parallel_workers=2,
        result_context_chars=4_000,
    ).execute(
        plan=plan,
        store=store,
        subagents=subagents,  # type: ignore[arg-type]
        runtime=_runtime(),
        session_key="webui:one",
        origin_channel="webui",
        origin_chat_id="one",
        origin_message_id=None,
        workspace=tmp_path,
        user_task="调研并分析",
        persist_state=persist,
    )

    assert outcome.status == "completed"
    assert [call["label"] for call in subagents.calls] == ["facts", "risks"]
    assert [receipt.status for receipt in store.receipts] == ["accepted", "accepted"]
    assert all(receipt.result_ref and receipt.result_ref.startswith("orchestration-result://") for receipt in store.receipts)
    assert saves >= 5


@pytest.mark.asyncio
async def test_conflicting_resource_claims_are_not_batched(tmp_path) -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key="webui:one")
    plan = new_plan(
        frame_id="tf_1",
        frame_revision=2,
        nodes=(
            PlanNode("write_a", "subagent", "A", "A", ("A",), resource_claims=("file:x",)),
            PlanNode("write_b", "subagent", "B", "B", ("B",), resource_claims=("file:x",)),
        ),
    )
    store.add_plan(plan, session_key="webui:one")
    subagents = _Subagents()

    outcome = await OrchestrationCoordinator(
        max_parallel_workers=2,
        result_context_chars=4_000,
    ).execute(
        plan=plan,
        store=store,
        subagents=subagents,  # type: ignore[arg-type]
        runtime=_runtime(),
        session_key="webui:one",
        origin_channel="webui",
        origin_chat_id="one",
        origin_message_id=None,
        workspace=tmp_path,
        user_task="写入同一文件",
        persist_state=lambda: None,
    )

    assert outcome.status == "completed"
    assert [call["label"] for call in subagents.calls] == ["write_a", "write_b"]


@pytest.mark.asyncio
async def test_empty_resource_claims_enter_running_state_together(tmp_path) -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key="webui:one")
    plan = new_plan(
        frame_id="tf_1",
        frame_revision=2,
        nodes=(
            PlanNode("facts", "subagent", "事实", "资料", ("来源",)),
            PlanNode("risks", "subagent", "风险", "结论", ("风险",)),
        ),
    )
    store.add_plan(plan, session_key="webui:one")
    subagents = _GatedSubagents()
    execution = asyncio.create_task(OrchestrationCoordinator(
        max_parallel_workers=2,
        result_context_chars=4_000,
    ).execute(
        plan=plan,
        store=store,
        subagents=subagents,  # type: ignore[arg-type]
        runtime=_runtime(),
        session_key="webui:one",
        origin_channel="webui",
        origin_chat_id="one",
        origin_message_id=None,
        workspace=tmp_path,
        user_task="分别调研事实与风险",
        persist_state=lambda: None,
    ))

    try:
        await asyncio.wait_for(subagents.all_started.wait(), timeout=1)
        assert subagents.started == {"facts", "risks"}
        assert subagents.max_active == 2
    finally:
        subagents.release.set()
    outcome = await execution

    assert outcome.status == "completed"


@pytest.mark.asyncio
async def test_matching_exclusive_resource_claims_never_overlap(tmp_path) -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key="webui:one")
    plan = new_plan(
        frame_id="tf_1",
        frame_revision=2,
        nodes=(
            PlanNode(
                "write_a", "subagent", "写入 A", "A", ("保存",),
                resource_claims=("exclusive:workspace:file:report.md",),
            ),
            PlanNode(
                "write_b", "subagent", "写入 B", "B", ("保存",),
                resource_claims=("exclusive:workspace:file:report.md",),
            ),
        ),
    )
    store.add_plan(plan, session_key="webui:one")
    subagents = _GatedSubagents()
    execution = asyncio.create_task(OrchestrationCoordinator(
        max_parallel_workers=2,
        result_context_chars=4_000,
    ).execute(
        plan=plan,
        store=store,
        subagents=subagents,  # type: ignore[arg-type]
        runtime=_runtime(),
        session_key="webui:one",
        origin_channel="webui",
        origin_chat_id="one",
        origin_message_id=None,
        workspace=tmp_path,
        user_task="写入同一报告",
        persist_state=lambda: None,
    ))

    try:
        await asyncio.wait_for(subagents.first_started.wait(), timeout=1)
        assert subagents.started == {"write_a"}
        assert subagents.max_active == 1
    finally:
        subagents.release.set()
    outcome = await execution

    assert outcome.status == "completed"
    assert subagents.max_active == 1


@pytest.mark.asyncio
async def test_worker_error_blocks_plan_without_accepting_its_receipt(tmp_path) -> None:
    metadata: dict[str, object] = {}
    store = OrchestrationStore(metadata, session_key="webui:one")
    plan = new_plan(
        frame_id="tf_1",
        frame_revision=2,
        nodes=(
            PlanNode("facts", "subagent", "事实", "资料", ("来源",)),
            PlanNode("risks", "subagent", "风险", "结论", ("风险",)),
        ),
    )
    store.add_plan(plan, session_key="webui:one")
    subagents = _Subagents()

    async def failed_inline(**kwargs):
        subagents.calls.append(kwargs)
        return ToolResult.error("worker failed")

    subagents.run_inline = failed_inline  # type: ignore[method-assign]
    outcome = await OrchestrationCoordinator(
        max_parallel_workers=2,
        result_context_chars=4_000,
    ).execute(
        plan=plan,
        store=store,
        subagents=subagents,  # type: ignore[arg-type]
        runtime=_runtime(),
        session_key="webui:one",
        origin_channel="webui",
        origin_chat_id="one",
        origin_message_id=None,
        workspace=tmp_path,
        user_task="调研",
        persist_state=lambda: None,
    )

    assert outcome.status == "blocked"
    assert {receipt.status for receipt in store.receipts} == {"rejected", "cancelled"}
