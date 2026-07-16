"""``shepherd lint`` — artifacts-tree naming-convention checker (bash: ``cmd_lint.sh``).

Native port of ``skills/context/scripts/cmd_lint.sh``: a pure filesystem
walk over the project's artifacts tree (``resolve_workdir()`` /
``shctx_artifacts_root``) that checks every ``plans/``, ``reports/``,
``docs/journal/``, and ``logs/`` filename against a fixed set of naming
conventions, printing one ``lint: <path> does not match ...`` line per
violation plus a final ``lint: ok`` / ``lint: FAIL (N violation(s))``
summary.

**NO DATABASE.** ``cmd_lint.sh`` never touches ``sqlite3``/``shctx_sql`` —
it is a bare ``find`` + ``case`` filename check — so this module imports
neither :mod:`shepherd_cli.db` nor any Tortoise model, opens no
``db.lifespan()``, and needs no ``models_lint.py`` mirror-model module (hard
rule #8's "no model module needed for a pure raw-SQL/filesystem command"
applies here in its filesystem form). The only shared import is
:func:`shepherd_cli.resolution.resolve_workdir`, which mirrors ``_lib.sh``'s
``resolve_workdir``/``shctx_artifacts_root`` precedence exactly.

**BASH QUIRK MIRRORED DELIBERATELY — the violation *count* is always 1, not
the real tally.** ``cmd_lint.sh``'s four ``case`` default arms all execute
the literal statement ``fail=1`` (never ``fail=$((fail+1))``) on every
violation, so its closing ``echo "lint: FAIL ($fail violation(s))"`` always
prints ``(1 violation(s))`` the instant ANY violation occurred, no matter
whether there was one violation or fifty — bash never counts past 1. This
is very likely an unintentional bug in the original script, but bash parity
is this port's bar (see the module's HARD RULES), not bash correctness, so
:func:`_lint` reproduces it byte-for-byte: ``fail`` here is a 0/1 flag, not
a running tally, exactly like the bash variable it mirrors. Every individual
``lint: <path> does not match ...`` line is still printed once per real
violation — only the trailing summary line's parenthetical count is capped
at 1.

**Recursive-walk file ORDER is a deliberate, documented deviation.**
``cmd_lint.sh`` discovers files via ``find "$dir" -type f -name '*.md'
-print0`` (``plans``/``reports``/``docs/journal``) or ``find "$dir"
-maxdepth 1 -type f -print0`` (``logs``), both of which yield files in
whatever order the underlying filesystem's directory entries happen to be
stored in — not portable, not sorted, and not reproducible across
filesystems or test runs. :func:`_walk_md_files`/:func:`_list_top_level_files`
below sort every directory's file list lexicographically by full path
instead, so this port's output order is deterministic and test-stable. This
changes ONLY the order violation lines are printed in — never which files
are flagged, never the exit code, and never the (always-1-when-nonzero)
final count.

Every other behavior is exact:

- ``.gitkeep`` is silently skipped in every directory (never counted as a
  violation, never printed).
- ``plans/`` (legacy top-level) AND ``docs/plans/`` (new location) are both
  checked, back-compat, in that order; same for ``reports/``/``docs/reports/``.
- A directory that does not exist on disk contributes zero files (bash:
  ``find`` on a missing dir writes nothing to stdout, its own stderr
  suppressed by ``2>/dev/null``) — never an error, never a violation.
- ``shepherd lint`` takes no meaningful arguments (``cmd_lint.sh`` never
  reads ``$1``/``$@`` at all — the bash dispatcher may pass extra tokens
  through unused), so this module's callback accepts and silently ignores
  any, exactly like bash silently ignoring them.
- Exit code: 0 with ``lint: ok`` on stdout when zero violations; 1 with
  every violation line followed by ``lint: FAIL (1 violation(s))`` on
  stdout when one or more violations were found. Bash never writes lint
  output to stderr, so neither does this module.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from shepherd_cli.resolution import resolve_workdir

app = typer.Typer(
    add_completion=False,
    help="Lint the artifacts tree's plan/report/journal/log filenames against naming conventions (bash: cmd_lint.sh).",
)

#: ``docs/journal/<file>.md`` must be exactly ``YYYY-MM-DD.md`` — bash:
#: ``[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md``.
_JOURNAL_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.md")

#: A ``reports/``/``docs/reports/`` file may alternatively be date-prefixed
#: — bash: ``[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*.md`` (the trailing
#: ``*`` may be empty, e.g. ``2024-01-01-.md`` is accepted by bash's glob
#: too — reproduced here via ``.*`` which also matches the empty string).
_REPORT_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}-.*\.md")

#: ``logs/`` accepted filename shapes — bash's four ``case`` patterns,
#: checked in the SAME order bash's ``case`` would (order is irrelevant
#: here since they're mutually exclusive literal shapes, but kept in
#: source order for readability/traceability against ``cmd_lint.sh``).
_LOG_EVENTS_RE = re.compile(r"events-\d{4}-\d{2}-\d{2}\.jsonl")
_LOG_DAILY_JSONL_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.log\.jsonl")
_LOG_DAILY_MD_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.log\.md")
_LOG_TIMESTAMPED_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.log\.jsonl")


# --------------------------------------------------------------------------
# Filesystem discovery helpers.
# --------------------------------------------------------------------------
def _walk_md_files(directory: Path) -> list[Path]:
    """Recursively list every regular ``*.md`` file under ``directory``, sorted.

    Mirrors bash's ``find "$directory" -type f -name '*.md' -print0
    2>/dev/null`` — used for ``plans/``, ``docs/plans/``, ``reports/``,
    ``docs/reports/``, and ``docs/journal/``, all of which ``cmd_lint.sh``
    walks with no ``-maxdepth`` (i.e. fully recursive, unlike ``logs/``).

    Args:
        directory: The directory to search recursively. Need not exist.

    Returns:
        Every regular ``*.md`` file found under ``directory``, sorted by
        full path string for deterministic output order (see the module
        docstring's file-order deviation note) — an empty list if
        ``directory`` does not exist, matching bash's silent no-op on a
        missing ``find`` target.
    """
    if not directory.is_dir():
        return []
    return sorted((path for path in directory.rglob("*.md") if path.is_file()), key=str)


def _list_top_level_files(directory: Path) -> list[Path]:
    """List every regular file directly inside ``directory`` (no recursion), sorted.

    Mirrors bash's ``find "$directory" -maxdepth 1 -type f -print0
    2>/dev/null`` — used for ``logs/`` only, which is checked one level
    deep (sub-directories like ``logs/hooks/`` are deliberately NOT linted
    at this depth, per ``cmd_lint.sh``'s own comment).

    Args:
        directory: The directory to list. Need not exist.

    Returns:
        Every regular file directly inside ``directory`` (any name, not
        just ``*.md`` — ``logs/`` accepts ``.jsonl`` filenames too),
        sorted by full path string — an empty list if ``directory`` does
        not exist.
    """
    if not directory.is_dir():
        return []
    return sorted((path for path in directory.iterdir() if path.is_file()), key=str)


# --------------------------------------------------------------------------
# Per-section violation checks — each returns the exact
# ``lint: <path> does not match ...`` lines bash's corresponding loop would
# echo, in file order, for that section alone.
# --------------------------------------------------------------------------
def _check_plans(root: Path) -> list[str]:
    """Check ``plans/`` and ``docs/plans/`` filenames.

    Bash parity with ``cmd_lint.sh``'s ``plans_dir`` loop: a file's
    basename must end in ``.seed.md`` or ``.plan.md``; ``.gitkeep`` is
    exempt.

    Args:
        root: The resolved artifacts root (``resolve_workdir()``).

    Returns:
        One ``lint: <path> does not match *.seed.md or *.plan.md`` line
        per non-conforming file, across both directories in bash's own
        order (``plans/`` first, then ``docs/plans/``).
    """
    messages: list[str] = []
    for plans_dir in (root / "plans", root / "docs" / "plans"):
        for path in _walk_md_files(plans_dir):
            name = path.name
            if name == ".gitkeep":
                continue
            if name.endswith(".seed.md") or name.endswith(".plan.md"):
                continue
            messages.append(f"lint: {path} does not match *.seed.md or *.plan.md")
    return messages


def _check_reports(root: Path) -> list[str]:
    """Check ``reports/`` and ``docs/reports/`` filenames.

    Bash parity with ``cmd_lint.sh``'s ``reports_dir`` loop: a file's
    basename must end in ``.phase0.md``, ``.close.md``, or ``.walk.md``,
    OR be date-prefixed (``YYYY-MM-DD-*.md``); ``.gitkeep`` is exempt.

    Args:
        root: The resolved artifacts root (``resolve_workdir()``).

    Returns:
        One ``lint: <path> does not match *.{phase0,close,walk}.md or
        YYYY-MM-DD-*.md`` line per non-conforming file, across both
        directories in bash's own order (``reports/`` first, then
        ``docs/reports/``).
    """
    messages: list[str] = []
    for reports_dir in (root / "reports", root / "docs" / "reports"):
        for path in _walk_md_files(reports_dir):
            name = path.name
            if name == ".gitkeep":
                continue
            if name.endswith(".phase0.md") or name.endswith(".close.md") or name.endswith(".walk.md"):
                continue
            if _REPORT_DATE_RE.fullmatch(name):
                continue
            messages.append(
                f"lint: {path} does not match *.{{phase0,close,walk}}.md or YYYY-MM-DD-*.md"
            )
    return messages


def _check_journal(root: Path) -> list[str]:
    """Check ``docs/journal/`` filenames.

    Bash parity with ``cmd_lint.sh``'s ``docs/journal`` loop: a file's
    basename must be exactly ``YYYY-MM-DD.md``; ``.gitkeep`` is exempt.

    Args:
        root: The resolved artifacts root (``resolve_workdir()``).

    Returns:
        One ``lint: <path> does not match YYYY-MM-DD.md`` line per
        non-conforming file.
    """
    messages: list[str] = []
    for path in _walk_md_files(root / "docs" / "journal"):
        name = path.name
        if name == ".gitkeep":
            continue
        if _JOURNAL_RE.fullmatch(name):
            continue
        messages.append(f"lint: {path} does not match YYYY-MM-DD.md")
    return messages


def _check_logs(root: Path) -> list[str]:
    """Check top-level ``logs/`` filenames.

    Bash parity with ``cmd_lint.sh``'s ``logs`` loop (``-maxdepth 1``, so
    ``logs/hooks/...`` and other sub-directories are never inspected): a
    file's basename must match one of four accepted shapes — legacy
    ``events-YYYY-MM-DD.jsonl``, or one of the newer
    ``YYYY-MM-DD.log.jsonl`` / ``YYYY-MM-DD.log.md`` /
    ``YYYY-MM-DDTHH-MM-SS.log.jsonl`` forms; ``.gitkeep`` is exempt.

    Args:
        root: The resolved artifacts root (``resolve_workdir()``).

    Returns:
        One ``lint: <path> has unrecognized log filename pattern`` line
        per non-conforming file.
    """
    messages: list[str] = []
    for path in _list_top_level_files(root / "logs"):
        name = path.name
        if name == ".gitkeep":
            continue
        if (
            _LOG_EVENTS_RE.fullmatch(name)
            or _LOG_DAILY_JSONL_RE.fullmatch(name)
            or _LOG_DAILY_MD_RE.fullmatch(name)
            or _LOG_TIMESTAMPED_RE.fullmatch(name)
        ):
            continue
        messages.append(f"lint: {path} has unrecognized log filename pattern")
    return messages


# --------------------------------------------------------------------------
# Whole-run driver + Typer wiring.
# --------------------------------------------------------------------------
def _lint(root: Path) -> int:
    """Run every section check, print bash-parity output, and return the exit code.

    Args:
        root: The resolved artifacts root (``resolve_workdir()``).

    Returns:
        0 if no violations were found (after printing ``lint: ok``); 1 if
        one or more violations were found (after printing every violation
        line, in section order — ``plans`` then ``reports`` then
        ``journal`` then ``logs`` — followed by ``lint: FAIL (1
        violation(s))``; see the module docstring for why the count is
        always 1 rather than a real tally, matching bash's own ``fail=1``
        (never incremented) exactly).
    """
    messages: list[str] = []
    messages.extend(_check_plans(root))
    messages.extend(_check_reports(root))
    messages.extend(_check_journal(root))
    messages.extend(_check_logs(root))

    fail = 1 if messages else 0
    for message in messages:
        typer.echo(message)

    if fail == 0:
        typer.echo("lint: ok")
        return 0
    typer.echo(f"lint: FAIL ({fail} violation(s))")
    return 1


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True})
def lint(
    args: list[str] = typer.Argument(
        None,
        hidden=True,
        help="Ignored — cmd_lint.sh reads no arguments; any tokens given are silently accepted for bash-CLI parity.",
    ),
) -> None:
    """Lint the artifacts tree's plan/report/journal/log filenames.

    Native port of ``shctx lint`` (``cmd_lint.sh``). No database, no
    subcommands, no flags — the bash script reads none, and this callback
    mirrors that by accepting (and ignoring) any argv tokens rather than
    erroring on them, exactly like bash's own script, which never
    references ``$1``/``$@``.

    Args:
        args: Any tokens given after ``lint`` on the command line —
            accepted and discarded, never inspected. Declared ``hidden``
            since it exists purely so an accidental extra token (or a
            caller passing bash-style flags out of habit) does not raise
            a Typer/Click usage error where bash would have silently
            ignored it.

    Raises:
        typer.Exit: code 0 with ``lint: ok`` on stdout if the artifacts
            tree has zero naming-convention violations; code 1 (every
            violation line, then a ``lint: FAIL (...)`` summary line, all
            on stdout) if one or more violations were found.
    """
    del args  # bash-parity: cmd_lint.sh never reads its own arguments.
    root = Path(resolve_workdir())
    exit_code = _lint(root)
    raise typer.Exit(code=exit_code)


__all__ = ["app"]
