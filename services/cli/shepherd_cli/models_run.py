"""Run-state schema + atomic IO for ``.shepherd/runs/{run}/run.json``.

The run directory is the standard home for ALL run-scoped artifacts
(v6.5.0 artifact schema — ``skills/context/references/naming-conventions.md``):

    runs/{run}/
      run.json          # THIS module's document — CLI-written, validated
      seed.md           # planter output
      mesh.md           # planter mesh report
      plan.md           # engineer master plan
      phase0.md         # engineer Phase-0 mesh
      lanes/{lane}/plan.md   # conductor-OWNED lane plan
      graph/            # stage-graph state (ephemeral)
      dispatch/         # dispatch contracts + dispatcher-patch ledger (ephemeral)
      reports/ audits/  # materialized role output (ephemeral)
      close.md handoff.md    # terminal records

Design rules (from the codex-shepherd port-back review):

- ``run.json`` is NEVER latent-space-written: this module is the one
  writer, with a closed pydantic schema, so producer and consumer cannot
  diverge (the exact gap codex-shepherd's own committed learning names).
- Writes are atomic: tempfile in the target directory -> fsync ->
  ``os.replace`` -> fsync(dir). A crashed writer never leaves a torn file.
- Identifiers are sanitized to ``[a-z0-9][a-z0-9-]*`` — no ``..``, no
  path separators, no absolute paths, matching the artifact-schema rules.
- The ``lanes[].accepted_commit``/``merged`` pair is the #242
  boundary-merge ledger: WAVE-COMPLETE acceptance records the commit,
  the boundary merge marks it merged, and the wave gate asserts the
  pending set (accepted, unmerged) is EMPTY before any gate goes green.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time

from pydantic import BaseModel, ConfigDict, Field

from shepherd_cli.resolution import resolve_workdir

#: Closed identifier grammar for run and lane ids (artifact-schema rule).
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: Closed run status vocabulary, in lifecycle order.
RUN_STATUSES: tuple[str, ...] = ("planted", "planned", "executing", "closing", "closed")

#: Closed lane state vocabulary (mirrors teammate declared_state semantics).
LANE_STATES: tuple[str, ...] = ("pending", "in-progress", "complete", "error")


class RunIdError(ValueError):
    """Raised for an identifier outside the closed ``[a-z0-9-]`` grammar."""


def validate_id(value: str, *, what: str = "id") -> str:
    """Validate one run/lane identifier against the closed grammar.

    Args:
        value: Candidate identifier.
        what: Label used in the error message (``run``/``lane``).

    Returns:
        The validated identifier, unchanged.

    Raises:
        RunIdError: On empty, uppercase, path-separator, ``..``, or
            absolute-path shapes.
    """
    if not value or not _ID_PATTERN.fullmatch(value):
        raise RunIdError(
            f"invalid {what} id: {value!r} (lowercase ASCII letters, digits, hyphens; "
            "must start alphanumeric; no path separators)"
        )
    return value


class LaneState(BaseModel):
    """One lane's registration + boundary-merge ledger row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    plan: str = ""  # repo-relative lanes/{lane}/plan.md path
    worktree: str = ""
    branch: str = ""
    state: str = "pending"
    accepted_commit: str | None = None  # 242 ledger: WAVE-COMPLETE-accepted sha
    merged: bool = False  # 242 ledger: boundary merge landed the sha
    updated_at: int = 0


class RunState(BaseModel):
    """The ``run.json`` document — the machine state of one run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run: str
    kind: str = "sprint"  # sprint | patch-arc
    branch: str = ""
    base: str = ""
    seed: str = ""  # repo-relative seed.md path, "" until planted
    plan: str = ""  # repo-relative plan.md path, "" until planned
    status: str = "planted"
    lanes: list[LaneState] = Field(default_factory=list)
    updated_at: int = 0

    def lane(self, lane_id: str) -> LaneState | None:
        """Look up one lane by id.

        Args:
            lane_id: The lane identifier.

        Returns:
            The matching lane, or None.
        """
        for lane in self.lanes:
            if lane.id == lane_id:
                return lane
        return None

    def pending_merges(self) -> list[LaneState]:
        """The #242 pending set: lanes accepted but not yet boundary-merged.

        Returns:
            Lanes with a recorded ``accepted_commit`` and ``merged`` False.
            A non-empty return at a wave gate is a mechanical stop.
        """
        return [lane for lane in self.lanes if lane.accepted_commit and not lane.merged]


def runs_root(workdir: str | None = None) -> str:
    """The runs directory under the resolved (or given) workdir."""
    return os.path.join(workdir if workdir is not None else resolve_workdir(), "runs")


def run_dir(run: str, workdir: str | None = None) -> str:
    """One run's directory: ``<workdir>/runs/<run>``.

    Args:
        run: The run identifier (validated).
        workdir: Optional workdir override (tests).

    Returns:
        The absolute run directory path (need not exist).
    """
    return os.path.join(runs_root(workdir), validate_id(run, what="run"))


def lane_dir(run: str, lane: str, workdir: str | None = None) -> str:
    """One lane's directory: ``<workdir>/runs/<run>/lanes/<lane>``."""
    return os.path.join(run_dir(run, workdir), "lanes", validate_id(lane, what="lane"))


def run_state_path(run: str, workdir: str | None = None) -> str:
    """The ``run.json`` path for one run."""
    return os.path.join(run_dir(run, workdir), "run.json")


def atomic_write_json(path: str, payload: dict[str, object]) -> None:
    """Write JSON atomically: tempfile -> fsync -> replace -> fsync(dir).

    Args:
        path: Destination file path; parent directories are created.
        payload: JSON-ready document (sorted keys on disk).
    """
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".run-json-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def load_run(run: str, workdir: str | None = None) -> RunState:
    """Load + validate one run's ``run.json``.

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests).

    Returns:
        The validated run state.

    Raises:
        FileNotFoundError: No ``run.json`` for this run.
        ValueError: The document fails schema validation (pydantic).
    """
    path = run_state_path(run, workdir)
    with open(path, "r", encoding="utf-8") as handle:
        return RunState.model_validate(json.load(handle))


def save_run(state: RunState, workdir: str | None = None) -> str:
    """Persist one run's state atomically, stamping ``updated_at``.

    Args:
        state: The run state to persist (``state.run`` names the target).
        workdir: Optional workdir override (tests).

    Returns:
        The path written.
    """
    state.updated_at = int(time.time())
    path = run_state_path(state.run, workdir)
    atomic_write_json(path, state.model_dump(mode="json"))
    return path


def list_runs(workdir: str | None = None) -> list[str]:
    """Enumerate run ids with a ``run.json``, sorted.

    Returns:
        Sorted run ids (directory names under ``runs/`` carrying a
        ``run.json`` — never an mtime scan).
    """
    root = runs_root(workdir)
    if not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        if _ID_PATTERN.fullmatch(name) and os.path.isfile(os.path.join(root, name, "run.json")):
            found.append(name)
    return found


__all__ = [
    "LANE_STATES",
    "RUN_STATUSES",
    "LaneState",
    "RunIdError",
    "RunState",
    "atomic_write_json",
    "lane_dir",
    "list_runs",
    "load_run",
    "run_dir",
    "run_state_path",
    "runs_root",
    "save_run",
    "validate_id",
]
