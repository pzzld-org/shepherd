"""Subprocess parity tests for ``shepherd ready`` (bootstrap pipeline).

Bash parity target: ``skills/context/scripts/cmd_ready.sh`` (retired).
Every test drives the real CLI as a subprocess (``${PY} -m shepherd_cli
ready ...``), exactly like ``test_sync.py``/``test_sprint.py`` — never by
importing ``shepherd_cli`` into the pytest process.

``shepherd ready`` is an ORCHESTRATION command with NO subcommands: it
re-invokes five ported sibling subcommands (``init``, ``migrate``,
``refresh``, ``lint``, ``doctor``) as child processes of the same
interpreter (``[sys.executable, "-m", "shepherd_cli", "<stage>", ...]``),
each of which may touch the network (``gh``) or the database on its own
terms, but ``shepherd ready`` itself only gates ``init`` on
``project.json``'s existence, times the pipeline, and aggregates exit
codes. Driving the REAL sibling stages from a gate test would violate the
"deterministic, local, free, <2s, never flaky" gate-test contract
(CLAUDE.md). Per that same contract's latent-vs-deterministic split, this
suite builds a throwaway FAKE ``shepherd_cli`` package (see
:func:`fake_cli_root`) and runs the CLI with that directory as the
subprocess cwd: ``python -m`` puts the cwd FIRST on ``sys.path`` (ahead of
``PYTHONPATH``), so both the parent invocation and every stage
re-invocation resolve the fake package. The fake's ``__main__`` handles the
five STAGE subcommands itself — logging each invocation to ``$CALL_LOG``,
printing deterministic stdout/stderr markers, and exiting with a
caller-controlled code (via ``FAKE_RC_*`` env vars) — and DELEGATES every
other subcommand (``ready``, the command under test) to the real package by
stripping itself off ``sys.path``. This gives full, fast, deterministic
control over every stage's exit code and stdout/stderr while exercising the
REAL production mechanism end to end (the actual ``-m shepherd_cli``
re-invocation), letting the tests below pin down ``shepherd ready``'s OWN
contract exactly: which argv it invokes each stage with, in what order, in
what shape (suppressed-vs-streamed output per stage), how the ``init``
stage's failure short-circuits the whole pipeline, and how it aggregates
per-stage exit codes into its own final exit code and summary text — all
bash-parity concerns that belong to ``shepherd ready``, not to any of the
five stages it calls.

No fixture database is built anywhere in this suite: ``shepherd ready``
never opens a Tortoise connection and never calls
:func:`shepherd_cli.resolution.resolve_db_path` — the only shared helper
reused for DB purposes is ``cli_env`` (for its stripped baseline
environment; the throwaway db path it sets is never actually opened).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import PY, cli_env

# --------------------------------------------------------------------------
# Fake shepherd_cli package — deterministic stand-ins for the init /
# migrate / refresh / lint / doctor stage re-invocations, delegating every
# other subcommand to the real package.
# --------------------------------------------------------------------------

_FAKE_MAIN = '''\
"""Test stand-in for ``python -m shepherd_cli`` (see test_ready.py docstring).

Stage subcommands (init/migrate/refresh/lint/doctor) are faked: log argv
to $CALL_LOG, print deterministic markers, exit with $FAKE_RC_<STAGE>.
Everything else (the ``ready`` command under test) delegates to the REAL
package.
"""
import os
import sys

_STAGES = {"init", "migrate", "refresh", "lint", "doctor"}


def _fake_stage(cmd, args):
    log_path = os.environ.get("CALL_LOG", "")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write((cmd + " " + " ".join(args)).rstrip() + "\\n")
    suffix = ":" + " ".join(args) if args else ""
    print(f"stdout:{cmd}{suffix}")
    print(f"stderr:{cmd}{suffix}", file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_RC_" + cmd.upper(), "0")))


_cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if _cmd in _STAGES:
    _fake_stage(_cmd, sys.argv[2:])

# Delegate to the real shepherd_cli: drop this fake package's directory off
# sys.path, forget the fake modules, and re-import the real entry point
# (resolved via PYTHONPATH, which conftest points at services/cli).
_here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _here]
for _name in [n for n in list(sys.modules) if n == "shepherd_cli" or n.startswith("shepherd_cli.")]:
    del sys.modules[_name]

from shepherd_cli.__main__ import main  # noqa: E402

main()
'''


def _make_fake_cli_root(tmp_path: Path) -> Path:
    """Build a throwaway directory whose ``shepherd_cli`` package fakes the stages.

    The returned directory is used as the subprocess CWD: ``python -m``
    resolves packages from the cwd before ``PYTHONPATH``, so both the
    parent ``ready`` invocation and every ``[sys.executable, "-m",
    "shepherd_cli", "<stage>"]`` stage re-invocation import this fake
    package first. The fake handles stage subcommands deterministically
    (see ``_FAKE_MAIN``) and delegates ``ready`` itself to the real
    package.

    Args:
        tmp_path: The pytest-provided per-test temp directory.

    Returns:
        The directory containing the fake ``shepherd_cli`` package (the
        cwd to run the CLI from).
    """
    fake_root = tmp_path / "fake-cli-root"
    pkg_dir = fake_root / "shepherd_cli"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text(_FAKE_MAIN)
    return fake_root


def ready_env(
    workdir: Path,
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd ready`` test.

    Args:
        workdir: An absolute directory ``SHEPHERD_WORKDIR`` points at —
            gives each test a private, empty-by-default ``project.json``
            location (``_run_init_stage``'s gating check).
        call_log: Path the fake stage stand-ins append one line to per
            invocation (``$CALL_LOG``) — read back to assert which stages
            actually ran, in what order, with what argv.
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_MIGRATE": "1"}``.

    Returns:
        A full subprocess environment ready for :func:`run_ready`.
        Deliberately does NOT rely on ``SHCTX_DB`` being opened —
        ``shepherd ready`` never resolves it (no database access at all),
        so a bare stripped-then-rebuilt environment (``clean_env_dict()``,
        reached via ``cli_env`` with a throwaway db path never actually
        opened) is sufficient.
    """
    env = cli_env(call_log.parent / "unused.db")
    env["SHEPHERD_WORKDIR"] = str(workdir)
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def run_ready(
    args: list[str],
    env: dict[str, str],
    fake_cli_root: Path,
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli ready ...`` with the fake package as cwd.

    ``conftest.run_cli`` pins ``cwd=CLI_ROOT`` (the real package), so this
    suite uses its own runner: the fake-cli-root cwd is exactly what makes
    the stage re-invocations resolve the fake stand-ins (see the module
    docstring).
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "ready", *args],
        env=env,
        cwd=str(fake_cli_root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order."""
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# Fixtures.
# --------------------------------------------------------------------------


@pytest.fixture
def fake_cli_root(tmp_path: Path) -> Path:
    return _make_fake_cli_root(tmp_path)


@pytest.fixture
def call_log(tmp_path: Path) -> Path:
    """Path the fake stage stand-ins append their invocations to."""
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
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    assert not (workdir / "project.json").exists()
    env = ready_env(workdir, call_log)
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready: bootstrap done (elapsed=" in proc.stdout
    assert "  init:    performed" in proc.stdout
    assert "  migrate: ok" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  doctor:  ok" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "init",
        "migrate",
        "refresh --scope=all",
        "lint",
        "doctor",
    ]


def test_bare_invocation_project_json_present_skips_init(
    fake_cli_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    env = ready_env(initialized_workdir, call_log)
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "  init:    skipped (already initialized)" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "migrate",
        "refresh --scope=all",
        "lint",
        "doctor",
    ]
    assert all(not call.startswith("init") for call in calls)


# --------------------------------------------------------------------------
# --shepherd / --artifacts (forwarded to the init stage, only when it runs).
# --------------------------------------------------------------------------


def test_shepherd_flag_forwarded_to_init_when_init_runs(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--shepherd"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert read_calls(call_log)[0] == "init --shepherd"


def test_artifacts_flag_forwarded_to_init_when_init_runs(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--artifacts"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert read_calls(call_log)[0] == "init --artifacts"


def test_both_shepherd_and_artifacts_forwarded_in_order(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: ``init_flags+=("$arg")`` is an append, not a
    reassignment — both flags accumulate, in the order given."""
    env = ready_env(workdir, call_log)
    proc = run_ready(["--shepherd", "--artifacts"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert read_calls(call_log)[0] == "init --shepherd --artifacts"


def test_init_flags_ignored_when_project_already_initialized(
    fake_cli_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    """Bash parity: ``--shepherd``/``--artifacts`` are always parsed into
    ``init_flags``, but never used at all when the ``init`` stage doesn't
    run (project already initialized)."""
    env = ready_env(initialized_workdir, call_log)
    proc = run_ready(["--shepherd"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "  init:    skipped (already initialized)" in proc.stdout
    assert all(not call.startswith("init") for call in read_calls(call_log))


# --------------------------------------------------------------------------
# init stdout always suppressed, stderr always inherited (regardless of
# --verbose) — the init stage is NOT run_stage-shaped.
# --------------------------------------------------------------------------


def test_init_stdout_always_suppressed_stderr_always_inherited_non_verbose(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:init" not in proc.stdout
    assert "stderr:init" in proc.stderr
    # No "─── init ───" header without --verbose.
    assert "─── init ───" not in proc.stdout


def test_init_stdout_always_suppressed_stderr_always_inherited_verbose(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── init ───" in proc.stdout
    # Bash's init block always redirects stdout (>/dev/null), even verbose.
    assert "stdout:init" not in proc.stdout
    assert "stderr:init" in proc.stderr


def test_init_header_absent_when_init_is_skipped_even_verbose(
    fake_cli_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    env = ready_env(initialized_workdir, call_log)
    proc = run_ready(["--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── init ───" not in proc.stdout


# --------------------------------------------------------------------------
# init failure short-circuits the ENTIRE pipeline (bash: unguarded set -e).
# --------------------------------------------------------------------------


def test_init_failure_short_circuits_no_later_stage_runs(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log, rc={"FAKE_RC_INIT": "7"})
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 7
    calls = read_calls(call_log)
    assert calls == ["init"]
    # No later stage ran, and no summary printed.
    assert "shctx ready: bootstrap done" not in proc.stdout
    assert "migrate:" not in proc.stdout


def test_init_failure_when_project_already_initialized_never_happens(
    fake_cli_root: Path, initialized_workdir: Path, call_log: Path
) -> None:
    """Sanity check: FAKE_RC_INIT has no effect at all when init is
    skipped — the stage never runs, so it can never fail."""
    env = ready_env(initialized_workdir, call_log, rc={"FAKE_RC_INIT": "7"})
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready: bootstrap done" in proc.stdout


# --------------------------------------------------------------------------
# migrate / refresh / lint: independent, each always runs, non-short-
# circuiting failures.
# --------------------------------------------------------------------------


def test_migrate_failure_still_runs_refresh_lint_doctor_and_exits_1(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log, rc={"FAKE_RC_MIGRATE": "1"})
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  migrate: fail (rc=1)" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  doctor:  ok" in proc.stdout
    assert len(read_calls(call_log)) == 5


def test_refresh_and_lint_failures_together_exit_1(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(
        workdir, call_log,
        rc={"FAKE_RC_REFRESH": "3", "FAKE_RC_LINT": "5"},
    )
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  migrate: ok" in proc.stdout
    assert "  refresh: fail (rc=3)" in proc.stdout
    assert "  lint:    fail (rc=5)" in proc.stdout
    assert "  doctor:  ok" in proc.stdout
    # Every stage still ran despite earlier failures.
    assert len(read_calls(call_log)) == 5


def test_all_stages_succeed_exits_0(fake_cli_root: Path, workdir: Path, call_log: Path) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr


# --------------------------------------------------------------------------
# doctor: always streamed regardless of --verbose; its exit code feeds the
# summary line but never the final exit code.
# --------------------------------------------------------------------------


def test_doctor_output_always_streams_non_verbose(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:doctor" in proc.stdout
    assert "stderr:doctor" in proc.stderr


def test_doctor_output_always_streams_verbose(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:doctor" in proc.stdout
    assert "stderr:doctor" in proc.stderr
    # doctor is never run_stage-wrapped: no "─── doctor ───" header exists.
    assert "─── doctor ───" not in proc.stdout


def test_doctor_rc_2_reports_warn_and_does_not_affect_exit_code(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log, rc={"FAKE_RC_DOCTOR": "2"})
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "  doctor:  warn" in proc.stdout


def test_doctor_rc_1_reports_fail_and_does_not_affect_exit_code(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log, rc={"FAKE_RC_DOCTOR": "1"})
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "  doctor:  fail (rc=1)" in proc.stdout


def test_doctor_failure_combined_with_migrate_failure_exits_1_from_migrate(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    """Only migrate/refresh/lint feed the final exit code — doctor never
    does, even when it fails alongside a real failure."""
    env = ready_env(
        workdir, call_log,
        rc={"FAKE_RC_DOCTOR": "1", "FAKE_RC_MIGRATE": "9"},
    )
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  migrate: fail (rc=9)" in proc.stdout
    assert "  doctor:  fail (rc=1)" in proc.stdout


# --------------------------------------------------------------------------
# --verbose / -v: migrate/refresh/lint get run_stage-shaped headers +
# streamed output; non-verbose suppresses them entirely.
# --------------------------------------------------------------------------


def test_verbose_streams_migrate_refresh_lint_with_headers(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── migrate ───" in proc.stdout
    assert "─── refresh ───" in proc.stdout
    assert "─── lint ───" in proc.stdout
    assert "stdout:migrate" in proc.stdout
    assert "stderr:migrate" in proc.stderr
    assert "stdout:refresh:--scope=all" in proc.stdout
    # The final bash-parity summary still prints after the streamed stages.
    assert "shctx ready: bootstrap done (elapsed=" in proc.stdout


def test_verbose_short_flag_is_equivalent(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["-v"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── migrate ───" in proc.stdout


def test_non_verbose_suppresses_migrate_refresh_lint_output_and_headers(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:migrate" not in proc.stdout
    assert "stderr:migrate" not in proc.stderr
    assert "stdout:refresh" not in proc.stdout
    assert "stdout:lint" not in proc.stdout
    assert "─── migrate ───" not in proc.stdout
    assert "─── refresh ───" not in proc.stdout
    assert "─── lint ───" not in proc.stdout


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------


def test_help_long_flag_prints_usage_and_exits_0(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--help"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready [--shepherd|--artifacts] [--verbose]" in proc.stdout
    assert "init → migrate → refresh --all → lint → doctor" in proc.stdout
    assert "First-time bootstrap." in proc.stdout
    # No pipeline stage ran at all.
    assert read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["-h"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready [--shepherd|--artifacts] [--verbose]" in proc.stdout
    assert read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_other_flags(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    """Bash parity: the ``for arg`` loop reaches ``-h``/``--help`` and
    exits immediately, regardless of what earlier flags already set —
    ``shepherd ready`` never reaches the pipeline stages once ``-h``/
    ``--help`` is seen, from any position."""
    env = ready_env(workdir, call_log)
    proc = run_ready(["--shepherd", "--verbose", "-h"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx ready [--shepherd|--artifacts] [--verbose]" in proc.stdout
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--bogus"], env, fake_cli_root)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


def test_positional_token_is_unknown_arg(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    """``shepherd ready`` takes no positional arguments — any bare token is
    an unknown arg, exit 1."""
    env = ready_env(workdir, call_log)
    proc = run_ready(["bogus"], env, fake_cli_root)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: bogus" in proc.stderr
    assert read_calls(call_log) == []


def test_unknown_arg_short_circuits_before_later_tokens_are_seen(
    fake_cli_root: Path, workdir: Path, call_log: Path
) -> None:
    env = ready_env(workdir, call_log)
    proc = run_ready(["--bogus", "--verbose"], env, fake_cli_root)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# _run_stage() launch-failure mode.
# --------------------------------------------------------------------------

_RUN_STAGE_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.ready import _run_stage\n"
    "print(_run_stage('probe', [sys.argv[1]], False))\n"
)


def test_unlaunchable_stage_counts_as_rc_127(tmp_path: Path) -> None:
    """A stage that cannot be launched at all (OSError from process
    creation — the moral equivalent of bash's missing/unexecutable
    ``cmd_*.sh``) maps to rc 127, the shell's own command-not-found code,
    instead of crashing the pipeline. Driven via a ``-c`` snippet in a
    fresh subprocess (the test_panes.py private-helper pattern)."""
    env = cli_env(tmp_path / "unused.db")
    proc = subprocess.run(
        [PY, "-c", _RUN_STAGE_SNIPPET, str(tmp_path / "no-such-interpreter")],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "127"
