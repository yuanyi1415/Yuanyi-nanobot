"""Tests for deterministic local skill recall (FR-3): binding, ambiguity, budgets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.skills import SkillsLoader


def _write_skill(
    base: Path,
    name: str,
    *,
    metadata_json: dict | None = None,
    body: str = "# Skill\n",
) -> Path:
    skill_dir = base / name
    skill_dir.mkdir(parents=True)
    lines = ["---"]
    if metadata_json is not None:
        payload = json.dumps({"nanobot": metadata_json}, separators=(",", ":"))
        lines.append(f"metadata: {payload}")
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


def test_high_confidence_single_candidate_bound(loader: SkillsLoader, tmp_path: Path) -> None:
    _write_skill(
        tmp_path / "ws" / "skills",
        "github",
        metadata_json={"description": "github pull requests and issues"},
    )
    result = loader.recall_skill_candidates("open a github pull request")
    assert result.bound == ("github",)
    assert result.candidates == ("github",)
    assert result.reason == "high_confidence"


def test_no_candidate_returns_none(loader: SkillsLoader, tmp_path: Path) -> None:
    _write_skill(tmp_path / "ws" / "skills", "github", metadata_json={"description": "github stuff"})
    result = loader.recall_skill_candidates("what is the weather today?")
    assert result.bound == ()
    assert result.candidates == ()
    assert result.reason == "none"


def test_ambiguous_multi_candidate_not_bound(loader: SkillsLoader, tmp_path: Path) -> None:
    """Approximate multi-candidate matches are recorded but never bound (V1)."""
    _write_skill(tmp_path / "ws" / "skills", "github", metadata_json={"description": "github prs"})
    _write_skill(tmp_path / "ws" / "skills", "git", metadata_json={"description": "git workflows"})
    result = loader.recall_skill_candidates("git and github both here")
    assert result.bound == ()
    assert set(result.candidates) == {"github", "git"}
    assert result.reason == "ambiguous_multi_candidate"


def test_explicit_excluded_skill_not_recalled(loader: SkillsLoader, tmp_path: Path) -> None:
    """``$skill``-referenced names are excluded from auto recall (FR-4 precedence)."""
    _write_skill(tmp_path / "ws" / "skills", "github", metadata_json={"description": "github prs"})
    _write_skill(tmp_path / "ws" / "skills", "git", metadata_json={"description": "git workflows"})
    result = loader.recall_skill_candidates("use $git github", exclude=["git"])
    assert result.bound == ("github",)
    assert result.candidates == ("github",)
    assert result.reason == "high_confidence"


def test_non_auto_activations_excluded(loader: SkillsLoader, tmp_path: Path) -> None:
    """manual/always/disabled skills never participate in auto recall."""
    _write_skill(tmp_path / "ws" / "skills", "auto-skill", metadata_json={"description": "auto stuff"})
    _write_skill(tmp_path / "ws" / "skills", "manual-skill", metadata_json={"manual": True, "description": "manual stuff"})
    _write_skill(tmp_path / "ws" / "skills", "always-skill", metadata_json={"always": True, "description": "always stuff"})
    _write_skill(tmp_path / "ws" / "skills", "disabled-skill", metadata_json={"disabled": True, "description": "disabled stuff"})
    result = loader.recall_skill_candidates("run auto-skill now")
    assert result.bound == ("auto-skill",)
    assert result.candidates == ("auto-skill",)


def test_unavailable_skill_excluded(
    loader: SkillsLoader, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_skill(
        tmp_path / "ws" / "skills",
        "needs-env",
        metadata_json={"description": "needs env stuff", "requires": {"env": ["NANOBOT_RECALL_TEST_ENV"]}},
    )
    monkeypatch.delenv("NANOBOT_RECALL_TEST_ENV", raising=False)
    result = loader.recall_skill_candidates("needs env stuff")
    assert result.bound == ()
    assert result.candidates == ()
    assert result.reason == "none"


def test_max_count_budget_truncates_bindings(loader: SkillsLoader, tmp_path: Path) -> None:
    """max_count caps the number of bound skills; candidates stay visible."""
    _write_skill(tmp_path / "ws" / "skills", "github", metadata_json={"description": "github prs"})
    _write_skill(tmp_path / "ws" / "skills", "beta", metadata_json={"description": "beta helper"})
    # "github helper": github (name+desc) scores 6, beta (desc only) scores 1 -> high confidence.
    result = loader.recall_skill_candidates("github helper", max_count=1, token_budget=2000)
    assert result.bound == ("github",)
    assert result.candidates == ("github", "beta")
    assert result.reason == "high_confidence"


def test_token_budget_overflow_degrades_to_no_binding(loader: SkillsLoader, tmp_path: Path) -> None:
    """First candidate body over the token budget degrades to no binding."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "huge",
        metadata_json={"description": "huge skill"},
        body="# Huge\n" + "x" * 200_000,
    )
    result = loader.recall_skill_candidates("huge skill", token_budget=10)
    assert result.candidates == ("huge",)
    assert result.bound == ()
    assert result.reason == "budget_limited"


def test_token_budget_truncates_partial_bindings(loader: SkillsLoader, tmp_path: Path) -> None:
    """Later candidates over the remaining token budget are not bound."""
    _write_skill(tmp_path / "ws" / "skills", "small", metadata_json={"description": "small skill"}, body="# Small\n")
    _write_skill(
        tmp_path / "ws" / "skills",
        "beta",
        metadata_json={"description": "beta helper"},
        body="# Beta\n" + "y" * 200_000,
    )
    result = loader.recall_skill_candidates("small helper", max_count=2, token_budget=2000)
    assert result.bound == ("small",)
    assert result.reason == "high_confidence"


def test_empty_text_returns_none(loader: SkillsLoader, tmp_path: Path) -> None:
    _write_skill(tmp_path / "ws" / "skills", "github", metadata_json={"description": "github prs"})
    assert loader.recall_skill_candidates("").reason == "none"
    assert loader.recall_skill_candidates("   ").reason == "none"


def test_name_hit_not_vetoed_by_incidental_description_terms(
    loader: SkillsLoader, tmp_path: Path
) -> None:
    """A name hit wins over an incidental description-only runner-up (gap rule)."""
    _write_skill(tmp_path / "ws" / "skills", "github", metadata_json={"description": "prs issues"})
    _write_skill(
        tmp_path / "ws" / "skills",
        "beta",
        metadata_json={"description": "beta weekly report helper"},
    )
    result = loader.recall_skill_candidates(
        "open github weekly report helper", max_count=1
    )
    # github: name hit only (5); beta: description terms only (3) -> bound.
    assert result.bound == ("github",)
    assert result.candidates == ("github", "beta")
    assert result.reason == "high_confidence"


def test_cjk_term_matching(loader: SkillsLoader, tmp_path: Path) -> None:
    """An exact CJK trigger is a strong automatic-binding signal."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "pdf",
        metadata_json={"description": "PDF 视觉设计 排版", "triggers": ["视觉设计"]},
    )
    result = loader.recall_skill_candidates("帮我做一个 视觉设计 的 PDF")
    assert result.bound == ("pdf",)
    assert result.reason == "high_confidence"


def test_description_only_match_is_observed_but_not_auto_bound(
    loader: SkillsLoader, tmp_path: Path
) -> None:
    """Generic description words must never inject an unrelated workflow."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "image-ocr",
        metadata_json={"description": "处理图片内容与文字" , "triggers": ["截图内容"]},
    )
    result = loader.recall_skill_candidates("里面的内容是按我说的来吗")
    assert result.candidates == ("image-ocr",)
    assert result.bound == ()
    assert result.reason == "weak_match"


def test_trigger_phrase_binds_the_intended_skill(loader: SkillsLoader, tmp_path: Path) -> None:
    _write_skill(
        tmp_path / "ws" / "skills",
        "image-ocr",
        metadata_json={"description": "处理图片内容与文字", "triggers": ["提取图片文字"]},
    )
    result = loader.recall_skill_candidates("请帮我提取图片文字")
    assert result.bound == ("image-ocr",)
    assert result.reason == "high_confidence"


def test_cjk_trigger_allows_inserted_modifiers_without_generic_bigrams(
    loader: SkillsLoader, tmp_path: Path
) -> None:
    _write_skill(
        tmp_path / "ws" / "skills",
        "image-ocr",
        metadata_json={"description": "处理图片内容与文字", "triggers": ["提取图片文字"]},
    )
    result = loader.recall_skill_candidates("帮我提取这张图片里的文字")
    assert result.bound == ("image-ocr",)
    assert result.reason == "high_confidence"


def test_auto_bind_triggers_require_an_action_phrase(loader: SkillsLoader, tmp_path: Path) -> None:
    """A Skill name may remain a candidate without becoming an auto command."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "my",
        metadata_json={
            "description": "inspect runtime state and context window",
            "triggers": ["上下文窗口"],
            "autoBind": {"triggers": ["检查上下文窗口"]},
        },
    )
    discussed = loader.recall_skill_candidates("一个 agent 的上下文窗口有限")
    requested = loader.recall_skill_candidates("请检查当前上下文窗口")

    assert discussed.candidates == ("my",)
    assert discussed.bound == ()
    assert discussed.reason == "weak_match"
    assert requested.bound == ("my",)
    assert requested.reason == "high_confidence"


def test_auto_bind_media_requirement_fails_closed_without_media(
    loader: SkillsLoader, tmp_path: Path
) -> None:
    """OCR-like workflows need both an action phrase and the current attachment."""
    _write_skill(
        tmp_path / "ws" / "skills",
        "image-ocr",
        metadata_json={
            "description": "extract text from images",
            "triggers": ["图片文字", "image-ocr"],
            "autoBind": {
                "triggers": ["提取图片文字"],
                "requires": ["current_media"],
            },
        },
    )

    no_media = loader.recall_skill_candidates("请提取图片文字")
    with_media = loader.recall_skill_candidates("请提取图片文字", has_current_media=True)
    discussed = loader.recall_skill_candidates("讨论 image-ocr 如何自动发现")

    assert no_media.candidates == ("image-ocr",)
    assert no_media.bound == ()
    assert no_media.reason == "missing_required_fact"
    assert with_media.bound == ("image-ocr",)
    assert with_media.reason == "high_confidence"
    assert discussed.candidates == ("image-ocr",)
    assert discussed.bound == ()
    assert discussed.reason == "weak_match"


def test_unknown_auto_bind_requirement_fails_closed(loader: SkillsLoader, tmp_path: Path) -> None:
    _write_skill(
        tmp_path / "ws" / "skills",
        "guarded",
        metadata_json={
            "description": "guarded workflow",
            "autoBind": {"triggers": ["运行 guarded"], "requires": ["unknown_fact"]},
        },
    )
    result = loader.recall_skill_candidates("运行 guarded")
    assert result.candidates == ("guarded",)
    assert result.bound == ()
    assert result.reason == "missing_required_fact"
