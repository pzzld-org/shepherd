"""``shepherd migrate`` — apply pending schema migrations (bash: ``cmd_migrate.sh``).

Native port of ``skills/context/scripts/cmd_migrate.sh``: a single verb
with two mutually exclusive behaviors, selected by the FIRST one or two
argv tokens (everything else is silently ignored — bash parity, not a
simplification, see :func:`_is_layout_v2` and :func:`_validate_layout_tokens`):

* Bare ``shepherd migrate`` (or any argv that doesn't literally start with
  ``--layout v2`` / ``--layout=v2``, including ``-h``/``--help``, which
  ``cmd_migrate.sh`` never special-cases): the DEFAULT schema-migration
  gap-fill path. Applies every migration file under
  ``skills/context/schema/migrations`` whose 4-digit version is ABSENT
  from ``schema_versions`` (not merely "greater than MAX(version)" — a
  genuine gap a middle migration left behind is caught too), in filename
  order, and prints a one-line summary.
* ``shepherd migrate --layout v2`` or ``shepherd migrate --layout=v2``:
  an OPT-IN, idempotent filesystem-layout migration (legacy top-level
  ``plans/``/``reports/``/``root.db*`` -> the v6.1.0 standard
  ``docs/plans/``/``docs/reports/``/``shepherd.db*`` layout, plus
  scaffolding any missing standard directories). No database access at
  all in this branch.

**WHY THIS COMMAND DOES NOT USE ``db.lifespan()``.** ``shepherd_cli.db``'s
``lifespan()`` already runs :func:`shepherd_cli.db.ensure_migrated` as a
silent, fail-soft self-heal BEFORE any Tortoise query — that is exactly
right for every OTHER command (a caller just wants a current schema, not
a migration report), but it is exactly WRONG for this one: this command's
entire job is to APPLY migrations and NARRATE what it did (the
``shctx migrate: applying NNNN_*.sql`` progress lines on stderr, and the
final ``shctx migrate: applied N migration(s)`` / ``no migrations
pending`` summary on stdout). If this module opened ``db.lifespan()``
first, the silent self-heal would already have applied everything before
this command's own loop ever ran, and every invocation would report
"no migrations pending" regardless of what it actually did. So this
module drives its own synchronous ``sqlite3`` connection directly — the
gap-fill algorithm and tolerated-error handling are mirrored from
:func:`shepherd_cli.db.ensure_migrated` / ``_lib.sh``'s
``shctx_apply_pending_migrations`` (same version-absence gap-fill
semantics, same ``duplicate column``/``already exists`` tolerance) but
re-implemented locally with the narration bash's own script produces, per
hard rule #9's "each command module stays self-contained" and the port
instructions' "schemas + helpers INLINE" directive. No Tortoise import,
no ``models_migrate.py`` — this is a raw-SQL/filesystem command (hard
rule #8), and ``schema_versions`` already has a read-scoped ORM mirror at
:class:`shepherd_cli.models.SchemaVersion` that this module deliberately
does NOT import (a version-absence gap-fill INSERT is a write outside
that model's read-only intended use, and the whole point here is a
synchronous, narrated, single-threaded connection rather than an async
Tortoise one).

**Ordering parity, including the abort-on-hard-failure case.**
``cmd_migrate.sh``'s default branch, verbatim::

    current=$(shctx_sql "SELECT COALESCE(MAX(version),0) FROM schema_versions;")
    applied="$(shctx_apply_pending_migrations)"   # progress -> stderr; count -> stdout
    if (( applied == 0 )); then
      echo "shctx migrate: no migrations pending (at version $current)"
    else
      echo "shctx migrate: applied $applied migration(s)"
    fi

``current`` (the pre-migration ``MAX(version)``) is read FIRST, before any
migration is applied, and is used ONLY in the "no migrations pending"
message — reproduced here by :func:`_read_current_version` running before
:func:`_apply_pending_migrations`. Critically, the whole script runs
under ``set -eu -o pipefail``: if ``shctx_apply_pending_migrations`` hits
a hard sqlite error (anything other than ``duplicate column``/``already
exists``), it prints ``shctx migrate: ERROR applying <fname>: <out>`` to
stderr and returns 1 — and because ``applied="$(...)"`` is a command
substitution used as the LAST command of an assignment, ``set -e``
propagates that nonzero status and the whole script exits 1 IMMEDIATELY,
never reaching the ``if (( applied == 0 ))`` block at all. This module
reproduces that exact control flow: :func:`_apply_pending_migrations`
returns ``(applied_so_far, error_message)``; a non-``None`` error message
means the summary line is NEVER printed and the process exits 1 having
already emitted only the progress + ERROR lines — see :func:`_default_migrate`.

**The ``no migrations dir`` short-circuit is unconditional and comes
first.** ``cmd_migrate.sh``: ``[[ -d "$migdir" ]] || { echo "no
migrations dir"; exit 0; }`` — this check runs BEFORE ``current`` is even
read, so a project with no migrations directory at all never touches the
database, prints exactly ``no migrations dir`` to stdout, and exits 0.
Mirrored by :func:`_default_migrate`'s first branch.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import typer

from shepherd_cli.resolution import find_migrations_dir, resolve_db_path, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity: cmd_migrate.sh has no usage/help output at all -- -h and
    # --help are just unrecognized tokens that fall through to the default
    # schema-migration branch (see the module docstring). help_option_names=[]
    # stops Click from intercepting --help and printing ITS OWN generated
    # help instead, which would NOT be bash parity -- mirrors
    # shepherd_cli.commands.search / sync / models' identical technique.
    context_settings={
        "help_option_names": [],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Apply pending schema migrations, or run the opt-in --layout v2 filesystem migration (bash: cmd_migrate.sh).",
)

#: Matches a shipped migration filename, capturing its 4-digit version --
#: mirrors shepherd_cli.db._MIGRATION_NAME_RE / _lib.sh's glob
#: `[0-9][0-9][0-9][0-9]_*.sql`.
_MIGRATION_NAME_RE = re.compile(r"^(\d{4})_.*\.sql$")

#: sqlite error substrings that mean "a sibling process (or an out-of-band
#: apply) already applied this migration" rather than a real failure --
#: mirrors shctx_apply_pending_migrations' / shepherd_cli.db.ensure_migrated's
#: identical tolerance list.
_TOLERATED_ERROR_MARKERS = ("duplicate column", "already exists")

#: The four standard directories `_layout_v2_migrate` scaffolds when
#: missing, in cmd_migrate.sh's exact source order: `for d in archive
#: scripts templates types cache docs/plans docs/reports`.
_LAYOUT_V2_STANDARD_DIRS = (
    "archive",
    "scripts",
    "templates",
    "types",
    "cache",
    os.path.join("docs", "plans"),
    os.path.join("docs", "reports"),
)

#: The root.db* -> shepherd.db* extension suffixes, in cmd_migrate.sh's
#: exact source order: `for ext in "" "-journal" "-wal" "-shm"`.
_LAYOUT_V2_DB_EXTENSIONS = ("", "-journal", "-wal", "-shm")


# --------------------------------------------------------------------------
# Default branch: schema-migration gap-fill (schema_versions).
# --------------------------------------------------------------------------
def _shipped_migrations(migrations_dir: str) -> list[tuple[int, str]]:
    """List shipped migration files as ``(version, filename)`` pairs, sorted.

    Args:
        migrations_dir: Directory to scan for ``NNNN_*.sql`` files.

    Returns:
        Pairs sorted by filename (equivalently by version, since the
        4-digit zero-padded prefix sorts identically either way) --
        matching the order bash's ``nullglob`` loop visits
        ``$migdir/[0-9][0-9][0-9][0-9]_*.sql`` in. Empty if the directory
        cannot be listed.
    """
    try:
        names = os.listdir(migrations_dir)
    except OSError:
        return []
    shipped = [
        (int(match.group(1)), name)
        for name in names
        if (match := _MIGRATION_NAME_RE.match(name)) is not None
    ]
    shipped.sort(key=lambda pair: pair[1])
    return shipped


def _read_current_version(db_path: str) -> int:
    """``SELECT COALESCE(MAX(version),0) FROM schema_versions;`` -- read BEFORE applying.

    Mirrors ``cmd_migrate.sh``'s ``current=$(shctx_sql ...)`` line, which
    runs before ``shctx_apply_pending_migrations`` and is used only in the
    "no migrations pending" message.

    Args:
        db_path: Path to the sqlite database file.

    Returns:
        The current ``MAX(version)``, or 0 if ``schema_versions`` has no
        rows.

    Raises:
        sqlite3.Error: If the database file cannot be opened or
            ``schema_versions`` does not exist -- mirrors bash's ``sqlite3
            -bail`` erroring out (and, under ``set -e``, aborting the
            whole script) on the same condition; the caller converts this
            into a stderr message + exit 1 rather than reproducing
            sqlite3's own CLI error text verbatim.
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_versions;").fetchone()
    finally:
        conn.close()
    return int(row[0]) if row is not None else 0


def _apply_pending_migrations(db_path: str, migrations_dir: str) -> tuple[int, str | None]:
    """Apply every migration whose version is ABSENT from ``schema_versions``.

    Mirrors ``_lib.sh``'s ``shctx_apply_pending_migrations`` /
    :func:`shepherd_cli.db.ensure_migrated`'s inner loop exactly (same
    gap-fill semantics, same tolerated-error markers), but additionally
    narrates each application with ``typer.echo(..., err=True)`` --
    bash's ``echo "shctx migrate: applying $fname" >&2`` -- which the
    silent :func:`shepherd_cli.db.ensure_migrated` deliberately does not
    do.

    Args:
        db_path: Path to the sqlite database file. Assumed to already
            exist and contain ``schema_versions`` (the caller reads
            :func:`_read_current_version` first, which would already have
            raised on either condition).
        migrations_dir: Directory containing ``NNNN_*.sql`` migration
            files.

    Returns:
        A ``(applied, error)`` pair. ``error`` is ``None`` on full
        success (every pending migration applied or tolerated); otherwise
        it is the exact bash-parity message (``"shctx migrate: ERROR
        applying <fname>: <detail>"``) for the FIRST hard failure
        encountered, and ``applied`` is the count of migrations that
        succeeded strictly before that failure -- mirroring bash's own
        "stop at the first non-tolerated error" behavior (the loop does
        not continue past it).
    """
    shipped = _shipped_migrations(migrations_dir)
    if not shipped:
        return 0, None

    applied = 0
    try:
        conn = sqlite3.connect(db_path, isolation_level=None)
    except sqlite3.Error as exc:
        return 0, f"shctx migrate: ERROR opening db: {exc}"

    try:
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
        except sqlite3.Error as exc:
            return 0, f"shctx migrate: ERROR opening db: {exc}"

        try:
            known_versions = {row[0] for row in conn.execute("SELECT version FROM schema_versions;")}
        except sqlite3.Error as exc:
            return 0, f"shctx migrate: ERROR reading schema_versions: {exc}"

        for version, fname in shipped:
            if version in known_versions:
                continue

            typer.echo(f"shctx migrate: applying {fname}", err=True)

            sql_path = os.path.join(migrations_dir, fname)
            try:
                with open(sql_path, encoding="utf-8") as fh:
                    sql_text = fh.read()
            except OSError as exc:
                return applied, f"shctx migrate: ERROR applying {fname}: {exc}"

            checksum = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
            try:
                conn.executescript(sql_text)
            except sqlite3.Error as exc:
                message = str(exc).lower()
                if not any(marker in message for marker in _TOLERATED_ERROR_MARKERS):
                    return applied, f"shctx migrate: ERROR applying {fname}: {exc}"
                # tolerated: a sibling process already applied this DDL --
                # fall through and still record the schema_versions row.

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES (?, ?, ?);",
                    (version, int(time.time()), checksum),
                )
            except sqlite3.Error as exc:
                return applied, f"shctx migrate: ERROR applying {fname}: {exc}"

            applied += 1
            known_versions.add(version)
    finally:
        conn.close()

    return applied, None


def _default_migrate() -> int:
    """Run the default schema-migration gap-fill branch and print its summary.

    Returns:
        0 on success (whether or not any migration was actually applied)
        or when no migrations directory exists at all; 1 if a hard
        migration failure occurred (the error line has already been
        printed to stderr and the summary line is deliberately never
        printed -- bash parity for the ``set -e`` abort, see the module
        docstring).
    """
    migrations_dir = find_migrations_dir()
    if migrations_dir is None:
        typer.echo("no migrations dir")
        return 0

    db_path = resolve_db_path()
    try:
        current = _read_current_version(db_path)
    except sqlite3.Error as exc:
        typer.echo(f"Error: {exc}", err=True)
        return 1

    applied, error = _apply_pending_migrations(db_path, migrations_dir)
    if error is not None:
        typer.echo(error, err=True)
        return 1

    if applied == 0:
        typer.echo(f"shctx migrate: no migrations pending (at version {current})")
    else:
        typer.echo(f"shctx migrate: applied {applied} migration(s)")
    return 0


# --------------------------------------------------------------------------
# --layout v2 branch: opt-in filesystem layout migration. No database.
# --------------------------------------------------------------------------
def _git_tracked(workdir: str, path: str) -> bool:
    """``git -C "$workdir" ls-files --error-unmatch "$path"`` -- is this file tracked?

    Args:
        workdir: The artifacts root (``git -C`` target directory).
        path: The candidate file's path.

    Returns:
        True if ``git`` is on ``PATH``, ``workdir`` is inside a git repo,
        and ``path`` is a tracked file within it; False otherwise --
        mirrors bash's ``... >/dev/null 2>&1`` exit-code check exactly
        (any failure, including "git not installed", degrades to "not
        tracked" rather than raising).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", workdir, "ls-files", "--error-unmatch", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return proc.returncode == 0


def _mv_file(workdir: str, src: str, dst: str) -> None:
    """Move ``src`` -> ``dst``: ``git mv`` if tracked, else a plain filesystem move.

    Mirrors ``_mv_dir_contents``'s per-file branch in ``cmd_migrate.sh``:
    ``if git -C "$wd" ls-files --error-unmatch "$f" ...; then git -C "$wd"
    mv "$f" "$dst/$base"; else mv "$f" "$dst/$base"; fi``.

    Args:
        workdir: The artifacts root (``git -C`` target directory).
        src: The source file path.
        dst: The destination file path.

    Raises:
        typer.Exit: If ``git mv`` is attempted (the file is tracked) and
            fails -- bash's ``set -e`` would abort the whole script on a
            failing ``git -C "$wd" mv ...`` the same way; reproduced here
            by echoing git's stderr and exiting with git's own return
            code (or 1 if git reported none).
    """
    if _git_tracked(workdir, src):
        proc = subprocess.run(["git", "-C", workdir, "mv", src, dst], capture_output=True, text=True)
        if proc.returncode != 0:
            if proc.stderr:
                typer.echo(proc.stderr, nl=False, err=True)
            raise typer.Exit(code=proc.returncode or 1)
        return
    shutil.move(src, dst)


def _layout_v2_migrate() -> int:
    """Run the ``--layout v2`` filesystem migration and print its progress + summary.

    Native port of ``cmd_migrate.sh``'s ``_layout_v2_migrate``: moves
    legacy top-level ``plans/``/``reports/`` content into
    ``docs/plans/``/``docs/reports/``, renames ``root.db*`` ->
    ``shepherd.db*`` (never clobbering an existing destination file --
    every collision is a SKIP, not an overwrite), and scaffolds any
    missing standard directories with a ``.gitkeep``.

    **Deliberate, documented file-order deviation** (same shape as
    :mod:`shepherd_cli.commands.lint`'s identical note): bash discovers
    each source directory's files via ``find "$src" -maxdepth 1 -type f
    -print0``, which yields filesystem-order (not portable, not sorted,
    not reproducible across filesystems or test runs). This port lists
    and sorts each directory's entries lexicographically instead, so
    output order is deterministic and test-stable -- this changes ONLY
    the order files within one directory are printed/moved in, never
    which files get moved, never a SKIP/moved/renamed/created
    classification, and never the final counts.

    Returns:
        Always 0 -- ``cmd_migrate.sh``'s ``--layout v2`` branch has no
        failure exit code of its own; a hard underlying failure (e.g. a
        tracked-file ``git mv`` failing) propagates via
        :func:`_mv_file`'s own ``typer.Exit`` instead, exactly mirroring
        bash's ``set -e`` abort mid-script.
    """
    workdir = resolve_workdir()
    typer.echo(f"shctx migrate --layout v2: workdir = {workdir}")

    moved = 0
    skipped = 0
    created = 0

    def _mv_dir_contents(src: str, dst: str) -> None:
        nonlocal moved, skipped
        if not os.path.isdir(src):
            return
        try:
            names = sorted(name for name in os.listdir(src) if os.path.isfile(os.path.join(src, name)))
        except OSError:
            return
        if not names:
            return
        os.makedirs(dst, exist_ok=True)
        for name in names:
            src_path = os.path.join(src, name)
            dst_path = os.path.join(dst, name)
            if os.path.exists(dst_path):
                typer.echo(f"  SKIP (dest exists): {src_path} -> {dst_path}")
                skipped += 1
                continue
            _mv_file(workdir, src_path, dst_path)
            typer.echo(f"  moved: {src_path} -> {dst_path}")
            moved += 1

    # 1. plans/* -> docs/plans/ (legacy top-level only).
    plans_src = os.path.join(workdir, "plans")
    plans_dst = os.path.join(workdir, "docs", "plans")
    if os.path.isdir(plans_src) and plans_src != plans_dst:
        _mv_dir_contents(plans_src, plans_dst)

    # 2. reports/* -> docs/reports/.
    reports_src = os.path.join(workdir, "reports")
    reports_dst = os.path.join(workdir, "docs", "reports")
    if os.path.isdir(reports_src) and reports_src != reports_dst:
        _mv_dir_contents(reports_src, reports_dst)

    # 3. root.db* -> shepherd.db* (gitignored runtime files; plain mv only).
    for ext in _LAYOUT_V2_DB_EXTENSIONS:
        src_path = os.path.join(workdir, f"root.db{ext}")
        dst_path = os.path.join(workdir, f"shepherd.db{ext}")
        if not os.path.isfile(src_path):
            continue
        if os.path.exists(dst_path):
            typer.echo(f"  SKIP (dest exists): {src_path} -> {dst_path}")
            skipped += 1
        else:
            shutil.move(src_path, dst_path)
            typer.echo(f"  renamed: {src_path} -> {dst_path}")
            moved += 1

    # 4. Create new standard dirs (idempotent).
    for rel_dir in _LAYOUT_V2_STANDARD_DIRS:
        dir_path = os.path.join(workdir, rel_dir)
        if not os.path.isdir(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            Path(os.path.join(dir_path, ".gitkeep")).touch()
            typer.echo(f"  created: {dir_path}/")
            created += 1

    typer.echo(f"shctx migrate --layout v2: done — moved={moved} skipped={skipped} created={created}")
    return 0


# --------------------------------------------------------------------------
# Flag dispatch (bash: the `for arg in "$@"` validation loop + the two-token
# `--layout v2` / one-token `--layout=v2` check).
# --------------------------------------------------------------------------
def _validate_layout_tokens(tokens: list[str]) -> None:
    """Reject an unsupported ``--layout=<value>``, from ANY position in argv.

    Mirrors ``cmd_migrate.sh``'s validation loop, which scans every token
    in ``"$@"`` (not just the first) BEFORE the two-token/one-token
    ``--layout v2`` check runs::

        for arg in "$@"; do
          case "$arg" in
            --layout=v2|--layout) : ;;
            --layout=*) echo "ERROR: unknown --layout value (only 'v2' supported)" >&2; exit 1 ;;
            v2) : ;;
            *) ;;
          esac
        done

    So e.g. ``shepherd migrate foo --layout=bogus`` errors even though
    ``--layout=bogus`` is not the first token, and ``shepherd migrate
    --layout v2`` / ``--layout=v2`` pass through untouched (handled by
    :func:`_is_layout_v2` afterward). Every other token -- ``v2`` on its
    own, ``--layout`` on its own, or anything else -- is silently
    accepted here (bash's catch-all ``*) ;;``).

    Args:
        tokens: Every argv token given after ``migrate``, in order.

    Raises:
        typer.Exit: Code 1, with the bash-verbatim error message on
            stderr, if any token matches ``--layout=<value>`` for a
            ``<value>`` other than ``v2``.
    """
    for token in tokens:
        if token in ("--layout=v2", "--layout=v3", "--layout"):
            continue
        if token.startswith("--layout="):
            typer.echo("ERROR: unknown --layout value (only 'v2' and 'v3' supported)", err=True)
            raise typer.Exit(code=1)
        # "v2"/"v3" on its own, or any other token: silently ignored (bash `*) ;;`).


def _is_layout_v2(tokens: list[str]) -> bool:
    """Does this argv select the ``--layout v2`` branch?

    Mirrors ``cmd_migrate.sh``'s exact positional check::

        if [[ "${1:-}" == "--layout" && "${2:-}" == "v2" ]] || [[ "${1:-}" == "--layout=v2" ]]; then

    Only the FIRST one or two tokens matter here (unlike
    :func:`_validate_layout_tokens`, which scans every token) -- e.g.
    ``shepherd migrate v2 --layout`` (wrong order) or ``shepherd migrate
    --layout`` alone (missing the ``v2`` second token) both fall through
    to the default schema-migration branch, exactly like bash.

    Args:
        tokens: Every argv token given after ``migrate``, in order.

    Returns:
        True if ``tokens[0] == "--layout" and tokens[1] == "v2"``, or if
        ``tokens[0] == "--layout=v2"``.
    """
    first = tokens[0] if len(tokens) >= 1 else ""
    second = tokens[1] if len(tokens) >= 2 else ""
    return (first == "--layout" and second == "v2") or first == "--layout=v2"


def _is_layout_v3(tokens: list[str]) -> bool:
    """Does this argv select the ``--layout v3`` branch?

    Same positional shape as :func:`_is_layout_v2`, for the v6.4.1
    run-scoped layout migration (NEW in Python; no bash counterpart —
    the bash layer never learned v3).

    Args:
        tokens: Every argv token given after ``migrate``, in order.

    Returns:
        True if ``tokens[0:2] == ["--layout", "v3"]`` or
        ``tokens[0] == "--layout=v3"``.
    """
    first = tokens[0] if len(tokens) >= 1 else ""
    second = tokens[1] if len(tokens) >= 2 else ""
    return (first == "--layout" and second == "v3") or first == "--layout=v3"


#: Filename suffixes _layout_v3_migrate maps into a run directory, in
#: match order: `<slug>.seed.md` -> `runs/<slug>/seed.md`,
#: `<slug>.plan.md` -> `runs/<slug>/plan.md`.
_LAYOUT_V3_RUN_SUFFIXES = ((".seed.md", "seed.md"), (".plan.md", "plan.md"))

#: The run/lane id grammar (mirrors shepherd_cli.models_run.validate_id) —
#: a plans/ filename whose slug falls outside it is SKIPped, never moved
#: to an invalid run directory.
_LAYOUT_V3_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _layout_v3_migrate() -> int:
    """Run the ``--layout v3`` migration: run-scoped artifacts + profiles.

    NEW in v6.4.1 (no bash counterpart). Two idempotent moves, both
    collision-safe (an existing destination is a SKIP, never an
    overwrite), both ``git mv``-aware via :func:`_mv_file`:

    1. Seeds/plans into run directories: ``docs/plans/<slug>.seed.md`` ->
       ``runs/<slug>/seed.md`` and ``docs/plans/<slug>.plan.md`` ->
       ``runs/<slug>/plan.md`` (legacy top-level ``plans/`` handled too).
       A ``<slug>`` outside the run-id grammar (lowercase alphanumerics +
       hyphens) is SKIPped — dated spec-style names stay where they are.
    2. Styles into profile directories: ``styles/<profile>.md`` ->
       ``profiles/<profile>/style.md`` (the v6.4.1 profiles layout;
       ``shepherd_cli.profiles`` reads BOTH shapes, so a partial
       migration is never a breakage). The ``styles`` DB table's
       ``source_path`` values self-heal on the next ``style init``/
       ``edit`` upsert — this branch stays DB-free like ``--layout v2``.

    Historical reports/handoffs under ``docs/`` are NOT moved: their
    date-prefixed names have no deterministic run mapping, and new runs
    write ``runs/{run}/``-scoped reports going forward.

    Returns:
        Always 0 (same contract as :func:`_layout_v2_migrate`).
    """
    workdir = resolve_workdir()
    typer.echo(f"shctx migrate --layout v3: workdir = {workdir}")

    moved = 0
    skipped = 0
    created = 0

    def _mv_into(src_path: str, dst_path: str) -> None:
        nonlocal moved, skipped
        if os.path.exists(dst_path):
            typer.echo(f"  SKIP (dest exists): {src_path} -> {dst_path}")
            skipped += 1
            return
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        _mv_file(workdir, src_path, dst_path)
        typer.echo(f"  moved: {src_path} -> {dst_path}")
        moved += 1

    # 1. Seeds/plans -> runs/<slug>/.
    for plans_rel in (os.path.join("docs", "plans"), "plans"):
        plans_dir = os.path.join(workdir, plans_rel)
        if not os.path.isdir(plans_dir):
            continue
        for name in sorted(os.listdir(plans_dir)):
            src_path = os.path.join(plans_dir, name)
            if not os.path.isfile(src_path):
                continue
            for suffix, target_name in _LAYOUT_V3_RUN_SUFFIXES:
                if not name.endswith(suffix):
                    continue
                slug = name[: -len(suffix)]
                if not _LAYOUT_V3_ID_RE.fullmatch(slug):
                    typer.echo(f"  SKIP (slug outside run-id grammar): {src_path}")
                    skipped += 1
                    break
                _mv_into(src_path, os.path.join(workdir, "runs", slug, target_name))
                break

    # 2. styles/<profile>.md -> profiles/<profile>/style.md.
    styles_dir = os.path.join(workdir, "styles")
    if os.path.isdir(styles_dir):
        for name in sorted(os.listdir(styles_dir)):
            if not name.endswith(".md"):
                continue
            src_path = os.path.join(styles_dir, name)
            if not os.path.isfile(src_path):
                continue
            profile = name[: -len(".md")]
            _mv_into(src_path, os.path.join(workdir, "profiles", profile, "style.md"))

    # 3. Scaffold the v3 standard dirs (idempotent).
    for rel_dir in ("runs", "profiles"):
        dir_path = os.path.join(workdir, rel_dir)
        if not os.path.isdir(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            Path(os.path.join(dir_path, ".gitkeep")).touch()
            typer.echo(f"  created: {dir_path}/")
            created += 1

    typer.echo(f"shctx migrate --layout v3: done — moved={moved} skipped={skipped} created={created}")
    return 0


@app.callback(invoke_without_command=True)
def migrate(
    ctx: typer.Context,
    args: list[str] = typer.Argument(
        None,
        metavar="[--layout v2 | --layout=v2]",
        help=(
            "With no arguments, applies pending schema migrations "
            "(schema_versions gap-fill). --layout v2 (or --layout=v2) instead "
            "runs the opt-in filesystem layout migration. -h/--help and any "
            "other token are silently ignored, falling through to the default "
            "schema-migration branch, exactly like cmd_migrate.sh."
        ),
    ),
) -> None:
    """Apply pending schema migrations, or run the ``--layout v2`` filesystem migration.

    Native port of ``shctx migrate`` (``cmd_migrate.sh``). See the module
    docstring for the full bash-parity contract, including why this
    command drives its own synchronous sqlite3 connection instead of
    ``db.lifespan()``.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works, matching every
            other single-verb command in this package, e.g.
            :mod:`shepherd_cli.commands.search`).
        args: Every token given after ``migrate``, in order.

    Raises:
        typer.Exit: Code 0 on success (``no migrations dir``, ``no
            migrations pending``, ``applied N migration(s)``, or the
            ``--layout v2`` summary line). Code 1 on an unsupported
            ``--layout=<value>`` or a hard migration-apply failure (the
            underlying sqlite error has already been printed to stderr).
            A non-zero ``git mv`` failure inside the ``--layout v2``
            branch propagates git's own exit code via :func:`_mv_file`.
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    tokens = list(args or [])
    _validate_layout_tokens(tokens)

    if _is_layout_v2(tokens):
        exit_code = _layout_v2_migrate()
    elif _is_layout_v3(tokens):
        exit_code = _layout_v3_migrate()
    else:
        exit_code = _default_migrate()

    raise typer.Exit(code=exit_code)


__all__ = ["app"]
