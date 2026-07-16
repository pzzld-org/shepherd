"""Subprocess parity tests for ``shepherd sync`` (refresh -> lint -> status pipeline).

Bash parity target: ``skills/context/scripts/cmd_sync.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli sync ...``),
exactly like ``test_sprint.py`` — never by importing ``shepherd_cli`` into
the pytest process.

``cmd_sync.sh`` is an ORCHESTRATION script with NO subcommands and NO
database access of its own: it shells out to three sibling scripts
(``cmd_refresh.sh``, ``cmd_lint.sh``, ``cmd_status.sh``), each of which may
touch the network (``gh``) or the database on its own terms, but
``cmd_sync.sh`` itself only times them and aggregates exit codes. Driving
the REAL sibling scripts from a gate test would violate the
"deterministic, local, free, <2s, never flaky" gate-test contract
(CLAUDE.md). Per that same contract's latent-vs-deterministic split, this
suite builds a throwaway "fake plugin root" (see :func:`fake_plugin_root`)
containing tiny, fully-scripted stand-ins for all three sibling scripts —
each one logs its invocation to ``$CALL_LOG`` and exits with a
caller-controlled code (via ``FAKE_RC_*`` env vars) — and points
``CLAUDE_PLUGIN_ROOT`` at it. This gives full, fast, deterministic control
over every stage's exit code and stdout/stderr, letting the tests below
pin down ``shepherd sync``'s OWN contract exactly: which argv it invokes
each stage with, in what order, in what shape (``run_stage``'s
verbose-vs-suppressed output handling), how it resolves ``--scope``/
``--all``/``--verbose``/``-v``/``-h``/``--help``/unknown-arg, and how it
aggregates per-stage exit codes into its own final exit code and summary
text — all bash-parity concerns that belong to ``cmd_sync.sh``, not to any
of the three scripts it calls.

No fixture database is built anywhere in this suite: ``shepherd sync``
never opens a Tortoise connection, never calls
:func:`shepherd_cli.resolution.resolve_db_path`, and the fixture DB
helpers in ``conftest.py`` (``build_full_schema_db`` etc.) are therefore
never needed here — the only shared helpers reused are ``cli_env`` (for
the sync-tooling-not-found test's stripped baseline environment),
``run_cli``, and ``PY``.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest
from conftest import PY, cli_env, run_cli

# --------------------------------------------------------------------------
# Fake sibling scripts — deterministic stand-ins for cmd_refresh.sh,
# cmd_lint.sh, cmd_status.sh.
# --------------------------------------------------------------------------

_STUB_PREAMBLE = '#!/usr/bin/env bash\necho "{name} $*" >> "$CALL_LOG"\n'

_FAKE_SCRIPTS: dict[str, str] = {
    "cmd_refresh.sh": _STUB_PREAMBLE.format(name="cmd_refresh.sh")
    + (
        'echo "stdout:cmd_refresh.sh:$*"\n'
        'echo "stderr:cmd_refresh.sh:$*" >&2\n'
        'exit "${FAKE_RC_REFRESH:-0}"\n'
    ),
    "cmd_lint.sh": _STUB_PREAMBLE.format(name="cmd_lint.sh")
    + ('echo "stdout:cmd_lint.sh"\necho "stderr:cmd_lint.sh" >&2\nexit "${FAKE_RC_LINT:-0}"\n'),
    "cmd_status.sh": _STUB_PREAMBLE.format(name="cmd_status.sh")
    + ('echo "stdout:cmd_status.sh"\necho "stderr:cmd_status.sh" >&2\nexit "${FAKE_RC_STATUS:-0}"\n'),
}


def _make_fake_plugin_root(tmp_path: Path) -> Path:
    """Build a throwaway ``CLAUDE_PLUGIN_ROOT`` tree with fully-scripted sibling commands.

    Layout mirrors the real plugin just enough for
    :func:`shepherd_cli.resolution.find_bash_shctx` to resolve it:
    ``skills/context/scripts/{shctx, cmd_refresh.sh, cmd_lint.sh,
    cmd_status.sh}``. ``shctx`` itself only needs to exist as a file (its
    dirname is all ``shepherd sync`` ever uses via ``_scripts_dir()``);
    the three ``cmd_*.sh`` stand-ins are real, executable, deterministic
    bash scripts (see ``_FAKE_SCRIPTS``).

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


def sync_env(
    fake_plugin_root: Path,
    call_log: Path,
    *,
    rc: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd sync`` test.

    Args:
        fake_plugin_root: The fake plugin root from
            :func:`_make_fake_plugin_root`, wired in as
            ``CLAUDE_PLUGIN_ROOT`` so ``find_bash_shctx()`` (and therefore
            ``_scripts_dir()``) resolves to the fake sibling scripts
            instead of the real, network-dependent ones.
        call_log: Path the fake sibling scripts append one line to per
            invocation (``$CALL_LOG``) — read back to assert which stages
            actually ran, in what order, with what argv.
        rc: ``FAKE_RC_*`` overrides, e.g. ``{"FAKE_RC_REFRESH": "1"}``.

    Returns:
        A full subprocess environment ready for :func:`conftest.run_cli`.
        Deliberately does NOT set ``SHCTX_DB``/``SHEPHERD_WORKDIR`` —
        ``shepherd sync`` never resolves either (no database, and
        ``cmd_sync.sh`` never reads ``project.json``), so a bare
        stripped-then-rebuilt environment (``clean_env_dict()``, reached
        via ``cli_env`` with a throwaway db path never actually opened) is
        sufficient and keeps every test's environment minimal.
    """
    env = cli_env(fake_plugin_root / "unused.db")
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
    env["CALL_LOG"] = str(call_log)
    for key, value in (rc or {}).items():
        env[key] = value
    return env


def read_calls(call_log: Path) -> list[str]:
    """Read back every logged stage invocation, in call order.

    Each line is right-stripped: ``cmd_lint.sh``/``cmd_status.sh`` are
    invoked with no arguments, which would otherwise leave a trailing
    space in the stub's ``"name $*"`` format when ``$*`` expands to
    nothing — cosmetic, not a signal worth asserting on.
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


# --------------------------------------------------------------------------
# Default (no-args) invocation — bash parity: runs the full pipeline
# immediately, scope="all", verbose=0. NOT a usage screen.
# --------------------------------------------------------------------------


def test_bare_invocation_runs_full_pipeline_with_scope_all(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=all  elapsed=" in proc.stdout
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  status:  ok" in proc.stdout

    calls = read_calls(call_log)
    assert calls == [
        "cmd_refresh.sh --scope=all",
        "cmd_lint.sh",
        "cmd_status.sh",
    ]


def test_bare_invocation_non_verbose_suppresses_stage_output(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync"], env)

    assert proc.returncode == 0, proc.stderr
    assert "stdout:cmd_refresh.sh" not in proc.stdout
    assert "stderr:cmd_refresh.sh" not in proc.stderr
    assert "───" not in proc.stdout  # no "─── name ───" headers


# --------------------------------------------------------------------------
# --scope=<value> / --all.
# --------------------------------------------------------------------------


def test_scope_flag_forwarded_verbatim_to_refresh(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=github  elapsed=" in proc.stdout

    calls = read_calls(call_log)
    assert calls[0] == "cmd_refresh.sh --scope=github"


def test_all_flag_is_alias_for_scope_all(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=all  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "cmd_refresh.sh --scope=all"


def test_last_of_scope_and_all_wins_scope_then_all(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash parity: plain variable reassignment in the ``for arg`` loop —
    ``--scope=github --all`` resolves to ``scope="all"`` (the later token
    wins)."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--scope=github", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=all  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "cmd_refresh.sh --scope=all"


def test_last_of_scope_and_all_wins_all_then_scope(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash parity, opposite order: ``--all --scope=github`` resolves to
    ``scope="github"`` — the later token still wins."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--all", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=github  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "cmd_refresh.sh --scope=github"


def test_scope_value_is_never_validated(fake_plugin_root: Path, call_log: Path) -> None:
    """Bash parity: cmd_sync.sh's ``--scope=*`` case arm accepts ANY
    value with no allow-list check — validation (if any) is
    cmd_refresh.sh's problem, not cmd_sync.sh's."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--scope=bogus-scope"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync: scope=bogus-scope  elapsed=" in proc.stdout
    assert read_calls(call_log)[0] == "cmd_refresh.sh --scope=bogus-scope"


# --------------------------------------------------------------------------
# --verbose / -v.
# --------------------------------------------------------------------------


def test_verbose_streams_stage_output_with_headers(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--verbose"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── refresh ───" in proc.stdout
    assert "─── lint ───" in proc.stdout
    assert "─── status ───" in proc.stdout
    assert "stdout:cmd_refresh.sh:--scope=all" in proc.stdout
    assert "stderr:cmd_refresh.sh:--scope=all" in proc.stderr
    # The final bash-parity summary still prints after the streamed stages.
    assert "shctx sync: scope=all  elapsed=" in proc.stdout


def test_verbose_short_flag_is_equivalent(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "-v"], env)

    assert proc.returncode == 0, proc.stderr
    assert "─── refresh ───" in proc.stdout
    assert "stdout:cmd_refresh.sh:--scope=all" in proc.stdout


# --------------------------------------------------------------------------
# Stage failure aggregation.
# --------------------------------------------------------------------------


def test_stage_failure_still_runs_every_later_stage_and_exits_1(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash parity: each rc_* is captured independently via ``run_stage
    ... || rc_*=$?`` — a failed early stage does NOT short-circuit later
    stages (no set -e-style abort)."""
    env = sync_env(fake_plugin_root, call_log, rc={"FAKE_RC_REFRESH": "1", "FAKE_RC_STATUS": "3"})
    proc = run_cli(["sync"], env)

    assert proc.returncode == 1
    assert "  refresh: fail (rc=1)" in proc.stdout
    assert "  lint:    ok" in proc.stdout
    assert "  status:  fail (rc=3)" in proc.stdout

    # Every stage still ran despite the first one failing.
    assert len(read_calls(call_log)) == 3


def test_all_stages_succeed_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync"], env)

    assert proc.returncode == 0, proc.stderr


def test_lint_only_failure_exits_1(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log, rc={"FAKE_RC_LINT": "5"})
    proc = run_cli(["sync"], env)

    assert proc.returncode == 1
    assert "  refresh: ok" in proc.stdout
    assert "  lint:    fail (rc=5)" in proc.stdout
    assert "  status:  ok" in proc.stdout


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------


def test_help_long_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--help"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync [--scope=symbols|github|artifacts|all] [--all] [--verbose]" in proc.stdout
    assert "refresh → lint → status" in proc.stdout
    assert '--all is the canonical "all targets" alias (= --scope=all).' in proc.stdout
    # No pipeline stage ran at all.
    assert read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync [--scope=symbols|github|artifacts|all]" in proc.stdout
    assert read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_other_flags(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash parity: the ``for arg`` loop reaches ``-h``/``--help`` and
    exits immediately, regardless of what earlier flags already set —
    ``cmd_sync.sh`` never reaches the pipeline stages once ``-h``/
    ``--help`` is seen, from any position."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--scope=github", "--verbose", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx sync [--scope=symbols|github|artifacts|all]" in proc.stdout
    assert read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_plugin_root: Path, call_log: Path) -> None:
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown arg: --bogus" in proc.stderr
    assert read_calls(call_log) == []


def test_bare_scope_without_equals_is_unknown_arg(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """``--scope`` (no ``=value``) does not match bash's ``--scope=*``
    case pattern and falls through to the catch-all ``*)`` arm."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--scope"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --scope" in proc.stderr
    assert read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    """``cmd_sync.sh`` takes no positional arguments — any bare token is
    an unknown arg, exit 1."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "symbols"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: symbols" in proc.stderr
    assert read_calls(call_log) == []


def test_unknown_arg_short_circuits_before_later_tokens_are_seen(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """Bash parity: the loop hits the bad token and ``exit 1``s
    immediately — a later, otherwise-valid ``--verbose`` never gets a
    chance to matter."""
    env = sync_env(fake_plugin_root, call_log)
    proc = run_cli(["sync", "--bogus", "--verbose"], env)

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

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "sync"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    assert "ERROR: bash shctx tooling not found" in proc.stderr
