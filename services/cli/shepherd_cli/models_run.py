"""Run-state schema + atomic IO for ``.shepherd/runs/{run}/run.json``.

The run directory is the standard home for ALL run-scoped artifacts
(v6.4.1 artifact schema — ``skills/context/references/naming-conventions.md``):

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

- ``run.json`` is NEVER latent-space-written: this module is the one CLI
  writer, so a CLI-originated write cannot invent its own field shapes.
  It is NOT the one *reader* — ``skills/bridge/SKILL.md`` names other
  shepherd implementations (prior bash versions, codex-shepherd) that
  read and write the same file with their own field sets. #247: a
  brand-new closed (``extra="forbid"``) schema rejected 100% of run.json
  files measured on live runs (33 and 17 validation errors on two
  runs), because every mutator goes through :func:`load_run`. The fix
  is a tolerant reader (:func:`normalize_run_document`) plus an open
  (``extra="allow"``) schema on both :class:`RunState` and
  :class:`LaneState`, so unknown fields — this CLI's own future fields
  included — round-trip through load -> save untouched instead of being
  silently dropped.
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

import datetime
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
    """One lane's registration + boundary-merge ledger row.

    #247: ``extra="allow"`` — other shepherd implementations (and future
    CLI fields) attach lane keys this model does not name; a load->save
    round trip must preserve them rather than silently drop them.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    plan: str = ""  # repo-relative lanes/{lane}/plan.md path
    worktree: str = ""
    branch: str = ""
    state: str = "pending"
    accepted_commit: str | None = None  # 242 ledger: WAVE-COMPLETE-accepted sha
    merged: bool = False  # 242 ledger: boundary merge landed the sha
    updated_at: int = 0


class RunState(BaseModel):
    """The ``run.json`` document — the machine state of one run.

    #247: ``extra="allow"`` — see the module docstring. This model names
    the fields the CLI itself reads/writes; every other top-level key a
    document carries (``decisions``, ``blockers``, ``acceptance``, ...)
    is preserved verbatim through :func:`load_run` / :func:`save_run`
    instead of being rejected or dropped.
    """

    model_config = ConfigDict(extra="allow")

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


def _coerce_epoch(value: object) -> int:
    """Coerce a legacy ``updated_at`` value into unix epoch seconds.

    Args:
        value: An ``int``/``float`` epoch, an ISO8601 string (bash and
            codex-shepherd both write ``updated_at`` as ISO8601 text),
            or anything else.

    Returns:
        The integer epoch. ``0`` for anything that cannot be parsed —
        this function never raises.
    """
    if isinstance(value, bool):
        return 0  # bool is an int subclass; never a meaningful timestamp.
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return 0
    text = value.strip()
    if not text:
        return 0
    try:
        return int(text)  # an epoch already serialized as a string.
    except ValueError:
        pass
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return int(parsed.timestamp())


def normalize_run_document(raw: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    """Normalize a legacy/foreign ``run.json`` document to the current shape.

    #247: prior shepherd versions and the sibling codex-shepherd
    implementation write ``run.json`` with a different field shape for
    three keys. This is a pure function (no IO, no pydantic) precisely
    so each divergence is independently unit-testable:

    - ``run_id`` (legacy) -> ``run`` (current), only when ``run`` is not
      already present.
    - ``lanes`` as a ``dict`` keyed by lane id (legacy) -> the current
      ``list[LaneState]`` shape, injecting the dict key as each lane's
      ``id`` (deterministic: the key always wins over an inline ``id``
      the lane dict might also carry) and sorting by id.
    - ``updated_at`` as an ISO8601 string (legacy) -> int epoch seconds
      via :func:`_coerce_epoch`.

    Every other key — the 27+ extra top-level fields legacy documents
    carry (``decisions``, ``blockers``, ``acceptance``, ...) — passes
    through untouched; :class:`RunState`'s ``extra="allow"`` config is
    what preserves them, not this function.

    Args:
        raw: The parsed JSON document, as-is off disk.

    Returns:
        A ``(normalized_document, applied)`` pair. ``applied`` lists the
        migrations this call actually performed, in a fixed
        ``["run_id->run", "lanes:dict->list", "updated_at:iso->epoch"]``
        order (never dict-iteration order) — empty when ``raw`` was
        already canonical.
    """
    doc = dict(raw)
    applied: list[str] = []

    if "run" not in doc and "run_id" in doc:
        doc["run"] = doc.pop("run_id")
        applied.append("run_id->run")

    lanes = doc.get("lanes")
    if isinstance(lanes, dict):
        normalized_lanes: list[object] = []
        for lane_id in sorted(lanes):
            lane_doc = lanes[lane_id]
            if isinstance(lane_doc, dict):
                lane_doc = dict(lane_doc)
            else:
                lane_doc = {}
            lane_doc["id"] = lane_id  # the dict key is authoritative, not any inline "id".
            normalized_lanes.append(lane_doc)
        doc["lanes"] = normalized_lanes
        applied.append("lanes:dict->list")

    if isinstance(doc.get("updated_at"), str):
        doc["updated_at"] = _coerce_epoch(doc["updated_at"])
        applied.append("updated_at:iso->epoch")

    return doc, applied


def load_run_with_migrations(run: str, workdir: str | None = None) -> tuple[RunState, list[str]]:
    """Load + tolerantly validate one run's ``run.json``, reporting migrations.

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests).

    Returns:
        ``(state, applied)`` — the validated run state, and the ordered
        list of :func:`normalize_run_document` migrations that were
        actually applied (empty when the document was already
        canonical).

    Raises:
        FileNotFoundError: No ``run.json`` for this run.
        json.JSONDecodeError: The file is not valid JSON.
        pydantic.ValidationError: The (normalized) document still fails
            schema validation.
    """
    path = run_state_path(run, workdir)
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        # Valid JSON, but not an object (e.g. a bare list/string/number) --
        # not this function's shape to normalize; let pydantic reject it
        # with its own "Input should be a valid dictionary" ValidationError
        # rather than normalize_run_document crashing on a non-dict.
        return RunState.model_validate(raw), []
    normalized, applied = normalize_run_document(raw)
    return RunState.model_validate(normalized), applied


def load_run(run: str, workdir: str | None = None) -> RunState:
    """Load + tolerantly validate one run's ``run.json``.

    A thin wrapper over :func:`load_run_with_migrations` for callers
    that don't need the applied-migrations list (e.g. every mutator
    other than ``run show``/``run migrate``).

    Args:
        run: The run identifier.
        workdir: Optional workdir override (tests).

    Returns:
        The validated run state, normalized per :func:`normalize_run_document`.

    Raises:
        FileNotFoundError: No ``run.json`` for this run.
        json.JSONDecodeError: The file is not valid JSON.
        pydantic.ValidationError: The (normalized) document still fails
            schema validation.
    """
    state, _applied = load_run_with_migrations(run, workdir)
    return state


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
    "load_run_with_migrations",
    "normalize_run_document",
    "run_dir",
    "run_state_path",
    "runs_root",
    "save_run",
    "validate_id",
]
