"""Tests for `shepherd doctor` — native port of `cmd_doctor.sh` (v5.0.4, bash-parity #198-successor).

Every test drives the real CLI as a subprocess (`${PY} -m shepherd_cli
doctor ...`) under an ISOLATED, NON-git `cwd` and an isolated
`XDG_CONFIG_HOME` — mirroring `test_config.py`'s isolation pattern, NOT
`conftest.run_cli`'s fixed `cwd=CLI_ROOT` (which sits inside THIS repo's
own git working tree, and which has a REAL `.claude/shepherd.toml` file at
its root — using it here would make every "shepherd.toml not found" /
"namespace dir" assertion depend on the accident of where this suite
happens to be checked out). `doctor` resolves the repo root via `git
rev-parse --show-toplevel`, exactly like `cmd_doctor.sh`'s own
`shctx_repo_root`, so this isolation is required for `namespace
dir`/`project.json`/`shepherd.toml` to be deterministic.

Covers: happy path (bin/ns/db/lock/refresh/config all `ok`), `--json`
shape + escaping, section/row ordering, the missing-DB branch (schema/
pending/refresh sections entirely absent, not degraded), the empty-
`schema_versions` WARN branch, the pending-migrations WARN branch (via
`conftest.build_partial_schema_db`, the #200 fixture), lock free/held/
stale/corrupt, refresh-zone never/fresh/stale (including the `artifacts`
zone's structural "always never refreshed" quirk — see
`shepherd_cli/commands/doctor.py`'s module docstring), the dual-namespace
WARN (plus its triplicated stderr warning), `shepherd.toml`
found/not-found, exit codes 0/1/2, `-h`/`--help`, an unknown arg, and
byte-for-byte STDOUT parity against the legacy `skills/context/scripts/
cmd_doctor.sh` on IDENTICAL fixture state — the same bash-parity pattern
`test_status.py`/`test_config.py` already established.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import (
    MIGRATIONS_DIR,
    PY,
    REPO_ROOT,
    build_full_schema_db,
    build_partial_schema_db,
    clean_env_dict,
    insert_project,
)

CMD_DOCTOR_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_doctor.sh"

_USAGE_MARKER = "shctx doctor [--md|--json]"

#: `cmd_doctor.sh`'s exact `for zone in symbols issues prs releases
#: artifacts` loop order (the "Refresh staleness" section).
EXPECTED_ZONE_ORDER = ("symbols", "issues", "prs", "releases", "artifacts")


def _shipped_migration_count() -> int:
    """Number of `migrations/NNNN_*.sql` files (excludes `0001_init.sql` itself)."""
    files = list(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    assert files, "no migration files found — fixture setup is broken"
    return len(files)


def _max_migration_version() -> int:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return max(int(f.name[:4]) for f in files)


# --------------------------------------------------------------------------
# Isolation fixtures + subprocess helpers (mirrors test_config.py exactly).
# --------------------------------------------------------------------------
@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory to use as the CLI's `cwd`.

    Never inside a git repository, so `resolve_repo_root()` (and bash's
    `shctx_repo_root`) both fall back to this exact directory rather than
    climbing up into this real repository's own root (which has a real
    `.claude/shepherd.toml` and would corrupt every "not found"/"missing"
    assertion below).
    """
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def xdg_dir(tmp_path: Path) -> Path:
    """An isolated, initially-empty `XDG_CONFIG_HOME` directory."""
    d = tmp_path / "xdg-config"
    d.mkdir()
    return d


def _doctor_env(xdg_dir: Path, *, db_path: Path | None = None, workdir: Path | None = None) -> dict[str, str]:
    """A stripped-then-rebuilt environment, isolated to `xdg_dir`/`db_path`/`workdir`.

    Args:
        xdg_dir: Isolated `XDG_CONFIG_HOME` (so a populated real
            `~/.config/shepherd.toml` on the host running this suite can
            never leak into a "not found" assertion).
        db_path: When given, sets `SHCTX_DB` (both tools then read/write
            this EXACT fixture file, independent of workdir auto-detect).
        workdir: When given, sets `SHEPHERD_WORKDIR` (an absolute path,
            used as-is per `resolve_workdir`'s own precedence) so
            `project.json`/`shepherd.lock`/the namespace-dir check all
            resolve inside it.
    """
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    if db_path is not None:
        env["SHCTX_DB"] = str(db_path)
    if workdir is not None:
        env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def run_doctor(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -m shepherd_cli doctor <args>` under `cwd`."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "doctor", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_bash_doctor(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_doctor.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(
        ["bash", str(CMD_DOCTOR_SH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write_lock_file(workdir: Path, payload: dict[str, object]) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "shepherd.lock").write_text(json.dumps(payload))


def _delete_schema_versions_rows(db_path: Path) -> None:
    """Empty `schema_versions` entirely — the "no schema_versions row" WARN fixture."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM schema_versions;")
        conn.commit()
    finally:
        conn.close()


def _insert_row(db_path: Path, table: str, **columns: object) -> None:
    """Insert one row into `table` via a fixed, hardcoded column list (no user input)."""
    conn = sqlite3.connect(str(db_path))
    try:
        keys = list(columns.keys())
        placeholders = ", ".join("?" for _ in keys)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})",  # noqa: S608 - fixed table/column names from hardcoded call sites, no user input
            [columns[k] for k in keys],
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# -h / --help / unknown arg / no-subcommand default.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("args", [["-h"], ["--help"]])
def test_help_variants_print_usage_and_exit_0(args: list[str], work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir)
    proc = run_doctor(args, work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _USAGE_MARKER + (
        "\n\n"
        "Pre-flight diagnostic for the shepherd context registry. Checks:\n"
        "  - required binaries (sqlite3, jq, gh, git)\n"
        "  - namespace dir + project.json present\n"
        "  - schema version + pending migrations\n"
        "  - lock state (held / stale / free)\n"
        "  - refresh staleness per zone (symbols / github / artifacts)\n"
        "  - shepherd.toml locatable\n"
        "\n"
        "Exit codes: 0 = ok, 1 = at least one FAIL, 2 = warnings only."
    )
    assert proc.stderr == ""


def test_help_matches_bash_usage_byte_for_byte(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir)
    python_proc = run_doctor(["--help"], work_dir, env)
    bash_proc = run_bash_doctor(["--help"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_unknown_arg_exits_1_with_bash_message(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir)
    proc = run_doctor(["--bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"


def test_unknown_arg_matches_bash(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir)
    python_proc = run_doctor(["--nope"], work_dir, env)
    bash_proc = run_bash_doctor(["--nope"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


def test_help_wins_even_after_other_tokens(work_dir: Path, xdg_dir: Path) -> None:
    """Bash parity: `-h` found ANYWHERE in the arg list short-circuits immediately."""
    env = _doctor_env(xdg_dir)
    proc = run_doctor(["--json", "-h"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)
    assert '"summary"' not in proc.stdout


def test_no_args_runs_full_md_report_not_help(work_dir: Path, xdg_dir: Path) -> None:
    """Bash parity: a bare `shctx doctor` runs the full check (fmt=md default), NOT a usage screen."""
    db_path = work_dir.parent / "shepherd.db"  # never created
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)
    proc = run_doctor([], work_dir, env)

    assert proc.stdout.startswith("STATUS CATEGORY  NAME                   MESSAGE\n")
    assert "shctx doctor:" in proc.stdout


# --------------------------------------------------------------------------
# Missing DB — schema/pending/refresh sections entirely absent (not degraded).
# --------------------------------------------------------------------------
def test_missing_db_fails_and_skips_schema_and_refresh_sections(work_dir: Path, xdg_dir: Path) -> None:
    (work_dir / "project.json").write_text(json.dumps({"id": "proj-1"}))  # isolate the db-specific FAIL
    db_path = work_dir.parent / "shepherd.db"  # never created
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert proc.returncode == 1, proc.stderr
    assert "FAIL   db        shepherd.db            missing" in proc.stdout
    assert "schema_version" not in proc.stdout
    assert "pending migrations" not in proc.stdout
    assert "refresh   " not in proc.stdout
    assert "1 fail," in proc.stdout.splitlines()[-1]


def test_missing_db_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# Happy path — everything ok, byte-for-byte bash parity.
# --------------------------------------------------------------------------
def test_happy_path_all_ok_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))
    now = int(time.time())
    for zone, table, cols in (
        ("index_symbols", "index_symbols", dict(id="s1", project_id=project_id, name="Foo", kind="fn", package="pkg", file_path="f.rs", language="rust", hash="h1", refreshed_at=now)),
        ("index_issues", "index_issues", dict(id="i1", project_id=project_id, source="github", number=1, title="t", state="open", url="https://x", created_at=now, updated_at=now, refreshed_at=now)),
        ("index_prs", "index_prs", dict(id="p1", project_id=project_id, source="github", number=1, title="t", state="open", base_branch="main", head_branch="feat", url="https://x", created_at=now, updated_at=now, refreshed_at=now)),
        ("index_releases", "index_releases", dict(id="r1", project_id=project_id, source="github", tag="v1", url="https://x", refreshed_at=now)),
    ):
        _insert_row(db_path, table, **cols)

    python_proc = run_doctor([], work_dir, _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir))
    bash_proc = run_bash_doctor([], work_dir, _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir))

    assert python_proc.returncode == bash_proc.returncode == 2  # artifacts zone always warns — see module docstring
    assert python_proc.stdout == bash_proc.stdout, f"python:\n{python_proc.stdout}\n---\nbash:\n{bash_proc.stdout}"
    assert f"OK     ns        project.json           id={project_id}" in python_proc.stdout
    assert "OK     db        schema_version" in python_proc.stdout
    assert "OK     db        pending migrations     none (schema at head)" in python_proc.stdout
    assert "OK     lock      shepherd.lock          free" in python_proc.stdout
    assert "OK     refresh   symbols                rows=1, fresh 0m" in python_proc.stdout
    assert "WARN   refresh   artifacts              rows=0, never refreshed" in python_proc.stdout


def test_json_shape_happy_path(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))

    proc = run_doctor(["--json"], work_dir, _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir))
    assert proc.returncode == 2, proc.stderr

    payload = json.loads(proc.stdout)
    assert payload["summary"]["total"] == len(payload["checks"])
    assert payload["summary"]["fail"] == 0
    assert payload["summary"]["warn"] == sum(1 for c in payload["checks"] if c["status"] == "warn")
    names = [c["name"] for c in payload["checks"] if c["category"] == "refresh"]
    assert names == list(EXPECTED_ZONE_ORDER)
    for check in payload["checks"]:
        assert set(check.keys()) == {"status", "category", "name", "message", "fix"}


def test_json_matches_bash_byte_for_byte(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    python_proc = run_doctor(["--json"], work_dir, env)
    bash_proc = run_bash_doctor(["--json"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# Section/row ordering.
# --------------------------------------------------------------------------
def test_section_order(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)
    assert proc.returncode in (0, 1, 2), proc.stderr

    lines = proc.stdout.splitlines()
    categories_in_order = [line.split()[1] for line in lines[1:] if line.strip() and not line.startswith(" ") and "shctx doctor:" not in line]
    # bin(x4), ns(x1+), db(x1-3), lock(x1), refresh(x0 or x5), config(x1) — categories must appear
    # in this relative order (never interleaved or reordered).
    seen_order: list[str] = []
    for cat in categories_in_order:
        if not seen_order or seen_order[-1] != cat:
            seen_order.append(cat)
    assert seen_order == ["bin", "ns", "db", "lock", "refresh", "config"]


def test_refresh_zone_order(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    names = [c["name"] for c in payload["checks"] if c["category"] == "refresh"]
    assert names == list(EXPECTED_ZONE_ORDER)


def test_bin_check_order(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir)
    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    names = [c["name"] for c in payload["checks"] if c["category"] == "bin"]
    assert names == ["sqlite3", "jq", "git", "gh"]


# --------------------------------------------------------------------------
# schema_version: empty schema_versions -> WARN.
# --------------------------------------------------------------------------
def test_empty_schema_versions_warns(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    _delete_schema_versions_rows(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "WARN   db        schema_version         no schema_versions row" in proc.stdout
    assert "→ fix: run 'shctx migrate'" in proc.stdout


def test_empty_schema_versions_matches_bash(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    _delete_schema_versions_rows(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert python_proc.stdout == bash_proc.stdout
    assert python_proc.returncode == bash_proc.returncode


# --------------------------------------------------------------------------
# Pending migrations — the v6.3.3 #200 fixture (NEVER self-healed by doctor).
# --------------------------------------------------------------------------
def test_pending_migrations_warns_with_gap_aware_count(work_dir: Path, xdg_dir: Path) -> None:
    """`build_partial_schema_db` applies only 0001+0007, records ONLY version=1 —
    every one of the shipped migrations/NNNN_*.sql files (0007 included,
    since ITS row was deliberately left unrecorded) reads as pending."""
    db_path = work_dir.parent / "shepherd.db"
    build_partial_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    expected_pending = _shipped_migration_count()
    assert f"WARN   db        pending migrations     {expected_pending} unapplied (schema drift)" in proc.stdout
    assert "run 'shctx migrate' (stateful commands also self-heal — v6.3.3 #200)" in proc.stdout
    assert "OK     db        schema_version         1" in proc.stdout


def test_pending_migrations_matches_bash(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_partial_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert python_proc.stdout == bash_proc.stdout
    assert python_proc.returncode == bash_proc.returncode


def test_doctor_never_self_heals_the_schema(work_dir: Path, xdg_dir: Path) -> None:
    """Running `shepherd doctor` twice against a behind-HEAD DB must report the
    SAME pending count both times — the self-heal `db.lifespan()` would
    otherwise trigger for every OTHER DB command must never fire here (see
    `shepherd_cli/commands/doctor.py`'s module docstring's central
    architecture note)."""
    db_path = work_dir.parent / "shepherd.db"
    build_partial_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    first = run_doctor([], work_dir, env)
    second = run_doctor([], work_dir, env)

    assert first.stdout == second.stdout
    expected_pending = _shipped_migration_count()
    assert f"{expected_pending} unapplied" in first.stdout
    assert f"{expected_pending} unapplied" in second.stdout
    # The schema_versions table itself must be untouched (still exactly one row).
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM schema_versions;").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_no_pending_migrations_on_full_schema_db(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "OK     db        pending migrations     none (schema at head)" in proc.stdout
    assert f"OK     db        schema_version         {_max_migration_version()}" in proc.stdout


# --------------------------------------------------------------------------
# project.json — missing / malformed / ok.
# --------------------------------------------------------------------------
def test_project_json_missing(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    proc = run_doctor([], work_dir, env)

    assert "FAIL   ns        project.json           missing" in proc.stdout
    assert "→ fix: run 'shctx init'" in proc.stdout


def test_project_json_malformed_no_id(work_dir: Path, xdg_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "project.json").write_text(json.dumps({"other": "field"}))
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "FAIL   ns        project.json           malformed (no .id)" in proc.stdout


def test_project_json_null_id_is_malformed(work_dir: Path, xdg_dir: Path) -> None:
    (work_dir / "project.json").write_text(json.dumps({"id": None}))
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "FAIL   ns        project.json           malformed (no .id)" in proc.stdout


def test_project_json_invalid_json_is_malformed(work_dir: Path, xdg_dir: Path) -> None:
    (work_dir / "project.json").write_text("{not valid json")
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "FAIL   ns        project.json           malformed (no .id)" in proc.stdout


def test_project_json_ok(work_dir: Path, xdg_dir: Path) -> None:
    (work_dir / "project.json").write_text(json.dumps({"id": "proj-abc"}))
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "OK     ns        project.json           id=proj-abc" in proc.stdout


def test_project_json_matches_bash_across_variants(work_dir: Path, xdg_dir: Path) -> None:
    for content in ('{"id":"abc"}', '{"other":1}', "{not json", '{"id":null}'):
        (work_dir / "project.json").write_text(content)
        env = _doctor_env(xdg_dir, workdir=work_dir)
        python_proc = run_doctor([], work_dir, env)
        bash_proc = run_bash_doctor([], work_dir, env)
        assert python_proc.stdout == bash_proc.stdout, content
        assert python_proc.returncode == bash_proc.returncode, content


# --------------------------------------------------------------------------
# Lock state — free / held-fresh / held-stale / corrupt.
# --------------------------------------------------------------------------
def test_lock_free(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    proc = run_doctor([], work_dir, env)
    assert "OK     lock      shepherd.lock          free" in proc.stdout


def test_lock_held_fresh_ok(work_dir: Path, xdg_dir: Path) -> None:
    now = int(time.time())
    _write_lock_file(work_dir, {"holder_session_id": "sess-1", "mode": "context", "acquired_at": now, "pid": 4242, "children": []})
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "OK     lock      shepherd.lock          held 0m by pid=4242 sess=sess-1" in proc.stdout
    assert "(stale?)" not in proc.stdout


def test_lock_held_stale_warns(work_dir: Path, xdg_dir: Path) -> None:
    old = int(time.time()) - 90 * 60  # 90 minutes ago — past the 60-minute threshold
    _write_lock_file(work_dir, {"holder_session_id": "sess-2", "mode": "context", "acquired_at": old, "pid": 999, "children": []})
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "WARN   lock      shepherd.lock          held 90m by pid=999 sess=sess-2 (stale?)" in proc.stdout
    assert "→ fix: run 'shctx lock reap'" in proc.stdout


def test_lock_corrupt_file_falls_back_to_question_marks(work_dir: Path, xdg_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "shepherd.lock").write_text("{not valid json")
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "pid=? sess=?" in proc.stdout
    assert "WARN   lock      shepherd.lock" in proc.stdout  # huge age (now - 0) always exceeds the 60m threshold


def test_lock_missing_fields_render_as_null_text(work_dir: Path, xdg_dir: Path) -> None:
    """A WELL-FORMED lock object missing `pid`/`holder_session_id` renders
    those as the literal text "null" (jq's own successful-parse
    behavior) — NOT "?" (that fallback is reserved for total parse
    failure, see the module docstring)."""
    _write_lock_file(work_dir, {"acquired_at": int(time.time())})
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "pid=null sess=null" in proc.stdout


def test_lock_variants_match_bash(work_dir: Path, xdg_dir: Path) -> None:
    now = int(time.time())
    scenarios = [
        None,
        {"holder_session_id": "s", "mode": "context", "acquired_at": now, "pid": 111, "children": []},
        {"holder_session_id": "s", "mode": "context", "acquired_at": now - 90 * 60, "pid": 222, "children": []},
        "{not valid json",
    ]
    for scenario in scenarios:
        lock_path = work_dir / "shepherd.lock"
        work_dir.mkdir(parents=True, exist_ok=True)
        if lock_path.exists():
            lock_path.unlink()
        if scenario is None:
            pass
        elif isinstance(scenario, str):
            lock_path.write_text(scenario)
        else:
            lock_path.write_text(json.dumps(scenario))
        env = _doctor_env(xdg_dir, workdir=work_dir)
        python_proc = run_doctor([], work_dir, env)
        bash_proc = run_bash_doctor([], work_dir, env)
        assert python_proc.stdout == bash_proc.stdout, scenario
        assert python_proc.returncode == bash_proc.returncode, scenario


# --------------------------------------------------------------------------
# Refresh staleness per zone — never / fresh / stale, and the artifacts quirk.
# --------------------------------------------------------------------------
def test_refresh_zone_never_when_empty(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    for zone in EXPECTED_ZONE_ORDER:
        assert f"rows=0, never refreshed" in proc.stdout
    assert proc.stdout.count("never refreshed") == 5


def test_refresh_zone_fresh(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    now = int(time.time())
    _insert_row(
        db_path, "index_symbols", id="s1", project_id=project_id, name="Foo", kind="fn",
        package="pkg", file_path="f.rs", language="rust", hash="h1", refreshed_at=now - 5 * 60,
    )
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "OK     refresh   symbols                rows=1, fresh 5m" in proc.stdout


def test_refresh_zone_stale_past_120_minutes(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    now = int(time.time())
    _insert_row(
        db_path, "index_symbols", id="s1", project_id=project_id, name="Foo", kind="fn",
        package="pkg", file_path="f.rs", language="rust", hash="h1", refreshed_at=now - 200 * 60,
    )
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert "WARN   refresh   symbols                rows=1, stale 200m" in proc.stdout
    assert "→ fix: run 'shctx refresh --scope=symbols'" in proc.stdout


def test_artifacts_zone_always_never_refreshed_even_with_rows(work_dir: Path, xdg_dir: Path) -> None:
    """Structural quirk (see module docstring): `artifacts` has no
    `refreshed_at` column at all, so this zone reads "never refreshed"
    unconditionally — verified against the real bash script too."""
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    now = int(time.time())
    _insert_row(
        db_path, "artifacts", id="a1", project_id=project_id, kind="doc",
        path="/tmp/a1.md", hash="h1", created_at=now, updated_at=now,
    )
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert "WARN   refresh   artifacts              rows=1, never refreshed" in python_proc.stdout
    assert python_proc.stdout == bash_proc.stdout


def test_refresh_zones_absent_when_db_missing(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"  # never created
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    # Category-column match ("refresh   ", the padded `_check_refresh_zones`
    # category text) -- not a bare substring check, which would false-positive
    # on this test's own tmp_path directory name embedding "refresh" (pytest
    # derives tmp_path from the test function's name).
    assert "refresh   " not in proc.stdout


# --------------------------------------------------------------------------
# Namespace dir + dual-namespace conflict.
# --------------------------------------------------------------------------
def test_namespace_dir_missing_fails(work_dir: Path, xdg_dir: Path) -> None:
    missing_workdir = work_dir / "does-not-exist"
    env = _doctor_env(xdg_dir, workdir=missing_workdir)

    proc = run_doctor([], work_dir, env)

    assert "FAIL   ns        namespace dir          missing" in proc.stdout
    assert "→ fix: run 'shctx init' or 'shctx ready'" in proc.stdout


def test_namespace_dir_present_ok(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    proc = run_doctor([], work_dir, env)
    assert f"OK     ns        namespace dir          {work_dir}" in proc.stdout


def test_dual_namespace_conflict_warns_and_triplicates_stderr_warning(work_dir: Path, xdg_dir: Path) -> None:
    """`SHEPHERD_WORKDIR` unset (auto-detect) + both `.shepherd/` and
    `.artifacts/` present at the repo root (== `work_dir` here, since it
    is not a git repo) triggers the split-brain conflict AND — bash
    parity, see the module docstring — the underlying stderr warning
    fires 3 times (once per un-quieted `resolve_workdir()` call), since
    `SHCTX_DB` is deliberately left UNSET so `resolve_db_path()` also
    calls `resolve_workdir()` instead of short-circuiting."""
    (work_dir / ".shepherd").mkdir()
    (work_dir / ".artifacts").mkdir()
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert python_proc.stdout == bash_proc.stdout
    assert python_proc.returncode == bash_proc.returncode
    assert "WARN   ns        namespace conflict" in python_proc.stdout
    assert "using .shepherd/, .artifacts/ is unused" in python_proc.stdout
    assert python_proc.stderr.count("shctx WARNING: both .shepherd/ and .artifacts/ exist") == 3
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# shepherd.toml — found (three candidate paths) / not found.
# --------------------------------------------------------------------------
def test_config_not_found_warns(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    proc = run_doctor([], work_dir, env)

    assert "WARN   config    shepherd.toml          not found at standard paths" in proc.stdout
    assert "→ fix: create .claude/shepherd.toml" in proc.stdout


def test_config_found_at_project_toml(work_dir: Path, xdg_dir: Path) -> None:
    toml_path = work_dir / ".claude" / "shepherd.toml"
    toml_path.parent.mkdir(parents=True)
    toml_path.write_text("name = \"x\"\n")
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert f"OK     config    shepherd.toml          {toml_path}" in proc.stdout


def test_config_found_at_xdg_when_project_absent(work_dir: Path, xdg_dir: Path) -> None:
    xdg_toml = xdg_dir / "shepherd.toml"
    xdg_toml.write_text("name = \"x\"\n")
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert f"OK     config    shepherd.toml          {xdg_toml}" in proc.stdout


def test_config_project_toml_wins_over_local_and_xdg(work_dir: Path, xdg_dir: Path) -> None:
    """Bash parity: candidate order is project -> local -> XDG (see module
    docstring — deliberately NOT `cfg_get`'s own local-first precedence)."""
    claude_dir = work_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "shepherd.toml").write_text("name = \"project\"\n")
    (claude_dir / "shepherd.local.toml").write_text("name = \"local\"\n")
    (xdg_dir / "shepherd.toml").write_text("name = \"xdg\"\n")
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert f"OK     config    shepherd.toml          {claude_dir / 'shepherd.toml'}" in proc.stdout


def test_config_matches_bash_across_variants(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)
    assert python_proc.stdout == bash_proc.stdout

    claude_dir = work_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "shepherd.local.toml").write_text("name = \"local\"\n")
    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# Exit codes — 0 (all ok) / 1 (any fail) / 2 (warn only, no fail).
# --------------------------------------------------------------------------
def test_exit_code_1_when_any_fail(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"  # missing -> FAIL
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)
    assert proc.returncode == 1


def test_exit_code_2_when_warn_only_no_fail(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    # namespace dir ok, project.json ok, db ok, schema ok, pending ok, lock
    # free ok -> the only WARNs left are the 5 refresh zones + config not
    # found -> warn-only, no fail -> exit 2.
    assert proc.returncode == 2, proc.stdout


def test_exit_code_0_requires_config_and_refresh_all_ok(work_dir: Path, xdg_dir: Path) -> None:
    """A fully green run (0 fail, 0 warn) needs every zone refreshed
    recently AND a locatable `shepherd.toml` AND `gh`/`sqlite3`/`jq`/`git`
    all present -- `artifacts` can never contribute a fresh row (see the
    module docstring), so this asserts the OTHER four zones + config can
    still reach exit 0 collectively is impossible; this test instead
    proves the boundary: with `artifacts` always warning, exit 2 is the
    best achievable outcome on any real project."""
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))
    now = int(time.time())
    for table, cols in (
        ("index_symbols", dict(id="s1", project_id=project_id, name="F", kind="fn", package="p", file_path="f.rs", language="rust", hash="h", refreshed_at=now)),
        ("index_issues", dict(id="i1", project_id=project_id, source="github", number=1, title="t", state="open", url="https://x", created_at=now, updated_at=now, refreshed_at=now)),
        ("index_prs", dict(id="p1", project_id=project_id, source="github", number=1, title="t", state="open", base_branch="main", head_branch="f", url="https://x", created_at=now, updated_at=now, refreshed_at=now)),
        ("index_releases", dict(id="r1", project_id=project_id, source="github", tag="v1", url="https://x", refreshed_at=now)),
    ):
        _insert_row(db_path, table, **cols)
    claude_dir = work_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "shepherd.toml").write_text("name = \"x\"\n")
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    proc = run_doctor([], work_dir, env)

    assert proc.returncode == 2, proc.stdout  # artifacts zone still warns — structural, see module docstring
    assert proc.stdout.count("WARN") == 1
    assert "WARN   refresh   artifacts" in proc.stdout


# --------------------------------------------------------------------------
# --md is a no-op alias for the default format.
# --------------------------------------------------------------------------
def test_md_flag_matches_default(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    default_proc = run_doctor([], work_dir, env)
    md_proc = run_doctor(["--md"], work_dir, env)
    assert default_proc.stdout == md_proc.stdout
    assert default_proc.returncode == md_proc.returncode


def test_last_format_flag_wins(work_dir: Path, xdg_dir: Path) -> None:
    """Bash parity: `--json --md` ends with `fmt=md` (plain reassignment, last wins)."""
    env = _doctor_env(xdg_dir, workdir=work_dir)
    proc = run_doctor(["--json", "--md"], work_dir, env)
    assert proc.stdout.startswith("STATUS CATEGORY  NAME                   MESSAGE\n")


# --------------------------------------------------------------------------
# Section 7 — gates-invocation ledger (v6.5.0 #59; post-parity, conditional).
# --------------------------------------------------------------------------
_GATES_TOML = (
    "[gates]\n"
    'check = "jq empty plugin.json"\n'
    'lint  = "./lint.sh"\n'
    'format = ""\n'
    "\n"
    "[gates.extra]\n"
    'hook_tests = "bash hooks/tests/run.sh"\n'
    'ctx_tests  = "bash skills/context/tests/run.sh"\n'
)


def _write_gates_toml(work_dir: Path) -> None:
    claude_dir = work_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "shepherd.toml").write_text(_GATES_TOML)


def _write_ledger(work_dir: Path, session: str, gates: list[str]) -> Path:
    """One ledger row per gate label, in the exact shape bash_post.sh appends."""
    tmp_dir = work_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ledger = tmp_dir / f"gates-ran-{session}.jsonl"
    with ledger.open("a", encoding="utf-8") as fh:
        for gate in gates:
            fh.write(json.dumps({"ts": "2026-08-03T00:00:00Z", "gate": gate, "command": "x"}) + "\n")
    return ledger


def test_gates_section_absent_when_no_gates_configured(work_dir: Path, xdg_dir: Path) -> None:
    """No `[gates]` config → NO gates rows at all (the conditional-row contract
    that keeps every bash-parity fixture rendering byte-identically)."""
    env = _doctor_env(xdg_dir, workdir=work_dir)
    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["category"] == "gates"] == []


def test_gates_reports_ran_and_missing(work_dir: Path, xdg_dir: Path) -> None:
    """Configured gates each get one row: `ok ran Nx` when the ledger records
    the invocation, `warn no recorded invocation` otherwise. `format = ""`
    (empty command) is not a gate and gets no row."""
    _write_gates_toml(work_dir)
    _write_ledger(work_dir, "sess1", ["check", "check", "extra:hook_tests"])
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    gates = {c["name"]: c for c in payload["checks"] if c["category"] == "gates"}

    assert set(gates) == {"check", "lint", "extra:hook_tests", "extra:ctx_tests"}
    assert gates["check"]["status"] == "ok"
    assert gates["check"]["message"] == "ran 2x this session"
    assert gates["extra:hook_tests"]["status"] == "ok"
    assert gates["lint"]["status"] == "warn"
    assert gates["lint"]["message"] == "no recorded invocation this session"
    assert gates["extra:ctx_tests"]["status"] == "warn"
    assert proc.returncode == 1  # the fixture's missing-DB FAIL dominates the warns


def test_gates_all_warn_when_no_ledger_exists(work_dir: Path, xdg_dir: Path) -> None:
    _write_gates_toml(work_dir)
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    gates = [c for c in payload["checks"] if c["category"] == "gates"]

    assert len(gates) == 4
    assert all(c["status"] == "warn" for c in gates)
    assert all("bash_post.sh records it" in c["fix"] for c in gates)


def test_gates_reads_newest_ledger_only(work_dir: Path, xdg_dir: Path) -> None:
    """Two per-session ledgers: only the NEWEST (by mtime) counts as "this
    session" — an older session's green ledger must not mask the current
    session's un-run gates."""
    import os as _os

    _write_gates_toml(work_dir)
    old = _write_ledger(work_dir, "old-sess", ["check", "lint", "extra:hook_tests", "extra:ctx_tests"])
    new = _write_ledger(work_dir, "new-sess", ["lint"])
    _os.utime(old, (1_000_000_000, 1_000_000_000))
    _os.utime(new, (2_000_000_000, 2_000_000_000))
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    gates = {c["name"]: c["status"] for c in payload["checks"] if c["category"] == "gates"}

    assert gates == {"check": "warn", "lint": "ok", "extra:hook_tests": "warn", "extra:ctx_tests": "warn"}


def test_gates_rows_render_after_config_in_md(work_dir: Path, xdg_dir: Path) -> None:
    """Section order: the gates rows append AFTER the config section (the
    post-parity tail), never interleaved into the bash-parity region."""
    _write_gates_toml(work_dir)
    env = _doctor_env(xdg_dir, workdir=work_dir)

    proc = run_doctor([], work_dir, env)
    lines = [line for line in proc.stdout.splitlines() if line.strip() and not line.startswith(" ") and "shctx doctor:" not in line]
    categories = [line.split()[1] for line in lines[1:]]
    assert categories.index("config") < categories.index("gates")


# --------------------------------------------------------------------------
# Section 8 — CLI/plugin version match (v6.5.0 #235; post-parity, conditional).
# --------------------------------------------------------------------------
def _write_plugin_json(root: Path, version: str) -> None:
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": "shepherd", "version": version}))


def test_version_match_emits_no_row(work_dir: Path, xdg_dir: Path) -> None:
    """`CLAUDE_PLUGIN_ROOT` = the real repo (plugin.json version == the
    installed `shepherd_cli.__version__`) → silent, no `version` row."""
    env = _doctor_env(xdg_dir, workdir=work_dir)  # CLAUDE_PLUGIN_ROOT = REPO_ROOT
    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["category"] == "version"] == []


def test_version_mismatch_warns(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    plugin_root = tmp_path / "stale-plugin"
    _write_plugin_json(plugin_root, "0.0.1")
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = [c for c in payload["checks"] if c["category"] == "version"]

    from shepherd_cli import __version__

    assert len(rows) == 1
    assert rows[0]["status"] == "warn"
    assert rows[0]["name"] == "cli/plugin"
    assert f"running CLI {__version__} != plugin 0.0.1" in rows[0]["message"]
    assert "session_venv.sh" in rows[0]["fix"]
    assert proc.returncode == 1  # the fixture's missing-DB FAIL dominates the warn


def test_version_unset_env_emits_no_row(work_dir: Path, xdg_dir: Path) -> None:
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["category"] == "version"] == []


def test_version_unreadable_plugin_json_emits_no_row(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """A missing or malformed plugin.json is not a mismatch — silent (the
    binary-version check only ever reports a POSITIVE drift detection)."""
    plugin_root = tmp_path / "broken-plugin"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text("{not json")
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["category"] == "version"] == []
