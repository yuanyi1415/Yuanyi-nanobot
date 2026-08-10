"""Tests for SubagentManager."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager, SubagentStatus
from nanobot.agent.tools.filesystem import FileToolsConfig
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.security.workspace_access import build_workspace_scope
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(provider: LLMProvider) -> LLMRuntime:
    provider.generation = GenerationSettings()
    return LLMRuntime.capture(provider, "test", context_window_tokens=128_000)


@pytest.mark.asyncio
async def test_subagent_uses_tool_loader():
    """Verify subagent registers tools via ToolLoader, not hard-coded imports."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=Path("/tmp"),
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )
    tools = sm._build_tools()
    assert tools.has("read_file")
    assert tools.has("write_file")
    assert not tools.has("message")
    assert not tools.has("spawn")


@pytest.mark.asyncio
async def test_subagent_build_tools_isolates_file_read_state(tmp_path):
    """Each spawned subagent needs a fresh file-state cache."""
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )

    first_read = sm._build_tools().get("read_file")
    second_read = sm._build_tools().get("read_file")

    assert first_read is not second_read
    assert (await first_read.execute(path="note.txt")).startswith("1| hello")
    second_result = await second_read.execute(path="note.txt")
    assert second_result.startswith("1| hello")
    assert "File unchanged" not in second_result


def test_subagent_respects_file_tool_toggle(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
        tools_config=ToolsConfig(file=FileToolsConfig(enable=False)),
    )

    tools = sm._build_tools()

    file_tools = {
        "apply_patch",
        "edit_file",
        "find_files",
        "grep",
        "list_dir",
        "read_file",
        "write_file",
    }
    assert file_tools.isdisjoint(tools.tool_names)


@pytest.mark.asyncio
async def test_publish_status_event_emits_runtime_event():
    """Subagent lifecycle publishes runtime events for WebUI subscribers."""
    from nanobot.bus.runtime_events import RuntimeEventBus, SubagentStatusChanged

    bus = MessageBus()
    rt = RuntimeEventBus()
    received: list[SubagentStatusChanged] = []
    rt.subscribe(received.append, SubagentStatusChanged)
    sm = SubagentManager(
        workspace=Path("/tmp"),
        bus=bus,
        max_tool_result_chars=16_000,
        runtime_events=rt,
    )

    sm._publish_status_event(
        {"channel": "websocket", "chat_id": "chat-1", "session_key": "websocket:chat-1"},
        "sa-1",
        "研究竞品",
        "started",
    )
    await asyncio.sleep(0)  # publish_nowait schedules a task
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].subagent_id == "sa-1"
    assert received[0].label == "研究竞品"
    assert received[0].status == "started"
    assert received[0].context.channel == "websocket"
    assert received[0].context.chat_id == "chat-1"


def test_subagent_prompt_explains_grouped_skill_paths(tmp_path):
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    global_skill = agent_workspace / "skills" / "global-custom" / "SKILL.md"
    project_skill = project / "skills" / "project-custom" / "SKILL.md"
    global_skill.parent.mkdir(parents=True)
    project_skill.parent.mkdir(parents=True)
    global_skill.write_text("---\ndescription: global skill\n---\nGlobal", encoding="utf-8")
    project_skill.write_text("---\ndescription: project skill\n---\nProject", encoding="utf-8")
    manager = SubagentManager(
        workspace=agent_workspace,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )

    prompt = manager._build_subagent_prompt(workspace=project)

    assert "one absolute root and relative SKILL.md paths" in prompt
    assert "Join them when using `read_file`" in prompt
    assert f"Current project workspace: {project.resolve()}" in prompt
    assert f"Nanobot's agent workspace: {agent_workspace.resolve()}" in prompt
    assert f"History log: {agent_workspace.resolve() / 'memory' / 'history.jsonl'}" in prompt
    assert "global-custom" in prompt
    assert "project-custom" not in prompt


@pytest.mark.asyncio
async def test_subagent_keeps_project_runtime_scope_with_agent_owned_tools(tmp_path):
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    agent_workspace.mkdir()
    project.mkdir()
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    manager = SubagentManager(
        workspace=agent_workspace,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )
    manager.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    manager._announce_result = AsyncMock()
    status = SubagentStatus(
        task_id="t1",
        label="label",
        task_description="task",
        started_at=0.0,
    )

    await manager._run_subagent(
        "t1",
        "task",
        "label",
        {"channel": "websocket", "chat_id": "direct"},
        status,
        _runtime(provider),
        workspace_scope=build_workspace_scope(project, "restricted"),
    )

    spec = manager.runner.run.call_args.args[0]
    assert spec.workspace == project
    assert spec.tools.get("read_file")._workspace == agent_workspace.resolve()


@pytest.mark.asyncio
async def test_subagent_forwards_fail_on_tool_error_to_runner(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
        fail_on_tool_error=False,
    )
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    status = SubagentStatus(
        task_id="t1",
        label="label",
        task_description="task",
        started_at=0.0,
    )

    await sm._run_subagent(
        "t1",
        "task",
        "label",
        {"channel": "cli", "chat_id": "direct"},
        status,
        _runtime(provider),
    )

    spec = sm.runner.run.call_args.args[0]
    assert spec.fail_on_tool_error is False


@pytest.mark.asyncio
async def test_announce_persists_oversized_result(tmp_path):
    """Oversized subagent results are persisted to disk and replaced with a reference."""
    bus = MessageBus()
    sm = SubagentManager(
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=16_000,
        max_subagent_result_chars=1_000,
    )

    long_result = "x" * 5_000
    await sm._announce_result(
        "t1", "label", "task", long_result,
        {"channel": "cli", "chat_id": "direct", "session_key": "s1"},
        "ok",
    )

    msg = await bus.consume_inbound()
    content = msg.content
    assert "[tool output persisted]" in content
    assert "Full output saved to:" in content
    assert "Original size: 5000 chars" in content
    # full text is on disk, not in the message
    assert "x" * 5_000 not in content
    assert (tmp_path / ".nanobot" / "tool-results").exists()


@pytest.mark.asyncio
async def test_announce_passes_short_result_through(tmp_path):
    """Short results are announced verbatim (no persistence)."""
    bus = MessageBus()
    sm = SubagentManager(
        workspace=tmp_path,
        bus=bus,
        max_tool_result_chars=16_000,
        max_subagent_result_chars=1_000,
    )

    await sm._announce_result(
        "t1", "label", "task", "short ok",
        {"channel": "cli", "chat_id": "direct", "session_key": "s1"},
        "ok",
    )

    msg = await bus.consume_inbound()
    content = msg.content
    assert "short ok" in content
    assert "[tool output persisted]" not in content
