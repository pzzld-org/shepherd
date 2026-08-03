"""Subprocess parity tests for ``shepherd refresh`` (cache-rebuild pipeline).

Bash parity target: ``skills/context/scripts/cmd_refresh.sh``. Every test
drives the real CLI as a subprocess (``${PY} -m shepherd_cli refresh ...``),
exactly like ``test_sync.py``/``test_audit.py``.

The pipeline is fully NATIVE now — ``symbols``/``github``/``artifacts``
run :mod:`shepherd_cli.refresh_impl`'s in-process ports of the former
``refresh-*.sh`` scripts, and ``shapes`` dispatches into the
:mod:`shepherd_cli.commands.dups` module in-process (which itself runs the
package-resident engine as ``[sys.executable, "-m",
"shepherd_cli.dups_core", ...]`` — a child of THIS interpreter, not bash).
This suite therefore pins down three concerns:

1. **The dispatcher's own contract** — flag parsing, the two distinct
   error paths (unknown arg vs unknown ``--scope``), single-scope
   exit-code propagation, and ``--scope=all``'s fixed order + always-0
   exit + per-stage failure isolation.
2. **That no bash sibling script is EVER executed.** A fake plugin root
   containing canary ``refresh-*.sh``/``cmd_dups.sh`` scripts (each logs
   to ``$CALL_LOG`` if run) is wired in; the tests assert the log stays
   empty — nothing in the pipeline touches the retired bash layer.
3. **The NATIVE ``telemetry`` zone** — driven against a REAL full-schema
   fixture DB (``build_full_schema_db`` + ``insert_project``, exactly like
   ``test_query.py``) with a real ``<workdir>/logs/events-*.jsonl`` file on
   disk, asserting on both the printed row count AND the actual
   ``index_cache_usage`` rows written.

Stage BEHAVIOR (which rows the symbols/github/artifacts zones write, the
gh retry loop, graceful tool absence with real fixture data) lives in
``test_refresh_impl.py`` — this file only needs each zone's cheapest
deterministic success/failure lever: a stub ``cargo``/``gh`` on ``PATH``,
the presence/absence of ``<workdir>/project.json``, and (for ``shapes``)
a poisoned ``[dups]`` config value that makes the real engine's own
``argparse`` reject its argv (exit 2) — the engine itself is exercised
end-to-end in :func:`test_scope_shapes_runs_the_real_engine_end_to_end`.

Like ``test_query.py``, ``shctx refresh`` resolves its project id from a
``<workdir>/project.json`` FILE (``_lib.sh``'s ``shctx_project_id``) — a
DIFFERENT location than the fixture DB whenever ``SHCTX_DB`` points at a
specific file. Every stateful test therefore sets ``SHEPHERD_WORKDIR`` to
an isolated tmp directory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest
from conftest import PY, build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Stub external binaries (cargo / gh) + the fake plugin root with bash
# CANARIES and a scripted dups-core.py.
# --------------------------------------------------------------------------

#: Canary bash scripts — the pipeline must NEVER execute these. Each one
#: would log a plainly-identifiable line to ``$CALL_LOG`` if it ever ran.
_BASH_CANARY_NAMES = ("refresh-symbols.sh", "refresh-github.sh", "refresh-artifacts.sh", "cmd_dups.sh")

#: cargo stub whose ``metadata`` output contains zero packages — the
#: symbols zone's cheapest deterministic SUCCESS ("no rust packages found").
_CARGO_EMPTY_STUB = '#!/usr/bin/env bash\nprintf \'{"packages":[]}\\n\'\n'

#: gh stub serving empty listings for every stage — the github zone's
#: cheapest deterministic SUCCESS. ``FAKE_RC_GITHUB`` flips it to a
#: non-transient failure (stderr text carries no transient marker).
_GH_EMPTY_STUB = (
    "#!/usr/bin/env bash\n"
    'if [ "${FAKE_RC_GITHUB:-0}" != "0" ]; then echo "stub gh: hard failure" >&2; exit "$FAKE_RC_GITHUB"; fi\n'
    'case "$1" in\n'
    '  repo) echo "stub-owner/stub-repo" ;;\n'
    '  issue|pr|release|api) echo "[]" ;;\n'
    "esac\n"
    "exit 0\n"
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _make_fake_plugin_root(tmp_path: Path) -> Path:
    """Build a throwaway ``CLAUDE_PLUGIN_ROOT`` tree of bash CANARIES.

    Layout mirrors the real plugin just enough for
    :func:`shepherd_cli.resolution.find_bash_shctx` to resolve it:
    ``skills/context/scripts/{shctx, <bash canaries>}`` — every script the
    OLD subprocess-orchestration code would have located and executed sits
    exactly where it used to look, ready to scream into ``$CALL_LOG`` if
    anything ever runs it.

    Args:
        tmp_path: The pytest-provided per-test temp directory.

    Returns:
        The fake plugin root directory (the ``CLAUDE_PLUGIN_ROOT`` value),
        three levels above ``skills/context/scripts``.
    """
    scripts_dir = tmp_path / "fake-plugin-root" / "skills" / "context" / "scripts"
    scripts_dir.mkdir(parents=True)

    _write_executable(scripts_dir / "shctx", "#!/usr/bin/env bash\nexit 0\n")
    for name in _BASH_CANARY_NAMES:
        _write_executable(
            scripts_dir / name,
            f'#!/usr/bin/env bash\necho "BASH-CANARY {name} $*" >> "$CALL_LOG"\nexit 0\n',
        )
    return scripts_dir.parent.parent.parent


def _make_stub_bin(tmp_path: Path, *, cargo: bool = False, gh: bool = False) -> Path:
    """A PATH-prefix directory holding stub ``cargo``/``gh`` executables."""
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    if cargo:
        _write_executable(bin_dir / "cargo", _CARGO_EMPTY_STUB)
    if gh:
        _write_executable(bin_dir / "gh", _GH_EMPTY_STUB)
    return bin_dir


def _pipeline_env(
    fake_plugin_root: Path,
    call_log: Path,
    *,
    bin_dir: Path | None = None,
    bare_path: bool = False,
    workdir: Path | None = None,
    project_id: str | None = None,
    db: Path | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd refresh`` test.

    Args:
        fake_plugin_root: Wired in as ``CLAUDE_PLUGIN_ROOT`` so the dups
            module resolves the fake ``dups-core.py`` (and the bash
            canaries sit where the old subprocess code would have looked).
        call_log: Path the canaries/dups-core stub append to.
        bin_dir: When given, prepended to ``PATH`` (stub cargo/gh).
        bare_path: When True, ``PATH`` is REPLACED by ``bin_dir`` (or an
            empty dir) — drives the which()-based graceful-absence
            branches deterministically.
        workdir: When given, sets ``SHEPHERD_WORKDIR``.
        project_id: When given (and ``workdir`` is set), writes
            ``<workdir>/project.json`` with this id.
        db: The ``SHCTX_DB`` fixture DB; defaults to a nonexistent path.
        extra: Additional env vars (e.g. ``FAKE_RC_SHAPES``).

    Returns:
        A full subprocess environment ready for :func:`conftest.run_cli`.
    """
    env = cli_env(db if db is not None else fake_plugin_root / "unused.db")
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
    env["CALL_LOG"] = str(call_log)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}" if not bare_path else str(bin_dir)
    elif bare_path:
        empty = fake_plugin_root / "empty-bin"
        empty.mkdir(exist_ok=True)
        env["PATH"] = str(empty)
    if workdir is not None:
        workdir.mkdir(parents=True, exist_ok=True)
        env["SHEPHERD_WORKDIR"] = str(workdir)
        if project_id is not None:
            (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    for key, value in (extra or {}).items():
        env[key] = value
    return env


def _read_calls(call_log: Path) -> list[str]:
    """Read back every logged invocation, in call order."""
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


def _assert_no_bash_canary(call_log: Path) -> None:
    """The load-bearing native-port assertion: no bash sibling script ever ran."""
    assert [line for line in _read_calls(call_log) if line.startswith("BASH-CANARY")] == []


@pytest.fixture
def fake_plugin_root(tmp_path: Path) -> Path:
    return _make_fake_plugin_root(tmp_path)


@pytest.fixture
def call_log(tmp_path: Path) -> Path:
    """Path the canaries and the dups-core stub append their invocations to."""
    return tmp_path / "calls.log"


# --------------------------------------------------------------------------
# -h / --help.
# --------------------------------------------------------------------------


def test_help_long_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--help"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == (
        "shctx refresh [--scope=symbols|shapes|github|artifacts|telemetry|all] [--all]\n"
        "\n"
        "  --scope=NAME  refresh a single zone\n"
        "                  symbols   — index public symbols from the workspace\n"
        "                  shapes    — index public struct/enum FIELD SHAPES for `dups` (v6.1.8 #157)\n"
        "                  github    — issues / PRs / releases / milestones via gh\n"
        "                  artifacts — markdown specs / plans / handoffs / journal\n"
        "                  telemetry — cache-usage events from <ns>/logs/events-*.jsonl (v5.1.3+)\n"
        "                  all       — every zone above (default)\n"
        "  --all         alias for --scope=all (canonical universal flag, v5.0.4)"
    )
    assert _read_calls(call_log) == []


def test_help_short_flag_prints_usage_and_exits_0(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh [--scope=symbols|shapes|github|artifacts|telemetry|all]" in proc.stdout
    assert _read_calls(call_log) == []


def test_help_flag_short_circuits_even_after_other_flags(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope=github", "-h"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh [--scope=" in proc.stdout
    assert _read_calls(call_log) == []


# --------------------------------------------------------------------------
# Unknown arg / unknown --scope — two DIFFERENT error paths.
# --------------------------------------------------------------------------


def test_unknown_arg_exits_1_with_error(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"
    assert _read_calls(call_log) == []


def test_verbose_flag_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    """Unlike ``cmd_sync.sh``, ``cmd_refresh.sh`` has no ``--verbose``/``-v`` flag."""
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "-v"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: -v" in proc.stderr
    assert _read_calls(call_log) == []


def test_bare_scope_without_equals_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --scope" in proc.stderr
    assert _read_calls(call_log) == []


def test_positional_token_is_unknown_arg(fake_plugin_root: Path, call_log: Path) -> None:
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "symbols"], env)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: symbols" in proc.stderr
    assert _read_calls(call_log) == []


def test_unknown_scope_value_exits_1_at_dispatch_not_parse(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """``--scope=bogus`` parses fine (any string matches ``--scope=*``); it
    only fails later, at dispatch — a textually DIFFERENT error than an
    unrecognized ARG token."""
    env = _pipeline_env(fake_plugin_root, call_log)
    proc = run_cli(["refresh", "--scope=bogus"], env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown --scope: bogus"
    assert _read_calls(call_log) == []


# --------------------------------------------------------------------------
# Single-scope: symbols — native zone, graceful cargo absence, project.json
# gate, exit-code propagation. (Row-level behavior: test_refresh_impl.py.)
# --------------------------------------------------------------------------


def test_scope_symbols_without_cargo_skips_and_exits_0(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log, bare_path=True)
    proc = run_cli(["refresh", "--scope=symbols"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx: cargo not installed; skipping rust symbols"
    _assert_no_bash_canary(call_log)


def test_scope_symbols_missing_project_json_exits_1(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _pipeline_env(
        fake_plugin_root, call_log, bin_dir=_make_stub_bin(tmp_path, cargo=True), workdir=workdir
    )
    proc = run_cli(["refresh", "--scope=symbols"], env)

    assert proc.returncode == 1
    pjson = workdir / "project.json"
    assert proc.stderr.rstrip("\n") == f"ERROR: {pjson} missing — run 'shctx init' first"
    _assert_no_bash_canary(call_log)


def test_scope_symbols_no_rust_packages_exits_0(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    env = _pipeline_env(
        fake_plugin_root,
        call_log,
        bin_dir=_make_stub_bin(tmp_path, cargo=True),
        workdir=tmp_path / "wd",
        project_id="proj-a",
    )
    proc = run_cli(["refresh", "--scope=symbols"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx: no rust packages found"
    _assert_no_bash_canary(call_log)


# --------------------------------------------------------------------------
# Single-scope: github — native zone, graceful gh absence, project.json
# gate. (Row-level behavior + retry loop: test_refresh_impl.py.)
# --------------------------------------------------------------------------


def test_scope_github_without_gh_skips_and_exits_0(
    fake_plugin_root: Path, call_log: Path
) -> None:
    env = _pipeline_env(fake_plugin_root, call_log, bare_path=True)
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx: gh CLI not installed; skipping github refresh"
    _assert_no_bash_canary(call_log)


def test_scope_github_missing_project_json_exits_1(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _pipeline_env(
        fake_plugin_root, call_log, bin_dir=_make_stub_bin(tmp_path, gh=True), workdir=workdir
    )
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 1
    pjson = workdir / "project.json"
    assert proc.stderr.rstrip("\n") == f"ERROR: {pjson} missing — run 'shctx init' first"
    _assert_no_bash_canary(call_log)


def test_scope_github_success_with_stub_gh(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    env = _pipeline_env(
        fake_plugin_root,
        call_log,
        bin_dir=_make_stub_bin(tmp_path, gh=True),
        workdir=tmp_path / "wd",
        project_id="proj-a",
        db=db_path,
    )
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh github: ok"
    _assert_no_bash_canary(call_log)


def test_scope_github_propagates_nonzero_exit_code(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    env = _pipeline_env(
        fake_plugin_root,
        call_log,
        bin_dir=_make_stub_bin(tmp_path, gh=True),
        workdir=tmp_path / "wd",
        project_id="proj-a",
        extra={"FAKE_RC_GITHUB": "7"},
    )
    proc = run_cli(["refresh", "--scope=github"], env)

    assert proc.returncode == 7
    assert "stub gh: hard failure" in proc.stderr
    _assert_no_bash_canary(call_log)


# --------------------------------------------------------------------------
# Single-scope: artifacts — native zone. (Row-level behavior:
# test_refresh_impl.py.)
# --------------------------------------------------------------------------


def test_scope_artifacts_missing_project_json_exits_1(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _pipeline_env(fake_plugin_root, call_log, workdir=workdir)
    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 1
    pjson = workdir / "project.json"
    assert proc.stderr.rstrip("\n") == f"ERROR: {pjson} missing — run 'shctx init' first"
    _assert_no_bash_canary(call_log)


def test_scope_artifacts_indexes_markdown_natively(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    workdir = tmp_path / "wd"
    plans = workdir / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "foo.plan.md").write_text("# Hello Plan\n")
    env = _pipeline_env(fake_plugin_root, call_log, workdir=workdir, project_id="proj-a", db=db_path)

    proc = run_cli(["refresh", "--scope=artifacts"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh artifacts: ok"
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT kind, title FROM artifacts;").fetchall()
    finally:
        conn.close()
    assert rows == [("plan", "Hello Plan")]
    _assert_no_bash_canary(call_log)


# --------------------------------------------------------------------------
# Single-scope: shapes — in-process dups dispatch running the REAL
# shepherd_cli.dups_core engine (bash's refresh_shapes() helper semantics:
# the "ok" line only on success).
# --------------------------------------------------------------------------


def _run_refresh_at(args: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """``run_cli`` with a caller-chosen cwd — needed when a test must control
    ``resolve_repo_root()``'s non-git getcwd() fallback (the dups scan reads
    its ``[dups]`` config from the REPO root, not the workdir)."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "refresh", *args],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_scope_shapes_success_prints_ok_line(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    env = _pipeline_env(fake_plugin_root, call_log, workdir=tmp_path / "wd", project_id="proj-a", db=db_path)
    proc = run_cli(["refresh", "--scope=shapes"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh shapes: ok" in proc.stdout
    _assert_no_bash_canary(call_log)


def test_scope_shapes_runs_the_real_engine_end_to_end(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    """``--scope=shapes`` drives the real ``shepherd_cli.dups_core`` engine
    (``scan --update --quiet``): rust struct shapes in the repo land in
    ``index_struct_shapes`` — proof the whole in-process chain (refresh ->
    dups dispatch -> engine subprocess of THIS interpreter) works."""
    repo = tmp_path / "fakerepo"
    repo.mkdir()
    (repo / "shapes.rs").write_text(
        "pub struct Alpha { pub id: u64, pub name: String, pub created_at: i64 }\n"
        "pub struct Beta { pub id: u64, pub name: String, pub updated_at: i64 }\n"
    )
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    env = _pipeline_env(fake_plugin_root, call_log, workdir=tmp_path / "wd", project_id="proj-a", db=db_path)

    proc = _run_refresh_at(["--scope=shapes"], env, repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh shapes: ok" in proc.stdout
    conn = sqlite3.connect(str(db_path))
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM index_struct_shapes")}
    finally:
        conn.close()
    assert {"Alpha", "Beta"} <= names
    _assert_no_bash_canary(call_log)


def test_scope_shapes_failure_suppresses_ok_line_and_propagates_rc(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    """A poisoned ``dups_threshold`` config value makes the engine's own
    ``argparse`` reject ``--threshold`` (exit 2) — the shapes zone
    propagates that code and never prints the "ok" line (bash: ``set -e``
    aborting ``refresh_shapes()`` before its echo)."""
    repo = tmp_path / "fakerepo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "shepherd.toml").write_text('dups_threshold = "not-a-number"\n')
    env = _pipeline_env(fake_plugin_root, call_log, workdir=tmp_path / "wd", project_id="proj-a")

    proc = _run_refresh_at(["--scope=shapes"], env, repo)

    assert proc.returncode == 2
    assert "shctx refresh shapes: ok" not in proc.stdout
    _assert_no_bash_canary(call_log)


# --------------------------------------------------------------------------
# --scope=all: fixed order, every stage always runs, exit code ALWAYS 0.
# --------------------------------------------------------------------------


def _all_happy_env(fake_plugin_root: Path, call_log: Path, tmp_path: Path) -> dict[str, str]:
    """An environment where every one of the five zones succeeds."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    return _pipeline_env(
        fake_plugin_root,
        call_log,
        bin_dir=_make_stub_bin(tmp_path, cargo=True, gh=True),
        workdir=tmp_path / "wd",  # project.json present, no logs/ dir -> telemetry skip line
        project_id="proj-a",
        db=db_path,
    )


def test_bare_invocation_defaults_to_scope_all_in_fixed_order(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    env = _all_happy_env(fake_plugin_root, call_log, tmp_path)
    proc = run_cli(["refresh"], env)

    assert proc.returncode == 0, proc.stderr
    # Every zone succeeded, in bash's fixed order.
    markers = [
        "shctx: no rust packages found",  # symbols (empty-metadata cargo stub)
        "shctx refresh shapes: ok",
        "shctx refresh github: ok",
        "shctx refresh artifacts: ok",
        "shctx refresh telemetry: no log dir at",
    ]
    positions = [proc.stdout.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert "refresh failed (continuing)" not in proc.stderr
    _assert_no_bash_canary(call_log)


def test_scope_all_continues_after_every_stage_fails_and_exits_0(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    # No project.json -> symbols/github/artifacts/telemetry each fail at
    # their own project-id gate; a poisoned dups_threshold config in the
    # (non-git, cwd-resolved) repo root fails the shapes engine's argparse.
    repo = tmp_path / "fakerepo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "shepherd.toml").write_text('dups_threshold = "not-a-number"\n')
    env = _pipeline_env(
        fake_plugin_root,
        call_log,
        bin_dir=_make_stub_bin(tmp_path, cargo=True, gh=True),
        workdir=tmp_path / "wd",
    )
    proc = _run_refresh_at(["--scope=all"], env, repo)

    assert proc.returncode == 0, proc.stderr
    for label in ("symbols", "shapes", "github", "artifacts", "telemetry"):
        assert f"shctx: {label} refresh failed (continuing)" in proc.stderr
    assert "shctx refresh shapes: ok" not in proc.stdout
    _assert_no_bash_canary(call_log)


def test_scope_all_isolates_a_single_failing_stage(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    env = _all_happy_env(fake_plugin_root, call_log, tmp_path)
    env["FAKE_RC_GITHUB"] = "3"
    proc = run_cli(["refresh", "--scope=all"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx: github refresh failed (continuing)" in proc.stderr
    assert "shctx: symbols refresh failed (continuing)" not in proc.stderr
    assert "shctx: shapes refresh failed (continuing)" not in proc.stderr
    assert "shctx: artifacts refresh failed (continuing)" not in proc.stderr
    assert "shctx: telemetry refresh failed (continuing)" not in proc.stderr
    # The stages after github still ran.
    assert "shctx refresh artifacts: ok" in proc.stdout
    assert "shctx refresh telemetry: no log dir at" in proc.stdout
    _assert_no_bash_canary(call_log)


def test_all_flag_then_scope_symbols_dispatches_symbols_only(
    fake_plugin_root: Path, call_log: Path
) -> None:
    """``--all --scope=symbols`` — the LAST token wins (plain reassignment)."""
    env = _pipeline_env(fake_plugin_root, call_log, bare_path=True)  # no cargo -> skip line
    proc = run_cli(["refresh", "--all", "--scope=symbols"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx: cargo not installed; skipping rust symbols"
    assert "shapes" not in proc.stdout


def test_scope_symbols_then_all_resolves_to_all(
    fake_plugin_root: Path, call_log: Path, tmp_path: Path
) -> None:
    env = _all_happy_env(fake_plugin_root, call_log, tmp_path)
    proc = run_cli(["refresh", "--scope=symbols", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx refresh shapes: ok" in proc.stdout
    assert "shctx refresh github: ok" in proc.stdout
    assert "shctx refresh artifacts: ok" in proc.stdout
    _assert_no_bash_canary(call_log)


# --------------------------------------------------------------------------
# telemetry — native zone, real DB + real events-*.jsonl fixtures.
# --------------------------------------------------------------------------


def _telemetry_env(
    db_path: Path,
    workdir: Path,
    *,
    project_id: str = "proj-a",
    write_project_json: bool = True,
) -> dict[str, str]:
    """The environment for driving ``shepherd refresh --scope=telemetry``.

    Args:
        db_path: The sqlite file (``SHCTX_DB`` via :func:`cli_env`) —
            independent of ``workdir``, exactly like ``test_query.py``'s
            ``query_env``.
        workdir: An isolated tmp directory (``SHEPHERD_WORKDIR``) —
            ``project.json`` and ``logs/events-*.jsonl`` both live here.
        project_id: The id written into ``project.json``'s ``"id"`` field.
        write_project_json: When False, no ``project.json`` is written
            (drives the "not initialized" error path).

    Returns:
        A full subprocess environment.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


@pytest.fixture
def telemetry_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path, project_id="proj-a")
    return db_path


def _read_cache_usage_rows(db_path: Path) -> list[dict[str, object]]:
    """Read back every ``index_cache_usage`` row, PRAGMA table_info tolerant."""
    conn = sqlite3.connect(str(db_path))
    try:
        columns = [info[1] for info in conn.execute("PRAGMA table_info(index_cache_usage)")]
        rows = conn.execute(f"SELECT {', '.join(columns)} FROM index_cache_usage ORDER BY id").fetchall()  # noqa: S608
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def test_telemetry_missing_project_json_exits_1(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir, write_project_json=False)

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 1
    pjson = workdir / "project.json"
    assert proc.stderr.rstrip("\n") == f"ERROR: {pjson} missing — run 'shctx init' first"
    assert proc.stdout == ""


def test_telemetry_no_log_dir_skips_and_exits_0(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == f"shctx refresh telemetry: no log dir at {workdir}/logs (skipping)"
    assert _read_cache_usage_rows(telemetry_db) == []


def test_telemetry_inserts_cache_usage_events(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "cache_usage",
                        "ts": "2026-07-16T12:00:00Z",
                        "session_id": "sess-1",
                        "role": "engineer",
                        "agent_id": "agent-1",
                        "sprint": "main",
                        "turns": 3,
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 10,
                        "ephemeral_5m_input_tokens": 10,
                        "ephemeral_1h_input_tokens": 0,
                        "hit_rate": 0.9,
                        "parse_error": None,
                    }
                ),
                json.dumps(
                    {
                        "event_type": "cache_usage",
                        "ts": 1752667200,
                        "session_id": "sess-2",
                        "role": "critic",
                        "agent_id": "agent-2",
                    }
                ),
                # Non-cache_usage event -> skipped.
                json.dumps({"event_type": "other", "ts": 1752667300}),
                # Malformed JSON line -> skipped.
                "not json at all",
                # Blank line -> skipped.
                "",
            ]
        )
        + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh telemetry: 2 new row(s)"

    rows = _read_cache_usage_rows(telemetry_db)
    assert len(rows) == 2
    by_session = {row["session_id"]: row for row in rows}

    row1 = by_session["sess-1"]
    assert row1["project_id"] == "proj-a"
    assert row1["ts"] == 1784203200  # 2026-07-16T12:00:00Z -> epoch seconds
    assert row1["role"] == "engineer"
    assert row1["agent_id"] == "agent-1"
    assert row1["sprint"] == "main"
    assert row1["turns"] == 3
    assert row1["input_tokens"] == 100
    assert row1["cache_read_input_tokens"] == 900
    assert row1["hit_rate"] == 0.9

    row2 = by_session["sess-2"]
    assert row2["project_id"] == "proj-a"
    assert row2["ts"] == 1752667200  # already-numeric ts passed straight through
    assert row2["role"] == "critic"  # present, not defaulted
    assert row2["turns"] is None


def test_telemetry_role_defaults_to_unknown_when_absent(
    telemetry_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752667200, "session_id": "sess-x"}) + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    rows = _read_cache_usage_rows(telemetry_db)
    assert len(rows) == 1
    assert rows[0]["role"] == "unknown"


def test_telemetry_is_idempotent_via_unique_constraint(
    telemetry_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        json.dumps(
            {
                "event_type": "cache_usage",
                "ts": 1752667200,
                "session_id": "sess-dup",
                "agent_id": "agent-dup",
            }
        )
        + "\n"
    )

    first = run_cli(["refresh", "--scope=telemetry"], env)
    assert first.returncode == 0, first.stderr
    assert first.stdout.rstrip("\n") == "shctx refresh telemetry: 1 new row(s)"

    second = run_cli(["refresh", "--scope=telemetry"], env)
    assert second.returncode == 0, second.stderr
    assert second.stdout.rstrip("\n") == "shctx refresh telemetry: 0 new row(s)"

    assert len(_read_cache_usage_rows(telemetry_db)) == 1


def test_telemetry_events_directory_globs_multiple_files_sorted(
    telemetry_db: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-15.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752580800, "session_id": "sess-a"}) + "\n"
    )
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752667200, "session_id": "sess-b"}) + "\n"
    )
    # A non-matching filename must be ignored entirely.
    (logs_dir / "other.jsonl").write_text(
        json.dumps({"event_type": "cache_usage", "ts": 1752667200, "session_id": "sess-ignored"}) + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh telemetry: 2 new row(s)"
    session_ids = {row["session_id"] for row in _read_cache_usage_rows(telemetry_db)}
    assert session_ids == {"sess-a", "sess-b"}


def test_telemetry_unparseable_ts_value_is_skipped(telemetry_db: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = _telemetry_env(telemetry_db, workdir)
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "events-2026-07-16.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_type": "cache_usage", "ts": "not-a-timestamp", "session_id": "bad-ts"}),
                json.dumps({"event_type": "cache_usage", "ts": None, "session_id": "null-ts"}),
                json.dumps({"event_type": "cache_usage", "session_id": "missing-ts"}),
            ]
        )
        + "\n"
    )

    proc = run_cli(["refresh", "--scope=telemetry"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "shctx refresh telemetry: 0 new row(s)"
    assert _read_cache_usage_rows(telemetry_db) == []
