"""Capability projection baselines for Runtime Registry vs model-visible views."""

from pathlib import Path
from typing import Any

from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry


class _ProjectionTool:
    def __init__(self, name: str):
        self.name = name

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.name,
                "parameters": {"type": "object", "properties": {}},
            },
        }


def _write_skill(path: Path, body: str) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\ndescription: {path.name} category\n---\n\n{body}",
        encoding="utf-8",
    )


def test_unprojected_nested_skill_does_not_change_category_navigation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    category = workspace / "skills" / "documents"
    category.mkdir(parents=True)
    (category / "SKILL.md").write_text(
        "---\ndescription: Document navigation\n---\n\n# Documents\n",
        encoding="utf-8",
    )
    loader = SkillsLoader(workspace, builtin_skills_dir=tmp_path / "builtin")
    before = loader.build_skill_navigation()

    _write_skill(category / "summarize", "# Summarize\n")

    after = loader.build_skill_navigation()

    assert loader.list_skills(filter_unavailable=False)[0]["name"] == "summarize"
    assert after == before


def test_tool_surface_projection_is_independent_from_skill_registry(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(_ProjectionTool("read_file"))
    before = registry.project_definitions().fingerprint

    _write_skill(tmp_path / "skills" / "new-skill", "# New skill\n")

    assert registry.project_definitions().fingerprint == before
