"""Subprocess parity tests for ``shepherd sync`` (refresh -> lint -> status pipeline).

Bash parity target: ``skills/context/scripts/cmd_sync.sh`` (retired). Every
test drives the real CLI as a subprocess (``${PY} -m shepherd_cli sync ...``),
exactly like ``test_sprint.py`` — never by importing ``shepherd_cli`` into
the pytest process.

``shepherd sync`` is an ORCHESTRATION command with NO subcommands and NO
database access of its own: it re-invokes three ported sibling subcommands
(``refresh``, ``lint``, ``status``) as child processes of the same
interpreter (``[sys.executable, "-m", "shepherd_cli", "<stage>", ...]``),
each of which may touch the network (``gh``) or the database on its own
terms, but ``shepherd sync`` itself only times them and aggregates exit
codes. Driving the REAL sibling stages from a gate test would violate the
"deterministic, local, free, <2s, never flaky" gate-test contract
(CLAUDE.md). Per that same contract's latent-vs-deterministic split, this
suite builds a throwaway FAKE ``shepherd_cli`` package (see
:func:`fake_cli_root`) and runs the CLI with that directory as the
subprocess cwd: ``python -m`` puts the cwd FIRST on ``sys.path`` (ahead of
``PYTHONPATH``), so both the parent invocation and every stage
re-invocation resolve the fake package. The fake's ``__main__`` handles the
three STAGE subcommands itself — logging each invocation to ``$CALL_LOG``,
printing deterministic stdout/stderr markers, and exiting with a
caller-controlled code (via ``FAKE_RC_*`` env vars) — and DELEGATES every
other subcommand (``sync``, the command under test) to the real package by
stripping itself off ``sys.path``. This gives full, fast, deterministic
control over every stage's exit code and stdout/stderr while exercising the
REAL production mechanism end to end (the actual ``-m shepherd_cli``
re-invocation), letting the tests below pin down ``shepherd sync``'s OWN
contract exactly: which argv it invokes each stage with, in what order, in
what shape (``run_stage``'s verbose-vs-suppressed output handling), how it
resolves ``--scope``/``--all``/``--verbose``/``-v``/``-h``/``--help``/
unknown-arg, and how it aggregates per-stage exit codes into its own final
exit code and summary text — all bash-parity concerns that belong to
``shepherd sync``, not to any of the three stages it calls.

No fixture database is built anywhere in this suite: ``shepherd sync``
never opens a Tortoise connection, never calls
:func:`shepherd_cli.resolution.resolve_db_path`, and the fixture DB
helpers in ``conftest.py`` (``build_full_schema_db`` etc.) are therefore
never needed here — the only shared helpers reused are ``cli_env`` (for
its stripped baseline environment) and ``PY``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import PY, cli_env

# --------------------------------------------------------------------------
# Fake shepherd_cli package — deterministic stand-ins for the refresh /
# lint / status stage re-invocations, delegating every other subcommand to
# the real package.
# --------------------------------------------------------------------------

_FAKE_MAIN = '''\
"""Test stand-in for ``python -m shepherd_cli`` (see test_sync.py docstring).

Stage subcommands (refresh/lint/status) are faked: log argv to $CALL_LOG,
print deterministic markers, exit with $FAKE_RC_<STAGE>. Everything else
(the ``sync`` command under test) delegates to the REAL package.
"""
import os
import sys

_STAGES = {"refresh", "lint", "status"}


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
    parent ``sync`` invocation and every ``[sys.executable, "-m",
    "shepherd_cli", "<stage>"]`` stage re-invocation import this fake
    package first. The fake handles stage subcommands deterministically
    (see ``_FAKE_MAIN``) and delegates ``sync`` itself to the real
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


def sync_env(
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd sync`` test.

    Args:
        call_log: Path the fake stage stand-ins append one line to per
            invocation (``$CALL_LOG``) — read back to assert which stages
            actually ran, in what order, with what argv.
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_REFRESH": "1"}``.

    Returns:
        A full subprocess environment ready for :func:`run_sync`.
        Deliberately does NOT set ``SHCTX_DB``/``SHEPHERD_WORKDIR`` to
        anything real — ``shepherd sync`` never resolves either (no
        database, no ``project.json`` read), so a bare
        stripped-then-rebuilt environment (``clean_env_dict()``, reached
        via ``cli_env`` with a throwaway db path never actually opened) is
        sufficient and keeps every test's environment minimal.
    """
    env = cli_env(call_log.parent / "unused.db")
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def run_sync(
    args: list[str],
    env: dict[str, str],
    fake_cli_root: Path,
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli sync ...`` with the fake package as cwd.

    ``conftest.run_cli`` pins ``cwd=CLI_ROOT`` (the real package), so this
    suite uses its own runner: the fake-cli-root cwd is exactly what makes
    the stage re-invocations resolve the fake stand-ins (see the module
    docstring).
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "sync", *args],
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


# --------------------------------------------------------------------------
# Default (no-args) invocation — bash parity: runs the full pipeline
# immediately, scope="all", verbose=0. NOT a usage screen.
# --------------------------------------------------------------------------


def test_bare_invocation_runs_full_pipeline_with_scope_all(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = sync_env(call_log)
    proc = run_sync([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=all  elapsed=" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  status:  ok" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "refresh --scope=all",
        "lint",
        "status",
    ]


def test_bare_invocation_non_verbose_suppresses_stage_output(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = sync_env(call_log)
    proc = run_sync([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:refresh" not in proc.stdout
    assert "stderr:refresh" not in proc.stderr
    assert "───" not in proc.stdout  # no "─── name ───" headers


# --------------------------------------------------------------------------
# --scope=<value> / --all.
# --------------------------------------------------------------------------


def test_scope_flag_forwarded_verbatim_to_refresh(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync(["--scope=github"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=github  elapsed=" in proc.stdout

    calls = read_calls(call_log)
    assert calls[0] == "refresh --scope=github"


def test_all_flag_is_alias_for_scope_all(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync(["--all"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=all  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "refresh --scope=all"


def test_last_of_scope_and_all_wins_scope_then_all(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash parity: plain variable reassignment in the ``for arg`` loop —
    ``--scope=github --all`` resolves to ``scope="all"`` (the later token
    wins)."""
    env = sync_env(call_log)
    proc = run_sync(["--scope=github", "--all"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=all  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "refresh --scope=all"


def test_last_of_scope_and_all_wins_all_then_scope(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash parity, opposite order: ``--all --scope=github`` resolves to
    ``scope="github"`` — the later token still wins."""
    env = sync_env(call_log)
    proc = run_sync(["--all", "--scope=github"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=github  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "refresh --scope=github"


def test_scope_value_is_never_validated(fake_cli_root: Path, call_log: Path) -> None:
    """Bash parity: cmd_sync.sh's ``--scope=*`` case arm accepts ANY
    value with no allow-list check — validation (if any) is the refresh
    stage's problem, not ``shepherd sync``'s."""
    env = sync_env(call_log)
    proc = run_sync(["--scope=bogus-scope"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=bogus-scope  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "refresh --scope=bogus-scope"


# --------------------------------------------------------------------------
# --verbose / -v.
# --------------------------------------------------------------------------


def test_verbose_streams_stage_output_with_headers(
    fake_cli_root: Path, call_log: Path
) -> None:
    env = sync_env(call_log)
    proc = run_sync(["--verbose"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── refresh ───" in proc.stdout
    assert "─── lint ───" in proc.stdout
    assert "─── status ───" in proc.stdout
    assert "stdout:refresh:--scope=all" in proc.stdout
    assert "stderr:refresh:--scope=all" in proc.stderr
    # The final bash-parity summary still prints after the streamed stages.
    assert "shctx sync: scope=all  elapsed=" in proc.stdout


def test_verbose_short_flag_is_equivalent(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync(["-v"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "─── refresh ───" in proc.stdout
    assert "stdout:refresh:--scope=all" in proc.stdout


# --------------------------------------------------------------------------
# Stage failure aggregation.
# --------------------------------------------------------------------------


def test_stage_failure_still_runs_every_later_stage_and_exits_1(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash parity: each rc_* is captured independently via ``run_stage
    ... || rc_*=$?`` — a failed early stage does NOT short-circuit later
    stages (no set -e-style abort)."""
    env = sync_env(call_log, rc={"FAKE_RC_REFRESH": "1", "FAKE_RC_STATUS": "3"})
    proc = run_sync([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  refresh: fail (rc=1)" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  status:  fail (rc=3)" in proc.stdout

    # Every stage still ran despite the first one failing.
    assert len(read_calls(call_log)) == 3


def test_all_stages_succeed_exits_0(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync([], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr


def test_lint_only_failure_exits_1(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log, rc={"FAKE_RC_LINT": "5"})
    proc = run_sync([], env, fake_cli_root)

    assert proc.returncode == 1
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    fail (rc=5)" in proc.stdout
    assert "  status:  ok" in proc.stdout


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------


def test_help_long_flag_prints_usage_and_exits_0(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync(["--help"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync [--scope=symbols|github|artifacts|all] [--all] [--verbose]" in proc.stdout
    assert "refresh → lint → status" in proc.stdout
    assert '--all is the canonical "all targets" alias (= --scope=all).' in proc.stdout
    # No pipeline stage ran at all.
    assert read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync(["-h"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync [--scope=symbols|github|artifacts|all]" in proc.stdout
    assert read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_other_flags(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash parity: the ``for arg`` loop reaches ``-h``/``--help`` and
    exits immediately, regardless of what earlier flags already set —
    ``shepherd sync`` never reaches the pipeline stages once ``-h``/
    ``--help`` is seen, from any position."""
    env = sync_env(call_log)
    proc = run_sync(["--scope=github", "--verbose", "-h"], env, fake_cli_root)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync [--scope=symbols|github|artifacts|all]" in proc.stdout
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_cli_root: Path, call_log: Path) -> None:
    env = sync_env(call_log)
    proc = run_sync(["--bogus"], env, fake_cli_root)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


def test_bare_scope_without_equals_is_unknown_arg(
    fake_cli_root: Path, call_log: Path
) -> None:
    """``--scope`` (no ``=value``) does not match bash's ``--scope=*``
    case pattern and falls through to the catch-all ``*)`` arm."""
    env = sync_env(call_log)
    proc = run_sync(["--scope"], env, fake_cli_root)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --scope" in proc.stderr
    assert read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_cli_root: Path, call_log: Path) -> None:
    """``shepherd sync`` takes no positional arguments — any bare token is
    an unknown arg, exit 1."""
    env = sync_env(call_log)
    proc = run_sync(["symbols"], env, fake_cli_root)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: symbols" in proc.stderr
    assert read_calls(call_log) == []


def test_unknown_arg_short_circuits_before_later_tokens_are_seen(
    fake_cli_root: Path, call_log: Path
) -> None:
    """Bash parity: the loop hits the bad token and ``exit 1``s
    immediately — a later, otherwise-valid ``--verbose`` never gets a
    chance to matter."""
    env = sync_env(call_log)
    proc = run_sync(["--bogus", "--verbose"], env, fake_cli_root)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# _run_stage() launch-failure mode.
# --------------------------------------------------------------------------

_RUN_STAGE_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.sync import _run_stage\n"
    "print(_run_stage('probe', [sys.argv[1]], sys.argv[2] == 'verbose'))\n"
)


@pytest.mark.parametrize("mode", ["quiet", "verbose"])
def test_unlaunchable_stage_counts_as_rc_127(tmp_path: Path, mode: str) -> None:
    """A stage that cannot be launched at all (OSError from process
    creation — the moral equivalent of bash's missing/unexecutable
    ``cmd_*.sh``) maps to rc 127, the shell's own command-not-found code,
    instead of crashing the pipeline. Driven via a ``-c`` snippet in a
    fresh subprocess (the test_panes.py private-helper pattern) since a
    real ``sys.executable`` can't be made to vanish from inside a
    subprocess-driven test."""
    env = cli_env(tmp_path / "unused.db")
    proc = subprocess.run(
        [PY, "-c", _RUN_STAGE_SNIPPET, str(tmp_path / "no-such-interpreter"), mode],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[-1] == "127"
