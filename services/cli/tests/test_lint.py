"""Subprocess parity tests for ``shepherd lint`` (bash: ``cmd_lint.sh``).

Bash parity target: ``skills/context/scripts/cmd_lint.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli lint``),
exactly like ``test_style.py``/``test_export.py`` — never by importing
``shepherd_cli`` into the pytest process.

**NO DATABASE.** ``cmd_lint.sh`` is a pure filesystem walk (no
``sqlite3``/``shctx_sql`` call anywhere in it) — these tests never build a
fixture DB, never set ``SHCTX_DB``, and never seed any table. The only
environment override that matters is ``SHEPHERD_WORKDIR``, pointed at an
isolated ``tmp_path`` so the real, committed ``.artifacts/`` directory in
this checkout (which has its own real files) is never touched — the same
isolation concern ``test_style.py``'s module docstring documents for the
filesystem half of that command.

**BASH QUIRK COVERED EXPLICITLY: the violation count is always capped at
1.** ``cmd_lint.sh``'s ``fail=1`` (never incremented) means the final
``lint: FAIL (N violation(s))`` line always reads ``(1 violation(s))`` the
instant any violation exists, regardless of how many real violations were
found — see :func:`shepherd_cli.commands.lint._lint`'s docstring.
:func:`test_multiple_violations_count_stays_capped_at_one` locks this in
byte-for-byte so a well-meaning "fix" to make the count accurate would be
caught as a parity regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import clean_env_dict, run_cli


# --------------------------------------------------------------------------
# Env/workdir helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """An isolated artifacts root — never the real checked-in ``.artifacts/``."""
    path = tmp_path / "workdir"
    path.mkdir()
    return path


def lint_env(workdir: Path) -> dict[str, str]:
    """The environment for driving ``shepherd lint``, isolated from the real repo.

    Args:
        workdir: The isolated artifacts root (sets ``SHEPHERD_WORKDIR``,
            overriding ``resolve_workdir()``'s real-``.artifacts/``
            auto-detection).

    Returns:
        The full environment dict for :func:`conftest.run_cli`. No
        ``SHCTX_DB``/``CLAUDE_PLUGIN_ROOT`` needed — ``lint`` touches
        neither the database nor any bundled skill asset.
    """
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def touch(path: Path) -> None:
    """Create an empty file, making parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


# --------------------------------------------------------------------------
# Empty / never-initialized tree.
# --------------------------------------------------------------------------
def test_uninitialized_tree_is_ok(workdir: Path) -> None:
    """No artifacts directories exist at all -> ``lint: ok``, exit 0.

    Bash parity: ``find`` on a nonexistent directory (``2>/dev/null``)
    prints nothing and the ``while read`` loop never iterates, so an
    uninitialized project trivially passes lint.
    """
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"
    assert result.stderr == ""


def test_empty_directories_are_ok(workdir: Path) -> None:
    """Every checked directory exists but is empty -> ``lint: ok``, exit 0."""
    for rel in ("plans", "docs/plans", "reports", "docs/reports", "docs/journal", "logs"):
        (workdir / rel).mkdir(parents=True)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


# --------------------------------------------------------------------------
# plans/ + docs/plans/
# --------------------------------------------------------------------------
def test_plans_happy_path(workdir: Path) -> None:
    """``*.seed.md``/``*.plan.md`` in both ``plans/`` and ``docs/plans/`` pass."""
    touch(workdir / "plans" / "wave-a.seed.md")
    touch(workdir / "plans" / "wave-b.plan.md")
    touch(workdir / "docs" / "plans" / "wave-c.seed.md")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_plans_gitkeep_exempt(workdir: Path) -> None:
    """``.gitkeep`` in ``plans/`` is silently skipped, never flagged."""
    touch(workdir / "plans" / ".gitkeep")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_plans_violation(workdir: Path) -> None:
    """A ``plans/`` file matching neither suffix is flagged and fails the run."""
    bad = workdir / "plans" / "notes.md"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines == [
        f"lint: {bad} does not match *.seed.md or *.plan.md",
        "lint: FAIL (1 violation(s))",
    ]


def test_plans_nested_subdirectory_is_walked(workdir: Path) -> None:
    """``plans/`` is walked recursively (bash's ``find`` has no ``-maxdepth``)."""
    bad = workdir / "plans" / "sub" / "dir" / "notes.md"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    assert f"lint: {bad} does not match *.seed.md or *.plan.md" in result.stdout


def test_plans_docs_plans_checked_after_legacy_plans(workdir: Path) -> None:
    """Violations in ``plans/`` are reported before violations in ``docs/plans/``."""
    legacy_bad = workdir / "plans" / "z-notes.md"
    new_bad = workdir / "docs" / "plans" / "a-notes.md"
    touch(legacy_bad)
    touch(new_bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines[0] == f"lint: {legacy_bad} does not match *.seed.md or *.plan.md"
    assert lines[1] == f"lint: {new_bad} does not match *.seed.md or *.plan.md"
    assert lines[2] == "lint: FAIL (1 violation(s))"


# --------------------------------------------------------------------------
# reports/ + docs/reports/
# --------------------------------------------------------------------------
def test_reports_happy_path(workdir: Path) -> None:
    """``*.phase0.md``/``*.close.md``/``*.walk.md`` and date-prefixed names pass."""
    touch(workdir / "reports" / "wave.phase0.md")
    touch(workdir / "reports" / "sprint.close.md")
    touch(workdir / "reports" / "audit.walk.md")
    touch(workdir / "docs" / "reports" / "2026-07-16-discovery-findings.md")
    touch(workdir / "docs" / "reports" / "2026-07-16-sprint-group.md")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_reports_date_prefixed_allows_empty_suffix(workdir: Path) -> None:
    """``YYYY-MM-DD-*.md`` accepts an empty ``*`` (bash glob parity: ``2026-07-16-.md``)."""
    touch(workdir / "reports" / "2026-07-16-.md")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_reports_gitkeep_exempt(workdir: Path) -> None:
    """``.gitkeep`` in ``reports/`` is silently skipped."""
    touch(workdir / "reports" / ".gitkeep")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_reports_violation(workdir: Path) -> None:
    """A ``reports/`` file matching none of the accepted shapes is flagged."""
    bad = workdir / "reports" / "random-notes.md"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines == [
        f"lint: {bad} does not match *.{{phase0,close,walk}}.md or YYYY-MM-DD-*.md",
        "lint: FAIL (1 violation(s))",
    ]


def test_reports_near_miss_date_prefix_still_violates(workdir: Path) -> None:
    """A malformed date prefix (single-digit month) does not satisfy the date pattern."""
    bad = workdir / "reports" / "2026-7-16-foo.md"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    assert f"lint: {bad} does not match *.{{phase0,close,walk}}.md or YYYY-MM-DD-*.md" in result.stdout


# --------------------------------------------------------------------------
# docs/journal/
# --------------------------------------------------------------------------
def test_journal_happy_path(workdir: Path) -> None:
    """Exactly ``YYYY-MM-DD.md`` passes."""
    touch(workdir / "docs" / "journal" / "2026-07-16.md")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_journal_gitkeep_exempt(workdir: Path) -> None:
    """``.gitkeep`` in ``docs/journal/`` is silently skipped."""
    touch(workdir / "docs" / "journal" / ".gitkeep")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_journal_violation(workdir: Path) -> None:
    """A journal filename with any suffix beyond the bare date is flagged."""
    bad = workdir / "docs" / "journal" / "2026-07-16-notes.md"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines == [
        f"lint: {bad} does not match YYYY-MM-DD.md",
        "lint: FAIL (1 violation(s))",
    ]


# --------------------------------------------------------------------------
# logs/
# --------------------------------------------------------------------------
def test_logs_happy_path(workdir: Path) -> None:
    """All four accepted ``logs/`` shapes pass."""
    touch(workdir / "logs" / "events-2026-07-16.jsonl")
    touch(workdir / "logs" / "2026-07-16.log.jsonl")
    touch(workdir / "logs" / "2026-07-16.log.md")
    touch(workdir / "logs" / "2026-07-16T10-30-00.log.jsonl")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_logs_gitkeep_exempt(workdir: Path) -> None:
    """``.gitkeep`` in ``logs/`` is silently skipped."""
    touch(workdir / "logs" / ".gitkeep")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_logs_violation(workdir: Path) -> None:
    """A ``logs/`` file matching none of the four accepted shapes is flagged."""
    bad = workdir / "logs" / "random.txt"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines == [
        f"lint: {bad} has unrecognized log filename pattern",
        "lint: FAIL (1 violation(s))",
    ]


def test_logs_subdirectory_not_walked(workdir: Path) -> None:
    """``logs/`` is checked only ``-maxdepth 1`` — sub-directories are never inspected.

    ``cmd_lint.sh``'s own comment calls this out explicitly: files under
    ``logs/hooks/`` (or any other nested directory) are not linted at this
    depth, no matter what they're named.
    """
    touch(workdir / "logs" / "hooks" / "whatever-name-at-all.txt")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_logs_events_pattern_is_exact(workdir: Path) -> None:
    """The legacy ``events-YYYY-MM-DD.jsonl`` pattern must match in full, not as a prefix."""
    bad = workdir / "logs" / "events-2026-07-16-extra.jsonl"
    touch(bad)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    assert f"lint: {bad} has unrecognized log filename pattern" in result.stdout


# --------------------------------------------------------------------------
# Cross-section ordering + the bash fail-count quirk.
# --------------------------------------------------------------------------
def test_section_order_plans_reports_journal_logs(workdir: Path) -> None:
    """Violations print in bash's own section order: plans, reports, journal, logs."""
    plans_bad = workdir / "plans" / "notes.md"
    reports_bad = workdir / "reports" / "notes.md"
    journal_bad = workdir / "docs" / "journal" / "notes.md"
    logs_bad = workdir / "logs" / "notes.txt"
    for path in (logs_bad, journal_bad, reports_bad, plans_bad):  # created out of order on purpose
        touch(path)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines == [
        f"lint: {plans_bad} does not match *.seed.md or *.plan.md",
        f"lint: {reports_bad} does not match *.{{phase0,close,walk}}.md or YYYY-MM-DD-*.md",
        f"lint: {journal_bad} does not match YYYY-MM-DD.md",
        f"lint: {logs_bad} has unrecognized log filename pattern",
        "lint: FAIL (1 violation(s))",
    ]


def test_multiple_violations_count_stays_capped_at_one(workdir: Path) -> None:
    """Bash-parity quirk: N>1 real violations still print ``(1 violation(s))``.

    ``cmd_lint.sh``'s ``fail=1`` literal assignment (never incremented) on
    every violating branch means the trailing summary line's count can
    never read anything but 1 once any violation exists — see
    ``shepherd_cli/commands/lint.py``'s module docstring. Every individual
    violation line is still printed once per real violation; only the
    final parenthetical count is capped.
    """
    bad_paths = [
        workdir / "plans" / "a.md",
        workdir / "plans" / "b.md",
        workdir / "reports" / "c.md",
        workdir / "docs" / "journal" / "d.md",
        workdir / "logs" / "e.txt",
    ]
    for path in bad_paths:
        touch(path)
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    assert len(lines) == len(bad_paths) + 1  # one line per violation + the summary
    assert lines[-1] == "lint: FAIL (1 violation(s))"


# --------------------------------------------------------------------------
# runs/ — #P4 canonical run-id WARN (Python-only extension, NOT bash parity —
# see lint.py's module docstring "#P4 EXTENSION" note). A non-canonical run
# directory is reported but NEVER fails the run or changes the violation
# count, since axiom has exactly this live mid-sprint and lint must not
# block it.
# --------------------------------------------------------------------------
def test_no_runs_directory_is_ok(workdir: Path) -> None:
    """``runs/`` never created at all -> no WARN, ``lint: ok``."""
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"


def test_canonical_run_is_not_warned(workdir: Path) -> None:
    init = run_cli(["run", "init", "v641-dev0"], lint_env(workdir))
    assert init.returncode == 0, init.stderr

    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"
    assert "WARN" not in result.stdout


def test_noncanonical_run_warns_but_does_not_fail(workdir: Path) -> None:
    """The exact axiom live-run shape (harness name + ordinal welded onto
    the slug) is WARNed, never fails the run -- exit 0, stderr empty."""
    init = run_cli(["run", "init", "v039-dev0-codex-01", "--force"], lint_env(workdir))
    assert init.returncode == 0, init.stderr

    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.rstrip("\n").splitlines()
    run_dir = workdir / "runs" / "v039-dev0-codex-01"
    assert lines == [
        f"lint: WARN {run_dir} is a non-canonical run id -- canonical form: v039-dev0 "
        "-- fix: shepherd run canonicalize v039-dev0-codex-01",
        "lint: ok",
    ]


def test_noncanonical_run_with_no_derivable_canonical_form_names_rename(workdir: Path) -> None:
    """When no canonical prefix can be derived at all, the WARN falls back to
    naming ``run rename`` (with a human-chosen destination) instead of
    ``run canonicalize``."""
    init = run_cli(["run", "init", "totally-invented", "--force"], lint_env(workdir))
    assert init.returncode == 0, init.stderr

    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    run_dir = workdir / "runs" / "totally-invented"
    assert (
        f"lint: WARN {run_dir} is a non-canonical run id -- no canonical form could be "
        "derived automatically -- fix: shepherd run rename totally-invented <canonical-id>"
        in result.stdout
    )


def test_noncanonical_run_warn_never_changes_the_violation_count(workdir: Path) -> None:
    """A real violation (``plans/``) plus a non-canonical run -> the WARN
    line is printed, but ``fail`` and the "(N violation(s))" count are
    driven ONLY by the real violation -- exactly what pure bash parity
    would have printed, plus the WARN line before the summary."""
    bad = workdir / "plans" / "notes.md"
    touch(bad)
    init = run_cli(["run", "init", "v039-dev0-codex-01", "--force"], lint_env(workdir))
    assert init.returncode == 0, init.stderr

    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    lines = result.stdout.rstrip("\n").splitlines()
    run_dir = workdir / "runs" / "v039-dev0-codex-01"
    assert lines == [
        f"lint: {bad} does not match *.seed.md or *.plan.md",
        f"lint: WARN {run_dir} is a non-canonical run id -- canonical form: v039-dev0 "
        "-- fix: shepherd run canonicalize v039-dev0-codex-01",
        "lint: FAIL (1 violation(s))",
    ]


def test_multiple_noncanonical_runs_each_get_their_own_warn_line(workdir: Path) -> None:
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], lint_env(workdir))
    run_cli(["run", "init", "v100-dev2-codex-05", "--force"], lint_env(workdir))

    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.count("lint: WARN") == 2
    assert "v039-dev0-codex-01" in result.stdout
    assert "v100-dev2-codex-05" in result.stdout


# --------------------------------------------------------------------------
# No-subcommand / argument-ignoring behavior.
# --------------------------------------------------------------------------
def test_no_arguments_runs_the_lint(workdir: Path) -> None:
    """``shepherd lint`` with no arguments runs the check directly (no subcommands exist)."""
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"
    assert result.stderr == ""


def test_extra_arguments_are_silently_ignored(workdir: Path) -> None:
    """``cmd_lint.sh`` never reads ``$1``/``$@`` — extra tokens must not error.

    Bash parity: the bash script has no argument-parsing logic at all, so
    any tokens the dispatcher happens to pass through are inert. This
    mirrors that by accepting arbitrary tokens (including option-shaped
    ones) rather than raising a Typer/Click usage error.
    """
    result = run_cli(["lint", "some-arg", "--unexpected-flag"], lint_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "lint: ok"
    assert result.stderr == ""


def test_stderr_is_always_empty(workdir: Path) -> None:
    """Bash never writes lint output to stderr, in either the ok or fail case."""
    touch(workdir / "plans" / "notes.md")
    result = run_cli(["lint"], lint_env(workdir))
    assert result.returncode == 1
    assert result.stderr == ""
