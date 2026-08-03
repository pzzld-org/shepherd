"""``shepherd run`` — run-directory lifecycle Typer sub-app.

NEW surface (v6.4.1) — the deterministic writer for
``.shepherd/runs/{run}/`` state (``shepherd_cli.models_run``). No bash
counterpart existed; run state was previously scattered (graph/ dir,
lock file, latent prose). Subcommands:

- ``run init <run> [--kind sprint|patch-arc] [--branch B] [--base B]`` —
  scaffold ``runs/<run>/`` (+ ``lanes/``) and write the initial
  ``run.json``. Refuses (exit 5) when the run already exists.
- ``run show <run> [--json]`` / ``run list [--json]`` — read side.
- ``run set <run> [--status S] [--seed P] [--plan P]`` — field updates
  (status validated against the closed vocabulary).
- ``run lane add <run> <lane> [--plan P] [--worktree P] [--branch B]`` /
  ``run lane set <run> <lane> --state S`` — lane registration + state.
- ``run wave accept <run> <lane> --commit SHA`` — record a
  WAVE-COMPLETE-accepted commit in the #242 boundary-merge ledger.
- ``run wave merged <run> <lane>`` — mark that lane's accepted commit
  boundary-merged.
- ``run wave pending <run> [--json]`` — the mechanical #242 gate: exit 0
  with no output when the pending set is empty; exit 6 listing
  ``lane<TAB>sha`` rows when accepted-but-unmerged lanes remain. Root
  MUST run this before declaring any wave gate green.

Exit codes: 0 ok; 2 usage/validation; 5 run exists (init) or missing
(everything else); 6 pending merges remain (``wave pending``).
"""

from __future__ import annotations

import json
import os

import typer

from shepherd_cli.models_run import (
    LANE_STATES,
    RUN_STATUSES,
    LaneState,
    RunIdError,
    RunState,
    lane_dir,
    list_runs,
    load_run,
    run_dir,
    run_state_path,
    save_run,
    validate_id,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Run-directory lifecycle: init/show/list/set, lane registry, #242 wave ledger.",
)

lane_app = typer.Typer(no_args_is_help=True, add_completion=False, help="Lane registration + state.")
wave_app = typer.Typer(no_args_is_help=True, add_completion=False, help="#242 boundary-merge ledger.")
app.add_typer(lane_app, name="lane")
app.add_typer(wave_app, name="wave")


def _fail(message: str, code: int) -> None:
    typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(code)


def _load_or_fail(run: str) -> RunState:
    try:
        return load_run(run)
    except RunIdError as exc:
        _fail(str(exc), 2)
    except FileNotFoundError:
        _fail(f"no such run: {run} (expected {run_state_path(run)})", 5)
    except ValueError as exc:
        _fail(f"corrupt run.json for {run}: {exc}", 2)
    raise AssertionError("unreachable")


@app.command("init")
def init_cmd(
    run: str = typer.Argument(..., help="Run id (sprint slug, e.g. v641-dev0)."),
    kind: str = typer.Option("sprint", "--kind", help="sprint | patch-arc."),
    branch: str = typer.Option("", "--branch", help="The run's git branch."),
    base: str = typer.Option("", "--base", help="The run's base branch."),
) -> None:
    """Scaffold ``runs/<run>/`` and write the initial run.json."""
    try:
        validate_id(run, what="run")
    except RunIdError as exc:
        _fail(str(exc), 2)
    if kind not in ("sprint", "patch-arc"):
        _fail(f"invalid --kind: {kind} (sprint | patch-arc)", 2)
    if os.path.isfile(run_state_path(run)):
        _fail(f"run already exists: {run}", 5)
    os.makedirs(os.path.join(run_dir(run), "lanes"), exist_ok=True)
    path = save_run(RunState(run=run, kind=kind, branch=branch, base=base))
    typer.echo(path)


@app.command("show")
def show_cmd(
    run: str = typer.Argument(...),
    json_flag: bool = typer.Option(False, "--json", help="Emit the raw run.json document."),
) -> None:
    """Print one run's state."""
    state = _load_or_fail(run)
    if json_flag:
        typer.echo(json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True))
        return
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


@wave_app.command("pending")
def wave_pending_cmd(
    run: str = typer.Argument(...),
    json_flag: bool = typer.Option(False, "--json"),
) -> None:
    """Assert the pending set is empty (exit 6 with the list when it is not)."""
    state = _load_or_fail(run)
    pending = state.pending_merges()
    if json_flag:
        typer.echo(json.dumps([{"lane": p.id, "commit": p.accepted_commit} for p in pending]))
    else:
        for row in pending:
            typer.echo(f"{row.id}\t{row.accepted_commit}")
    if pending:
        raise typer.Exit(6)


__all__ = ["app"]
