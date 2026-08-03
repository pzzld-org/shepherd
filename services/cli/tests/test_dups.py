"""Subprocess parity tests for ``shepherd dups`` (field-shape similar-struct detection).

Bash parity target: ``skills/context/scripts/cmd_dups.sh`` (v6.1.8, #157),
driving the REAL :mod:`shepherd_cli.dups_core` engine (relocated
byte-for-byte from the retired ``skills/context/scripts/dups-core.py``;
pure stdlib, no network, no build step, fully deterministic for a fixed set
of small ``*.rs`` source strings) -- exactly like the module under test
itself does: ``[sys.executable, "-m", "shepherd_cli.dups_core", ...]``, a
child of the CLI's own interpreter, never bash and never a path lookup
into ``skills/context/scripts/``. This suite therefore needs no
fake-sibling-script harness the way ``test_sync.py``/``test_sprint.py`` do
for their bash siblings: every test below builds a throwaway git repo with
a handful of tiny Rust source files and lets ``shepherd dups`` run the
genuine engine, which easily clears the "deterministic, local, free, <2s"
gate-test bar on inputs this small. ``CLAUDE_PLUGIN_ROOT`` is deliberately
NEVER set here (and the throwaway repos live under ``tmp_path``, far from
any ``skills/context/`` tree), so a regression back toward locating the
engine via ``find_bash_shctx()`` would fail loudly instead of silently
passing against the real checkout.

No fixture database is built anywhere in this suite via
``conftest.build_full_schema_db`` -- ``shepherd dups`` never opens a
Tortoise connection (see the module docstring in
``shepherd_cli/commands/dups.py``). The few tests that DO exercise
``--update``/``registry update`` (which persist rows into
``index_struct_shapes`` via ``shepherd_cli.dups_core``'s own raw
``sqlite3`` connection) point ``SHCTX_DB`` at a bare, not-yet-existing
sqlite file and verify the resulting rows with plain ``sqlite3`` -- no ORM
involved on either side of that assertion.

Every test drives the real CLI as a subprocess
(``${PY} -m shepherd_cli dups ...``), never by importing ``shepherd_cli``
into the pytest process -- matching every other suite in this package.
``run_cli`` from ``conftest.py`` is NOT reused here: it hard-codes
``cwd=CLI_ROOT``, but ``shepherd dups`` resolves its repo root from the
subprocess's OWN cwd (``git rev-parse --show-toplevel``), which every test
below needs pointed at its own throwaway git repo, not the real shepherd
checkout. :func:`_run` is this suite's own thin wrapper for that reason
(and to support piping ``--stdin`` content for the ``check --stdin`` tests).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from conftest import PY, clean_env_dict

# --------------------------------------------------------------------------
# Rust fixture source -- a same-shape, different-name pair (the "rename to
# evade dedup" shadow #157 targets): identical three-field shape
# (id/name/email: String), so weighted-Jaccard similarity is exactly 1.0
# regardless of --name-weight, landing comfortably above both the default
# --threshold (0.7) and --block-threshold (0.85).
# --------------------------------------------------------------------------
_ALPHA_RS = 'pub struct AlphaProfile {\n    pub id: String,\n    pub name: String,\n    pub email: String,\n}\n'
_BETA_RS = 'pub struct BetaProfile {\n    pub id: String,\n    pub name: String,\n    pub email: String,\n}\n'
# A third, same-shape struct used as a "new candidate" for `dups check`,
# kept OUTSIDE any scanned repo so it never contaminates the corpus itself.
_GAMMA_RS = 'pub struct GammaProfile {\n    pub id: String,\n    pub name: String,\n    pub email: String,\n}\n'
# A lone, field-less struct -- below --min-fields (default 2), and alone
# in its own file, so `dups scan` always reports zero clusters for it.
_LONE_RS = 'pub struct Marker;\n'


# --------------------------------------------------------------------------
# Environment / invocation helpers.
# --------------------------------------------------------------------------
def _init_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a throwaway git repo at ``tmp_path/repo`` with the given files.

    Args:
        tmp_path: The pytest-provided per-test temp directory.
        files: Relative-path -> file content, written under the repo root.
            ``git init`` alone is sufficient for ``git ls-files --others
            --exclude-standard`` to see untracked-but-not-ignored files --
            no commit is required.

    Returns:
        The repo root path.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for rel_path, content in files.items():
        target = repo / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return repo


def _dups_env(
    *,
    db_path: Path | None = None,
    workdir: Path | None = None,
    no_python3: bool = False,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd dups`` test.

    Args:
        db_path: When given, sets ``SHCTX_DB`` (need not exist yet --
            ``shepherd_cli.dups_core``'s own ``persist_shapes()`` creates
            it via plain ``sqlite3.connect``).
        workdir: When given, sets ``SHEPHERD_WORKDIR`` to this ABSOLUTE
            path (so ``resolve_workdir()``/``registry_path()``/
            ``project.json`` resolution land here instead of auto-detecting
            ``.shepherd``/``.artifacts`` under the repo).
        no_python3: When True, sets ``PATH`` to a directory containing no
            ``python3`` (or ``git``) binary at all. Under bash this drove
            ``require_python()``'s fail-open skip; the native port runs
            the engine via ``sys.executable`` (never a ``PATH`` lookup),
            so the same starved environment now proves the STRONGER
            contract: scan/check/registry-update all still do their real
            work (``resolve_repo_root()``/``_list_rust_files()`` fall back
            to ``os.getcwd()``/``os.walk`` when git is unreachable). The
            harness's own ``${PY}`` invocation is unaffected since it is
            launched by absolute path.

    Returns:
        A stripped-then-rebuilt environment holding whatever of the above
        was requested. ``CLAUDE_PLUGIN_ROOT`` is deliberately NOT set --
        nothing in the ported dups pipeline may depend on locating the
        retired ``skills/context/scripts/`` tree (see module docstring).
    """
    env = clean_env_dict()
    if db_path is not None:
        env["SHCTX_DB"] = str(db_path)
    if workdir is not None:
        env["SHEPHERD_WORKDIR"] = str(workdir)
    if no_python3:
        env["PATH"] = "/nonexistent-bin-dir-for-tests"
    return env


def _run(
    args: list[str],
    env: dict[str, str],
    cwd: Path,
    *,
    input_text: str | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run ``${PY} -m shepherd_cli <args>`` from ``cwd``, optionally feeding stdin.

    Args:
        args: Arguments after the module name, e.g. ``["dups", "scan"]``.
        env: The full subprocess environment (see :func:`_dups_env`).
        cwd: The working directory the subprocess is launched from --
            drives ``resolve_repo_root()``'s ``git rev-parse
            --show-toplevel``, which every ``shepherd dups`` invocation
            depends on.
        input_text: When given, piped to the subprocess's stdin (for
            ``dups check --stdin`` tests); otherwise stdin is closed
            (``subprocess.DEVNULL``) so a test can never accidentally hang
            waiting on a real terminal.
        timeout: Seconds to wait before the test fails with a timeout.

    Returns:
        The completed subprocess, stdout/stderr captured as text.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", *args],
        env=env,
        cwd=str(cwd),
        input=input_text,
        stdin=None if input_text is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _sqlite_shape_rows(db_path: Path) -> list[sqlite3.Row]:
    """Read every ``index_struct_shapes`` row back with plain ``sqlite3``."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM index_struct_shapes ORDER BY name"))
    finally:
        conn.close()


# ==========================================================================
# No-subcommand / -h / --help / unknown subcommand.
# ==========================================================================


def test_bare_invocation_prints_usage_and_exits_0(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    env = _dups_env()
    proc = _run(["dups"], env, repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups — field-shape similar-struct detection (#157)" in proc.stdout
    assert "scan  [--threshold F]" in proc.stdout
    assert "registry show|path|allow A B" in proc.stdout


def test_help_long_flag_prints_usage_and_exits_0(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "--help"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups — field-shape similar-struct detection (#157)" in proc.stdout


def test_help_short_flag_prints_usage_and_exits_0(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "-h"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups — field-shape similar-struct detection (#157)" in proc.stdout


def test_unknown_subcommand_exits_1_with_usage_on_stderr(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "bogus"], _dups_env(), repo)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown dups subcommand: bogus" in proc.stderr
    assert "shctx dups — field-shape similar-struct detection (#157)" in proc.stderr


# ==========================================================================
# scan
# ==========================================================================


def test_scan_no_rust_files_reports_no_clusters(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "scan"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "0 public struct/enum defs in 0 files" in proc.stdout
    assert "no duplicate-shape clusters above threshold" in proc.stdout


def test_scan_single_field_less_struct_reports_no_clusters(tmp_path: Path) -> None:
    """A lone marker struct (0 fields) never participates -- below --min-fields."""
    repo = _init_repo(tmp_path, {"lone.rs": _LONE_RS})
    proc = _run(["dups", "scan"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "1 public struct/enum defs in 1 files" in proc.stdout
    assert "no duplicate-shape clusters above threshold" in proc.stdout


def test_scan_detects_same_shape_cluster(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "2 public struct/enum defs in 2 files; 1 similar-shape cluster(s)" in proc.stdout
    assert "▲ HIGH" in proc.stdout
    assert "concept≈AlphaProfile" in proc.stdout
    # shapes_a.rs sorts before shapes_b.rs -> AlphaProfile is the canonical
    # by the "most fields" tie-break (both have 0 consumers, equal field
    # counts, so lexicographically-first file/line wins).
    assert "suggested canonical: (root)::AlphaProfile" in proc.stdout
    assert "★ canonical" in proc.stdout


def test_scan_json_output_shape(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan", "--json"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["schema"] == "dups-scan/1"
    assert payload["threshold"] == 0.7
    assert payload["stats"] == {"files": 2, "types": 2, "clusters": 1, "clustered_types": 2}
    assert len(payload["clusters"]) == 1
    cluster = payload["clusters"][0]
    assert cluster["concept"] == "AlphaProfile"
    assert cluster["severity"] == "high"
    assert cluster["max_similarity"] == 1.0
    assert cluster["suggested_canonical"] == "(root)::AlphaProfile"


def test_scan_fail_on_medium_gates_nonzero_exit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan", "--fail-on", "medium"], _dups_env(), repo)

    assert proc.returncode == 3
    assert "✗ GATE FAILED (--fail-on medium)." in proc.stdout


def test_scan_fail_on_equals_form_also_gates(tmp_path: Path) -> None:
    """``--fail-on=value`` (shctx house style) is equivalent to ``--fail-on value``."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan", "--fail-on=medium"], _dups_env(), repo)

    assert proc.returncode == 3
    assert "✗ GATE FAILED (--fail-on medium)." in proc.stdout


def test_scan_no_fail_on_never_gates(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "GATE FAILED" not in proc.stdout


def test_scan_quiet_suppresses_stdout_but_keeps_exit_code(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan", "--quiet", "--fail-on", "medium"], _dups_env(), repo)

    assert proc.returncode == 3
    assert proc.stdout == ""


def test_scan_threshold_equals_form_parses(tmp_path: Path) -> None:
    """A --threshold above 1.0 (unreachable similarity) suppresses every cluster."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan", "--threshold=1.1"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "no duplicate-shape clusters above threshold" in proc.stdout


def test_scan_help_flag_short_circuits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    proc = _run(["dups", "scan", "-h"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups — field-shape similar-struct detection (#157)" in proc.stdout


def test_scan_unknown_arg_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "scan", "--bogus"], _dups_env(), repo)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown arg: --bogus" in proc.stderr


def test_scan_threshold_flag_missing_value_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "scan", "--threshold"], _dups_env(), repo)

    assert proc.returncode == 1
    assert "ERROR: --threshold needs a value" in proc.stderr


def test_scan_runs_engine_without_python3_on_path(tmp_path: Path) -> None:
    """Bash's require_python() fail-open (skip everything when python3 is
    not on PATH) is retired: the engine runs via sys.executable, so a
    PATH with no python3 (and no git -- _list_rust_files falls back to
    its os.walk branch) still performs the REAL scan."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    proc = _run(["dups", "scan"], _dups_env(no_python3=True), repo)

    assert proc.returncode == 0, proc.stderr
    assert "2 public struct/enum defs in 2 files; 1 similar-shape cluster(s)" in proc.stdout
    assert "python3 not found" not in proc.stderr


def test_scan_update_persists_shapes_to_index_struct_shapes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-1"}))
    db_path = tmp_path / "shepherd.db"

    proc = _run(["dups", "scan", "--update"], _dups_env(db_path=db_path, workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr
    assert db_path.is_file()
    rows = _sqlite_shape_rows(db_path)
    names = sorted(r["name"] for r in rows)
    assert names == ["AlphaProfile", "BetaProfile"]
    for row in rows:
        assert row["project_id"] == "proj-dups-1"
        assert row["kind"] == "struct"
        assert row["field_count"] == 3
        assert json.loads(row["field_names"]) == ["email", "id", "name"]


def test_scan_update_without_project_id_skips_persist_silently(tmp_path: Path) -> None:
    """No project.json -> pid resolves to "" -> bash's `[[ -n "$pid" ]]` guard
    means --update/--db/--project-id are silently never added; scan still
    runs and reports normally, it just never persists."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    workdir = tmp_path / "workdir-empty"
    workdir.mkdir()
    db_path = tmp_path / "shepherd.db"

    proc = _run(["dups", "scan", "--update"], _dups_env(db_path=db_path, workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr
    assert "1 similar-shape cluster(s)" in proc.stdout
    assert not db_path.exists()


# ==========================================================================
# check
# ==========================================================================


def test_check_missing_file_and_no_stdin_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "check"], _dups_env(), repo)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx dups check <file> | --stdin --as <path>" in proc.stderr


def test_check_help_flag_short_circuits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "check", "-h"], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups — field-shape similar-struct detection (#157)" in proc.stdout


def test_check_unknown_flag_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "check", "--bogus"], _dups_env(), repo)

    assert proc.returncode == 1
    assert "ERROR: unknown arg: --bogus" in proc.stderr


def test_check_runs_engine_without_python3_on_path(tmp_path: Path) -> None:
    """The authoring gate keeps its exit-5 block contract even on a PATH
    with no python3 at all -- the retired fail-open branch would have
    silently exited 0 here, letting a shape duplicate through."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-nopy"}))
    db_path = tmp_path / "shepherd.db"

    scan_proc = _run(["dups", "scan", "--update"], _dups_env(db_path=db_path, workdir=workdir), repo)
    assert scan_proc.returncode == 0, scan_proc.stderr

    candidate_dir = tmp_path / "outside-repo"
    candidate_dir.mkdir()
    candidate = candidate_dir / "gamma.rs"
    candidate.write_text(_GAMMA_RS)

    check_proc = _run(
        ["dups", "check", str(candidate)],
        _dups_env(db_path=db_path, workdir=workdir, no_python3=True),
        repo,
    )

    assert check_proc.returncode == 5
    assert "BLOCKED" in check_proc.stdout
    assert "python3 not found" not in check_proc.stderr


def test_check_no_corpus_reports_nothing(tmp_path: Path) -> None:
    """No persisted corpus at all (fresh DB, or no --db/--project-id) -> no hits."""
    repo = _init_repo(tmp_path, {})
    candidate = tmp_path / "candidate.rs"
    candidate.write_text(_GAMMA_RS)
    proc = _run(["dups", "check", str(candidate)], _dups_env(), repo)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


def test_check_against_persisted_corpus_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-2"}))
    db_path = tmp_path / "shepherd.db"
    env = _dups_env(db_path=db_path, workdir=workdir)

    scan_proc = _run(["dups", "scan", "--update"], env, repo)
    assert scan_proc.returncode == 0, scan_proc.stderr
    assert _sqlite_shape_rows(db_path)

    candidate_dir = tmp_path / "outside-repo"
    candidate_dir.mkdir()
    candidate = candidate_dir / "gamma.rs"
    candidate.write_text(_GAMMA_RS)

    check_proc = _run(["dups", "check", str(candidate)], env, repo)

    assert check_proc.returncode == 5
    assert "BLOCKED" in check_proc.stdout
    assert "GammaProfile" in check_proc.stdout
    assert "AlphaProfile" in check_proc.stdout
    assert "reuse it?" in check_proc.stdout
    assert "shared fields: email, id, name" in check_proc.stdout


def test_check_below_block_threshold_matches_but_does_not_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-3"}))
    db_path = tmp_path / "shepherd.db"
    env = _dups_env(db_path=db_path, workdir=workdir)

    assert _run(["dups", "scan", "--update"], env, repo).returncode == 0

    candidate_dir = tmp_path / "outside-repo"
    candidate_dir.mkdir()
    candidate = candidate_dir / "gamma.rs"
    candidate.write_text(_GAMMA_RS)

    check_proc = _run(["dups", "check", str(candidate), "--block-threshold", "1.1"], env, repo)

    assert check_proc.returncode == 0, check_proc.stderr
    assert "similar-shape match(es)" in check_proc.stdout
    assert "BLOCKED" not in check_proc.stdout


def test_check_stdin_reads_piped_content(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-4"}))
    db_path = tmp_path / "shepherd.db"
    env = _dups_env(db_path=db_path, workdir=workdir)

    assert _run(["dups", "scan", "--update"], env, repo).returncode == 0

    check_proc = _run(
        ["dups", "check", "--stdin", "--as", "outside/gamma.rs"],
        env,
        repo,
        input_text=_GAMMA_RS,
    )

    assert check_proc.returncode == 5
    assert "outside/gamma.rs: BLOCKED" in check_proc.stdout
    assert "GammaProfile" in check_proc.stdout


def test_check_json_output_shape(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-5"}))
    db_path = tmp_path / "shepherd.db"
    env = _dups_env(db_path=db_path, workdir=workdir)

    assert _run(["dups", "scan", "--update"], env, repo).returncode == 0

    check_proc = _run(
        ["dups", "check", "--stdin", "--as", "candidate.rs", "--json"],
        env,
        repo,
        input_text=_GAMMA_RS,
    )

    assert check_proc.returncode == 5
    payload = json.loads(check_proc.stdout)
    assert payload["schema"] == "dups-check/1"
    assert payload["block"] is True
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["name"] == "GammaProfile"
    assert payload["candidates"][0]["hits"][0]["name"] == "AlphaProfile"


def test_check_as_path_normalized_to_repo_relative_excludes_self(tmp_path: Path) -> None:
    """A candidate file INSIDE the repo, given as an absolute --as path
    matching the repo root prefix, is stripped to repo-relative so it can
    self-exclude an identically-pathed corpus row -- here it simply proves
    the normalization doesn't crash and still finds the (different-file)
    corpus hit."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "project.json").write_text(json.dumps({"id": "proj-dups-6"}))
    db_path = tmp_path / "shepherd.db"
    env = _dups_env(db_path=db_path, workdir=workdir)

    assert _run(["dups", "scan", "--update"], env, repo).returncode == 0

    candidate = repo / "gamma.rs"
    candidate.write_text(_GAMMA_RS)
    abs_as_path = str(repo / "gamma.rs")

    check_proc = _run(["dups", "check", str(candidate), "--as", abs_as_path], env, repo)

    assert check_proc.returncode == 5
    assert "GammaProfile" in check_proc.stdout


# ==========================================================================
# registry
# ==========================================================================


def test_registry_defaults_to_show(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proc = _run(["dups", "registry"], _dups_env(workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr
    assert "DO-NOT-MERGE allow-list (0 pair(s)):" in proc.stdout
    assert "Concept → canonical pins (0):" in proc.stdout


def test_registry_path_default_location(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proc = _run(["dups", "registry", "path"], _dups_env(workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == str(workdir / "dups-registry.json")


def test_registry_show_json_on_fresh_registry(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proc = _run(["dups", "registry", "show", "--json"], _dups_env(workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"version": 1, "canonical": {}, "allow": []}


def test_registry_allow_then_show(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    allow_proc = _run(["dups", "registry", "allow", "pkg::A", "pkg::B"], env, repo)
    assert allow_proc.returncode == 0, allow_proc.stderr
    assert f"shctx dups registry: wrote {workdir / 'dups-registry.json'}" in allow_proc.stdout

    show_proc = _run(["dups", "registry", "show"], env, repo)
    assert "DO-NOT-MERGE allow-list (1 pair(s)):" in show_proc.stdout
    assert "  - pkg::A  ⟷  pkg::B" in show_proc.stdout


def test_registry_allow_missing_args_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "registry", "allow", "pkg::A"], _dups_env(workdir=tmp_path / "wd"), repo)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx dups registry allow <A> <B>" in proc.stderr


def test_registry_allow_dedupes_and_sorts(tmp_path: Path) -> None:
    """jq's `unique` both dedupes exact-duplicate pairs and resorts the
    whole array -- adding B/C, then A/B, then re-adding B/C, ends up
    lexicographically ordered with no duplicate entry."""
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    _run(["dups", "registry", "allow", "pkg::B", "pkg::C"], env, repo)
    _run(["dups", "registry", "allow", "pkg::A", "pkg::B"], env, repo)
    _run(["dups", "registry", "allow", "pkg::B", "pkg::C"], env, repo)

    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["allow"] == [["pkg::A", "pkg::B"], ["pkg::B", "pkg::C"]]


def test_registry_unallow_is_order_insensitive_and_preserves_rest(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    _run(["dups", "registry", "allow", "pkg::A", "pkg::B"], env, repo)
    _run(["dups", "registry", "allow", "pkg::C", "pkg::D"], env, repo)

    unallow_proc = _run(["dups", "registry", "unallow", "pkg::B", "pkg::A"], env, repo)
    assert unallow_proc.returncode == 0, unallow_proc.stderr

    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["allow"] == [["pkg::C", "pkg::D"]]


def test_registry_unallow_missing_args_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "registry", "unallow"], _dups_env(workdir=tmp_path / "wd"), repo)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx dups registry unallow <A> <B>" in proc.stderr


def test_registry_pin_then_show(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    pin_proc = _run(["dups", "registry", "pin", "profile", "core::Profile"], env, repo)
    assert pin_proc.returncode == 0, pin_proc.stderr

    show_proc = _run(["dups", "registry", "show"], env, repo)
    assert "Concept → canonical pins (1):" in show_proc.stdout
    assert "  - profile  →  core::Profile" in show_proc.stdout


def test_registry_pin_overwrites_existing_value(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    _run(["dups", "registry", "pin", "profile", "core::Profile"], env, repo)
    _run(["dups", "registry", "pin", "profile", "core::ProfileV2"], env, repo)

    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["canonical"] == {"profile": "core::ProfileV2"}


def test_registry_pin_missing_args_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "registry", "pin", "profile"], _dups_env(workdir=tmp_path / "wd"), repo)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx dups registry pin <concept> <pkg::Type>" in proc.stderr


def test_registry_unpin_removes_existing_pin(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    _run(["dups", "registry", "pin", "profile", "core::Profile"], env, repo)
    unpin_proc = _run(["dups", "registry", "unpin", "profile"], env, repo)
    assert unpin_proc.returncode == 0, unpin_proc.stderr

    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["canonical"] == {}


def test_registry_unpin_unknown_concept_is_a_no_op_success(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proc = _run(["dups", "registry", "unpin", "never-pinned"], _dups_env(workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr


def test_registry_unpin_missing_arg_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "registry", "unpin"], _dups_env(workdir=tmp_path / "wd"), repo)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx dups registry unpin <concept>" in proc.stderr


def test_registry_unknown_action_exits_1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {})
    proc = _run(["dups", "registry", "bogus"], _dups_env(workdir=tmp_path / "wd"), repo)

    assert proc.returncode == 1
    assert "ERROR: usage: shctx dups registry <show|path|allow|unallow|pin|unpin|update>" in proc.stderr


def test_registry_update_merges_suggested_canonical(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    proc = _run(["dups", "registry", "update"], env, repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups registry update: considered 1 cluster concept(s)." in proc.stdout

    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["canonical"] == {"AlphaProfile": "(root)::AlphaProfile"}


def test_registry_update_never_overwrites_an_existing_pin(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir)

    _run(["dups", "registry", "pin", "AlphaProfile", "core::AlreadyPinned"], env, repo)
    proc = _run(["dups", "registry", "update"], env, repo)

    assert proc.returncode == 0, proc.stderr
    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["canonical"] == {"AlphaProfile": "core::AlreadyPinned"}


def test_registry_update_no_rust_files_reports_no_scan_output_or_empty_merge(tmp_path: Path) -> None:
    """With zero .rs files, dups-core.py's scan still emits a well-formed
    JSON payload (0 clusters) -- so this is "considered 0 cluster
    concept(s)", not the "no scan output" branch (which only fires if the
    subprocess produced literally no stdout at all)."""
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proc = _run(["dups", "registry", "update"], _dups_env(workdir=workdir), repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups registry update: considered 0 cluster concept(s)." in proc.stdout
    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["canonical"] == {}


def test_registry_update_runs_engine_without_python3_on_path(tmp_path: Path) -> None:
    """registry update also lost the fail-open skip: with no python3 (or
    git) on PATH the engine still scans (os.walk fallback file listing)
    and the canonical-pin merge still lands on disk."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS, "shapes_b.rs": _BETA_RS})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    proc = _run(["dups", "registry", "update"], _dups_env(workdir=workdir, no_python3=True), repo)

    assert proc.returncode == 0, proc.stderr
    assert "shctx dups registry update: considered 1 cluster concept(s)." in proc.stdout
    assert "python3 not found" not in proc.stderr

    registry = json.loads((workdir / "dups-registry.json").read_text())
    assert registry["canonical"] == {"AlphaProfile": "(root)::AlphaProfile"}


def test_registry_show_and_path_do_not_require_python3(tmp_path: Path) -> None:
    """The pure JSON-curation actions never touch the engine at all (no
    subprocess anywhere on their path), so a PATH with no python3/git
    changes nothing for them -- true under bash (they skipped
    require_python()) and still true natively."""
    repo = _init_repo(tmp_path, {})
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    env = _dups_env(workdir=workdir, no_python3=True)

    show_proc = _run(["dups", "registry", "show"], env, repo)
    assert show_proc.returncode == 0, show_proc.stderr

    path_proc = _run(["dups", "registry", "path"], env, repo)
    assert path_proc.returncode == 0, path_proc.stderr

    pin_proc = _run(["dups", "registry", "pin", "x", "pkg::X"], env, repo)
    assert pin_proc.returncode == 0, pin_proc.stderr


# ==========================================================================
# The relocated engine module itself (shepherd_cli.dups_core).
# ==========================================================================


def test_dups_core_module_is_directly_invocable(tmp_path: Path) -> None:
    """The engine's package home is a real runnable module: ``${PY} -m
    shepherd_cli.dups_core extract --files-stdin`` parses shapes with no
    wrapper CLI involved -- the exact child argv prefix ``shepherd dups``
    builds (see ``dups.py``'s ``_core_argv()``)."""
    src = tmp_path / "alpha.rs"
    src.write_text(_ALPHA_RS)

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli.dups_core", "extract", "--files-stdin"],
        env=clean_env_dict(),
        cwd=str(tmp_path),
        input=f"{src}\n",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    shape = json.loads(proc.stdout.splitlines()[0])
    assert shape["name"] == "AlphaProfile"
    assert shape["kind"] == "struct"
    assert shape["field_names"] == ["email", "id", "name"]


def test_dups_core_bad_fail_on_choice_is_argparse_exit_2(tmp_path: Path) -> None:
    """A malformed ``--fail-on`` value flows through the wrapper's own
    no-validation parse loop (bash parity) and lands in the engine's
    argparse: exit 2, with the engine's byte-parity ``prog``
    ("dups-core.py") in the error text -- exactly how bash surfaced it."""
    repo = _init_repo(tmp_path, {"shapes_a.rs": _ALPHA_RS})
    proc = _run(["dups", "scan", "--fail-on", "bogus"], _dups_env(), repo)

    assert proc.returncode == 2
    assert "dups-core.py" in proc.stderr
    assert "invalid choice" in proc.stderr
