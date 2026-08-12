"""Tests for the macOS native folder picker (workspace_api)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from nanobot.webui.workspace_api import (
    WorkspaceDirectoryError,
    pick_folder_payload,
)
from nanobot.webui.ws_http import GatewayHTTPHandler


def _handler(*, authorized: bool = True) -> GatewayHTTPHandler:
    handler = object.__new__(GatewayHTTPHandler)
    handler.tokens = SimpleNamespace(check_api_token=lambda _request: authorized)
    return handler


def _request(path: str = "/api/workspace/pick-folder") -> SimpleNamespace:
    return SimpleNamespace(path=path, headers=SimpleNamespace())


def _run_result(*, returncode: int = 0, stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def _stub_run(monkeypatch: pytest.MonkeyPatch, result) -> None:
    monkeypatch.setattr(
        "nanobot.webui.workspace_api.subprocess.run",
        lambda *_args, **_kwargs: result,
    )


def test_pick_folder_returns_the_chosen_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_run(monkeypatch, _run_result(stdout="/Users/yuanyi/Desktop/AI\n"))

    assert pick_folder_payload() == {"path": "/Users/yuanyi/Desktop/AI"}


def test_pick_folder_cancel_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_run(monkeypatch, _run_result(returncode=1))

    assert pick_folder_payload() == {"cancelled": True}


def test_pick_folder_empty_stdout_is_treated_as_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_run(monkeypatch, _run_result())

    assert pick_folder_payload() == {"cancelled": True}


def test_pick_folder_requires_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.webui.workspace_api.sys",
        SimpleNamespace(platform="linux"),
    )

    with pytest.raises(WorkspaceDirectoryError) as exc_info:
        pick_folder_payload()

    assert exc_info.value.status == 501


def test_pick_folder_timeout_raises_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=600)

    monkeypatch.setattr("nanobot.webui.workspace_api.subprocess.run", run)

    with pytest.raises(WorkspaceDirectoryError) as exc_info:
        pick_folder_payload()

    assert exc_info.value.status == 500


def test_pick_folder_os_error_raises_500(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*_args, **_kwargs):
        raise FileNotFoundError("osascript")

    monkeypatch.setattr("nanobot.webui.workspace_api.subprocess.run", run)

    with pytest.raises(WorkspaceDirectoryError) as exc_info:
        pick_folder_payload()

    assert exc_info.value.status == 500
    assert "folder picker failed" in exc_info.value.message


async def test_pick_folder_route_requires_api_token() -> None:
    response = await _handler(authorized=False)._dispatch_misc_routes(
        None, _request(), "/api/workspace/pick-folder"
    )

    assert response is not None
    assert response.status_code == 401


async def test_pick_folder_route_rejects_remote_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._is_local_browser_request",
        lambda _connection, _headers: False,
    )

    response = await _handler()._dispatch_misc_routes(
        None, _request(), "/api/workspace/pick-folder"
    )

    assert response is not None
    assert response.status_code == 403


async def test_pick_folder_route_returns_chosen_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._is_local_browser_request",
        lambda _connection, _headers: True,
    )
    monkeypatch.setattr(
        "nanobot.webui.ws_http.pick_folder_payload",
        lambda: {"path": "/Users/yuanyi/Desktop/AI"},
    )

    response = await _handler()._dispatch_misc_routes(
        None, _request(), "/api/workspace/pick-folder"
    )

    assert response is not None
    assert response.status_code == 200
    assert json.loads(response.body) == {"path": "/Users/yuanyi/Desktop/AI"}


async def test_pick_folder_route_maps_errors_to_http_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nanobot.webui.ws_http._is_local_browser_request",
        lambda _connection, _headers: True,
    )

    def fail() -> dict:
        raise WorkspaceDirectoryError("folder picker requires macOS", status=501)

    monkeypatch.setattr("nanobot.webui.ws_http.pick_folder_payload", fail)

    response = await _handler()._dispatch_misc_routes(
        None, _request(), "/api/workspace/pick-folder"
    )

    assert response is not None
    assert response.status_code == 501
    assert response.body.decode() == "folder picker requires macOS"
