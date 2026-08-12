from pathlib import Path

import pytest

from nanobot.security.workspace_access import default_workspace_scope
from nanobot.webui.file_preview import (
    WebUIFilePreviewError,
    file_preview_availability_payload,
    file_preview_payload,
)


def test_restricted_preview_allows_media_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    uploaded = media / "upload.txt"
    uploaded.write_text("uploaded", encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.file_preview.get_media_dir", lambda: media)

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)

    payload = file_preview_payload(str(uploaded), scope=scope)

    assert payload["content"] == "uploaded"
    assert Path(payload["path"]) == uploaded.resolve()


def test_restricted_preview_rejects_other_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = tmp_path / "media"
    media.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr("nanobot.webui.file_preview.get_media_dir", lambda: media)

    scope = default_workspace_scope(workspace, restrict_to_workspace=True)

    with pytest.raises(WebUIFilePreviewError, match="outside the current workspace") as exc_info:
        file_preview_payload(str(outside), scope=scope)

    assert exc_info.value.status == 403


def _prefixed_project(tmp_path: Path) -> tuple[Path, Path]:
    """Create a project directory whose name also appears in relative refs."""
    project = tmp_path / "qizicheng-skill管理删除优化"
    docs = project / "01_docs" / "03_方案"
    docs.mkdir(parents=True)
    doc = docs / "Skill删除优化-替换文件方案-v1.0.md"
    doc.write_text("# 方案\n\n正文内容", encoding="utf-8")
    return project, doc


def test_prefixed_project_name_reference_is_available(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = f"{project.name}/01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"

    assert file_preview_availability_payload(raw, scope=scope) == {"available": True}


def test_prefixed_project_name_reference_resolves_payload(tmp_path: Path) -> None:
    project, doc = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = f"{project.name}/01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"
    payload = file_preview_payload(raw, scope=scope)

    assert Path(payload["path"]) == doc.resolve()
    assert payload["display_path"] == "01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"
    assert payload["content"] == "# 方案\n\n正文内容"


def test_relative_reference_without_prefix_resolves_directly(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    assert file_preview_availability_payload(
        "01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md",
        scope=scope,
    ) == {"available": True}


def test_absolute_reference_resolves_directly(tmp_path: Path) -> None:
    project, doc = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    assert file_preview_availability_payload(str(doc), scope=scope) == {"available": True}


def test_missing_file_still_404(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(
            "01_docs/03_方案/不存在的文件.md",
            scope=scope,
        )

    assert exc_info.value.status == 404


def test_prefixed_missing_file_still_404_after_retry(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = f"{project.name}/01_docs/03_方案/不存在的文件.md"
    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(raw, scope=scope)

    assert exc_info.value.status == 404


def test_unrelated_prefix_still_404(tmp_path: Path) -> None:
    project, _ = _prefixed_project(tmp_path)
    scope = default_workspace_scope(project, restrict_to_workspace=True)

    raw = "other-project/01_docs/03_方案/Skill删除优化-替换文件方案-v1.0.md"
    with pytest.raises(WebUIFilePreviewError, match="file not found") as exc_info:
        file_preview_availability_payload(raw, scope=scope)

    assert exc_info.value.status == 404
