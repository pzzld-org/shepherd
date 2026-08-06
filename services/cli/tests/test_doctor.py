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


# --------------------------------------------------------------------------
# Post-parity section stripping (sections 7-9, v6.4.1 #59/#235/#254).
#
# Every section `cmd_doctor.sh` itself never had is CONDITIONAL by design
# (silent on a gate-less / version-matched / no-declared-profile fixture —
# see `shepherd_cli/commands/doctor.py`'s module docstring), so most
# fixtures in this file never need this. But `_doctor_env` points
# `CLAUDE_PLUGIN_ROOT` at the real checked-out repo (needed for
# `find_migrations_dir`/bundled-style lookups elsewhere in this suite), and
# section 8 fires whenever the checked-out `.claude-plugin/plugin.json`
# version drifts from the installed `shepherd_cli.__version__` — an
# environment/release-hygiene condition entirely orthogonal to `doctor`
# correctness. The bash-parity assertions below strip every post-parity
# category and recompute the trailing tally from what's left, so they test
# what they say they test: parity on `cmd_doctor.sh`'s own six sections,
# regardless of what an unrelated version drift happens to add on top.
# --------------------------------------------------------------------------
_POST_PARITY_CATEGORIES = {"gates", "version", "user", "bootstrap"}


def _strip_post_parity_md(stdout: str) -> str:
    """Drop every post-parity row (+ its optional `-> fix:` continuation)
    from an md report and recompute the trailing summary line from the
    rows that remain — see the block comment above."""
    lines = stdout.split("\n")
    kept: list[str] = []
    skip_next_fix = False
    for line in lines:
        if skip_next_fix and line.startswith("       ") and "→ fix:" in line:
            skip_next_fix = False
            continue
        skip_next_fix = False
        if line.startswith("shctx doctor:"):
            continue
        columns = line.split(None, 2)
        if len(columns) >= 2 and columns[1] in _POST_PARITY_CATEGORIES:
            skip_next_fix = True
            continue
        kept.append(line)
    while kept and kept[-1] == "":
        kept.pop()
    fail = sum(1 for line in kept if line.startswith("FAIL"))
    warn = sum(1 for line in kept if line.startswith("WARN"))
    ok = sum(1 for line in kept if line.startswith("OK"))
    kept.append("")
    kept.append(f"shctx doctor: {fail} fail, {warn} warn, {ok} ok")
    kept.append("")  # preserve the trailing newline `typer.echo` (and bash's own `echo`) always emit
    return "\n".join(kept)


def _strip_post_parity_json(payload: dict) -> dict:
    """JSON-mode analogue of `_strip_post_parity_md`."""
    checks = [c for c in payload["checks"] if c["category"] not in _POST_PARITY_CATEGORIES]
    return {
        "summary": {
            "total": len(checks),
            "fail": sum(1 for c in checks if c["status"] == "fail"),
            "warn": sum(1 for c in checks if c["status"] == "warn"),
        },
        "checks": checks,
    }


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
    # Stripped to the bash-parity 6-section tally (`_strip_post_parity_md`):
    # section 10's own `bootstrap db` row ALSO fails on a missing DB (see
    # `test_bootstrap_db_row_matches_section_3_missing` below) -- correctly,
    # not a regression -- so the RAW last line now reads "2 fail," and this
    # assertion only asserts what `cmd_doctor.sh` itself would have said.
    assert "1 fail," in _strip_post_parity_md(proc.stdout).splitlines()[-1]


def test_missing_db_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=work_dir)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout


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
    stripped = _strip_post_parity_md(python_proc.stdout)
    assert stripped == bash_proc.stdout, f"python (stripped):\n{stripped}\n---\nbash:\n{bash_proc.stdout}"
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
    # Structural, not byte-for-byte: `_strip_post_parity_json` recomputes
    # `summary` from the filtered `checks` list, so a `total`/`warn` count
    # inflated by an unrelated `version`/`gates`/`user` row can never mask
    # a genuine parity break in cmd_doctor.sh's own six sections.
    assert _strip_post_parity_json(json.loads(python_proc.stdout)) == json.loads(bash_proc.stdout)


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
    # in this relative order (never interleaved or reordered). Post-parity
    # categories (gates/version/user — sections 7-9) are conditional tails
    # that may or may not fire depending on config/environment (e.g. a
    # `plugin.json` version drift); this fixture cares only that the SIX
    # bash-native sections stay in their fixed relative order, so those
    # tails are dropped before comparing.
    seen_order: list[str] = []
    for cat in categories_in_order:
        if cat in _POST_PARITY_CATEGORIES:
            continue
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

    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout
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

    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout
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
        assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout, content
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
        assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout, scenario
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
    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout


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

    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout
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
    assert "→ fix: run 'shctx config init'" in proc.stdout


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
    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout

    claude_dir = work_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "shepherd.local.toml").write_text("name = \"local\"\n")
    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)
    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout


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
    # Counted on the stripped report: an unrelated post-parity WARN (e.g. a
    # `plugin.json` version drift, section 8) is not this fixture's concern
    # — see `_strip_post_parity_md`.
    assert _strip_post_parity_md(proc.stdout).count("WARN") == 1
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
# Section 7 — gates-invocation ledger (v6.4.1 #59; post-parity, conditional).
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
# Section 8 — CLI/plugin version match (v6.4.1 #235; post-parity, conditional).
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


# --------------------------------------------------------------------------
# Section 8b — a NEWER plugin installed under another publisher (v6.4.3 #235,
# second half). Section 8 compares the CLI against the plugin at
# CLAUDE_PLUGIN_ROOT; this one compares that plugin against every OTHER
# publisher's installs, which is the discrepancy the reported incident had
# and nothing surfaced.
# --------------------------------------------------------------------------
def _cache_tree(tmp_path: Path, installs: dict[str, str]) -> Path:
    """Build `.../cache/<publisher>/shepherd/<version>/` for each pair given."""
    cache = tmp_path / "cache"
    for publisher, version in installs.items():
        target = cache / publisher / "shepherd" / version / ".claude-plugin"
        target.mkdir(parents=True, exist_ok=True)
        (target / "plugin.json").write_text(json.dumps({"name": "shepherd", "version": version}))
    return cache


def _version_rows(work_dir: Path, env: dict[str, str], name: str) -> list[dict]:
    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    return [c for c in payload["checks"] if c["category"] == "version" and c["name"] == name]


def test_newer_plugin_under_another_publisher_warns(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """The #235 incident, verbatim: fl03/6.3.3 in use, pzzld/6.3.9 installed.

    A launcher globbing one publisher pinned the whole fleet — root, six lane
    conductors, and the hooks — to the dead 6.3.3 for days. Doctor could not
    see it, because the only version check compared the CLI against the very
    plugin root that was already wrong.
    """
    cache = _cache_tree(tmp_path, {"fl03": "6.3.3", "pzzld": "6.3.9"})
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(cache / "fl03" / "shepherd" / "6.3.3")

    rows = _version_rows(work_dir, env, "plugin/installed")
    assert len(rows) == 1
    assert rows[0]["status"] == "warn"
    assert "running plugin 6.3.3" in rows[0]["message"]
    assert "6.3.9 is installed under another publisher dir" in rows[0]["message"]
    assert "install-shctx-launcher.sh" in rows[0]["fix"]


def test_newest_plugin_in_use_emits_no_row(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """Already on the highest install → silent, whichever publisher ships it."""
    cache = _cache_tree(tmp_path, {"fl03": "6.3.3", "pzzld": "6.3.9"})
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(cache / "pzzld" / "shepherd" / "6.3.9")

    assert _version_rows(work_dir, env, "plugin/installed") == []


def test_newer_plugin_compares_segments_numerically(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """6.4.10 beats 6.4.9 — a string sort gets this backwards.

    The launcher fix and this check must agree on ordering, and both must be
    genuinely numeric rather than accidentally right while patch numbers
    stay single-digit.
    """
    cache = _cache_tree(tmp_path, {"fl03": "6.4.10", "pzzld": "6.4.9"})
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(cache / "pzzld" / "shepherd" / "6.4.9")

    rows = _version_rows(work_dir, env, "plugin/installed")
    assert len(rows) == 1
    assert "6.4.10 is installed" in rows[0]["message"]


def test_non_cache_plugin_root_emits_no_row(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """A repo clone run in place is not the cache layout — stay silent, never guess."""
    plugin_root = tmp_path / "checkout" / "claude-shepherd"
    _write_plugin_json(plugin_root, "6.4.3")
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    assert _version_rows(work_dir, env, "plugin/installed") == []


# --------------------------------------------------------------------------
# Section 9 — user-level tier, `~/.shepherd` (v6.4.1 #254; post-parity, NOT
# purely conditional — see `_check_user_tier`'s own docstring). Every test
# below pops `CLAUDE_PLUGIN_ROOT` (`test_version_unset_env_emits_no_row`'s
# own technique) so section 8's own real-repo version-drift condition never
# adds noise here — `_check_user_tier` has no `CLAUDE_PLUGIN_ROOT`
# dependency of its own.
# --------------------------------------------------------------------------
def _user_tier_env(xdg_dir: Path, *, db_path: Path, workdir: Path, home_dir: Path) -> dict[str, str]:
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=workdir)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env["SHEPHERD_HOME"] = str(home_dir)
    return env


def test_user_tier_absent_is_info_not_a_failure(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"  # never created -> a real FAIL, to prove info != fail/warn
    env = _user_tier_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = [c for c in payload["checks"] if c["category"] == "user"]

    assert len(rows) == 1
    assert rows[0]["name"] == "~/.shepherd"
    assert rows[0]["status"] == "info"
    assert str(home_dir) in rows[0]["message"]
    assert rows[0]["fix"] == "shepherd home init"
    # `info` must never be tallied as `fail` or `warn`.
    assert payload["summary"]["warn"] == sum(1 for c in payload["checks"] if c["status"] == "warn")
    assert payload["summary"]["fail"] == sum(1 for c in payload["checks"] if c["status"] == "fail")

    md_proc = run_doctor([], work_dir, env)
    assert "INFO   user      ~/.shepherd" in md_proc.stdout
    assert "shepherd home init" in md_proc.stdout


def test_user_tier_present_reports_ok(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "user-home" / ".shepherd"
    home_dir.mkdir(parents=True)
    db_path = work_dir.parent / "shepherd.db"
    env = _user_tier_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = [c for c in payload["checks"] if c["category"] == "user"]

    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert rows[0]["message"] == str(home_dir)
    assert rows[0]["fix"] == ""


def test_user_tier_reports_declared_profile_source(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """A profile with a real project-tier file gets a `profile:<name>` row
    naming the tier it resolves from."""
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    canonical = work_dir / "profiles" / "rust" / "style.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("PROJECT RUST STYLE\n")
    env = _user_tier_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = {c["name"]: c for c in payload["checks"] if c["category"] == "user"}

    assert "profile:rust" in rows
    assert rows["profile:rust"]["status"] == "ok"
    assert rows["profile:rust"]["message"] == "resolves from project"


def test_user_tier_reports_legacy_and_user_tier_profiles(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "user-home" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    legacy = work_dir / "styles" / "go.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("LEGACY GO STYLE\n")
    user_style = home_dir / "profiles" / "python" / "style.md"
    user_style.parent.mkdir(parents=True)
    user_style.write_text("USER PYTHON STYLE\n")
    env = _user_tier_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = {c["name"]: c["message"] for c in payload["checks"] if c["category"] == "user"}

    assert rows["profile:go"] == "resolves from legacy"
    assert rows["profile:python"] == "resolves from user"


def test_user_tier_excludes_bundled_only_profiles(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """A language with ONLY a bundled default (no project/legacy/user file)
    is not "declared" by the project — no `profile:*` row for it, even
    though `shepherd style show` would happily resolve it from bundled."""
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    env = _user_tier_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)  # real bundled styles/ exist here — must still be excluded

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    profile_rows = [c for c in payload["checks"] if c["category"] == "user" and c["name"].startswith("profile:")]

    assert profile_rows == []


def test_user_tier_row_appears_after_config_section_in_md(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    env = _user_tier_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor([], work_dir, env)
    lines = [line for line in proc.stdout.splitlines() if line.strip() and not line.startswith(" ") and "shctx doctor:" not in line]
    categories = [line.split()[1] for line in lines[1:]]
    assert categories.index("config") < categories.index("user")


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


# --------------------------------------------------------------------------
# Section 10 — bootstrap completeness (v6.4.2 #P3; post-parity, NOT in
# cmd_doctor.sh). Always exactly 5 rows, unlike sections 7/8's purely
# conditional tails — see `_check_bootstrap`'s own docstring. Every test
# here pops `CLAUDE_PLUGIN_ROOT` (section 9's own technique, `_user_tier_env`)
# so section 8's real-repo version-drift condition never adds noise, and
# sets `SHEPHERD_HOME` so section 9's `~/.shepherd` row never touches the
# real host home.
# --------------------------------------------------------------------------
def _bootstrap_env(xdg_dir: Path, *, db_path: Path, workdir: Path, home_dir: Path) -> dict[str, str]:
    env = _doctor_env(xdg_dir, db_path=db_path, workdir=workdir)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env["SHEPHERD_HOME"] = str(home_dir)
    return env


def _bootstrap_rows(payload: dict) -> dict[str, dict]:
    return {c["name"]: c for c in payload["checks"] if c["category"] == "bootstrap"}


def test_bootstrap_section_always_emits_exactly_five_rows(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"  # never created -- the sparsest possible fixture
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = _bootstrap_rows(payload)

    assert set(rows) == {"namespace", "db", "project", "shepherd.toml", "user tier"}


def test_bootstrap_namespace_row_missing_and_present(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"

    missing_workdir = work_dir / "does-not-exist"
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=missing_workdir, home_dir=home_dir)
    proc = run_doctor(["--json"], work_dir, env)
    row = _bootstrap_rows(json.loads(proc.stdout))["namespace"]
    assert row["status"] == "fail"
    assert row["fix"] == "shepherd init"

    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)
    proc = run_doctor(["--json"], work_dir, env)
    row = _bootstrap_rows(json.loads(proc.stdout))["namespace"]
    assert row["status"] == "ok"
    assert row["message"] == str(work_dir)
    assert row["fix"] == ""


def test_bootstrap_db_row_missing_present_and_pending(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"

    missing_db = work_dir.parent / "shepherd.db"
    env = _bootstrap_env(xdg_dir, db_path=missing_db, workdir=work_dir, home_dir=home_dir)
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["db"]
    assert row["status"] == "fail"
    assert row["message"] == "missing"
    assert row["fix"] == "shepherd init"

    head_db = work_dir.parent / "head.db"
    build_full_schema_db(head_db)
    env = _bootstrap_env(xdg_dir, db_path=head_db, workdir=work_dir, home_dir=home_dir)
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["db"]
    assert row["status"] == "ok"
    assert row["message"] == "present, at HEAD"
    assert row["fix"] == ""

    # Pending-migration DETECTION needs a resolvable migrations dir, i.e.
    # CLAUDE_PLUGIN_ROOT -- unlike the other two cases above, this one
    # cannot pop it the way `_bootstrap_env` does for the rest of this
    # section (see that helper's own "section 8 noise" rationale); the
    # `version` category simply isn't asserted on here.
    partial_db = work_dir.parent / "partial.db"
    build_partial_schema_db(partial_db)
    env = _doctor_env(xdg_dir, db_path=partial_db, workdir=work_dir)
    env["SHEPHERD_HOME"] = str(home_dir)
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["db"]
    assert row["status"] == "warn"
    expected_pending = _shipped_migration_count()
    assert row["message"] == f"present, {expected_pending} pending migration(s)"
    assert row["fix"] == "shepherd init"


def test_bootstrap_project_row_missing_malformed_and_ok(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)

    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["project"]
    assert row["status"] == "fail"
    assert row["message"] == "not registered"

    (work_dir / "project.json").write_text(json.dumps({"id": None}))
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["project"]
    assert row["status"] == "fail"

    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["project"]
    assert row["status"] == "ok"
    assert row["message"] == f"registered (id={project_id})"
    assert row["fix"] == ""


def test_bootstrap_config_row_names_the_resolved_tier(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """Bash-parity section 6 is frozen (3 legacy candidates only — see
    `_bootstrap_config_row`'s own docstring); THIS row imports lane P1's
    live `_config_search_paths` and therefore sees the v6.4.2 workdir
    tier too — the exact gap section 6 cannot close without breaking its
    own bash-parity contract."""
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["shepherd.toml"]
    assert row["status"] == "warn"
    assert row["message"] == "not present"
    assert row["fix"] == "shepherd init"

    workdir_toml = work_dir / "shepherd.toml"
    workdir_toml.write_text("[project]\nname = \"x\"\n")
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["shepherd.toml"]
    assert row["status"] == "ok"
    assert f"(workdir tier) at {workdir_toml}" in row["message"]

    workdir_toml.unlink()
    # resolve_repo_root() falls back to cwd (== work_dir, non-git) here, so
    # the legacy candidate is <cwd>/.claude/shepherd.toml.
    legacy_toml = work_dir / ".claude" / "shepherd.toml"
    legacy_toml.parent.mkdir(parents=True)
    legacy_toml.write_text("name = \"legacy\"\n")
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["shepherd.toml"]
    assert row["status"] == "ok"
    assert f"(legacy tier) at {legacy_toml}" in row["message"]


def test_bootstrap_user_tier_row_matches_section_9_semantics(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    db_path = work_dir.parent / "shepherd.db"

    absent_home = tmp_path / "does-not-exist" / ".shepherd"
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=absent_home)
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["user tier"]
    assert row["status"] == "info"  # never fail/warn — section 9's own semantics, not duplicated
    assert row["fix"] == "shepherd home init"

    present_home = tmp_path / "user-home" / ".shepherd"
    present_home.mkdir(parents=True)
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=present_home)
    row = _bootstrap_rows(json.loads(run_doctor(["--json"], work_dir, env).stdout))["user tier"]
    assert row["status"] == "ok"
    assert row["message"] == str(present_home)


def test_bootstrap_section_appears_after_user_section_in_md(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    proc = run_doctor([], work_dir, env)
    lines = [line for line in proc.stdout.splitlines() if line.strip() and not line.startswith(" ") and "shctx doctor:" not in line]
    categories = [line.split()[1] for line in lines[1:]]
    assert categories.index("user") < categories.index("bootstrap")


def test_bootstrap_section_bash_parity_stripped_matches_bash(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """The new section never leaks into (or otherwise changes) the
    byte-for-byte bash comparison once stripped — same discipline every
    other post-parity section's own bash-parity test already applies."""
    home_dir = tmp_path / "does-not-exist" / ".shepherd"
    db_path = work_dir.parent / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    (work_dir / "project.json").write_text(json.dumps({"id": project_id}))
    env = _bootstrap_env(xdg_dir, db_path=db_path, workdir=work_dir, home_dir=home_dir)

    python_proc = run_doctor([], work_dir, env)
    bash_proc = run_bash_doctor([], work_dir, env)

    assert _strip_post_parity_md(python_proc.stdout) == bash_proc.stdout


def test_bootstrap_row_count_never_disturbs_dual_namespace_stderr_warning_count(
    work_dir: Path, xdg_dir: Path
) -> None:
    """Section 10's `shepherd.toml` row calls `_config_search_paths`, which
    resolves `resolve_workdir()` INTERNALLY -- must stay wrapped in
    `_quiet_env` (see `_bootstrap_config_row`'s own docstring) or this
    would silently become a 4th un-quieted call and break this exact
    triplicate-warning count, the same one
    `test_dual_namespace_conflict_warns_and_triplicates_stderr_warning`
    (bash-parity, unmodified) already pins down."""
    (work_dir / ".shepherd").mkdir()
    (work_dir / ".artifacts").mkdir()
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    proc = run_doctor([], work_dir, env)

    assert proc.stderr.count("shctx WARNING: both .shepherd/ and .artifacts/ exist") == 3


# --------------------------------------------------------------------------
# Section 8a — CLI venv provisioned (#266).
# --------------------------------------------------------------------------
def test_unprovisioned_cli_venv_fails(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """A venv DIRECTORY with no installed distributions is the #266 state.

    `poetry env info --executable` creates the venv as a side effect, so this is
    exactly what a fresh upgrade left behind: present, empty, and fatal to every
    `shepherd` command with a traceback naming `typer` rather than the venv.
    """
    plugin_root = tmp_path / "plugin"
    _write_plugin_json(plugin_root, "0.0.1")
    (plugin_root / "services" / "cli" / ".venv" / "bin").mkdir(parents=True)
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    rows = [c for c in payload["checks"] if c["name"] == "cli/venv"]

    assert len(rows) == 1
    assert rows[0]["status"] == "fail"
    assert "no installed dependencies" in rows[0]["message"]
    assert "poetry install" in rows[0]["fix"]


def test_provisioned_cli_venv_emits_no_row(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """The console script `poetry install` writes is sufficient evidence."""
    plugin_root = tmp_path / "plugin"
    _write_plugin_json(plugin_root, "0.0.1")
    bindir = plugin_root / "services" / "cli" / ".venv" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "shepherd").write_text("#!/bin/sh\n")
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["name"] == "cli/venv"] == []


def test_no_root_install_cli_venv_emits_no_row(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """A `--no-root` install has deps but no console script — still healthy."""
    plugin_root = tmp_path / "plugin"
    _write_plugin_json(plugin_root, "0.0.1")
    site = plugin_root / "services" / "cli" / ".venv" / "lib" / "python3.11" / "site-packages"
    (site / "typer").mkdir(parents=True)
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["name"] == "cli/venv"] == []


def test_absent_cli_venv_emits_no_row(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """No venv at all is normal (PYTHONPATH / system install) — never flagged.

    Reporting this would fire on every healthy non-poetry setup; the broken
    state is specifically present-but-empty.
    """
    plugin_root = tmp_path / "plugin"
    _write_plugin_json(plugin_root, "0.0.1")
    env = _doctor_env(xdg_dir, workdir=work_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)

    proc = run_doctor(["--json"], work_dir, env)
    payload = json.loads(proc.stdout)
    assert [c for c in payload["checks"] if c["name"] == "cli/venv"] == []
