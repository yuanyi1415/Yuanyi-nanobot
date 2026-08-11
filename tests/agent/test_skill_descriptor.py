"""Tests for SkillDescriptor generation (FR-2): activation resolution, fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.skills import SkillDescriptor, SkillsLoader


def _write_skill(
    base: Path,
    name: str,
    *,
    metadata_json: dict | None = None,
    body: str = "# Skill\n",
    top_level: dict[str, object] | None = None,
) -> Path:
    """Create ``base / name / SKILL.md`` with optional metadata + top-level fields."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    if metadata_json is not None:
        payload = json.dumps({"nanobot": metadata_json}, separators=(",", ":"))
        lines.append(f"metadata: {payload}")
    for key, value in (top_level or {}).items():
        if isinstance(value, (dict, list)):
            encoded = json.dumps(value, separators=(",", ":"))
        elif isinstance(value, bool):
            encoded = "true" if value else "false"
        else:
            encoded = str(value)
        lines.append(f"{key}: {encoded}")
    lines.extend(["---", "", body])
    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def loader(tmp_path: Path) -> SkillsLoader:
    workspace = tmp_path / "ws"
    (workspace / "skills").mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    return SkillsLoader(workspace, builtin_skills_dir=builtin)


def _descriptor(loader: SkillsLoader, name: str) -> SkillDescriptor:
    by_name = {d.name: d for d in loader.list_skill_descriptors()}
    return by_name[name]


def test_descriptor_defaults_activation_auto(loader: SkillsLoader, tmp_path: Path) -> None:
    """Legacy skills without new fields default to activation=auto."""
    _write_skill(tmp_path / "ws" / "skills", "legacy", metadata_json={"description": "old skill"})
    desc = _descriptor(loader, "legacy")
    assert desc.activation == "auto"
    assert desc.source == "workspace"
    assert desc.availability is True
    assert desc.missing_requirements == ""
    assert desc.tags == ()
    assert desc.triggers == ()
    assert len(desc.content_fingerprint) == 16


def test_descriptor_activation_explicit_string(loader: SkillsLoader, tmp_path: Path) -> None:
    """activation string in nanobot metadata is honored."""
    _write_skill(tmp_path / "ws" / "skills", "manual-x", metadata_json={"activation": "manual"})
    _write_skill(tmp_path / "ws" / "skills", "always-x", metadata_json={"activation": "always"})
    _write_skill(tmp_path / "ws" / "skills", "disabled-x", metadata_json={"activation": "disabled"})
    _write_skill(tmp_path / "ws" / "skills", "auto-x", metadata_json={"activation": "auto"})
    assert _descriptor(loader, "manual-x").activation == "manual"
    assert _descriptor(loader, "always-x").activation == "always"
    assert _descriptor(loader, "disabled-x").activation == "disabled"
    assert _descriptor(loader, "auto-x").activation == "auto"


def test_descriptor_activation_top_level(loader: SkillsLoader, tmp_path: Path) -> None:
    """Top-level frontmatter activation is honored when metadata is absent."""
    _write_skill(tmp_path / "ws" / "skills", "top-manual", top_level={"activation": "manual"})
    assert _descriptor(loader, "top-manual").activation == "manual"


def test_descriptor_activation_legacy_booleans_preserved(loader: SkillsLoader, tmp_path: Path) -> None:
    """always/manual/disabled booleans keep their legacy semantics."""
    _write_skill(tmp_path / "ws" / "skills", "legacy-always", metadata_json={"always": True})
    _write_skill(tmp_path / "ws" / "skills", "legacy-manual", metadata_json={"manual": True})
    _write_skill(tmp_path / "ws" / "skills", "legacy-disabled", metadata_json={"disabled": True})
    _write_skill(tmp_path / "ws" / "skills", "top-always", top_level={"always": True})
    assert _descriptor(loader, "legacy-always").activation == "always"
    assert _descriptor(loader, "legacy-manual").activation == "manual"
    assert _descriptor(loader, "legacy-disabled").activation == "disabled"
    assert _descriptor(loader, "top-always").activation == "always"


def test_descriptor_activation_metadata_beats_top_level(
    loader: SkillsLoader, tmp_path: Path
) -> None:
    """Explicit activation in nanobot metadata wins over top-level fields."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "conflict",
        metadata_json={"activation": "auto"},
        top_level={"activation": "disabled"},
    )
    assert _descriptor(loader, "conflict").activation == "auto"


def test_descriptor_activation_invalid_value_falls_back(loader: SkillsLoader, tmp_path: Path) -> None:
    """Unknown activation strings fall back to auto."""
    _write_skill(tmp_path / "ws" / "skills", "weird", metadata_json={"activation": "sometimes"})
    assert _descriptor(loader, "weird").activation == "auto"


def test_descriptor_tags_and_triggers(loader: SkillsLoader, tmp_path: Path) -> None:
    """tags/triggers are parsed from list or comma/JSON-string forms."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "tagged",
        metadata_json={"description": "x", "tags": ["repo", "pr"], "triggers": ["merge"]},
    )
    _write_skill(
        tmp_path / "ws" / "skills",
        "str-tagged",
        top_level={"tags": "review, lint", "triggers": "['fix']"},
    )
    desc = _descriptor(loader, "tagged")
    assert desc.tags == ("repo", "pr")
    assert desc.triggers == ("merge",)
    str_desc = _descriptor(loader, "str-tagged")
    assert str_desc.tags == ("review, lint",)
    assert str_desc.triggers == ("fix",)


def test_descriptor_unavailable_records_missing_requirements(
    loader: SkillsLoader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unmet requirements flip availability and populate missing_requirements."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "needs-bin",
        metadata_json={"requires": {"bins": ["nanobot_test_fake_binary"]}},
    )
    monkeypatch.setattr("nanobot.agent.skills.shutil.which", lambda _cmd: None)
    desc = _descriptor(loader, "needs-bin")
    assert desc.availability is False
    assert "nanobot_test_fake_binary" in desc.missing_requirements


def test_descriptor_skips_disabled_skills_config(loader: SkillsLoader, tmp_path: Path) -> None:
    """Skills listed in disabled_skills are excluded from descriptors."""
    _write_skill(tmp_path / "ws" / "skills", "alpha")
    _write_skill(tmp_path / "ws" / "skills", "beta")
    loader.disabled_skills = {"alpha"}
    names = {d.name for d in loader.list_skill_descriptors()}
    assert names == {"beta"}


def test_descriptor_description_falls_back_to_name(loader: SkillsLoader, tmp_path: Path) -> None:
    """Missing description falls back to the skill name."""
    _write_skill(tmp_path / "ws" / "skills", "no-desc")
    assert _descriptor(loader, "no-desc").description == "no-desc"


def test_descriptor_fingerprint_changes_with_body(loader: SkillsLoader, tmp_path: Path) -> None:
    """content_fingerprint tracks SKILL.md body changes."""
    path = _write_skill(tmp_path / "ws" / "skills", "fing", body="# v1")
    before = _descriptor(loader, "fing").content_fingerprint
    path.write_text("# v2 changed", encoding="utf-8")
    after = _descriptor(loader, "fing").content_fingerprint
    assert before != after


def test_descriptor_reuses_file_cache_until_skill_changes(
    loader: SkillsLoader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged skills are parsed once; a changed file invalidates its entry."""
    path = _write_skill(tmp_path / "ws" / "skills", "cached", body="# v1")
    original_read_text = Path.read_text
    reads = 0

    def _count_reads(self: Path, *args: object, **kwargs: object) -> str:
        nonlocal reads
        if self == path:
            reads += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _count_reads)
    _descriptor(loader, "cached")
    _descriptor(loader, "cached")
    assert reads == 1

    path.write_text("# v2 changed", encoding="utf-8")
    _descriptor(loader, "cached")
    assert reads == 2
