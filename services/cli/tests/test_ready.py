"""Subprocess parity tests for ``shepherd ready`` (bootstrap pipeline).

Bash parity target: ``skills/context/scripts/cmd_ready.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli ready ...``),
exactly like ``test_sync.py``/``test_sprint.py`` — never by importing
``shepherd_cli`` into the pytest process.

``cmd_ready.sh`` is an ORCHESTRATION script with NO subcommands: it shells
out to five sibling scripts (``cmd_init.sh``, ``cmd_migrate.sh``,
``cmd_refresh.sh``, ``cmd_lint.sh``, ``cmd_doctor.sh``), each of which may
touch the network (``gh``) or the database on its own terms, but
``cmd_ready.sh`` itself only gates ``init`` on ``project.json``'s
existence, times the pipeline, and aggregates exit codes. Driving the REAL
sibling scripts from a gate test would violate the "deterministic, local,
free, <2s, never flaky" gate-test contract (CLAUDE.md). Per that same
contract's latent-vs-deterministic split, this suite builds a throwaway
"fake plugin root" (see :func:`fake_plugin_root`) containing tiny,
fully-scripted stand-ins for all five sibling scripts — each one logs its
invocation to ``$CALL_LOG`` and exits with a caller-controlled code (via
``FAKE_RC_*`` env vars) — and points ``CLAUDE_PLUGIN_ROOT`` at it. This
gives full, fast, deterministic control over every stage's exit code and
stdout/stderr, letting the tests below pin down ``shepherd ready``'s OWN
contract exactly: which argv it invokes each stage with, in what order,
in what shape (suppressed-vs-streamed output per stage), how the ``init``
stage's failure short-circuits the whole pipeline, and how it aggregates
per-stage exit codes into its own final exit code and summary text — all
bash-parity concerns that belong to ``cmd_ready.sh``, not to any of the
five scripts it calls.

No fixture database is built anywhere in this suite: ``shepherd ready``
never opens a Tortoise connection and never calls
:func:`shepherd_cli.resolution.resolve_db_path` — the only shared helper
reused for DB purposes is ``cli_env`` (for its stripped baseline
environment; the throwaway db path it sets is never actually opened).
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest
from conftest import PY, cli_env, run_cli

# --------------------------------------------------------------------------
# Fake sibling scripts — deterministic stand-ins for cmd_init.sh,
# cmd_migrate.sh, cmd_refresh.sh, cmd_lint.sh, cmd_doctor.sh.
# --------------------------------------------------------------------------

_STUB_PREAMBLE = '#!/usr/bin/env bash\necho "{name} $*" >> "$CALL_LOG"\n'

_FAKE_SCRIPTS: dict[str, str] = {
    "cmd_init.sh": _STUB_PREAMBLE.format(name="cmd_init.sh")
    + (
        'echo "stdout:cmd_init.sh:$*"\n'
        'echo "stderr:cmd_init.sh:$*" >&2\n'
        'exit "${FAKE_RC_INIT:-0}"\n'
    ),
    "cmd_migrate.sh": _STUB_PREAMBLE.format(name="cmd_migrate.sh")
    + ('echo "stdout:cmd_migrate.sh"\necho "stderr:cmd_migrate.sh" >&2\nexit "${FAKE_RC_MIGRATE:-0}"\n'),
    "cmd_refresh.sh": _STUB_PREAMBLE.format(name="cmd_refresh.sh")
    + (
        'echo "stdout:cmd_refresh.sh:$*"\n'
        'echo "stderr:cmd_refresh.sh:$*" >&2\n'
        'exit "${FAKE_RC_REFRESH:-0}"\n'
    ),
    "cmd_lint.sh": _STUB_PREAMBLE.format(name="cmd_lint.sh")
    + ('echo "stdout:cmd_lint.sh"\necho "stderr:cmd_lint.sh" >&2\nexit "${FAKE_RC_LINT:-0}"\n'),
    "cmd_doctor.sh": _STUB_PREAMBLE.format(name="cmd_doctor.sh")
    + ('echo "stdout:cmd_doctor.sh"\necho "stderr:cmd_doctor.sh" >&2\nexit "${FAKE_RC_DOCTOR:-0}"\n'),
}


def _make_fake_plugin_root(tmp_path: Path) -> Path:
    """Build a throwaway ``CLAUDE_PLUGIN_ROOT`` tree with fully-scripted sibling commands.

    Layout mirrors the real plugin just enough for
    :func:`shepherd_cli.resolution.find_bash_shctx` to resolve it:
    ``skills/context/scripts/{shctx, cmd_init.sh, cmd_migrate.sh,
    cmd_refresh.sh, cmd_lint.sh, cmd_doctor.sh}``. ``shctx`` itself only
    needs to exist as a file (its dirname is all ``shepherd ready`` ever
    uses via ``_scripts_dir()``); the five ``cmd_*.sh`` stand-ins are
    real, executable, deterministic bash scripts (see ``_FAKE_SCRIPTS``).

    Args:
        tmp_path: The pytest-provided per-test temp directory.

    Returns:
        The fake plugin root directory (the ``CLAUDE_PLUGIN_ROOT`` value),
        three levels above ``skills/context/scripts``.
    """
    scripts_dir = tmp_path / "fake-plugin-root" / "skills" / "context" / "scripts"
    scripts_dir.mkdir(parents=True)

    shctx_path = scripts_dir / "shctx"
    shctx_path.write_text("#!/usr/bin/env bash\nexit 0\n")
    shctx_path.chmod(shctx_path.stat().st_mode | stat.S_IEXEC)

    for name, content in _FAKE_SCRIPTS.items():
        script_path = scripts_dir / name
        script_path.write_text(content)
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    return scripts_dir.parent.parent.parent


def ready_env(
    fake_plugin_root: Path,
    workdir: Path,
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd ready`` test.

    Args:
        fake_plugin_root: The fake plugin root from
            :func:`_make_fake_plugin_root`, wired in as
            ``CLAUDE_PLUGIN_ROOT`` so ``find_bash_shctx()`` (and therefore
            ``_scripts_dir()``) resolves to the fake sibling scripts
            instead of the real, network-dependent ones.
        workdir: An absolute directory ``SHEPHERD_WORKDIR`` points at —
            gives each test a private, empty-by-default ``project.json``
            location (``_run_init_stage``'s gating check).
        call_log: Path the fake sibling scripts append one line to per
            invocation (``$CALL_LOG``) — read back to assert which stages
            actually ran, in what order, with what argv.
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_MIGRATE": "1"}``.

    Returns:
        A full subprocess environment ready for :func:`conftest.run_cli`.
        Deliberately does NOT rely on ``SHCTX_DB`` being opened —
        ``shepherd ready`` never resolves it (no database access at all),
        so a bare stripped-then-rebuilt environment (``clean_env_dict()``,
        reached via ``cli_env`` with a throwaway db path never actually
        opened) is sufficient.
    """
    env = cli_env(fake_plugin_root / "unused.db")
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order.

    Each line is right-stripped: a no-argument stage (``cmd_migrate.sh``,
    ``cmd_lint.sh``, ``cmd_doctor.sh``) still leaves a trailing space in
    the stub's ``"name $*"`` format when ``$*`` expands to nothing —
    cosmetic, not a signal worth asserting on.
    """
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# Fixtures.
# --------------------------------------------------------------------------


@pytest.fixture
def fake_plugin_root(tmp_path: Path) -> Path:
    return _make_fake_plugin_root(tmp_path)


@pytest.fixture
def call_log(tmp_path: Path) -> Path:
    """Path the fake sibling scripts append their invocations to."""
    return tmp_path / "calls.log"


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A private, empty SHEPHERD_WORKDIR for one test (no project.json yet)."""
    path = tmp_path / "workdir"
    path.mkdir()
    return path


@pytest.fixture
def initialized_workdir(workdir: Path) -> Path:
    """The same private workdir, but with a ``project.json`` already present."""
    (workdir / "project.json").write_text('{"id": "proj-existing"}')
    return workdir


# --------------------------------------------------------------------------
# Bare invocation, project.json absent — init runs, full pipeline in order.
# --------------------------------------------------------------------------


def test_bare_invocation_project_json_absent_runs_init_then_full_pipeline(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    assert not (workdir / "project.json").exists()
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready: bootstrap done (elapsed=" in proc.stdout
    assert "  init:    performed" in proc.stdout
    assert "  migrate: ok" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  doctor:  ok" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "cmd_init.sh",
        "cmd_migrate.sh",
        "cmd_refresh.sh --scope=all",
        "cmd_lint.sh",
        "cmd_doctor.sh",
    ]


def test_bare_invocation_project_json_present_skips_init(
    fake_plugin_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, initialized_workdir, call_log)
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  init:    skipped (already initialized)" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "cmd_migrate.sh",
        "cmd_refresh.sh --scope=all",
        "cmd_lint.sh",
        "cmd_doctor.sh",
    ]
    assert all("cmd_init.sh" not in call for call in calls)


# --------------------------------------------------------------------------
# --shepherd / --artifacts (forwarded to cmd_init.sh, only when init runs).
# --------------------------------------------------------------------------


def test_shepherd_flag_forwarded_to_init_when_init_runs(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--shepherd"], env)

    assert proc.returncode == 0, proc.stderr
    assert read_calls(call_log)[0] == "cmd_init.sh --shepherd"


def test_artifacts_flag_forwarded_to_init_when_init_runs(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    assert read_calls(call_log)[0] == "cmd_init.sh --artifacts"


def test_both_shepherd_and_artifacts_forwarded_in_order(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: ``init_flags+=("$arg")`` is an append, not a
    reassignment — both flags accumulate, in the order given."""
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--shepherd", "--artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    assert read_calls(call_log)[0] == "cmd_init.sh --shepherd --artifacts"


def test_init_flags_ignored_when_project_already_initialized(
    fake_plugin_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    """Bash parity: ``--shepherd``/``--artifacts`` are always parsed into
    ``init_flags``, but never used at all when the ``init`` stage doesn't
    run (project already initialized)."""
    env = ready_env(fake_plugin_root, initialized_workdir, call_log)
    proc = run_cli(["ready", "--shepherd"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  init:    skipped (already initialized)" in proc.stdout
    assert all("cmd_init.sh" not in call for call in read_calls(call_log))


# --------------------------------------------------------------------------
# init stdout always suppressed, stderr always inherited (regardless of
# --verbose) — the init stage is NOT run_stage-shaped.
# --------------------------------------------------------------------------


def test_init_stdout_always_suppressed_stderr_always_inherited_non_verbose(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:cmd_init.sh" not in proc.stdout
    assert "stderr:cmd_init.sh" in proc.stderr
    # No "─── init ───" header without --verbose.
    assert "─── init ───" not in proc.stdout


def test_init_stdout_always_suppressed_stderr_always_inherited_verbose(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── init ───" in proc.stdout
    # Bash's init block always redirects stdout (>/dev/null), even verbose.
    assert "stdout:cmd_init.sh" not in proc.stdout
    assert "stderr:cmd_init.sh" in proc.stderr


def test_init_header_absent_when_init_is_skipped_even_verbose(
    fake_plugin_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, initialized_workdir, call_log)
    proc = run_cli(["ready", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── init ───" not in proc.stdout


# --------------------------------------------------------------------------
# init failure short-circuits the ENTIRE pipeline (bash: unguarded set -e).
# --------------------------------------------------------------------------


def test_init_failure_short_circuits_no_later_stage_runs(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log, rc={"FAKE_RC_INIT": "7"})
    proc = run_cli(["ready"], env)

    assert proc.returncode == 7
    calls = read_calls(call_log)
    assert calls == ["cmd_init.sh"]
    # No later stage ran, and no summary printed.
    assert "shctx ready: bootstrap done" not in proc.stdout
    assert "migrate:" not in proc.stdout


def test_init_failure_when_project_already_initialized_never_happens(
    fake_plugin_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    """Sanity check: FAKE_RC_INIT has no effect at all when init is
    skipped — the stage never runs, so it can never fail."""
    env = ready_env(
        fake_plugin_root, initialized_workdir, call_log, rc={"FAKE_RC_INIT": "7"}
    )
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready: bootstrap done" in proc.stdout


# --------------------------------------------------------------------------
# migrate / refresh / lint: independent, each always runs, non-short-
# circuiting failures.
# --------------------------------------------------------------------------


def test_migrate_failure_still_runs_refresh_lint_doctor_and_exits_1(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log, rc={"FAKE_RC_MIGRATE": "1"})
    proc = run_cli(["ready"], env)

    assert proc.returncode == 1
    assert "  migrate: fail (rc=1)" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  doctor:  ok" in proc.stdout
    assert len(read_calls(call_log)) == 5


def test_refresh_and_lint_failures_together_exit_1(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(
        fake_plugin_root, workdir, call_log,
        rc={"FAKE_RC_REFRESH": "3", "FAKE_RC_LINT": "5"},
    )
    proc = run_cli(["ready"], env)

    assert proc.returncode == 1
    assert "  migrate: ok" in proc.stdout
    assert "  refresh: fail (rc=3)" in proc.stdout
    assert "  lint:    fail (rc=5)" in proc.stdout
    assert "  doctor:  ok" in proc.stdout
    # Every stage still ran despite earlier failures.
    assert len(read_calls(call_log)) == 5


def test_all_stages_succeed_exits_0(fake_plugin_root: Path, workdir: Path, call_log: Path) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# doctor: always streamed regardless of --verbose; its exit code feeds the
# summary line but never the final exit code.
# --------------------------------------------------------------------------


def test_doctor_output_always_streams_non_verbose(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:cmd_doctor.sh" in proc.stdout
    assert "stderr:cmd_doctor.sh" in proc.stderr


def test_doctor_output_always_streams_verbose(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:cmd_doctor.sh" in proc.stdout
    assert "stderr:cmd_doctor.sh" in proc.stderr
    # doctor is never run_stage-wrapped: no "─── doctor ───" header exists.
    assert "─── doctor ───" not in proc.stdout


def test_doctor_rc_2_reports_warn_and_does_not_affect_exit_code(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log, rc={"FAKE_RC_DOCTOR": "2"})
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  doctor:  warn" in proc.stdout


def test_doctor_rc_1_reports_fail_and_does_not_affect_exit_code(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log, rc={"FAKE_RC_DOCTOR": "1"})
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "  doctor:  fail (rc=1)" in proc.stdout


def test_doctor_failure_combined_with_migrate_failure_exits_1_from_migrate(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    """Only migrate/refresh/lint feed the final exit code — doctor never
    does, even when it fails alongside a real failure."""
    env = ready_env(
        fake_plugin_root, workdir, call_log,
        rc={"FAKE_RC_DOCTOR": "1", "FAKE_RC_MIGRATE": "9"},
    )
    proc = run_cli(["ready"], env)

    assert proc.returncode == 1
    assert "  migrate: fail (rc=9)" in proc.stdout
    assert "  doctor:  fail (rc=1)" in proc.stdout


# --------------------------------------------------------------------------
# --verbose / -v: migrate/refresh/lint get run_stage-shaped headers +
# streamed output; non-verbose suppresses them entirely.
# --------------------------------------------------------------------------


def test_verbose_streams_migrate_refresh_lint_with_headers(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── migrate ───" in proc.stdout
    assert "─── refresh ───" in proc.stdout
    assert "─── lint ───" in proc.stdout
    assert "stdout:cmd_migrate.sh" in proc.stdout
    assert "stderr:cmd_migrate.sh" in proc.stderr
    assert "stdout:cmd_refresh.sh:--scope=all" in proc.stdout
    # The final bash-parity summary still prints after the streamed stages.
    assert "shctx ready: bootstrap done (elapsed=" in proc.stdout


def test_verbose_short_flag_is_equivalent(fake_plugin_root: Path, workdir: Path, call_log: Path) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "-v"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── migrate ───" in proc.stdout


def test_non_verbose_suppresses_migrate_refresh_lint_output_and_headers(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:cmd_migrate.sh" not in proc.stdout
    assert "stderr:cmd_migrate.sh" not in proc.stderr
    assert "stdout:cmd_refresh.sh" not in proc.stdout
    assert "stdout:cmd_lint.sh" not in proc.stdout
    assert "─── migrate ───" not in proc.stdout
    assert "─── refresh ───" not in proc.stdout
    assert "─── lint ───" not in proc.stdout


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------


def test_help_long_flag_prints_usage_and_exits_0(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--help"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready [--shepherd|--artifacts] [--verbose]" in proc.stdout
    assert "init → migrate → refresh --all → lint → doctor" in proc.stdout
    assert "First-time bootstrap." in proc.stdout
    # No pipeline stage ran at all.
    assert read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready [--shepherd|--artifacts] [--verbose]" in proc.stdout
    assert read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_other_flags(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: the ``for arg`` loop reaches ``-h``/``--help`` and
    exits immediately, regardless of what earlier flags already set —
    ``cmd_ready.sh`` never reaches the pipeline stages once ``-h``/
    ``--help`` is seen, from any position."""
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--shepherd", "--verbose", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready [--shepherd|--artifacts] [--verbose]" in proc.stdout
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_plugin_root: Path, workdir: Path, call_log: Path) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_plugin_root: Path, workdir: Path, call_log: Path) -> None:
    """``cmd_ready.sh`` takes no positional arguments — any bare token is
    an unknown arg, exit 1."""
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "bogus"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: bogus" in proc.stderr
    assert read_calls(call_log) == []


def test_unknown_arg_short_circuits_before_later_tokens_are_seen(
    fake_plugin_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(fake_plugin_root, workdir, call_log)
    proc = run_cli(["ready", "--bogus", "--verbose"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# _scripts_dir() failure mode.
# --------------------------------------------------------------------------


def test_missing_bash_shctx_tooling_exits_1(tmp_path: Path) -> None:
    """When the bash shctx tooling cannot be located at all (no
    CLAUDE_PLUGIN_ROOT match and no skills/context/scripts/shctx found by
    walking up from the repo root), the pipeline is unusable — exit 1
    with a clear stderr message rather than a stack trace."""
    env = cli_env(tmp_path / "unused.db")
    # Point CLAUDE_PLUGIN_ROOT somewhere with no skills/context/scripts/shctx,
    # and run from an empty cwd outside any git repo so the walk-up fallback
    # in find_bash_shctx() also fails to find the real tree.
    empty_root = tmp_path / "no-plugin-here"
    empty_root.mkdir()
    env["CLAUDE_PLUGIN_ROOT"] = str(empty_root)
    env["SHEPHERD_WORKDIR"] = str(tmp_path / "workdir")

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "ready"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    assert "ERROR: bash shctx tooling not found" in proc.stderr
