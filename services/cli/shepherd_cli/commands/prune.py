"""``shepherd prune`` — outcome-safe workdir + registry GC (bash: ``cmd_prune.sh``).

Native port of ``skills/context/scripts/cmd_prune.sh`` (v6.2.5, first-cut).
**DESTRUCTIVE, HANDLE WITH CARE** — this is the one command group in this
port whose whole job is to move/delete a user's data. The safety contract
this module reproduces byte-for-byte:

1. **Dry-run is the DEFAULT.** Without ``--confirm``, NOTHING is removed —
   the plan is only printed and written to
   ``/tmp/shepherd-prune-<epoch>/plan.csv``.
2. **``--confirm`` is required to actually move anything.** Even then,
   on-disk sweeps MOVE (never permanently delete) targets into that
   ``/tmp`` run dir, preserving the workdir-relative path (so
   ``logs/hooks/foo.jsonl`` lands at ``<run>/logs/hooks/foo.jsonl``, not
   flattened into ``<run>/foo.jsonl`` — a real historical data-loss bug
   the bash test suite (``skills/context/tests/test_prune.sh``) regression
   -guards). Restoring is mechanical: ``mv <run>/<rel> <workdir>/<rel>``.
3. **The snapshot happens BEFORE any removal** — :func:`_sweep_path`
   creates the destination directory and performs the move as one atomic
   step per item; nothing is deleted without first landing in ``run_dir``.
4. **Every DB read is table-guarded.** ``registry rows`` are PREVIEW ONLY
   in this bash version (v6.2.5) — eligible counts are printed, but NO
   ``DELETE`` is ever issued against the registry; a table absent from
   ``sqlite_master`` (a DB that predates that table's migration) is
   skipped with ``skip:table-absent``, never an error. See
   :func:`_count_pre`.
5. **Retention windows**: flag > ``[prune]`` config (``shepherd.toml``,
   local -> project -> XDG precedence) > built-in default
   (``logs_days=60``, ``dispatch_days=30``, ``snapshots_keep=20``).
6. **``--vacuum`` is opt-in and itself gated on ``--confirm``** — in
   dry-run mode it prints a no-op notice instead of touching the DB file.

ARCHITECTURE DEVIATION FROM HARD RULE 7 (no ``db.lifespan()``/Tortoise) —
mirrors :mod:`shepherd_cli.commands.doctor`'s OWN documented deviation, for
the SAME reason
=============================================================================
``cmd_prune.sh`` never calls ``shctx_ensure_migrated``/
``shctx_apply_pending_migrations`` anywhere — its own header comment says
so explicitly: DB-row sweeps are guarded specifically because "this DB may
lack migrations 8-18". The whole point of the table-guard is to report
the registry's ACTUAL on-disk state, including a legitimately-behind
schema, not a self-healed one. ``shepherd_cli.db.lifespan()`` would run
:func:`shepherd_cli.db.ensure_migrated` BEFORE ever touching the DB —
silently applying every pending migration (creating ``heartbeats``,
``session_signals``, etc. out of thin air) before the "is this table even
present" check ever ran, which would make the ``skip:table-absent`` /
"this DB may lack migrations 8-18" case UNREACHABLE for any DB this
command itself just healed. That is exactly wrong for a diagnostic/GC
preview whose job is to describe the registry as it actually is. So, like
``doctor.py``, this module opens a plain, synchronous ``sqlite3.connect()``
for its one DB-preview pass (see :func:`_db_preview`) — never through
Tortoise, no ``db.lifespan()`` — and needs no ``models_prune.py`` mirror
model as a result (nothing here is a Tortoise query to mirror). The
on-disk sweeps (dispatch dirs, logs, snapshots) and ``--vacuum`` need no
ORM/DB access model at all — they are plain filesystem/`sqlite3` PRAGMA
operations.

ADDITIVE, DOCUMENTED DEVIATION — retention-window flags are validated as
integers
=============================================================================
``cmd_prune.sh`` never validates ``--logs-days``/``--dispatch-days``/
``--snapshots-keep`` as integers at all — a non-numeric value produces
THREE DIFFERENT silent bash failure modes depending on which code path
consumes it (``find -mtime +N`` fails silently under its own
``2>/dev/null``, effectively "nothing is aged"; the ``[[ $i -le
$snapshots_keep ]]`` arithmetic comparison can abort the whole script
under ``set -e`` with bash's own "integer expression expected" runtime
error; SQLite's dynamic typing coerces a non-numeric string to ``0`` in
the ``ts < $now_s - $logs_days*86400`` arithmetic, silently changing the
DB-preview predicate's meaning). Reproducing all three inconsistent
behaviors faithfully would add real complexity for a scenario no
documented bash usage ever exercises (the flag's own name says "N").
:func:`_resolve_retention` instead validates once, uniformly: a
non-numeric flag/config value is a hard ``ERROR`` (exit 2) BEFORE any
sweep begins — the correct, safe behavior for a destructive-GC tool's own
threshold inputs, and never silently drops into "nothing is eligible" or
"everything is eligible" for a legitimate window value.

DOCUMENTED APPROXIMATION — on-disk traversal order
=============================================================================
``cmd_prune.sh``'s dispatch-dir loop iterates bash's own glob expansion
order (locale-dependent, effectively sorted for this port's purposes) and
its aged-logs loop iterates GNU ``find``'s own filesystem traversal order
(UNSPECIFIED — verified empirically to NOT be alphabetical: a real ext4
directory produced ``logs/hooks/...`` before ``logs/events-old.jsonl``).
Since eligibility, move outcome, and count are unaffected by traversal
order, and no documented bash behavior depends on a SPECIFIC non-sorted
order, this port visits dispatch-dir names sorted and aged-log files
sorted by full path — deterministic and testable, at the cost of not
byte-for-byte matching an arbitrary filesystem's ``find`` order on a
specific machine. Every eligibility PREDICATE (age, current-branch fence,
snapshot retention count) is reproduced exactly.

Timestamps: epoch SECONDS throughout (``shctx_now`` / ``date +%s`` — the
run-dir suffix, every ``mtime``-day-floor computation, and the
``logs_events.ts`` DB-preview cutoff), matching every other
``_lib.sh``-second-denominated command this port has already established.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import time
import tomllib

import typer

from shepherd_cli.resolution import resolve_db_path, resolve_repo_root, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires full control over -h/--help's own output (the
    # verbatim usage comment block below) and a custom exit-2 unknown-arg
    # error, so Click's own option/help parsing is disabled entirely --
    # mirroring shepherd_cli.commands.doctor/config/sync's identical
    # technique.
    context_settings={
        "help_option_names": [],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Outcome-safe workdir + registry GC, dry-run by default (bash: cmd_prune.sh).",
)

#: Verbatim bash-parity usage text -- `sed -n '2,22p' cmd_prune.sh`'s OWN
#: header comment block, printed raw (`#`/`# ` prefixes included -- `sed`
#: does not strip comment syntax) on `-h`/`--help`, exit 0. No trailing
#: newline: the sole caller prints it via `typer.echo`, which appends
#: exactly one, matching `sed`'s own trailing-newline-terminated output.
_USAGE = (
    "# shctx prune [--confirm] [--vacuum] [--json] [--logs-days=N] [--dispatch-days=N] [--snapshots-keep=N]\n"
    "#\n"
    "# Outcome-safe workdir + registry GC (v6.2.5, first-cut). See skills/context/SKILL.md §Workdir hygiene.\n"
    "#\n"
    "# --dry-run is the DEFAULT: nothing is removed; the plan is printed and written\n"
    "# to /tmp/shepherd-prune-<epoch>/plan.csv. --confirm executes the ON-DISK sweeps\n"
    "# by MOVING targets into that /tmp run dir, which MIRRORS the workdir tree\n"
    "# (reversible — the snapshot IS the move; `mv <run>/<rel-path> <workdir>/<rel-path>`\n"
    "# to restore). Preserving the relative path keeps subdir files (e.g. logs/hooks/)\n"
    "# from colliding on basename and makes the restore mechanical.\n"
    "#\n"
    "# Fence (ALL of): the item's sprint/branch != the CURRENT git branch, a terminal\n"
    "# state, and age >= floor. NEVER touches index_releases, the current sprint's\n"
    "# focus, sprint_metrics, pinned/doctrine memory, unresolved escalations, pending\n"
    "# deliverables, active locks (released_at IS NULL), or active loops.\n"
    "#\n"
    "# On-disk sweeps EXECUTE now (with --confirm):\n"
    "#   - dispatch/<sprint>/ dirs where sprint != current branch, older than dispatch_days\n"
    "#   - logs/events-*.jsonl + logs/hooks/*.jsonl older than logs_days\n"
    "#   - memory/snapshots/precompact-*.json beyond snapshots_keep (newest-first)\n"
    "# DB-row sweeps are PREVIEW-ONLY in v6.2.5 (eligible counts printed, nothing"
)

#: Built-in retention defaults -- `cmd_prune.sh`'s own fallback values
#: (`[[ -n "$logs_days" ]] || logs_days=60`, etc.), used only when NEITHER
#: a `--*-days`/`--snapshots-keep` flag NOR a `[prune].<key>` config entry
#: resolves to a non-empty value.
_DEFAULT_LOGS_DAYS = 60
_DEFAULT_DISPATCH_DAYS = 30
_DEFAULT_SNAPSHOTS_KEEP = 20

#: The six DB-preview checks, in `cmd_prune.sh`'s exact `count_pre` call
#: order: (label, table, where_sql, params_kind, desc). `params_kind` is
#: `"cutoff"` for the one check that binds a computed epoch-seconds cutoff,
#: `"branch"` for the two that bind the current branch name, or `None` for
#: a WHERE clause with no bound parameters.
_DB_CHECKS: tuple[tuple[str, str, str, str | None, str], ...] = (
    ("logs_events", "logs_events", "ts < ?", "cutoff", "observability rows older than {n}d"),
    (
        "crashed_hb",
        "heartbeats",
        "teammate_id IN (SELECT id FROM teammates WHERE status IN ('crashed','retired'))",
        None,
        "heartbeats for crashed/retired teammates",
    ),
    (
        "consumed_sig",
        "session_signals",
        "consumed_at IS NOT NULL",
        None,
        "cross-session signals already consumed",
    ),
    (
        "closed_disc",
        "discovery_findings",
        "sprint_branch IS NOT NULL AND sprint_branch != ?",
        "branch",
        "discovery findings from non-current sprints",
    ),
    (
        "closed_audit",
        "audit_findings",
        "sprint_branch IS NOT NULL AND sprint_branch != ?",
        "branch",
        "audit findings from non-current sprints",
    ),
    ("released_locks", "locks_history", "released_at IS NOT NULL", None, "released locks"),
)

_CSV_HEADER = "category,path_or_table,detail,action"


# --------------------------------------------------------------------------
# Small stdlib helpers (self-contained per this package's module convention
# -- duplicated, not imported, from shepherd_cli.commands.models/dash/etc.).
# --------------------------------------------------------------------------
def _current_sprint() -> str:
    """Return the current git branch name, bash-parity with ``_lib.sh``'s ``current_sprint()``.

    Bash: ``git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown'``.

    Returns:
        The current branch name (stripped), or the literal string
        ``"unknown"`` if ``git`` is unavailable, not a repo, or the
        command otherwise fails.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
        )
    except OSError:
        return "unknown"
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config file paths ``cfg_section_get`` checks, in precedence order.

    Bash parity with ``_lib.sh``'s ``cfg_section_get`` file loop:
    ``.claude/shepherd.local.toml`` (per-key local override) ->
    ``.claude/shepherd.toml`` (project) -> ``$XDG_CONFIG_HOME/shepherd.toml``
    (user global, falling back to ``$HOME/.config`` when
    ``XDG_CONFIG_HOME`` is unset or empty). Duplicated verbatim from
    :mod:`shepherd_cli.commands.models`'s identically-named helper.

    Args:
        repo_root: The resolved repository root.

    Returns:
        The three candidate file paths, in the order they must be tried.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or ""
    if not xdg_config_home:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        xdg_config_home = os.path.join(home, ".config")
    return (
        os.path.join(repo_root, ".claude", "shepherd.local.toml"),
        os.path.join(repo_root, ".claude", "shepherd.toml"),
        os.path.join(xdg_config_home, "shepherd.toml"),
    )


def _cfg_section_get(section: str, key: str, repo_root: str) -> str | None:
    """Read one ``key`` under one ``[section]``, by the shared config precedence.

    Bash parity with ``_lib.sh``'s ``cfg_section_get``: the FIRST file (in
    local -> project -> XDG order) that both exists AND has a non-empty
    value for ``[section].key`` wins. Duplicated from
    :mod:`shepherd_cli.commands.models`'s identically-named helper (small,
    intentional duplication per this package's self-contained-module
    convention).

    Args:
        section: The TOML table name, e.g. ``"prune"``.
        key: The key within that table, e.g. ``"logs_days"``.
        repo_root: The resolved repository root, for locating the local/
            project config files.

    Returns:
        The value as a string (non-string TOML values are coerced via
        ``str()``), or None if no candidate file has a non-empty value for
        this key.
    """
    for path in _config_search_paths(repo_root):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        section_table = data.get(section)
        if not isinstance(section_table, dict):
            continue
        value = section_table.get(key)
        if value is None:
            continue
        value_str = str(value)
        if value_str:
            return value_str
    return None


def _resolve_retention(flag_value: str | None, key: str, default: int, repo_root: str) -> int:
    """Resolve one retention window: flag > ``[prune]`` config > built-in default.

    Bash parity with ``cmd_prune.sh``'s precedence chain:
    ``[[ -n "$logs_days" ]] || logs_days="$(cfg_section_get prune logs_days)";
    [[ -n "$logs_days" ]] || logs_days=60`` (and the analogous two lines for
    ``dispatch_days``/``snapshots_keep``). See the module docstring's
    "ADDITIVE, DOCUMENTED DEVIATION" note for why the resolved value is
    validated as an integer here (bash never validates it at all).

    Args:
        flag_value: The raw ``--logs-days``/``--dispatch-days``/
            ``--snapshots-keep`` value, or None if the flag was not given.
        key: The ``[prune]`` config key to fall back to, e.g.
            ``"logs_days"``.
        default: The built-in default when neither a flag nor a config
            value resolves.
        repo_root: The resolved repository root, for config lookup.

    Returns:
        The resolved retention window, as an int.

    Raises:
        typer.Exit: code 2, with a stderr message, if the resolved value
            (from a flag or config file) is not a valid base-10 integer.
    """
    raw = flag_value if flag_value else _cfg_section_get("prune", key, repo_root)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        typer.echo(f"ERROR: invalid --{key.replace('_', '-')} value: {raw}", err=True)
        raise typer.Exit(code=2) from None


def _mtime_age_days(path: str, now_s: int) -> int | None:
    """Whole days between ``now_s`` and ``path``'s mtime, floor-divided.

    Bash parity with GNU ``find -mtime +N``'s own day-floor computation:
    ``floor((now - mtime) / 86400)``. A path this eligible for ``+N``
    means ``_mtime_age_days(...) > N``.

    Args:
        path: The file or directory to stat.
        now_s: The current time, epoch seconds.

    Returns:
        The floor-divided age in whole days, or None if ``path`` could not
        be stat'd (vanished between listing and stat -- treated as
        ineligible by every caller, mirroring ``find``'s own silent
        ``2>/dev/null`` tolerance of a raced-away path).
    """
    try:
        mtime = int(os.stat(path).st_mtime)
    except OSError:
        return None
    return (now_s - mtime) // 86400


# --------------------------------------------------------------------------
# Argument parsing (bash-parity port of cmd_prune.sh's ``for a in "$@"``
# ``case`` loop).
# --------------------------------------------------------------------------
class _ParsedArgs:
    """The resolved flag state from one ``shepherd prune`` invocation's argv.

    Attributes:
        confirm: True if ``--confirm`` was the LAST confirm/dry-run flag
            given (``--dry-run`` sets this back to False -- plain sequential
            reassignment, bash parity).
        vacuum: True if ``--vacuum`` was given.
        json_out: True if ``--json`` was given.
        logs_days: The raw ``--logs-days=N`` value, or None if not given.
        dispatch_days: The raw ``--dispatch-days=N`` value, or None.
        snapshots_keep: The raw ``--snapshots-keep=N`` value, or None.
    """

    __slots__ = ("confirm", "vacuum", "json_out", "logs_days", "dispatch_days", "snapshots_keep")

    def __init__(self) -> None:
        self.confirm = False
        self.vacuum = False
        self.json_out = False
        self.logs_days: str | None = None
        self.dispatch_days: str | None = None
        self.snapshots_keep: str | None = None


def _parse_args(tokens: list[str]) -> _ParsedArgs:
    """Classify every token, bash-parity with ``cmd_prune.sh``'s ``for a in "$@"`` loop.

    Every token is visited in order; ``--confirm``/``--dry-run`` are plain
    sequential reassignments of the SAME ``confirm`` flag (the LAST one
    given wins, e.g. ``--confirm --dry-run`` resolves to dry-run), matching
    bash's own ``confirm=1``/``confirm=0`` case arms exactly.

    Args:
        tokens: Every token given after ``prune``, in order.

    Returns:
        The resolved :class:`_ParsedArgs`.

    Raises:
        typer.Exit: code 0, after printing :data:`_USAGE` to stdout, on the
            FIRST ``-h``/``--help`` token (bash: ``exit 0`` inside the
            loop's own ``case`` arm -- later tokens are never examined).
            Code 2, after printing bash's exact ``"ERROR: unknown arg:
            <token>"`` stderr message, on the first token matching none of
            the recognized shapes.
    """
    parsed = _ParsedArgs()
    for token in tokens:
        if token == "--confirm":
            parsed.confirm = True
        elif token == "--vacuum":
            parsed.vacuum = True
        elif token == "--json":
            parsed.json_out = True
        elif token == "--dry-run":
            parsed.confirm = False
        elif token.startswith("--logs-days="):
            parsed.logs_days = token[len("--logs-days=") :]
        elif token.startswith("--dispatch-days="):
            parsed.dispatch_days = token[len("--dispatch-days=") :]
        elif token.startswith("--snapshots-keep="):
            parsed.snapshots_keep = token[len("--snapshots-keep=") :]
        elif token in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {token}", err=True)
            raise typer.Exit(code=2)
    return parsed


# --------------------------------------------------------------------------
# On-disk sweep plan (dispatch dirs / aged logs / precompact snapshots).
# --------------------------------------------------------------------------
class _PlanRow:
    """One row of the plan CSV -- mirrors ``add_csv``'s four-column shape.

    Attributes:
        category: ``"dispatch"``/``"logs"``/``"snapshots"`` for an on-disk
            row, or ``"db:<label>"`` for a registry-preview row.
        path_or_table: The absolute on-disk path, or the DB table name.
        detail: A short human-readable eligibility reason.
        action: ``"would-move"``/``"moved"``/``"move-failed"`` for an
            on-disk row, or ``"skip:table-absent"``/``"preview:<n>"`` for a
            registry row.
    """

    __slots__ = ("category", "path_or_table", "detail", "action")

    def __init__(self, category: str, path_or_table: str, detail: str, action: str) -> None:
        self.category = category
        self.path_or_table = path_or_table
        self.detail = detail
        self.action = action


def _sweep_path(
    rows: list[_PlanRow], *, category: str, path: str, detail: str, confirm: bool, wd: str, run_dir: str
) -> None:
    """Record + (with ``confirm``) MOVE one path into ``run_dir``, preserving its workdir-relative path.

    Bash parity with ``cmd_prune.sh``'s ``sweep_path()``: in dry-run mode
    (``confirm=False``), only records ``"would-move"`` -- nothing on disk
    is touched. With ``confirm=True``, creates the destination's parent
    directory under ``run_dir`` (preserving ``path``'s subpath relative to
    ``wd``, e.g. ``logs/hooks/foo.jsonl`` -> ``<run_dir>/logs/hooks/
    foo.jsonl`` -- this is the reversibility contract the module docstring
    describes) and moves the path there. A move failure (permissions, a
    raced-away path, cross-filesystem edge case) is recorded as
    ``"move-failed"`` rather than raising -- bash's own ``mv ... 2>/dev/null``
    tolerance.

    Args:
        rows: The plan accumulator; one :class:`_PlanRow` is appended.
        category: ``"dispatch"``/``"logs"``/``"snapshots"``.
        path: The absolute path to sweep.
        detail: The eligibility reason, e.g. ``"age>30d"``.
        confirm: Whether to actually perform the move.
        wd: The resolved shepherd work directory (for computing the
            workdir-relative destination path).
        run_dir: The ``/tmp/shepherd-prune-<epoch>`` run directory.
    """
    if not confirm:
        rows.append(_PlanRow(category, path, detail, "would-move"))
        return

    prefix = wd.rstrip("/") + "/"
    rel = path[len(prefix) :] if path.startswith(prefix) else path
    dest = os.path.join(run_dir, rel)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(path, dest)
    except (OSError, shutil.Error):
        rows.append(_PlanRow(category, path, detail, "move-failed"))
    else:
        rows.append(_PlanRow(category, path, detail, "moved"))


def _sweep_dispatch(rows: list[_PlanRow], *, wd: str, branch: str, dispatch_days: int, confirm: bool, run_dir: str, now_s: int) -> int:
    """Sweep ``<wd>/dispatch/<sprint>/`` dirs: non-current branch, aged past ``dispatch_days``.

    Bash parity with ``cmd_prune.sh``'s dispatch loop: the CURRENT branch's
    own dispatch dir is NEVER swept (the active-sprint fence), regardless
    of its age. See the module docstring's "DOCUMENTED APPROXIMATION" note
    for why directory names are visited in sorted order here rather than
    bash's own glob-expansion order.

    Args:
        rows: The plan accumulator.
        wd: The resolved shepherd work directory.
        branch: The current git branch (never swept).
        dispatch_days: The resolved ``dispatch_days`` retention window.
        confirm: Whether to actually perform moves.
        run_dir: The ``/tmp/shepherd-prune-<epoch>`` run directory.
        now_s: The current time, epoch seconds.

    Returns:
        The count of eligible (swept, regardless of move success/failure)
        dispatch dirs.
    """
    disp = os.path.join(wd, "dispatch")
    if not os.path.isdir(disp):
        return 0
    count = 0
    try:
        names = sorted(os.listdir(disp))
    except OSError:
        return 0
    for name in names:
        d = os.path.join(disp, name)
        if not os.path.isdir(d):
            continue
        if name == branch:
            continue
        age = _mtime_age_days(d, now_s)
        if age is not None and age > dispatch_days:
            _sweep_path(rows, category="dispatch", path=d, detail=f"sprint={name} age>{dispatch_days}d", confirm=confirm, wd=wd, run_dir=run_dir)
            count += 1
    return count


def _sweep_logs(rows: list[_PlanRow], *, wd: str, logs_days: int, confirm: bool, run_dir: str, now_s: int) -> int:
    """Sweep ``<wd>/logs/events-*.jsonl`` + ``<wd>/logs/**/hooks/*.jsonl``, aged past ``logs_days``.

    Bash parity with ``cmd_prune.sh``'s ``find "$logsdir" -type f \\(
    -name 'events-*.jsonl' -o -path '*/hooks/*.jsonl' \\) -mtime
    +"$logs_days"``. See the module docstring's "DOCUMENTED APPROXIMATION"
    note for the traversal-order caveat.

    Args:
        rows: The plan accumulator.
        wd: The resolved shepherd work directory.
        logs_days: The resolved ``logs_days`` retention window.
        confirm: Whether to actually perform moves.
        run_dir: The ``/tmp/shepherd-prune-<epoch>`` run directory.
        now_s: The current time, epoch seconds.

    Returns:
        The count of eligible (swept) log files.
    """
    logsdir = os.path.join(wd, "logs")
    if not os.path.isdir(logsdir):
        return 0
    candidates: list[str] = []
    for root, _dirs, files in os.walk(logsdir):
        for fname in files:
            full = os.path.join(root, fname)
            is_events = fname.startswith("events-") and fname.endswith(".jsonl")
            is_hooks = full.endswith(".jsonl") and (f"{os.sep}hooks{os.sep}" in full)
            if is_events or is_hooks:
                candidates.append(full)
    count = 0
    for f in sorted(candidates):
        age = _mtime_age_days(f, now_s)
        if age is not None and age > logs_days:
            _sweep_path(rows, category="logs", path=f, detail=f"age>{logs_days}d", confirm=confirm, wd=wd, run_dir=run_dir)
            count += 1
    return count


#: Every directory ``_sweep_snapshots`` considers, canonical first. Retention
#: is applied across the UNION, not per-directory: keeping newest-N in each of
#: three directories independently would retain up to 3N snapshots during the
#: v6.4.4 transition, which is not what ``snapshots_keep`` means.
_SNAPSHOT_DIRS: tuple[tuple[str, ...], ...] = (
    ("cache", "snapshots"),   # canonical (v6.4.4)
    ("memory", "snapshots"),  # retired (v6.1.3) — see naming-conventions.md
    ("snapshots",),           # retired (pre-v6.1.3)
)


def _sweep_snapshots(rows: list[_PlanRow], *, wd: str, snapshots_keep: int, confirm: bool, run_dir: str) -> int:
    """Sweep ``<wd>/cache/snapshots/precompact-*.json`` beyond the newest-N.

    Bash parity with ``cmd_prune.sh``'s ``ls -t "$snapdir"/precompact-*.json``
    (newest-first) loop: the ``snapshots_keep`` most-recently-modified files
    survive; everything older is eligible.

    v6.4.4 moved the snapshot directory from ``memory/snapshots`` to
    ``cache/snapshots`` (``memory/`` is retired — see
    ``naming-conventions.md §One knowledge silo``). Both retired locations are
    still swept so an un-migrated project's old snapshots are still subject to
    retention rather than accumulating forever, and mtime ordering runs over
    the union so ``snapshots_keep`` keeps N snapshots total, not N per
    directory.

    Args:
        rows: The plan accumulator.
        wd: The resolved shepherd work directory.
        snapshots_keep: The resolved ``snapshots_keep`` retention count.
        confirm: Whether to actually perform moves.
        run_dir: The ``/tmp/shepherd-prune-<epoch>`` run directory.

    Returns:
        The count of eligible (swept) snapshot files.
    """
    dated: list[tuple[str, float]] = []
    for parts in _SNAPSHOT_DIRS:
        snapdir = os.path.join(wd, *parts)
        if not os.path.isdir(snapdir):
            continue
        for path in glob.glob(os.path.join(snapdir, "precompact-*.json")):
            try:
                dated.append((path, os.stat(path).st_mtime))
            except OSError:
                continue
    if not dated:
        return 0
    # Secondary sort on path keeps the order total (and the plan output
    # stable) when two snapshots share an mtime — common on fast filesystems
    # with coarse timestamp granularity.
    dated.sort(key=lambda pair: (-pair[1], pair[0]))
    count = 0
    for index, (path, _mtime) in enumerate(dated, start=1):
        if index <= snapshots_keep:
            continue
        _sweep_path(rows, category="snapshots", path=path, detail=f"beyond newest-{snapshots_keep}", confirm=confirm, wd=wd, run_dir=run_dir)
        count += 1
    return count


# --------------------------------------------------------------------------
# DB-row eligibility preview (plain sqlite3 -- see module docstring's
# ARCHITECTURE DEVIATION note for why this never uses Tortoise/db.lifespan).
# --------------------------------------------------------------------------
class _DbPreviewRow:
    """One resolved registry-preview row -- both its CSV shape and its display shape.

    Attributes:
        label: The check's short label, e.g. ``"logs_events"``.
        table: The backing table name.
        csv_detail: The ``detail`` field written to the plan CSV -- the
            BARE description, with no ``"(table absent)"`` suffix even
            when the table is missing (bash parity: ``add_csv``'s ``$desc``
            argument is never suffixed; only the text/md-render-only
            ``db_rows`` string appends that suffix -- see
            :func:`_render_text`).
        csv_action: ``"skip:table-absent"`` or ``"preview:<n>"``/
            ``"preview:?"``, written to the plan CSV.
        display_n: The count as displayed in text/md mode: ``"n/a"`` when
            the table is absent, ``"?"`` on a query error, else the count
            as a string.
        display_detail: The description as displayed in text/md mode --
            WITH the ``" (table absent)"`` suffix when the table is
            missing (bash parity: the ``db_rows`` string bash's own
            text-render loop reads).
    """

    __slots__ = ("label", "table", "csv_detail", "csv_action", "display_n", "display_detail")

    def __init__(self, label: str, table: str, csv_detail: str, csv_action: str, display_n: str, display_detail: str) -> None:
        self.label = label
        self.table = table
        self.csv_detail = csv_detail
        self.csv_action = csv_action
        self.display_n = display_n
        self.display_detail = display_detail


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Whether ``table`` is a real table in ``sqlite_master``.

    Args:
        conn: An open sqlite3 connection.
        table: The table name to check (a fixed constant from
            :data:`_DB_CHECKS`, never user input).

    Returns:
        True if a row exists in ``sqlite_master`` with ``type='table'``
        and this exact name.
    """
    row = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row is not None and row[0])


def _count_pre(conn: sqlite3.Connection, *, label: str, table: str, where_sql: str, params: tuple[object, ...], desc: str) -> _DbPreviewRow:
    """Run one bash-parity ``count_pre`` check: table-guarded eligibility count.

    Bash parity with ``cmd_prune.sh``'s ``count_pre()``: checks
    ``sqlite_master`` first (never queries a table that might not exist);
    a genuinely absent table is ``skip:table-absent`` (never an error). A
    present table whose count query itself fails (e.g. a column the WHERE
    clause references is missing under an even-more-partial schema) falls
    back to ``"?"``, mirroring bash's ``|| echo '?'``.

    Args:
        conn: An open sqlite3 connection.
        label: The check's short label, e.g. ``"logs_events"``.
        table: The backing table name (a fixed constant, never user
            input -- safe to interpolate into the SQL text below).
        where_sql: The WHERE clause (fixed constant text with ``?``
            placeholders).
        params: Bound parameters for ``where_sql``.
        desc: The human-readable eligibility description.

    Returns:
        The resolved :class:`_DbPreviewRow`.
    """
    if not _table_exists(conn, table):
        return _DbPreviewRow(label, table, desc, "skip:table-absent", "n/a", f"{desc} (table absent)")
    try:
        row = conn.execute(f"SELECT count(*) FROM {table} WHERE {where_sql}", params).fetchone()  # noqa: S608 - fixed table/where allow-list in _DB_CHECKS above, no user input
        n = row[0] if row is not None else 0
    except sqlite3.Error:
        return _DbPreviewRow(label, table, desc, "preview:?", "?", desc)
    return _DbPreviewRow(label, table, desc, f"preview:{n}", str(n), desc)


def _db_preview(db_path: str, *, branch: str, logs_days: int) -> list[_DbPreviewRow]:
    """Run all six bash-parity registry-preview checks, in :data:`_DB_CHECKS` order.

    Args:
        db_path: The resolved database file path (already confirmed to
            exist by the caller).
        branch: The current git branch (bound into the ``closed_disc``/
            ``closed_audit`` checks).
        logs_days: The resolved ``logs_days`` retention window (used to
            compute the ``logs_events`` cutoff).

    Returns:
        Six :class:`_DbPreviewRow`, in :data:`_DB_CHECKS` order.
    """
    now_s = int(time.time())
    cutoff = now_s - logs_days * 86400
    conn = sqlite3.connect(db_path)
    try:
        results: list[_DbPreviewRow] = []
        for label, table, where_sql, params_kind, desc_template in _DB_CHECKS:
            desc = desc_template.format(n=logs_days)
            if params_kind == "cutoff":
                params: tuple[object, ...] = (cutoff,)
            elif params_kind == "branch":
                params = (branch,)
            else:
                params = ()
            results.append(_count_pre(conn, label=label, table=table, where_sql=where_sql, params=params, desc=desc))
        return results
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Plan CSV I/O -- bash parity with cmd_prune.sh's naive, unescaped
# printf-based writer AND its python3-embedded csv.DictReader-based JSON
# emitter (the SAME asymmetry: a field containing a literal comma would
# misalign columns on read-back, exactly like bash's own printf writer
# would produce).
# --------------------------------------------------------------------------
def _write_plan_csv(csv_path: str, rows: list[_PlanRow]) -> None:
    """Write the plan CSV, bash parity with ``printf '%s,%s,%s,%s\\n'`` (no escaping).

    Args:
        csv_path: The destination path (``<run_dir>/plan.csv``).
        rows: Every :class:`_PlanRow`, in insertion order.
    """
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write(_CSV_HEADER + "\n")
        for row in rows:
            fh.write(f"{row.category},{row.path_or_table},{row.detail},{row.action}\n")


def _read_plan_csv(csv_path: str) -> list[dict[str, str]]:
    """Read the plan CSV back via ``csv.DictReader`` -- bash parity with the JSON emitter.

    Args:
        csv_path: The plan CSV to read.

    Returns:
        Every row as a dict keyed by :data:`_CSV_HEADER`'s columns.
    """
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------
# Rendering.
# --------------------------------------------------------------------------
def _render_text(
    *,
    mode: str,
    wd: str,
    branch: str,
    dispatch_days: int,
    n_dispatch: int,
    logs_days: int,
    n_logs: int,
    snapshots_keep: int,
    n_snaps: int,
    db_present: bool,
    db_path: str,
    db_rows: list[_DbPreviewRow],
    confirm: bool,
    total_disk: int,
    run_dir: str,
    csv_path: str,
) -> str:
    """Render the bash-parity plain-text report, mirroring every ``echo``/``printf`` call.

    Args:
        mode: ``"confirm"`` or ``"dry-run"``.
        wd: The resolved shepherd work directory.
        branch: The current git branch.
        dispatch_days: The resolved ``dispatch_days`` window.
        n_dispatch: Eligible dispatch-dir count.
        logs_days: The resolved ``logs_days`` window.
        n_logs: Eligible log-file count.
        snapshots_keep: The resolved ``snapshots_keep`` count.
        n_snaps: Eligible snapshot-file count.
        db_present: Whether the registry DB file exists.
        db_path: The resolved database file path (shown when absent).
        db_rows: The six :class:`_DbPreviewRow` (only rendered when
            ``db_present``).
        confirm: Whether this was a ``--confirm`` run.
        total_disk: ``n_dispatch + n_logs + n_snaps``.
        run_dir: The ``/tmp/shepherd-prune-<epoch>`` run directory.
        csv_path: The plan CSV path.

    Returns:
        The full multi-line report (no trailing newline -- the caller's
        ``typer.echo`` supplies exactly one).
    """
    lines = [
        f"shctx prune — {mode} (workdir={wd}, branch={branch})",
        "",
        "on-disk (executes with --confirm):",
        f"  dispatch dirs (non-current, >{dispatch_days}d):   {n_dispatch}",
        f"  log files (>{logs_days}d):                    {n_logs}",
        f"  precompact snapshots (beyond {snapshots_keep}):     {n_snaps}",
        "",
    ]
    if db_present:
        lines.append("registry rows (PREVIEW ONLY in v6.2.5 — nothing deleted):")
        for row in db_rows:
            lines.append(f"  {row.label:<16} {row.display_n:>6}   {row.display_detail}")
        lines.append("")
    else:
        lines.append(f"registry DB: none at {db_path} (skipped)")
        lines.append("")
    if confirm:
        lines.append(f"MOVED {total_disk} on-disk item(s) into {run_dir} (mirrors the workdir tree; mv a path back to restore).")
    else:
        lines.append(f"DRY-RUN: nothing removed. Re-run with --confirm to move the {total_disk} on-disk item(s) to /tmp.")
    lines.append(f"plan CSV: {csv_path}")
    return "\n".join(lines)


def _render_json(
    *,
    mode: str,
    wd: str,
    branch: str,
    run_dir: str,
    csv_path: str,
    db_present: bool,
    n_dispatch: int,
    n_logs: int,
    n_snaps: int,
) -> str:
    """Render the bash-parity JSON report, re-reading the plan CSV like ``cmd_prune.sh``'s own emitter.

    Bash parity: ``cmd_prune.sh``'s ``--json`` branch shells to an embedded
    ``python3`` script that opens ``$csv`` fresh via ``csv.DictReader`` and
    partitions rows by whether ``category`` starts with ``"db:"`` --
    reproduced here identically (see :func:`_read_plan_csv`) rather than
    reusing the in-memory row list, so any CSV-writer quirk (e.g. a comma
    inside a field misaligning columns) affects both tools identically.

    Args:
        mode: ``"confirm"`` or ``"dry-run"``.
        wd: The resolved shepherd work directory.
        branch: The current git branch.
        run_dir: The ``/tmp/shepherd-prune-<epoch>`` run directory.
        csv_path: The plan CSV path (already written by the caller).
        db_present: Whether the registry DB file exists.
        n_dispatch: Eligible dispatch-dir count.
        n_logs: Eligible log-file count.
        n_snaps: Eligible snapshot-file count.

    Returns:
        The full JSON text (no trailing newline -- the caller's
        ``typer.echo`` supplies exactly one).
    """
    csv_rows = _read_plan_csv(csv_path)
    disk_rows = [r for r in csv_rows if not r["category"].startswith("db:")]
    db_csv_rows = [r for r in csv_rows if r["category"].startswith("db:")]

    payload = {
        "mode": mode,
        "workdir": wd,
        "branch": branch,
        "run_dir": run_dir,
        "csv": csv_path,
        "db_present": db_present,
        "on_disk": {
            "dispatch": n_dispatch,
            "logs": n_logs,
            "snapshots": n_snaps,
            "items": [
                {"category": r["category"], "path": r["path_or_table"], "detail": r["detail"], "action": r["action"]}
                for r in disk_rows
            ],
        },
        "db_preview": [
            {"name": r["category"][3:], "table": r["path_or_table"], "detail": r["detail"], "action": r["action"]}
            for r in db_csv_rows
        ],
    }
    return json.dumps(payload, indent=2)


# --------------------------------------------------------------------------
# --vacuum.
# --------------------------------------------------------------------------
def _run_vacuum(db_path: str, *, confirm: bool, db_present: bool) -> None:
    """Optionally ``PRAGMA wal_checkpoint(TRUNCATE); VACUUM;`` -- opt-in, needs ``--confirm``.

    Bash parity with ``cmd_prune.sh``'s trailing vacuum block, which runs
    UNCONDITIONALLY after the text/JSON report is printed (even in
    ``--json`` mode -- these lines land on stdout AFTER the JSON blob,
    which is a known bash quirk this module reproduces exactly rather than
    "fixing").

    Args:
        db_path: The resolved database file path.
        confirm: Whether ``--confirm`` was given.
        db_present: Whether the registry DB file exists.

    Side Effects:
        Prints ``"vacuum: WAL checkpointed + VACUUM ok"`` to stdout on
        success; ``"vacuum: skipped (DB busy/locked; retry when no
        shepherd process holds it)"`` to STDERR if the PRAGMA/VACUUM
        sequence raises; ``"vacuum: --vacuum requires --confirm (skipped
        in dry-run)"`` to stdout if ``--vacuum`` was given without
        ``--confirm``. Prints nothing at all if ``--vacuum`` was not
        given, or if the registry DB does not exist (bash: the entire
        block is gated on ``vacuum == 1 && db_present == 1``).
    """
    if not db_present:
        return
    if not confirm:
        typer.echo("vacuum: --vacuum requires --confirm (skipped in dry-run)")
        return
    try:
        conn = sqlite3.connect(db_path, isolation_level=None)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("VACUUM;")
        finally:
            conn.close()
    except sqlite3.Error:
        typer.echo("vacuum: skipped (DB busy/locked; retry when no shepherd process holds it)", err=True)
    else:
        typer.echo("vacuum: WAL checkpointed + VACUUM ok")


# --------------------------------------------------------------------------
# Top-level driver.
# --------------------------------------------------------------------------
def _prune_impl(parsed: _ParsedArgs) -> None:
    """Run the full prune plan + (optionally) execute it, bash parity with ``cmd_prune.sh``'s main body.

    NO ``db.lifespan()``/Tortoise anywhere -- see the module docstring's
    "ARCHITECTURE DEVIATION" note. Every DB touch here is a plain,
    synchronous ``sqlite3.connect()``.

    Args:
        parsed: The already-classified :class:`_ParsedArgs`.

    Raises:
        typer.Exit: code 2, if a retention-window flag/config value fails
            integer validation (see :func:`_resolve_retention`). Otherwise
            this function returns normally (bash: unconditional ``exit
            0`` -- even a vacuum failure only writes to stderr, never
            changes the exit code).
    """
    repo_root = resolve_repo_root()
    logs_days = _resolve_retention(parsed.logs_days, "logs_days", _DEFAULT_LOGS_DAYS, repo_root)
    dispatch_days = _resolve_retention(parsed.dispatch_days, "dispatch_days", _DEFAULT_DISPATCH_DAYS, repo_root)
    snapshots_keep = _resolve_retention(parsed.snapshots_keep, "snapshots_keep", _DEFAULT_SNAPSHOTS_KEEP, repo_root)

    wd = resolve_workdir()
    branch = _current_sprint()
    db_path = resolve_db_path()

    run_now = int(time.time())
    run_dir = f"/tmp/shepherd-prune-{run_now}"
    csv_path = os.path.join(run_dir, "plan.csv")
    os.makedirs(run_dir, exist_ok=True)

    mode = "confirm" if parsed.confirm else "dry-run"

    rows: list[_PlanRow] = []
    n_dispatch = _sweep_dispatch(
        rows, wd=wd, branch=branch, dispatch_days=dispatch_days, confirm=parsed.confirm, run_dir=run_dir, now_s=run_now
    )
    n_logs = _sweep_logs(rows, wd=wd, logs_days=logs_days, confirm=parsed.confirm, run_dir=run_dir, now_s=run_now)
    n_snaps = _sweep_snapshots(rows, wd=wd, snapshots_keep=snapshots_keep, confirm=parsed.confirm, run_dir=run_dir)

    db_present = os.path.isfile(db_path)
    db_rows: list[_DbPreviewRow] = []
    if db_present:
        db_rows = _db_preview(db_path, branch=branch, logs_days=logs_days)
        for db_row in db_rows:
            rows.append(_PlanRow(f"db:{db_row.label}", db_row.table, db_row.csv_detail, db_row.csv_action))

    total_disk = n_dispatch + n_logs + n_snaps
    _write_plan_csv(csv_path, rows)

    if parsed.json_out:
        typer.echo(
            _render_json(
                mode=mode,
                wd=wd,
                branch=branch,
                run_dir=run_dir,
                csv_path=csv_path,
                db_present=db_present,
                n_dispatch=n_dispatch,
                n_logs=n_logs,
                n_snaps=n_snaps,
            )
        )
    else:
        typer.echo(
            _render_text(
                mode=mode,
                wd=wd,
                branch=branch,
                dispatch_days=dispatch_days,
                n_dispatch=n_dispatch,
                logs_days=logs_days,
                n_logs=n_logs,
                snapshots_keep=snapshots_keep,
                n_snaps=n_snaps,
                db_present=db_present,
                db_path=db_path,
                db_rows=db_rows,
                confirm=parsed.confirm,
                total_disk=total_disk,
                run_dir=run_dir,
                csv_path=csv_path,
            )
        )

    if parsed.vacuum:
        _run_vacuum(db_path, confirm=parsed.confirm, db_present=db_present)


@app.callback(invoke_without_command=True)
def prune(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="[--confirm] [--vacuum] [--json] [--logs-days=N] [--dispatch-days=N] [--snapshots-keep=N]",
        help="Flags only -- see -h/--help for the full bash-parity usage text.",
    ),
) -> None:
    """Outcome-safe workdir + registry GC. DRY-RUN by default; ``--confirm`` to execute.

    Native port of ``shctx prune`` (``cmd_prune.sh``, v6.2.5). See the
    module docstring for the full safety contract this reproduces.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works like every other
            single-verb group in this package).
        raw: Every token given after ``prune``, in order.

    Raises:
        typer.Exit: code 0 on ``-h``/``--help`` (usage printed, nothing
            else runs). Code 2 on an unrecognized flag, or an invalid
            (non-integer) retention-window value. Otherwise exits 0
            (bash parity: ``exit 0`` unconditionally at the bottom of the
            script, even after a tolerated vacuum failure).
    """
    del ctx
    parsed = _parse_args(raw or [])
    _prune_impl(parsed)


__all__ = ["app"]
