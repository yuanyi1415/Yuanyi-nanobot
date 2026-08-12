"""macOS native folder picker for the WebUI workspace picker.

Serves ``GET /api/workspace/pick-folder``. On macOS this launches the system
folder-selection dialog via ``osascript``; the selected folder is returned as
an absolute POSIX path. Dismissing the dialog is not an error.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any


class WorkspaceDirectoryError(Exception):
    """A safe folder-picker error for the WebUI."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


_FOLDER_PICKER_TIMEOUT_S = 600
_FOLDER_PICKER_SCRIPT = 'POSIX path of (choose folder with prompt "选择项目文件夹")'


def pick_folder_payload() -> dict[str, Any]:
    """Open the macOS native folder picker and return the chosen path.

    Returns ``{"path": "<absolute path>"}`` on success or
    ``{"cancelled": True}`` when the user dismisses the dialog (never an
    error). Raises :class:`WorkspaceDirectoryError` when the platform is
    unsupported (501) or the picker itself fails (500). This function blocks
    until the user answers — callers should run it in a worker thread.
    """
    if sys.platform != "darwin":
        raise WorkspaceDirectoryError("folder picker requires macOS", status=501)
    try:
        result = subprocess.run(
            ["osascript", "-e", _FOLDER_PICKER_SCRIPT],
            capture_output=True,
            text=True,
            timeout=_FOLDER_PICKER_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceDirectoryError(f"folder picker failed: {exc}", status=500) from exc
    if result.returncode != 0:
        return {"cancelled": True}
    picked = result.stdout.strip()
    if not picked:
        return {"cancelled": True}
    return {"path": picked}
