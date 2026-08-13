"""``shepherd run`` — run-directory lifecycle Typer sub-app.

NEW surface (v6.4.1) — the deterministic writer for
``.shepherd/runs/{run}/`` state (``shepherd_cli.models_run``). No bash
counterpart existed; run state was previously scattered (graph/ dir,
lock file, latent prose). Subcommands:

- ``run init [<run>] [--kind sprint|patch-arc] [--branch B] [--base B]
  [--version V] [--force]`` — scaffold ``runs/<run>/`` (+ ``lanes/``) and
  write the initial ``run.json``. Refuses (exit 5) when the run already
  exists. #P4 (2026-08-03 operator directive — see
  :mod:`shepherd_cli.models_run`'s "CANONICAL RUN IDS" section): ``<run>``
  may be omitted when ``--version``/``--branch`` is given, deriving the id
  via :func:`shepherd_cli.models_run.derive_run_id`; an explicit ``<run>``
  that is not itself canonical
  (:func:`shepherd_cli.models_run.is_canonical_run_id`) is REFUSED
  (exit 2) unless ``--force``, which proceeds but warns loudly on stderr.
- ``run rename <old> <new>`` — moves ``runs/<old>/`` to ``runs/<new>/``
  and rewrites ``run.json``'s ``run`` field (plus any self-referential
  ``runs/<old>/``-prefixed ``seed``/``plan`` paths). Refuses (exit 5) if
  ``<new>`` already exists or ``<old>`` does not. Prints (stderr) every
  other ``.json``/``.md`` file under the workdir still mentioning
  ``<old>`` — reported, NEVER rewritten, since fixing those would mean
  editing a file outside the run directory.
- ``run canonicalize [<run>|--all] [--dry-run]`` — the ``run rename``
  migration path for a run planted with a non-canonical id (axiom's live
  ``v039-dev0-codex-01``): computes each target's canonical form
  (:func:`shepherd_cli.models_run.suggest_canonical_id`) and renames it.
  Idempotent on an already-canonical run (no-op); a run with no
  recognizable canonical prefix is reported and skipped, never crashed
  on; ``--dry-run`` previews every planned rename with no changes made.
- ``run show <run> [--json]`` / ``run list [--json]`` — read side.
- ``run set <run> [--status S] [--seed P] [--plan P]`` — field updates
  (status validated against the closed vocabulary).
- ``run migrate <run> | --all`` — #247: load a run.json tolerantly
  (:func:`shepherd_cli.models_run.normalize_run_document`) and rewrite
  it in canonical form, reporting the migrations applied. Idempotent —
  a second run reports none applied.
- ``run lane add <run> <lane> [--plan P] [--worktree P] [--branch B]`` /
  ``run lane set <run> <lane> --state S`` — lane registration + state.
- ``run wave accept <run> <lane> --commit SHA`` — record a
  WAVE-COMPLETE-accepted commit in the #242 boundary-merge ledger.
- ``run wave merged <run> <lane>`` — mark that lane's accepted commit
  boundary-merged.
- ``run wave pending <run> [--json]`` — the mechanical #242 gate: exit 0
  with no output when the pending set is empty AND the ledger is
  lane-complete; exit 6 listing ``lane<TAB>sha`` rows for each
  accepted-but-unmerged lane and ``lane<TAB>MISSING-DECLARED-LANE`` rows
  for each lane the run's plan.md ``## Lane projection`` table declares
  but ``run.json`` never registered at all (#1 GATE-EXIT-CODE-MISMATCH,
  DF-63 — an omitted ``run lane add`` used to make this gate GREENER, not
  redder, since a lane with zero rows is trivially "not pending"). Root
  MUST run this before declaring any wave gate green.
- ``run ledger path [<run>] [--check]`` — v6.4.3 (#261): print the run's
  audit ledger's ABSOLUTE, PRIMARY-checkout path
  (:func:`shepherd_cli.verdicts.ledger_path`) — the ONE verb every agent
  should use instead of hand-composing a
  ``.shepherd/runs/<run>/auditor-verdicts.txt``-shaped relative path, which
  resolves to a divorced physical copy from inside a linked worktree.
  ``<run>`` may be omitted to use the ACTIVE run (the mtime-newest
  ``run.json`` whose ``status`` is ``"executing"`` — mirrors
  ``hooks/scripts/_lib.sh``'s ``active_run_dir``). ``--check`` additionally
  exits 3 when the caller's cwd is inside a linked worktree AND a local,
  worktree-relative copy of the ledger also exists there — a divergence
  RISK signal, cheaper than (and independent of) ``ledger check`` below.
- ``run ledger check [<run>] [--json]`` — v6.4.3 (#261): the mechanical
  worktree-ledger divergence check
  (:func:`shepherd_cli.verdicts.compare_worktree_ledgers`). FAILS (exit 7)
  on any row a linked worktree's local ledger copy holds that the primary
  lacks — the destructive case: merging that worktree could silently drop
  a sibling lane's verdict row. A worktree merely BEHIND the primary
  (every lane's normal state between merges) is NEVER flagged. Exit 5 when
  the run has no ledger yet.
- ``run wave verify <run> [--wave N] [--json]`` — v6.4.3 (#262): the
  step/verdict join (:func:`shepherd_cli.verdicts.join`) nothing else
  performs: enumerates every ``W-L-S`` step id from
  ``{run_dir}/lanes/*/plan.md`` and joins it against the parsed ledger,
  surfacing ``NO-VERDICT`` / ``UNRESOLVED-VERDICT`` / ``ORPHAN-VERDICT`` /
  ``MALFORMED-ROW`` findings that reading the ledger top-to-bottom cannot
  show. Exit 6 (the mechanical stop, matching ``wave pending``'s exit-6
  idiom) when any finding is present; exit 5 when the run or its
  lane-plan directory is missing.

Exit codes: 0 ok; 2 usage/validation (includes a non-canonical explicit
``run init`` id, without ``--force``, and ``ledger path``/``ledger
check`` given no ``<run>`` and no resolvable active run — see the module
docstring's ``ledger path`` entry); 3 a divergent local ledger copy was
detected (``ledger path --check``); 5 run exists (init) or missing
(everything else, including ``rename``'s source/destination checks,
``ledger check`` when the run's ledger is absent, and ``wave verify``
when the run or its lane-plan directory is absent); 6 pending merges
remain OR a plan-declared lane has no ledger row (``wave pending``, #1
GATE-EXIT-CODE-MISMATCH) or step/verdict join findings are present
(``wave verify``); 7 worktree ledger divergence (``ledger check``).
"""

from __future__ import annotations

import json
import os
import subprocess

import typer
from pydantic import ValidationError

from shepherd_cli import verdicts
from shepherd_cli.models_run import (
    LANE_STATES,
    RUN_STATUSES,
    RUN_SUBDIRS,
    RUN_TRACKED_FILES,
    LaneState,
    RunIdDerivationError,
    RunIdError,
    RunState,
    derive_run_id,
    is_canonical_run_id,
    lane_dir,
    list_runs,
    load_run,
    load_run_with_migrations,
    missing_run_subdirs,
    run_dir,
    run_state_path,
    runs_root,
    save_run,
    scaffold_run_layout,
    suggest_canonical_id,
    validate_id,
)
from shepherd_cli.resolution import in_subworktree, resolve_workdir

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Run-directory lifecycle: init/show/list/set, lane registry, #242 wave ledger.",
)

lane_app = typer.Typer(no_args_is_help=True, add_completion=False, help="Lane registration + state.")
wave_app = typer.Typer(no_args_is_help=True, add_completion=False, help="#242 boundary-merge ledger.")
ledger_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="#261 audit-ledger custody (auditor-verdicts.txt)."
)
app.add_typer(lane_app, name="lane")
app.add_typer(wave_app, name="wave")
app.add_typer(ledger_app, name="ledger")


def _fail(message: str, code: int) -> None:
    typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(code)


def _unreadable_message(run: str, exc: Exception, *, schema_shaped: bool) -> str:
    """Build the #247 non-"corrupt" wording for an unreadable run.json.

    Args:
        run: The run identifier.
        exc: The underlying parse/validation exception.
        schema_shaped: True when ``exc`` is a pydantic validation failure
            (the document parsed as JSON but doesn't fit the schema —
            exactly what ``run migrate`` exists to fix), False for a
            genuine JSON parse failure.

    Returns:
        The message text (without the ``ERROR:`` prefix ``_fail`` adds).
    """
    message = f"run.json for {run} could not be read: {exc}"
    if schema_shaped:
        message += f" — try: shepherd run migrate {run}"
    return message


def _load_or_fail(run: str) -> RunState:
    try:
        return load_run(run)
    except RunIdError as exc:
        _fail(str(exc), 2)
    except FileNotFoundError:
        _fail(f"no such run: {run} (expected {run_state_path(run)})", 5)
    except json.JSONDecodeError as exc:
        _fail(_unreadable_message(run, exc, schema_shaped=False), 2)
    except ValidationError as exc:
        _fail(_unreadable_message(run, exc, schema_shaped=True), 2)
    raise AssertionError("unreachable")


def _load_with_migrations_or_fail(run: str) -> tuple[RunState, list[str]]:
    """Like :func:`_load_or_fail`, but also returns the applied #247 migrations."""
    try:
        return load_run_with_migrations(run)
    except RunIdError as exc:
        _fail(str(exc), 2)
    except FileNotFoundError:
        _fail(f"no such run: {run} (expected {run_state_path(run)})", 5)
    except json.JSONDecodeError as exc:
        _fail(_unreadable_message(run, exc, schema_shaped=False), 2)
    except ValidationError as exc:
        _fail(_unreadable_message(run, exc, schema_shaped=True), 2)
    raise AssertionError("unreachable")


#: #P4: why ``run init --force`` isn't a quiet escape hatch — printed to
#: stderr every time a non-canonical explicit id is forced through, so the
#: cost of skipping the rule is never silent.
_FORCE_WARNING = (
    "WARNING: {run!r} is a non-canonical run id, forced by --force. "
    "skills/bridge/SKILL.md has two shepherd implementations SHARING one run "
    "and arbitrating custody through run.json; a harness-suffixed id lets "
    "each implementation create its OWN run and silently work in parallel "
    "instead of coordinating -- exactly the failure the bridge contract "
    "exists to prevent. Fix it with: shepherd run canonicalize {run!r}"
)


@app.command("init")
def init_cmd(
    run: str | None = typer.Argument(
        None, help="Run id (sprint slug, e.g. v641-dev0). Omit to derive one from --version/--branch."
    ),
    kind: str = typer.Option("sprint", "--kind", help="sprint | patch-arc."),
    branch: str = typer.Option("", "--branch", help="The run's git branch."),
    base: str = typer.Option("", "--base", help="The run's base branch."),
    version: str = typer.Option(
        "", "--version", help="Version/branch to derive <run> from (e.g. v0.3.9-dev.0). Ignored if <run> is given."
    ),
    force: bool = typer.Option(
        False, "--force", help="Allow a non-canonical explicit <run> id (NOT RECOMMENDED — see #P4)."
    ),
) -> None:
    """Scaffold ``runs/<run>/`` and write the initial run.json.

    #P4: ``<run>`` is either derived (omit it, pass ``--version`` or
    ``--branch``) or validated for canonicality (pass it explicitly) — see
    :mod:`shepherd_cli.models_run`'s "CANONICAL RUN IDS" section. The
    ``[a-z0-9][a-z0-9-]*`` path-safety grammar (:func:`shepherd_cli.models_run.validate_id`)
    is checked either way and is NEVER bypassable, including with
    ``--force`` — canonicality and grammar are separate concerns.
    """
    if kind not in ("sprint", "patch-arc"):
        _fail(f"invalid --kind: {kind} (sprint | patch-arc)", 2)

    if run is None:
        source = version or branch
        if not source:
            _fail("pass <run>, or --version/--branch to derive one from", 2)
        try:
            run = derive_run_id(source, kind=kind)
        except RunIdDerivationError as exc:
            _fail(str(exc), 2)
    else:
        try:
            validate_id(run, what="run")
        except RunIdError as exc:
            _fail(str(exc), 2)
        if not is_canonical_run_id(run):
            if not force:
                suggestion = suggest_canonical_id(run)
                hint = f" (did you mean {suggestion!r}?)" if suggestion and suggestion != run else ""
                _fail(
                    f"non-canonical run id: {run!r}{hint} -- run ids come from "
                    "[branching].sprint_slug_pattern/patch_slug_pattern, never invented ad hoc "
                    "(skills/context/references/naming-conventions.md). Pass --force to override.",
                    2,
                )
            typer.echo(_FORCE_WARNING.format(run=run), err=True)

    if os.path.isfile(run_state_path(run)):
        _fail(f"run already exists: {run}", 5)
    # Scaffold the FULL canonical layout, not just lanes/ (v6.4.3): a run's
    # shape must be identical from creation, whoever creates it -- the planter
    # via `plant`, root, or a sibling implementation -- and whatever the sprint
    # later happens to use or skip.
    scaffold_run_layout(run)
    path = save_run(RunState(run=run, kind=kind, branch=branch, base=base))
    typer.echo(path)


def _find_run_id_references(run_id: str, *, workdir: str | None = None) -> list[str]:
    """Scan the workdir tree for literal mentions of ``run_id``.

    A deterministic, bounded scan (``.json``/``.md`` files under the
    resolved workdir only — never the whole repo) used by ``run
    rename``/``run canonicalize`` to surface what a rename would leave
    dangling: other ``run.json`` documents, lane plans, or prose that
    still names the old id. This function NEVER rewrites anything; it
    only reports paths for the operator to fix by hand — editing free-text
    prose (or a file outside the run directory) is out of scope for a
    deterministic renamer.

    Args:
        run_id: The (old) run id to search for.
        workdir: Optional workdir override (avoids a second
            ``resolve_workdir()`` call when the caller already has one).

    Returns:
        Sorted ``"<path>:<line>"`` references, one per matching line.
    """
    root = workdir if workdir is not None else resolve_workdir()
    if not os.path.isdir(root):
        return []
    hits: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not (filename.endswith(".json") or filename.endswith(".md")):
                continue
            path = os.path.join(dirpath, filename)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    lines = handle.readlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(lines, start=1):
                if run_id in line:
                    hits.append(f"{path}:{lineno}")
    return sorted(hits)


def _run_dir_names() -> list[str]:
    """Every directory name directly under ``runs/``, sorted.

    Deliberately NOT :func:`shepherd_cli.models_run.list_runs`, which indexes
    by ``run.json`` presence — an unregistered directory is invisible to it,
    and that is the population ``canonicalize`` most needs to reach.

    Returns:
        Sorted directory names, or ``[]`` when ``runs/`` does not exist.
    """
    base = runs_root()
    if not os.path.isdir(base):
        return []
    return sorted(name for name in os.listdir(base) if os.path.isdir(os.path.join(base, name)))


def _rename_run(old: str, new: str) -> list[str]:
    """Move ``runs/<old>/`` to ``runs/<new>/`` and rewrite the moved run.json.

    Callers (:func:`rename_cmd`/:func:`canonicalize_cmd`) own every
    existence/collision precondition — this assumes both have already
    been checked and performs the move unconditionally.

    Besides ``run.json``'s ``run`` field, this also fixes ``seed``/``plan``
    top-level fields when they are themselves a ``runs/<old>/``-prefixed
    repo-relative path (root's own convention — see the module docstring's
    run-dir layout table): those paths point at files INSIDE the run
    directory that just moved, so leaving them stale would silently break
    ``run show``'s ``seed``/``plan`` fields for no reason. Nothing outside
    ``runs/<new>/`` is ever written.

    Args:
        old: The existing run id (source).
        new: The new run id (destination).

    Returns:
        :func:`_find_run_id_references` for ``old``, run AFTER the move
        completes (so nothing under the just-moved ``runs/<new>/`` tree is
        missed if its own prose still mentions ``old``).
    """
    # An UNREGISTERED directory (no run.json) is renameable. That population is
    # precisely the one that most needs renaming: `run init` REFUSES a
    # non-canonical id, so a misnamed directory nothing registered could
    # previously be neither registered nor renamed -- `shepherd lint`'s
    # unregistered-run check points here, and it must not point at a dead end.
    # Observed in this repo: `runs/2026-05-04-shepherd-context`, a date-topic
    # SPEC name, unregistered and unfixable through any sanctioned command.
    registered = os.path.isfile(run_state_path(old))
    state = _load_or_fail(old) if registered else None  # corrupt run.json fails cleanly (exit 2)
    old_dir = run_dir(old)
    new_dir = run_dir(new)
    os.rename(old_dir, new_dir)

    if state is not None:
        state.run = new
        old_prefix = f"runs/{old}/"
        new_prefix = f"runs/{new}/"
        if state.seed.startswith(old_prefix):
            state.seed = new_prefix + state.seed[len(old_prefix) :]
        if state.plan.startswith(old_prefix):
            state.plan = new_prefix + state.plan[len(old_prefix) :]
        save_run(state)

    return _find_run_id_references(old)


def _report_dangling_references(old: str, references: list[str]) -> None:
    """Print (stderr) every leftover mention of ``old`` a rename left behind."""
    if not references:
        return
    typer.echo(
        f"WARNING: {old} is still referenced in {len(references)} place(s) below "
        "(outside the run directory — NOT rewritten; fix these by hand):",
        err=True,
    )
    for reference in references:
        typer.echo(f"  {reference}", err=True)


@app.command("rename")
def rename_cmd(
    old: str = typer.Argument(..., help="Existing run id."),
    new: str = typer.Argument(..., help="New run id to rename it to."),
) -> None:
    """Move ``runs/<old>/`` to ``runs/<new>/`` and rewrite ``run.json``'s ``run`` field.

    Refuses (exit 5) if ``<new>`` already exists or ``<old>`` does not.
    NEVER destroys data: both checks happen before anything on disk moves.
    Prints any other file under the workdir still mentioning ``<old>`` —
    see :func:`_find_run_id_references`.
    """
    try:
        validate_id(old, what="run")
        validate_id(new, what="run")
    except RunIdError as exc:
        _fail(str(exc), 2)
    if old == new:
        _fail("old and new run ids are identical", 2)
    # Gate on the DIRECTORY, not run.json: an unregistered directory is exactly
    # what most needs renaming (see _rename_run), and `run init` will not take
    # a non-canonical id, so requiring run.json here made those a dead end.
    if not os.path.isdir(run_dir(old)):
        _fail(f"no such run directory: {old} (expected {run_dir(old)})", 5)
    if os.path.isfile(run_state_path(new)) or os.path.isdir(run_dir(new)):
        _fail(f"destination already exists: {new}", 5)

    registered = os.path.isfile(run_state_path(old))
    references = _rename_run(old, new)
    typer.echo(f"renamed {old} -> {new}: {run_dir(new)}")
    if not registered:
        typer.echo(
            f"NOTE: {new} has no run.json — it is not yet a run that anything can read. "
            f"Register it with: shepherd run init {new}",
            err=True,
        )
    _report_dangling_references(old, references)


@app.command("canonicalize")
def canonicalize_cmd(
    run: str | None = typer.Argument(None, help="One run id, or omit with --all."),
    all_runs: bool = typer.Option(False, "--all", help="Canonicalize every non-canonical run under runs/."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned renames without changing anything."),
) -> None:
    """The ``run rename`` migration path: rename every non-canonical run to its canonical id.

    #P4's fix for a live non-canonical run (axiom's ``v039-dev0-codex-01``):
    computes each target's canonical form
    (:func:`shepherd_cli.models_run.suggest_canonical_id`) and renames it.
    Idempotent on an already-canonical run (reported, no rename). A run
    with no recognizable canonical prefix, or whose canonical destination
    already exists, is reported and skipped rather than failing the whole
    invocation — never blocks a mid-sprint ``--all`` on one bad run.
    """
    if bool(run) == all_runs:
        _fail("pass exactly one of <run> or --all", 2)
    # --all enumerates DIRECTORIES, not `list_runs` (which indexes by run.json):
    # a misnamed directory usually has no run.json either, and `run init`
    # refuses a non-canonical id, so gating on registration made exactly the
    # population this command exists to fix unreachable by it.
    targets: list[str] = _run_dir_names() if all_runs else [run]  # type: ignore[list-item]
    if all_runs and not targets:
        typer.echo("no runs to canonicalize")
        return

    for target in targets:
        if not os.path.isdir(run_dir(target)):
            _fail(f"no such run directory: {target} (expected {run_dir(target)})", 5)
        if is_canonical_run_id(target):
            typer.echo(f"{target}: already canonical")
            continue
        suggestion = suggest_canonical_id(target)
        if suggestion is None:
            typer.echo(
                f"{target}: no recognizable canonical form -- fix manually with: "
                f"shepherd run rename {target} <new-id>"
            )
            continue
        if os.path.isfile(run_state_path(suggestion)) or os.path.isdir(run_dir(suggestion)):
            typer.echo(f"{target}: canonical form {suggestion!r} already exists -- refusing to overwrite, fix manually")
            continue
        if dry_run:
            typer.echo(f"{target} -> {suggestion} (dry run, no changes made)")
            continue
        registered = os.path.isfile(run_state_path(target))
        references = _rename_run(target, suggestion)
        typer.echo(f"{target} -> {suggestion}: {run_dir(suggestion)}")
        if not registered:
            typer.echo(
                f"NOTE: {suggestion} has no run.json — register it with: "
                f"shepherd run init {suggestion}",
                err=True,
            )
        _report_dangling_references(target, references)


@app.command("show")
def show_cmd(
    run: str = typer.Argument(...),
    json_flag: bool = typer.Option(False, "--json", help="Emit the raw run.json document."),
) -> None:
    """Print one run's state."""
    state, applied = _load_with_migrations_or_fail(run)
    if json_flag:
        typer.echo(json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True))
        return
    if applied:
        typer.echo(f"(normalized: {', '.join(applied)})")
    typer.echo(f"run: {state.run}")
    typer.echo(f"kind: {state.kind}")
    typer.echo(f"status: {state.status}")
    typer.echo(f"branch: {state.branch or '-'}")
    typer.echo(f"base: {state.base or '-'}")
    typer.echo(f"seed: {state.seed or '-'}")
    typer.echo(f"plan: {state.plan or '-'}")
    typer.echo(f"lanes: {len(state.lanes)}")
    for lane in state.lanes:
        pending = " PENDING-MERGE" if lane.accepted_commit and not lane.merged else ""
        typer.echo(f"  {lane.id}: {lane.state}{pending}")


@app.command("list")
def list_cmd(
    json_flag: bool = typer.Option(False, "--json", help="Emit a JSON array of run ids."),
) -> None:
    """List runs (directories under runs/ carrying a run.json)."""
    runs = list_runs()
    if json_flag:
        typer.echo(json.dumps(runs))
        return
    for name in runs:
        typer.echo(name)


@app.command("migrate")
def migrate_cmd(
    run: str | None = typer.Argument(None, help="Run id to migrate (omit when using --all)."),
    all_runs: bool = typer.Option(False, "--all", help="Migrate every run under runs/."),
) -> None:
    """#247: rewrite one (or every) run.json in canonical form.

    Loads tolerantly (:func:`shepherd_cli.models_run.normalize_run_document`)
    then saves, so the file becomes loadable by a strict reader. Prints the
    migrations applied per run; idempotent — a second run reports none.
    """
    if bool(run) == all_runs:
        _fail("pass exactly one of <run> or --all", 2)
    targets: list[str] = list_runs() if all_runs else [run]  # type: ignore[list-item]
    if all_runs and not targets:
        typer.echo("no runs to migrate")
        return
    for target in targets:
        state, applied = _load_with_migrations_or_fail(target)
        path = save_run(state)
        note = ", ".join(applied) if applied else "no changes"
        typer.echo(f"migrated {target} ({note}): {path}")


@app.command("set")
def set_cmd(
    run: str = typer.Argument(...),
    status: str = typer.Option("", "--status", help=f"One of: {', '.join(RUN_STATUSES)}."),
    seed: str = typer.Option("", "--seed", help="Repo-relative seed path."),
    plan: str = typer.Option("", "--plan", help="Repo-relative plan path."),
) -> None:
    """Update run fields (only the provided ones)."""
    if not (status or seed or plan):
        _fail("nothing to set (pass --status, --seed, and/or --plan)", 2)
    if status and status not in RUN_STATUSES:
        _fail(f"invalid --status: {status} (valid: {', '.join(RUN_STATUSES)})", 2)
    state = _load_or_fail(run)
    if status:
        state.status = status
    if seed:
        state.seed = seed
    if plan:
        state.plan = plan
    save_run(state)
    typer.echo(f"updated {run}")


@lane_app.command("add")
def lane_add_cmd(
    run: str = typer.Argument(...),
    lane: str = typer.Argument(...),
    plan: str = typer.Option("", "--plan", help="Repo-relative lane plan path."),
    worktree: str = typer.Option("", "--worktree"),
    branch: str = typer.Option("", "--branch"),
) -> None:
    """Register one lane (scaffolds ``lanes/<lane>/``)."""
    state = _load_or_fail(run)
    try:
        validate_id(lane, what="lane")
    except RunIdError as exc:
        _fail(str(exc), 2)
    if state.lane(lane) is not None:
        _fail(f"lane already registered: {lane}", 2)
    os.makedirs(lane_dir(run, lane), exist_ok=True)
    default_plan = os.path.join("lanes", lane, "plan.md")
    state.lanes.append(LaneState(id=lane, plan=plan or default_plan, worktree=worktree, branch=branch))
    save_run(state)
    typer.echo(f"lane {lane} registered in {run}")


@lane_app.command("set")
def lane_set_cmd(
    run: str = typer.Argument(...),
    lane: str = typer.Argument(...),
    state_value: str = typer.Option(..., "--state", help=f"One of: {', '.join(LANE_STATES)}."),
) -> None:
    """Set one lane's state."""
    if state_value not in LANE_STATES:
        _fail(f"invalid --state: {state_value} (valid: {', '.join(LANE_STATES)})", 2)
    state = _load_or_fail(run)
    lane_row = state.lane(lane)
    if lane_row is None:
        _fail(f"no such lane: {lane} in run {run}", 5)
    lane_row.state = state_value
    save_run(state)
    typer.echo(f"lane {lane} -> {state_value}")


@wave_app.command("accept")
def wave_accept_cmd(
    run: str = typer.Argument(...),
    lane: str = typer.Argument(...),
    commit: str = typer.Option(..., "--commit", help="The WAVE-COMPLETE-accepted commit sha."),
) -> None:
    """Record an accepted-but-unmerged lane commit (#242 ledger, accept side)."""
    if not commit:
        _fail("--commit must be non-empty", 2)
    state = _load_or_fail(run)
    lane_row = state.lane(lane)
    if lane_row is None:
        _fail(f"no such lane: {lane} in run {run}", 5)
    lane_row.accepted_commit = commit
    lane_row.merged = False
    save_run(state)
    typer.echo(f"accepted {lane} @ {commit}")


@wave_app.command("merged")
def wave_merged_cmd(
    run: str = typer.Argument(...),
    lane: str = typer.Argument(...),
) -> None:
    """Mark one lane's accepted commit boundary-merged (#242 ledger, merge side)."""
    state = _load_or_fail(run)
    lane_row = state.lane(lane)
    if lane_row is None:
        _fail(f"no such lane: {lane} in run {run}", 5)
    if not lane_row.accepted_commit:
        _fail(f"lane {lane} has no accepted commit to mark merged", 2)
    lane_row.merged = True
    save_run(state)
    typer.echo(f"merged {lane} @ {lane_row.accepted_commit}")


def _plan_text_or_empty(run: str) -> str:
    """The run's ``plan.md`` text, or ``""`` when it doesn't exist yet.

    ``wave_pending_cmd``'s ledger-completeness check
    (:meth:`~shepherd_cli.models_run.RunState.missing_declared_lanes`)
    reads this to learn which lanes the run's plan actually declares. A
    run whose plan predates or omits the ``## Lane projection`` section --
    or has no ``plan.md`` at all yet (``run init`` scaffolds the run
    before ``plan.md`` is written) -- has nothing declared to check
    completeness against, so absence here is silent, never an error.

    Args:
        run: The run identifier (already validated by the caller's
            :func:`_load_or_fail`).

    Returns:
        The file's text, or ``""``.
    """
    path = os.path.join(run_dir(run), "plan.md")
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


@wave_app.command("pending")
def wave_pending_cmd(
    run: str = typer.Argument(...),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Assert the pending set is empty AND the ledger is lane-complete.

    #1 GATE-EXIT-CODE-MISMATCH (DF-63): exit 6 fires on EITHER an
    accepted-but-unmerged lane (the original #242 pending-set check) OR a
    lane the plan's ``## Lane projection`` table declares but ``run.json``
    never registered at all -- an omitted ``run lane add`` used to make
    this gate GREENER, not redder, because a lane with zero ledger rows is
    trivially "not pending". Absence is not acceptance.
    """
    state = _load_or_fail(run)
    pending = state.pending_merges()
    missing = state.missing_declared_lanes(_plan_text_or_empty(run))
    if json_flag:
        typer.echo(
            json.dumps(
                {
                    "pending": [{"lane": p.id, "commit": p.accepted_commit} for p in pending],
                    "missing_lanes": missing,
                    "ok": not pending and not missing,
                }
            )
        )
    else:
        for row in pending:
            typer.echo(f"{row.id}\t{row.accepted_commit}")
        for lane_id in missing:
            typer.echo(f"{lane_id}\tMISSING-DECLARED-LANE")
    if pending or missing:
        raise typer.Exit(6)


# --------------------------------------------------------------------------
# #261/#262 — audit-ledger custody + step/verdict join (v6.4.3).
#
# Every rule (grammar, last-wins resolution, the join, the divergence
# compare) lives in :mod:`shepherd_cli.verdicts` — a pure-function module
# with no typer/subprocess/sys.exit of its own (see its own module
# docstring). Everything below is a THIN wrapper: enumerate
# ``git worktree list --porcelain`` (verdicts.py deliberately never touches
# git), read the plain files verdicts.py is handed as text, and translate
# its return values into stdout/stderr/exit codes — matching every other
# command in this module's own ``_fail()``/exit-code idiom exactly.
# --------------------------------------------------------------------------
def _find_active_run(workdir: str | None = None) -> str | None:
    """The ACTIVE run: the mtime-newest ``runs/*/run.json`` with ``status: "executing"``.

    Mirrors ``hooks/scripts/_lib.sh``'s ``active_run_dir()`` exactly (same
    "most-recently-modified run.json, first one whose status is executing
    wins" resolution) so ``shepherd run ledger path``/``ledger check``
    resolve the SAME "current run" a session's own precompact snapshot
    already infers, when ``<run>`` is omitted (spec section 1.1/1.2's
    ``[<run>]`` bracket notation).

    Args:
        workdir: Optional workdir override (tests).

    Returns:
        The run id, or None when ``runs/`` doesn't exist, is empty, or no
        run.json parses with ``status == "executing"``.
    """
    root = runs_root(workdir)
    if not os.path.isdir(root):
        return None
    candidates: list[tuple[float, str, str]] = []
    for name in os.listdir(root):
        path = os.path.join(root, name, "run.json")
        if os.path.isfile(path):
            candidates.append((os.path.getmtime(path), name, path))
    candidates.sort(key=lambda row: row[0], reverse=True)
    for _mtime, name, path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("status") == "executing":
            return name
    return None


def _resolve_run_arg(run: str | None) -> str:
    """Resolve an OPTIONAL ``<run>`` CLI argument to a concrete run id.

    Args:
        run: The literal CLI argument, or None when omitted.

    Returns:
        ``run`` unchanged when given.

    Raises:
        typer.Exit: Code 2 (usage — "which run?" is unresolvable, the same
            class of error as ``run migrate``'s "pass exactly one of <run>
            or --all") when ``run`` is None and :func:`_find_active_run`
            finds no active run either.
    """
    if run is not None:
        return run
    active = _find_active_run()
    if active is None:
        _fail(
            "no <run> given and no active run found (a runs/*/run.json with "
            'status: "executing") -- pass <run> explicitly',
            2,
        )
        raise AssertionError("unreachable")  # _fail always raises
    return active


def _list_worktrees() -> list[str]:
    """Every worktree path from ``git worktree list --porcelain``, primary first.

    Spec section 1.2: "the first entry is the primary" — trusted verbatim
    from git's own listing order, never re-derived. Runs from the CLI
    process's own cwd; git worktree metadata is shared via the common
    ``.git`` dir, so this returns the SAME full list regardless of which
    worktree (primary or linked) that cwd happens to be inside.

    Returns:
        Worktree paths in git's own listing order (primary first). Empty
        if ``git`` is unavailable, the cwd is not inside a repo, or the
        command otherwise fails.
    """
    try:
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [line[len("worktree ") :] for line in proc.stdout.splitlines() if line.startswith("worktree ")]


def _current_worktree_root() -> str | None:
    """The CURRENT worktree's own root (``git rev-parse --show-toplevel``).

    Deliberately NOT :func:`shepherd_cli.resolution.resolve_repo_root`,
    which always resolves to the PRIMARY worktree even from inside a
    linked one (#221/#231) — this function exists precisely to get the
    OTHER answer, the linked worktree's own checkout root, so
    :func:`_worktree_local_ledger_candidate` can compute where a
    hand-composed relative ledger path would actually land.

    Returns:
        The absolute worktree root, or None outside a git repo / on any
        git failure.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def _worktree_local_ledger_candidate(run: str) -> str | None:
    """Where a NAIVE, hand-composed relative ledger path would land from here.

    Spec section 1: the exact wrong path an agent might compose by
    mistake, ``<current-worktree-root>/<namespace-basename>/runs/<run>/
    auditor-verdicts.txt`` — the ``ledger path --check`` divergence-risk
    signal, never an actual read/write target. Uses the RESOLVED
    namespace basename (``os.path.basename(resolve_workdir())``), never a
    hardcoded ``.shepherd``, so a project scaffolded with ``--artifacts``
    (or any other workdir override) still gets the right candidate.

    Args:
        run: The run id (already validated by the caller).

    Returns:
        None when the cwd is not inside a linked worktree at all (nothing
        to warn about); otherwise the candidate path (need not exist —
        the caller checks that).
    """
    if not in_subworktree():
        return None
    current_root = _current_worktree_root()
    if current_root is None:
        return None
    basename = os.path.basename(resolve_workdir())
    return os.path.join(current_root, basename, "runs", run, verdicts.LEDGER_FILENAME)


@ledger_app.command("path")
def ledger_path_cmd(
    run: str | None = typer.Argument(None, help="Run id. Omit to resolve the active (status=executing) run."),
    check: bool = typer.Option(
        False,
        "--check",
        help="Exit 3 if cwd is inside a linked worktree AND a local, worktree-relative ledger copy also exists there.",
    ),
) -> None:
    """Print the run's audit ledger's ABSOLUTE, PRIMARY-checkout path (spec section 1.1).

    THE verb every agent should use instead of hand-composing a
    ``.shepherd/runs/<run>/auditor-verdicts.txt``-shaped relative path,
    which resolves to a divorced physical copy from inside a linked
    worktree (#261). Delegates entirely to
    :func:`shepherd_cli.verdicts.ledger_path` — never re-composes the path
    itself.
    """
    resolved_run = _resolve_run_arg(run)
    try:
        path = verdicts.ledger_path(resolved_run)
    except RunIdError as exc:
        _fail(str(exc), 2)
        return
    typer.echo(path)

    if check:
        candidate = _worktree_local_ledger_candidate(resolved_run)
        if candidate is not None and os.path.isfile(candidate):
            typer.echo(
                f"ERROR: divergent local ledger copy at {candidate} -- this is NOT the "
                f"canonical ledger; use the absolute path above ({path}) instead (#261)",
                err=True,
            )
            raise typer.Exit(3)


@ledger_app.command("check")
def ledger_check_cmd(
    run: str | None = typer.Argument(None, help="Run id. Omit to resolve the active (status=executing) run."),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """The #261 mechanical worktree-ledger divergence check (spec section 1.2).

    FAILS (exit 7) on any row a linked worktree's local ledger copy holds
    that the PRIMARY lacks -- the destructive case: a lane wrote a verdict
    only its own copy carries, and boundary-merging it could silently drop
    a sibling lane's row. A worktree merely BEHIND the primary (every
    lane's normal state between merges) is NEVER flagged -- a hard
    requirement, enforced entirely by
    :func:`shepherd_cli.verdicts.compare_worktree_ledgers`, which this
    command never re-derives.
    """
    resolved_run = _resolve_run_arg(run)
    try:
        primary_path = verdicts.ledger_path(resolved_run)
    except RunIdError as exc:
        _fail(str(exc), 2)
        return
    if not os.path.isfile(primary_path):
        _fail(f"no ledger for run {resolved_run} (expected {primary_path})", 5)
        return

    with open(primary_path, "r", encoding="utf-8") as handle:
        primary_text = handle.read()

    basename = os.path.basename(resolve_workdir())
    worktrees: dict[str, str | None] = {}
    for wt_path in _list_worktrees()[1:]:  # [0] is the primary -- never compared against itself.
        candidate = os.path.join(wt_path, basename, "runs", resolved_run, verdicts.LEDGER_FILENAME)
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as handle:
                worktrees[wt_path] = handle.read()
        else:
            worktrees[wt_path] = None  # absent copy is fine, not a finding.

    divergences = verdicts.compare_worktree_ledgers(primary_text, worktrees)

    if json_flag:
        typer.echo(
            json.dumps(
                {
                    "run": resolved_run,
                    "divergences": [d.model_dump(mode="json") for d in divergences],
                    "ok": not divergences,
                }
            )
        )
    else:
        for divergence in divergences:
            typer.echo(f"{divergence.worktree}\t{divergence.row}")

    if divergences:
        raise typer.Exit(7)


@wave_app.command("verify")
def wave_verify_cmd(
    run: str = typer.Argument(...),
    wave: int | None = typer.Option(None, "--wave", help="Filter to one wave number."),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """The #262 step/verdict join (spec section 4) -- what the ledger alone cannot show.

    Enumerates every ``W-L-S`` step id from ``{run_dir}/lanes/*/plan.md``
    and joins it against the parsed ledger
    (:func:`shepherd_cli.verdicts.join`), surfacing ``NO-VERDICT`` /
    ``UNRESOLVED-VERDICT`` / ``ORPHAN-VERDICT`` / ``MALFORMED-ROW``
    findings. Prints the per-step table, then any findings; exit 6 (the
    mechanical stop, matching ``wave pending``'s exit-6 idiom) when any
    finding is present.
    """
    try:
        run_directory = run_dir(run)
    except RunIdError as exc:
        _fail(str(exc), 2)
        return

    try:
        steps = verdicts.enumerate_plan_steps(run_directory)
    except FileNotFoundError as exc:
        _fail(str(exc), 5)
        return

    if wave is not None:
        steps = [step for step in steps if step.wave == wave]

    ledger_file = verdicts.ledger_path(run)
    ledger_text = ""
    if os.path.isfile(ledger_file):
        with open(ledger_file, "r", encoding="utf-8") as handle:
            ledger_text = handle.read()
    rows, malformed = verdicts.parse_ledger(ledger_text)
    if wave is not None:
        rows = [row for row in rows if row.wave == wave]

    result = verdicts.join(steps, rows, malformed=malformed)

    if json_flag:
        typer.echo(
            json.dumps(
                {
                    "run": run,
                    "wave": wave,
                    "steps": [step.model_dump(mode="json") for step in result.steps],
                    "findings": [finding.model_dump(mode="json") for finding in result.findings],
                    "ok": result.ok,
                }
            )
        )
    else:
        for step_result in result.steps:
            typer.echo(f"{step_result.step}\t{step_result.verdict or '-'}\t{step_result.raw or '-'}")
        if result.findings:
            typer.echo("")
            typer.echo("FINDINGS:")
            for finding in result.findings:
                typer.echo(f"{finding.kind}\t{finding.detail}")

    if not result.ok:
        raise typer.Exit(6)


__all__ = ["app"]


@app.command("layout")
def layout_cmd(
    run: str = typer.Argument(..., help="Run id."),
    repair: bool = typer.Option(False, "--repair", help="Create any missing canonical subdirectory."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Verify (and optionally repair) a run's canonical directory layout.

    ``skills/context/references/naming-conventions.md §Run layout`` fixes what
    a run directory contains. Before v6.4.3 only ``lanes/`` was scaffolded and
    the rest materialized as a side effect of activity, so "does this run have
    a ``reports/``" answered "did this sprint dispatch a read-only role", not
    "is this a run" — a layout nothing could rely on.

    Read-only by default so it is safe to run against a live sprint;
    ``--repair`` creates what is missing and creates nothing else. Repair is
    idempotent and never touches files, only directories.

    Exit codes: 0 layout complete (or repaired); 5 run missing; 6 layout
    incomplete and ``--repair`` not given — the mechanical stop, matching
    ``wave pending``/``wave verify``.
    """
    try:
        validate_id(run, what="run")
    except RunIdError as exc:
        _fail(str(exc), 2)
    if not os.path.isfile(run_state_path(run)):
        _fail(f"no such run: {run} (expected {run_state_path(run)})", 5)

    missing = missing_run_subdirs(run)
    created: list[str] = []
    if repair and missing:
        created = scaffold_run_layout(run)
        missing = missing_run_subdirs(run)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "run": run,
                    "run_dir": run_dir(run),
                    "subdirs": list(RUN_SUBDIRS),
                    "missing": missing,
                    "created": created,
                    "tracked_files_present": [
                        f for f in RUN_TRACKED_FILES if os.path.isfile(os.path.join(run_dir(run), f))
                    ],
                    "ok": not missing,
                },
                indent=2,
            )
        )
    else:
        base = run_dir(run)
        for name in RUN_SUBDIRS:
            mark = "missing" if name in missing else ("created" if name in created else "ok")
            typer.echo(f"{name + '/':<12}{mark}")
        present = [f for f in RUN_TRACKED_FILES if os.path.isfile(os.path.join(base, f))]
        typer.echo(f"tracked artifacts: {', '.join(present) if present else '(none yet)'}")
        if created:
            typer.echo(f"repaired: {', '.join(created)}", err=True)

    if missing:
        if not repair:
            typer.echo(
                f"ERROR: layout incomplete ({', '.join(missing)}) — re-run with --repair",
                err=True,
            )
        raise typer.Exit(6)
