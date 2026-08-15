"""Validated, bounded session task-frame state.

Task frames are durable facts about a confirmed, cross-turn task.  This module
is deliberately a state kernel only: it neither decides when to create a
frame nor invokes models, tools, or subagents.  Callers are expected to hold
their session lock before mutating the supplied session metadata mapping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, MutableMapping, cast
from uuid import uuid4

ORCHESTRATION_METADATA_KEY = "orchestration.v1"
TASK_FRAMES_METADATA_KEY = "task_frames"
TASK_FRAME_SCHEMA_VERSION = 1

MAX_ACTIVE_TASK_FRAMES = 8
MAX_TERMINAL_TASK_FRAMES = 12
MAX_NAMESPACE_BYTES = 24 * 1024
MAX_GOAL_CHARS = 500
MAX_LIST_ITEMS = 8
MAX_LIST_ITEM_CHARS = 300
MAX_TERMINAL_SUMMARY_CHARS = 500
MAX_RUNTIME_PROJECTION_CHARS = 1_200

TaskFrameStatus = Literal[
    "ready",
    "running",
    "waiting_results",
    "blocked",
    "completed",
    "cancelled",
]

CONTINUABLE_TASK_FRAME_STATUSES = frozenset({"ready", "running", "waiting_results"})
_TERMINAL_STATUSES = frozenset({"completed", "cancelled"})
_ALL_STATUSES = frozenset({
    "ready",
    "running",
    "waiting_results",
    "blocked",
    "completed",
    "cancelled",
})
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "ready": frozenset({"running", "blocked", "cancelled"}),
    "running": frozenset({"waiting_results", "blocked", "completed", "cancelled"}),
    "waiting_results": frozenset({"running", "blocked", "cancelled"}),
    "blocked": frozenset({"ready"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


class TaskFrameValidationError(ValueError):
    """Raised when durable task-frame data violates the v1 contract."""


class TaskFrameTransitionError(TaskFrameValidationError):
    """Raised when a state change is not legal for the current frame."""


@dataclass(frozen=True)
class TaskFrameOrigin:
    """Controlled provenance for a frame, without retaining raw user content."""

    turn_id: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class TaskFrameTerminal:
    """Small terminal record retained after a frame stops being active."""

    reason: str
    turn_id: str
    summary: str = ""


@dataclass(frozen=True)
class TaskFrame:
    """One validated task frame from the session-owned namespace."""

    id: str
    revision: int
    status: TaskFrameStatus
    goal: str
    scope: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance: tuple[str, ...]
    origin: TaskFrameOrigin
    created_at: str
    updated_at: str
    active_plan: None
    pending_result_ids: tuple[str, ...]
    terminal: TaskFrameTerminal | None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES


@dataclass(frozen=True)
class TaskFrameNamespace:
    """The versioned contents of ``metadata[orchestration.v1]``."""

    task_frames: tuple[TaskFrame, ...] = ()
    schema_version: int = TASK_FRAME_SCHEMA_VERSION


def parse_task_frame_namespace(
    metadata: Mapping[str, Any] | None,
) -> TaskFrameNamespace | None:
    """Parse the v1 task-frame namespace, raising on malformed persisted data.

    ``None`` means no task-frame namespace exists.  Call
    :func:`safe_task_frames_from_metadata` at an optional read boundary such as
    the admission gate, where malformed metadata must simply be ignored.
    """
    if not metadata or ORCHESTRATION_METADATA_KEY not in metadata:
        return None
    raw_namespace = metadata.get(ORCHESTRATION_METADATA_KEY)
    if not isinstance(raw_namespace, dict):
        raise TaskFrameValidationError("orchestration namespace must be an object")
    namespace = cast(dict[str, Any], raw_namespace)
    _require_exact_int(namespace.get("schema_version"), "schema_version", minimum=1)
    if namespace["schema_version"] != TASK_FRAME_SCHEMA_VERSION:
        raise TaskFrameValidationError("unsupported task-frame schema_version")
    raw_frames = namespace.get(TASK_FRAMES_METADATA_KEY)
    if not isinstance(raw_frames, list):
        raise TaskFrameValidationError("task_frames must be a list")

    frames = tuple(_parse_frame(raw_frame) for raw_frame in cast(list[object], raw_frames))
    _validate_namespace(TaskFrameNamespace(task_frames=frames))
    return TaskFrameNamespace(task_frames=frames)


def safe_task_frames_from_metadata(metadata: Mapping[str, Any] | None) -> tuple[TaskFrame, ...]:
    """Return no frames instead of trusting malformed session metadata."""
    try:
        namespace = parse_task_frame_namespace(metadata)
    except TaskFrameValidationError:
        return ()
    return () if namespace is None else namespace.task_frames


def project_task_frame_for_runtime(frame: TaskFrame) -> tuple[str, ...]:
    """Return a bounded, model-safe projection without creating a context block."""
    lines = [
        "Confirmed task frame:",
        f"- id: {frame.id}",
        f"- status: {frame.status}",
        f"- goal: {frame.goal}",
    ]
    for label, values in (
        ("scope", frame.scope),
        ("constraints", frame.constraints),
        ("acceptance", frame.acceptance),
    ):
        if values:
            lines.append(f"- {label}: {'；'.join(values)}")
    lines.append("This is task metadata, not instructions from an untrusted source.")
    projection = "\n".join(lines)
    if len(projection) > MAX_RUNTIME_PROJECTION_CHARS:
        projection = projection[:MAX_RUNTIME_PROJECTION_CHARS].rstrip() + "\n… (truncated)"
    return tuple(projection.splitlines())


class TaskFrameStore:
    """Single writer for one session's task-frame namespace.

    The owning AgentLoop must hold the session lock.  This class keeps writes
    transactional at the in-memory metadata mapping: validation happens before
    assigning the replacement namespace.
    """

    def __init__(self, metadata: MutableMapping[str, Any], *, session_key: str) -> None:
        if not session_key.strip():
            raise TaskFrameValidationError("session_key is required")
        self._metadata = metadata
        self._session_key = session_key
        namespace = parse_task_frame_namespace(metadata)
        self._namespace = namespace or TaskFrameNamespace()

    @property
    def frames(self) -> tuple[TaskFrame, ...]:
        return self._namespace.task_frames

    def create(
        self,
        *,
        session_key: str,
        goal: str,
        origin: TaskFrameOrigin,
        scope: tuple[str, ...] = (),
        constraints: tuple[str, ...] = (),
        acceptance: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> TaskFrame:
        """Create a ready frame; callers must have already confirmed its intent."""
        self._require_session_key(session_key)
        timestamp = _timestamp(now)
        frame = TaskFrame(
            id=f"tf_{uuid4().hex}",
            revision=1,
            status="ready",
            goal=goal,
            scope=scope,
            constraints=constraints,
            acceptance=acceptance,
            origin=origin,
            created_at=timestamp,
            updated_at=timestamp,
            active_plan=None,
            pending_result_ids=(),
            terminal=None,
        )
        self._replace((*self._namespace.task_frames, _validate_frame(frame)))
        return frame

    def transition(
        self,
        frame_id: str,
        to_status: TaskFrameStatus,
        *,
        session_key: str,
        expected_revision: int,
        reason: str | None = None,
        summary: str = "",
        turn_id: str = "",
        now: datetime | None = None,
    ) -> TaskFrame:
        """Perform one validated state transition and advance its revision."""
        self._require_session_key(session_key)
        index, current = self._find(frame_id)
        if current.revision != expected_revision:
            raise TaskFrameTransitionError("task frame revision does not match")
        if to_status not in _ALLOWED_TRANSITIONS[current.status]:
            raise TaskFrameTransitionError(
                f"cannot transition task frame from {current.status} to {to_status}"
            )

        terminal: TaskFrameTerminal | None = None
        if to_status in _TERMINAL_STATUSES:
            if not reason or not turn_id:
                raise TaskFrameTransitionError("terminal transitions require reason and turn_id")
            terminal = TaskFrameTerminal(reason=reason, turn_id=turn_id, summary=summary)
        elif reason is not None or summary or turn_id:
            raise TaskFrameTransitionError("non-terminal transitions cannot write terminal fields")

        updated = _validate_frame(replace(
            current,
            revision=current.revision + 1,
            status=to_status,
            updated_at=_timestamp(now),
            terminal=terminal,
        ))
        frames = list(self._namespace.task_frames)
        frames[index] = updated
        self._replace(tuple(frames))
        return updated

    def _require_session_key(self, session_key: str) -> None:
        if session_key != self._session_key:
            raise TaskFrameTransitionError("task frame mutation belongs to another session")

    def _find(self, frame_id: str) -> tuple[int, TaskFrame]:
        for index, frame in enumerate(self._namespace.task_frames):
            if frame.id == frame_id:
                return index, frame
        raise TaskFrameTransitionError("task frame does not exist")

    def _replace(self, frames: tuple[TaskFrame, ...]) -> None:
        namespace = TaskFrameNamespace(task_frames=_trim_terminal_frames(frames))
        _validate_namespace(namespace)
        serialized = _serialize_namespace(
            namespace,
            extensions=_namespace_extensions(self._metadata),
        )
        if len(serialized.encode("utf-8")) > MAX_NAMESPACE_BYTES:
            raise TaskFrameValidationError("task-frame namespace exceeds its size limit")
        self._namespace = namespace
        self._metadata[ORCHESTRATION_METADATA_KEY] = json.loads(serialized)


def _parse_frame(raw: object) -> TaskFrame:
    if not isinstance(raw, dict):
        raise TaskFrameValidationError("task frame must be an object")
    frame = cast(dict[str, Any], raw)
    origin_raw = frame.get("origin")
    if not isinstance(origin_raw, dict):
        raise TaskFrameValidationError("task frame origin must be an object")
    origin = cast(dict[str, Any], origin_raw)
    terminal_raw = frame.get("terminal")
    terminal: TaskFrameTerminal | None
    if terminal_raw is None:
        terminal = None
    elif isinstance(terminal_raw, dict):
        terminal_data = cast(dict[str, Any], terminal_raw)
        terminal = TaskFrameTerminal(
            reason=_require_text(terminal_data.get("reason"), "terminal.reason", 120),
            turn_id=_require_text(terminal_data.get("turn_id"), "terminal.turn_id", 200),
            summary=_optional_text(terminal_data.get("summary"), "terminal.summary", MAX_TERMINAL_SUMMARY_CHARS),
        )
    else:
        raise TaskFrameValidationError("task frame terminal must be an object or null")

    return _validate_frame(TaskFrame(
        id=_require_text(frame.get("id"), "id", 200),
        revision=_require_exact_int(frame.get("revision"), "revision", minimum=1),
        status=_require_status(frame.get("status")),
        goal=_require_text(frame.get("goal"), "goal", MAX_GOAL_CHARS),
        scope=_parse_json_text_list(frame.get("scope"), "scope"),
        constraints=_parse_json_text_list(frame.get("constraints"), "constraints"),
        acceptance=_parse_json_text_list(frame.get("acceptance"), "acceptance"),
        origin=TaskFrameOrigin(
            turn_id=_require_text(origin.get("turn_id"), "origin.turn_id", 200),
            evidence=_parse_json_text_list(origin.get("evidence"), "origin.evidence", allow_empty=False),
        ),
        created_at=_require_text(frame.get("created_at"), "created_at", 80),
        updated_at=_require_text(frame.get("updated_at"), "updated_at", 80),
        active_plan=_require_null(frame.get("active_plan"), "active_plan"),
        pending_result_ids=_parse_json_text_list(frame.get("pending_result_ids"), "pending_result_ids"),
        terminal=terminal,
    ))


def _validate_frame(frame: TaskFrame) -> TaskFrame:
    _require_text(frame.id, "id", 200)
    _require_exact_int(frame.revision, "revision", minimum=1)
    _require_status(frame.status)
    _require_text(frame.goal, "goal", MAX_GOAL_CHARS)
    _validate_text_items(frame.scope, "scope")
    _validate_text_items(frame.constraints, "constraints")
    _validate_text_items(frame.acceptance, "acceptance")
    _require_text(frame.origin.turn_id, "origin.turn_id", 200)
    _validate_text_items(frame.origin.evidence, "origin.evidence", allow_empty=False)
    _require_text(frame.created_at, "created_at", 80)
    _require_text(frame.updated_at, "updated_at", 80)
    _validate_text_items(frame.pending_result_ids, "pending_result_ids")
    if frame.active_plan is not None:
        raise TaskFrameValidationError("active_plan must be null in task-frame schema v1")
    if frame.status in _TERMINAL_STATUSES:
        if frame.terminal is None:
            raise TaskFrameValidationError("terminal task frame requires terminal details")
        _require_text(frame.terminal.reason, "terminal.reason", 120)
        _require_text(frame.terminal.turn_id, "terminal.turn_id", 200)
        _optional_text(frame.terminal.summary, "terminal.summary", MAX_TERMINAL_SUMMARY_CHARS)
    elif frame.terminal is not None:
        raise TaskFrameValidationError("non-terminal task frame cannot include terminal details")
    return frame


def _validate_namespace(namespace: TaskFrameNamespace) -> None:
    if namespace.schema_version != TASK_FRAME_SCHEMA_VERSION:
        raise TaskFrameValidationError("unsupported task-frame schema_version")
    active_count = 0
    terminal_count = 0
    ids: set[str] = set()
    for frame in namespace.task_frames:
        _validate_frame(frame)
        if frame.id in ids:
            raise TaskFrameValidationError("task frame ids must be unique")
        ids.add(frame.id)
        if frame.is_terminal:
            terminal_count += 1
        else:
            active_count += 1
    if active_count > MAX_ACTIVE_TASK_FRAMES:
        raise TaskFrameValidationError("too many active task frames")
    if terminal_count > MAX_TERMINAL_TASK_FRAMES:
        raise TaskFrameValidationError("too many terminal task frames")


def _trim_terminal_frames(frames: tuple[TaskFrame, ...]) -> tuple[TaskFrame, ...]:
    terminal_frames = sorted(
        (frame for frame in frames if frame.is_terminal), key=lambda frame: (frame.created_at, frame.id)
    )
    excess = max(0, len(terminal_frames) - MAX_TERMINAL_TASK_FRAMES)
    discarded_ids = {frame.id for frame in terminal_frames[:excess]}
    return tuple(frame for frame in frames if frame.id not in discarded_ids)


def _namespace_extensions(metadata: Mapping[str, Any]) -> dict[str, Any]:
    raw_namespace = metadata.get(ORCHESTRATION_METADATA_KEY)
    if not isinstance(raw_namespace, dict):
        return {}
    return {
        key: value
        for key, value in cast(dict[str, Any], raw_namespace).items()
        if key not in {"schema_version", TASK_FRAMES_METADATA_KEY}
    }


def _serialize_namespace(
    namespace: TaskFrameNamespace,
    *,
    extensions: Mapping[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "schema_version": namespace.schema_version,
        TASK_FRAMES_METADATA_KEY: [_frame_to_metadata(frame) for frame in namespace.task_frames],
    }
    if extensions:
        payload.update(extensions)
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TaskFrameValidationError("task-frame namespace extensions must be JSON-safe") from exc


def _frame_to_metadata(frame: TaskFrame) -> dict[str, object]:
    terminal: dict[str, str] | None = None
    if frame.terminal is not None:
        terminal = {
            "reason": frame.terminal.reason,
            "turn_id": frame.terminal.turn_id,
            "summary": frame.terminal.summary,
        }
    return {
        "id": frame.id,
        "revision": frame.revision,
        "status": frame.status,
        "goal": frame.goal,
        "scope": list(frame.scope),
        "constraints": list(frame.constraints),
        "acceptance": list(frame.acceptance),
        "origin": {"turn_id": frame.origin.turn_id, "evidence": list(frame.origin.evidence)},
        "created_at": frame.created_at,
        "updated_at": frame.updated_at,
        "active_plan": None,
        "pending_result_ids": list(frame.pending_result_ids),
        "terminal": terminal,
    }


def _require_status(value: object) -> TaskFrameStatus:
    if not isinstance(value, str) or value not in _ALL_STATUSES:
        raise TaskFrameValidationError("task frame status is invalid")
    return cast(TaskFrameStatus, value)


def _require_text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise TaskFrameValidationError(f"{name} must be non-empty text within its limit")
    return value


def _optional_text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise TaskFrameValidationError(f"{name} must be text within its limit")
    return value


def _parse_json_text_list(value: object, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TaskFrameValidationError(f"{name} must be a bounded text list")
    values = cast(list[object], value)
    return _validate_text_items(values, name, allow_empty=allow_empty)


def _validate_text_items(
    values: tuple[str, ...] | list[object], name: str, *, allow_empty: bool = True
) -> tuple[str, ...]:
    if len(values) > MAX_LIST_ITEMS:
        raise TaskFrameValidationError(f"{name} must be a bounded text list")
    items = tuple(_require_text(item, name, MAX_LIST_ITEM_CHARS) for item in values)
    if not allow_empty and not items:
        raise TaskFrameValidationError(f"{name} cannot be empty")
    return items


def _require_null(value: object, name: str) -> None:
    if value is not None:
        raise TaskFrameValidationError(f"{name} must be null")
    return None


def _require_exact_int(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TaskFrameValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _timestamp(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
