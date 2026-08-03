"""Shared contract module for ``shepherd plan`` + ``shepherd graph``.

The two command groups (:mod:`shepherd_cli.commands.plan`,
:mod:`shepherd_cli.commands.graph`) are two projections of ONE artifact:
the Stage Graph state file ``<graph-dir>/state.json`` plus its append-only
event log ``<graph-dir>/trace.jsonl``. ``plan extract`` is the single
WRITER of that file; every ``graph`` subcommand (and ``plan topology``/
``plan validate``) is a READER/UPDATER. This module owns everything both
sides must agree on, so the contract cannot drift between the two
modules:

- the pydantic models describing the state-file shape (writer-side
  validation; see the "readers use plain dicts" note below);
- graph-dir path resolution, including the run-scoped artifact shim;
- the ``cfg_get`` / ``cfg_section_get`` config readers (bash ``_lib.sh``
  parity);
- ``current_sprint()`` (bash ``git rev-parse --abbrev-ref HEAD`` parity);
- trace-event appending.

READERS USE PLAIN DICTS, ON PURPOSE
====================================
``state.json`` can be hand-edited (GH #225's fixture C: an ``agents``
entry corrupted back to ``{"count": 3}`` with no ``role`` key). The bash
readers (``graph next``/``status``/``compile``/``diagram``, ``plan
topology``) all carry defense-in-depth guards that DEGRADE on such a
shape instead of crashing — a pydantic ``model_validate`` on the read
path would turn that graceful degradation into a hard ``ValidationError``
and reintroduce the #225 crash class with a different traceback. So the
models below are used to validate what ``plan extract`` WRITES (advisory
— see :func:`shepherd_cli.commands.plan` extract), while every reader
operates on ``json.load``'ed plain dicts exactly like the bash heredocs
do.

RUN-SCOPED ARTIFACT SHIM (repo migration to ``<workdir>/runs/{run}/``)
=======================================================================
The repo is migrating run artifacts from ``<workdir>/graph/`` to
``<workdir>/runs/<run>/graph/``. This module's :func:`resolve_run` /
:func:`resolve_graph_dir` pair implements the small, documented compat
shim both command modules share:

- A run is identifiable from, in precedence order: an explicit
  ``--run=<name>`` flag (additive-only — bash has no such flag), the
  ``SHEPHERD_RUN`` environment variable, or a one-line
  ``<workdir>/runs/current`` marker file.
- WRITES of NEW state (``plan extract``) go to
  ``<workdir>/runs/<run>/graph/`` when a run is identifiable, else to the
  legacy ``<workdir>/graph/``.
- READS (and read-modify-write: ``graph mark``/``reset``/``compile``/
  ``diagram``) prefer the run-scoped ``state.json`` when it exists, and
  ALWAYS fall back to the legacy path when the run-scoped one is absent.
- With no identifiable run, both sides resolve to the legacy
  ``<workdir>/graph/`` — byte-for-byte bash behavior.

Derived artifacts (``compiled/``, ``diagrams/``, ``trace.jsonl``) always
hang off whichever graph dir the state resolved to, so a run's artifacts
stay together.

CONFIG READERS
==============
:func:`cfg_get` deliberately mirrors ``_lib.sh``'s ``cfg_get`` as a
LINE-ORIENTED scan (grep/tail/sed transliteration), NOT a tomllib parse:
bash's ``cfg_get`` is section-AGNOSTIC by contract (docs/configuration.md
§config-resolution) — a ``plans = ...`` line matches whether it sits at
the top level or inside any ``[section]``, last match in a file wins. A
tomllib parse cannot reproduce that without re-flattening every table.
:func:`cfg_section_get` mirrors :mod:`shepherd_cli.commands.models`'s
``_cfg_section_get`` (tomllib, per-file first-non-empty-wins precedence)
— duplicated here, not imported, per this package's self-contained
command-module convention (see ``init.py``'s identical note).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib

from pydantic import BaseModel, ConfigDict, Field

from shepherd_cli.resolution import resolve_repo_root, resolve_workdir

# --------------------------------------------------------------------------
# Pydantic models — the state.json / critic-proof contract (writer-side).
# --------------------------------------------------------------------------


class AgentSpec(BaseModel):
    """One normalized ``agents`` entry as ``plan extract`` writes it (GH #225).

    ``plan extract`` is the single writer of the per-node ``agents`` field
    and normalizes every entry to a mapping with a truthy ``role`` and an
    int ``count`` (the natural shorthand ``agents: [engineer]`` expands to
    ``{"role": "engineer", "count": 1}``). Extra keys (``concerns``,
    ``briefs``, ...) are preserved verbatim — ``graph compile`` reads them
    for per-spawn brief tags.

    Attributes:
        role: The flock role name, e.g. ``"coder"``.
        count: How many agents of this role the node spawns (>= 1).
    """

    model_config = ConfigDict(extra="allow")

    role: str
    count: int = 1


class InPredicate(BaseModel):
    """One AND-join inbound predicate on a node (all must be satisfied).

    Attributes:
        predecessor: The upstream node id (may be None in a malformed
            plan; ``plan validate`` reports it rather than extract
            rejecting it — bash parity).
        edge: The labeled exit edge of ``predecessor`` that satisfies
            this predicate.
        satisfied: Flipped by ``graph mark --state=done --exit=<edge>``.
    """

    predecessor: str | None = None
    edge: str | None = None
    satisfied: bool = False


class GraphNode(BaseModel):
    """One Stage Graph node as materialized in ``state.json``.

    Attributes:
        id: Node id (unique across the graph).
        type: Node type, e.g. ``WAVE-1-IMPL``; ``UNKNOWN`` when unset.
        state: One of ``pending | ready | in_flight | done | skipped``.
        parallel_with: Ids of clique peers dispatched in the same batch.
        agents: Normalized agent specs (see :class:`AgentSpec`).
        in_predicates: AND-join predicates gating readiness.
        started_at: Epoch seconds when marked ``in_flight`` (else None).
        exited_at: Epoch seconds when marked ``done``/``skipped``.
        exit_edge: The outgoing edge label that fired on ``done``.
        agent_ids: Agent ids recorded via ``graph mark --agent=<id>``.
    """

    id: str
    type: str = "UNKNOWN"
    state: str = "pending"
    parallel_with: list[str] = Field(default_factory=list)
    agents: list[AgentSpec] = Field(default_factory=list)
    in_predicates: list[InPredicate] = Field(default_factory=list)
    started_at: int | None = None
    exited_at: int | None = None
    exit_edge: str | None = None
    agent_ids: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """One labeled edge, serialized with the bash key name ``from``.

    Attributes:
        from_: Source node id (JSON key ``from`` — a Python keyword,
            hence the alias).
        label: The edge label (``on-pass``, ...); None when unset.
        to: Target node id; None when the plan omitted ``target``.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    label: str | None = None
    to: str | None = None


class GraphState(BaseModel):
    """The full ``state.json`` document ``plan extract`` writes.

    Attributes:
        schema_version: Currently always 1.
        sprint: The sprint branch this graph was extracted for.
        plan_path: The plan.md path, exactly as given on the command line.
        extracted_at: Epoch seconds of extraction.
        nodes: Node id -> node mapping (insertion order preserved).
        edges: Flat labeled edge list.
        trace_path: Sibling ``trace.jsonl`` path.
    """

    schema_version: int = 1
    sprint: str
    plan_path: str
    extracted_at: int
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]
    trace_path: str


class CriticVerdict(BaseModel):
    """The ``critic`` sub-document of a critic-proof.

    Attributes:
        verdict: The critic's verdict string, e.g. ``PASS``.
        iterations: Critique/revision iterations performed (>= 1 to pass
            ``plan verify``).
        findings: Findings count the critic reported.
    """

    verdict: str
    iterations: int = 1
    findings: int = 0


class CriticProof(BaseModel):
    """The ``<slug>.critic-proof.json`` sidecar ``plan record-critique`` writes.

    Attributes:
        schema_version: Currently always 1.
        sprint: Sprint branch at record time.
        plan_path: The proved plan's path.
        pre_critic_hash: ``sha256:<hex>`` captured BEFORE the critic pass.
        post_critic_hash: ``sha256:<hex>`` of the plan bytes at record time.
        edited: ``pre_critic_hash != post_critic_hash``.
        critic: The verdict/iterations/findings sub-document.
        recorded_at: UTC timestamp, ``%Y-%m-%dT%H:%M:%SZ``.
    """

    schema_version: int = 1
    sprint: str
    plan_path: str
    pre_critic_hash: str
    post_critic_hash: str
    edited: bool
    critic: CriticVerdict
    recorded_at: str


# --------------------------------------------------------------------------
# Run-scoped artifact shim + graph paths.
# --------------------------------------------------------------------------
def resolve_run(explicit: str | None = None) -> str | None:
    """Identify the active run, if any (see the module docstring's shim spec).

    Precedence: the explicit ``--run=<name>`` flag value, then the
    ``SHEPHERD_RUN`` environment variable, then a one-line
    ``<workdir>/runs/current`` marker file. All three are ADDITIVE-only
    conventions — bash ``shctx`` has none of them, so their absence
    reproduces bash behavior exactly.

    Args:
        explicit: The ``--run`` flag value, when the caller parsed one.

    Returns:
        The run name, or None when no run is identifiable.
    """
    if explicit:
        return explicit
    env_run = os.environ.get("SHEPHERD_RUN", "")
    if env_run:
        return env_run
    marker = os.path.join(resolve_workdir(), "runs", "current")
    try:
        with open(marker, encoding="utf-8") as fh:
            first_line = fh.readline().strip()
    except OSError:
        return None
    return first_line or None


def resolve_graph_dir(run: str | None, *, for_write: bool = False) -> str:
    """Resolve the graph state directory, honoring the run-scoped shim.

    Args:
        run: The identified run (from :func:`resolve_run`), or None.
        for_write: True for the NEW-state writer (``plan extract``): the
            run-scoped dir is chosen whenever a run is identifiable, even
            though nothing exists there yet. False for readers and
            read-modify-write commands: the run-scoped dir is chosen only
            when its ``state.json`` already exists, else the legacy dir —
            the "ALWAYS fall back to reading legacy paths" rule.

    Returns:
        The graph directory path (need not exist on disk).
    """
    workdir = resolve_workdir()
    if run:
        run_dir = f"{workdir}/runs/{run}/graph"
        if for_write:
            return run_dir
        if os.path.isfile(f"{run_dir}/state.json"):
            return run_dir
    return f"{workdir}/graph"


def state_path(graph_dir: str) -> str:
    """The ``state.json`` path inside one graph dir."""
    return f"{graph_dir}/state.json"


def trace_path(graph_dir: str) -> str:
    """The ``trace.jsonl`` path inside one graph dir."""
    return f"{graph_dir}/trace.jsonl"


def append_trace(path: str, event: dict[str, object]) -> None:
    """Append one JSON event line to the trace log (bash ``_trace_append``).

    Args:
        path: The trace.jsonl path.
        event: The event fields; serialized as one compact JSON line.
    """
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def load_state(path: str) -> dict:
    """Load ``state.json`` as a PLAIN dict (deliberately un-validated).

    See the module docstring: readers must degrade on hand-edited shapes
    (#225 fixture C), so no pydantic validation happens here.

    Args:
        path: The state.json path (caller has already checked existence).

    Returns:
        The decoded JSON document.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Git + config helpers (bash _lib.sh parity).
# --------------------------------------------------------------------------
def current_sprint() -> str:
    """The current branch name, or ``"unknown"`` (bash ``current_sprint``).

    Returns:
        ``git rev-parse --abbrev-ref HEAD`` stdout, or ``"unknown"`` when
        git is unavailable, errors, or prints nothing.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    out = proc.stdout.strip()
    if proc.returncode == 0 and out:
        return out
    return "unknown"


def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config files, in ``_lib.sh`` precedence order.

    ``local`` -> ``project`` -> XDG global, with ``${XDG_CONFIG_HOME:-
    $HOME/.config}`` semantics (an empty env var falls back too).

    Args:
        repo_root: The resolved repository root.

    Returns:
        The three candidate paths, in the order they must be tried.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME") or ""
    if not xdg:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        xdg = os.path.join(home, ".config")
    return (
        os.path.join(repo_root, ".claude", "shepherd.local.toml"),
        os.path.join(repo_root, ".claude", "shepherd.toml"),
        os.path.join(xdg, "shepherd.toml"),
    )


def cfg_get(key: str) -> str:
    """Section-agnostic single-key config lookup (bash ``cfg_get`` parity).

    Line-oriented on purpose — see the module docstring. Per file (local
    -> project -> XDG): every ``key = value`` line matches regardless of
    which ``[section]`` it sits under, the LAST match in the file wins,
    surrounding double-quotes and a trailing `` # inline comment`` are
    stripped. The first file yielding a non-empty value short-circuits.

    Args:
        key: The bare key name, e.g. ``"plans"``.

    Returns:
        The resolved value, or ``""`` when unset anywhere (bash echoes
        the empty string, never fails).
    """
    line_re = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=")
    repo = resolve_repo_root()
    for path in _config_search_paths(repo):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        value = ""
        for line in lines:
            if not line_re.match(line):
                continue
            candidate = line.split("=", 1)[1]
            candidate = re.sub(r"[ \t]+#.*$", "", candidate).strip()
            if candidate.startswith('"') and candidate.endswith('"') and len(candidate) >= 2:
                candidate = candidate[1:-1]
            value = candidate
        if value:
            return value
    return ""


def cfg_section_get(section: str, key: str) -> str | None:
    """``[section].key`` config lookup (tomllib, ``models.py`` parity).

    Duplicated from :mod:`shepherd_cli.commands.models`'s
    ``_cfg_section_get`` per the self-contained-module convention: the
    first file (local -> project -> XDG) with a non-empty value wins; a
    malformed TOML file is treated as absent rather than raising.

    Args:
        section: The TOML table name, e.g. ``"models"``.
        key: The key within that table, e.g. a role name.

    Returns:
        The value as a string, or None when unset everywhere.
    """
    repo = resolve_repo_root()
    for path in _config_search_paths(repo):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        table = data.get(section)
        if not isinstance(table, dict):
            continue
        value = table.get(key)
        if value is None:
            continue
        value_str = str(value)
        if value_str:
            return value_str
    return None


__all__ = [
    "AgentSpec",
    "InPredicate",
    "GraphNode",
    "GraphEdge",
    "GraphState",
    "CriticVerdict",
    "CriticProof",
    "resolve_run",
    "resolve_graph_dir",
    "state_path",
    "trace_path",
    "append_trace",
    "load_state",
    "current_sprint",
    "cfg_get",
    "cfg_section_get",
]
