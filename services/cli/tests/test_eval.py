"""Subprocess parity tests for ``shepherd eval`` (quality-score a latent output).

Bash parity target: ``skills/context/scripts/cmd_eval.sh`` (v6.2.3), which
shells out to the REAL ``services/eval/eval.sh`` (which itself shells out to
the REAL ``services/llm/llm.sh``) — exactly what
``shepherd_cli.commands.eval`` does too (see that module's docstring). Every
test below drives the real CLI as a subprocess (``${PY} -m shepherd_cli
eval ...``), never by importing ``shepherd_cli`` into the pytest process,
matching every other suite in this package.

The judge is MOCKED via ``SHEPHERD_LLM_MOCK_TEXT`` (``services/llm/llm.sh``'s
own deterministic, free, no-network test seam — the SAME mechanism
``services/eval/tests/test_eval_score.sh`` uses for the bash side), so this
suite makes zero real model calls and stays fast/deterministic, while still
exercising the REAL ``services/eval/eval.sh`` judge-prompt-build + weighted-
overall arithmetic end to end — a true integration test of the subprocess
boundary, not a reimplementation of it.

Unlike :mod:`shepherd_cli.commands.mem`/``lock``'s "read the ``projects``
table" deviation, ``shctx eval`` resolves the active project from a
``project.json`` FILE (mirrors ``cmd_query.sh``/``cmd_search.sh`` — see
``test_query.py``'s module docstring for the identical setup rationale), so
every test here sets ``SHEPHERD_WORKDIR`` to an isolated tmp directory
containing a ``project.json`` whose ``id`` matches the fixture DB's seeded
``projects.id`` row.

Rows are seeded directly via raw ``sqlite3`` (schema-tolerant via ``PRAGMA
table_info``, mirroring ``conftest.insert_teammate``/``test_query.py``'s
``_insert_row``) rather than through the CLI itself, so ordering/filter/
render tests don't depend on ``run --record`` also being correct.

**Integration note:** as of this test file's authoring, ``eval`` is not yet
wired into :mod:`shepherd_cli.app`'s ``add_typer`` calls,
:mod:`shepherd_cli.__main__`'s ``PORTED`` set, or
:mod:`shepherd_cli.db`'s ``modules={"models": [...]}`` list — that wiring
is a separate "integrate" pass (the established two-step pattern this
repo's own task history follows for every new command group). Every test
below is written assuming that wiring is complete, matching every other
test module in this suite.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, build_full_schema_db, cli_env, insert_project, run_cli

# --------------------------------------------------------------------------
# Fixture DB + workdir/project.json + raw-sqlite3 seed helpers.
# --------------------------------------------------------------------------


def _insert_row(db_path: Path, table: str, values: dict[str, object]) -> None:
    """Insert one row into ``table``, keeping only columns that actually exist.

    Schema-tolerant like ``conftest.insert_teammate``/``test_query.py``'s
    identically-named helper (duplicated here — self-contained test
    modules, mirroring the command modules' own convention): reads
    ``PRAGMA table_info(table)`` and silently drops any key in ``values``
    that isn't a real column.

    Args:
        db_path: The fixture DB to write into.
        table: Table name (test-controlled constant, never user input).
        values: ``{column: value}`` to insert; extra keys are ignored.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {info[1] for info in conn.execute(f"PRAGMA table_info({table})")}  # noqa: S608 - fixed test table names only
        fields = [key for key in values if key in columns]
        placeholders = ", ".join("?" for _ in fields)
        col_list = ", ".join(fields)
        conn.execute(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",  # noqa: S608 - fixed table/column allow-list above
            [values[key] for key in fields],
        )
        conn.commit()
    finally:
        conn.close()


def _eval_runs_rows(db_path: Path) -> list[sqlite3.Row]:
    """Every ``eval_runs`` row, ordered by ``id`` (insertion order)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM eval_runs ORDER BY id"))
    finally:
        conn.close()


@pytest.fixture
def eval_db(tmp_path: Path) -> tuple[Path, str]:
    """A full-schema fixture DB (every migration applied, including 0018) with one project.

    ``build_full_schema_db`` applies every ``migrations/*.sql`` file, so
    ``eval_runs``/``v_eval_latest`` already exist before any CLI
    invocation touches this DB — this suite therefore cannot construct
    the bash-parity "eval_runs table missing" scenario (a real bash
    project predating migration 0018) as a genuine fixture: this port's
    own schema self-heal (``db.lifespan()`` -> ``ensure_migrated``) would
    silently apply migration 0018 the moment ANY ``shepherd eval``
    subcommand opens a connection, before ``_has_eval_table()`` ever runs
    — making that branch structurally unreachable through a real fixture
    DB in this port (a deliberate, documented consequence of the self-
    heal contract every ported command shares, not a gap specific to this
    module). The reachable "empty" analog — project registered, table
    present, zero matching rows — is covered instead (see
    ``test_report_empty_but_table_and_project_present`` /
    ``test_list_empty_but_table_and_project_present``).

    Returns:
        ``(db_path, project_id)``.
    """
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    project_id = insert_project(db_path)
    return db_path, project_id


def eval_env(
    db_path: Path,
    workdir: Path,
    *,
    project_id: str = "proj-test",
    write_project_json: bool = True,
    llm_mock_text: str | None = None,
    eval_svc: str | None = None,
) -> dict[str, str]:
    """The environment for driving ``shepherd eval`` against one fixture DB.

    Args:
        db_path: The sqlite file (drives ``SHCTX_DB`` via :func:`cli_env`).
        workdir: An isolated tmp directory used as the shepherd work
            directory (``SHEPHERD_WORKDIR``) — where ``project.json`` is
            read from, independently of ``SHCTX_DB``.
        project_id: The id to write into ``project.json``'s ``"id"``
            field, when ``write_project_json`` is True.
        write_project_json: When False, ``workdir`` is created but no
            ``project.json`` is written — drives the "registry not
            initialized" (``run``) / "no evals yet" (``report``/``list``)
            paths.
        llm_mock_text: When given, sets ``SHEPHERD_LLM_MOCK_TEXT`` so
            ``services/llm/llm.sh`` returns this verbatim instead of
            calling the real ``claude`` binary — the deterministic mock
            seam ``run`` tests need.
        eval_svc: When given, sets ``SHEPHERD_EVAL_SVC`` to override
            which ``eval.sh`` gets shelled out to (used by the
            "service not found" test).

    Returns:
        A full subprocess environment.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    if llm_mock_text is not None:
        env["SHEPHERD_LLM_MOCK_TEXT"] = llm_mock_text
    if eval_svc is not None:
        env["SHEPHERD_EVAL_SVC"] = eval_svc
    return env


_HIGH_SCORES = json.dumps(
    {"scores": {"specificity": 4, "actionability": 4, "grounding": 3}, "rationale": "a specific, actionable lesson"}
)
# 4,4,3 -> weighted sum = 4*2+4*2+3*1 = 19 -> overall = round(100*19/25) = 76 -> PASS (threshold 60).

_LOW_SCORES = json.dumps(
    {"scores": {"specificity": 1, "actionability": 1, "grounding": 1}, "rationale": "vague, generic advice"}
)
# 1,1,1 -> overall = 20 -> FAIL (threshold 60).


# --------------------------------------------------------------------------
# Top-level dispatch: no-subcommand / help / unknown subcommand.
# --------------------------------------------------------------------------
def test_no_subcommand_prints_usage_and_exits_0(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # Bash parity: cmd="${1:-help}" -- a bare `shctx eval` is NOT a usage error.
    db_path, project_id = eval_db
    proc = run_cli(["eval"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 0
    assert proc.stdout.startswith("shctx eval — quality-score a latent agent output against a rubric.")
    assert "eval run --kind=K" in proc.stdout
    assert "Exit (run): 0 pass · 1 below threshold · 2 usage · 4 judge/parse error." in proc.stdout


@pytest.mark.parametrize("flag", ["help", "-h", "--help"])
def test_help_variants_print_usage_and_exit_0(eval_db: tuple[Path, str], tmp_path: Path, flag: str) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", flag], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 0
    assert "shctx eval — quality-score" in proc.stdout


def test_unknown_subcommand_exits_2_with_message(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "bogus"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "shctx eval: unknown subcommand: bogus (try: run | report | list | help)" in proc.stderr


# --------------------------------------------------------------------------
# run — validation / usage errors (exit 2).
# --------------------------------------------------------------------------
def test_run_missing_kind_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "run", "--input=x"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "shctx eval: run needs --kind=<rubric>" in proc.stderr


def test_run_unknown_arg_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--bogus"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id),
    )
    assert proc.returncode == 2
    assert "shctx eval: unknown arg: --bogus" in proc.stderr


def test_run_no_input_source_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "run", "--kind=reflection"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "no input — pass --input-file/--input/-" in proc.stderr


def test_run_input_file_not_found_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    missing = tmp_path / "does-not-exist.txt"
    proc = run_cli(
        ["eval", "run", "--kind=reflection", f"--input-file={missing}"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id),
    )
    assert proc.returncode == 2
    assert f"shctx eval: --input-file not found: {missing}" in proc.stderr


def test_run_empty_input_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=   "],
        eval_env(db_path, tmp_path / "wd", project_id=project_id),
    )
    assert proc.returncode == 2
    assert "shctx eval: nothing to evaluate (empty input)" in proc.stderr


def test_run_service_not_found_exits_4(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    missing_svc = str(tmp_path / "no-such-eval.sh")
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, eval_svc=missing_svc),
    )
    assert proc.returncode == 4
    assert f"shctx eval: eval service not found at {missing_svc}" in proc.stderr


def test_run_judge_output_missing_dimensions_exits_4(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # Bash parity: services/eval/tests/test_eval_errors.sh's "missing dimension" case
    # -- a syntactically valid but incomplete judge response fails deterministic
    # validation inside services/eval/eval.sh itself, which exits 4; cmd_eval.sh
    # forwards that exit code verbatim (rc >= 2 -> die "eval service error ...").
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text="{}"),
    )
    assert proc.returncode == 4
    assert "shctx eval: eval service error (exit 4)" in proc.stderr


# --------------------------------------------------------------------------
# run — happy paths (--json / --md / text), pass and fail verdicts.
# --------------------------------------------------------------------------
def test_run_json_pass_verdict(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    verdict = json.loads(proc.stdout)
    assert verdict["kind"] == "reflection"
    assert verdict["overall"] == 76
    assert verdict["threshold"] == 60
    assert verdict["passed"] is True
    assert verdict["scores"] == {"specificity": 4, "actionability": 4, "grounding": 3}
    assert verdict["rationale"] == "a specific, actionable lesson"


def test_run_json_fail_verdict_exits_1(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_LOW_SCORES),
    )
    assert proc.returncode == 1
    verdict = json.loads(proc.stdout)
    assert verdict["overall"] == 20
    assert verdict["passed"] is False


def test_run_threshold_override_flips_verdict(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # overall=76 normally PASSes (threshold 60); --threshold=80 flips it to FAIL.
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x", "--threshold=80", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 1
    verdict = json.loads(proc.stdout)
    assert verdict["threshold"] == 80
    assert verdict["passed"] is False


def test_run_text_format(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert lines[0] == "EVAL reflection (inline) — score=76/100 threshold=60 PASS  model=opus"
    assert lines[1] == '  scores: {"specificity":4,"actionability":4,"grounding":3}'
    assert lines[2] == "  rationale: a specific, actionable lesson"


def test_run_md_format(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x", "--md"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    expected = (
        "**EVAL `reflection`** (inline) — **76/100** (threshold 60) — PASS · model `opus`\n"
        "\n"
        "- specificity: 4\n"
        "- actionability: 4\n"
        "- grounding: 3\n"
        "\n"
        "_a specific, actionable lesson_"
    )
    assert proc.stdout.rstrip("\n") == expected


def test_run_subject_ref_defaults_to_inline_for_dash_input(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # --input= with no --sprint -> subject_ref "inline" (bash: subject_ref="${sprint:-inline}").
    # subject_ref isn't part of the service's own JSON payload (that's a
    # cmd_eval.sh-side concept, not services/eval/eval.sh's), so it's only
    # observable via --record + a DB read, or the text renderer's "(inline)".
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x", "--record"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    assert "(inline)" in proc.stdout.splitlines()[0]
    rows = _eval_runs_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["subject_ref"] == "inline"


def test_run_input_file_subject_ref_is_basename(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    input_file = tmp_path / "note.txt"
    input_file.write_text("a specific, grounded lesson about test coverage")
    proc = run_cli(
        ["eval", "run", "--kind=reflection", f"--input-file={input_file}"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    assert "EVAL reflection (note.txt)" in proc.stdout.splitlines()[0]


def test_run_stdin_dash(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # run_cli() (conftest.py) never pipes stdin text, so the "-" stdin sentinel
    # needs a raw subprocess.run() call here instead.
    db_path, project_id = eval_db
    env = eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES)
    completed = subprocess.run(
        [PY, "-m", "shepherd_cli", "eval", "run", "--kind=reflection", "-", "--json"],
        input="a specific, grounded lesson via stdin",
        env=env,
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0
    verdict = json.loads(completed.stdout)
    assert verdict["overall"] == 76


# --------------------------------------------------------------------------
# run — reflection-note pull from the registry.
# --------------------------------------------------------------------------
def _seed_reflection(db_path: Path, project_id: str, sprint: str, note: str) -> None:
    now = int(time.time())
    _insert_row(
        db_path,
        "mem_entries",
        {
            "id": f"mem-{sprint}",
            "project_id": project_id,
            "kind": "prior",
            "title": f"prior: reflection ({sprint})",
            "body": f"[reflection] sprint {sprint}: {note}",
            "tags": "[]",
            "pinned": 0,
            "created_at": now,
            "updated_at": now,
        },
    )


def test_run_reflection_pulls_stored_note(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    _seed_reflection(db_path, project_id, "sprint-7", "write more integration tests up front")
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--sprint=sprint-7", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    verdict = json.loads(proc.stdout)
    assert verdict["overall"] == 76


def test_run_reflection_missing_note_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--sprint=no-such-sprint"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 2
    assert "shctx eval: no reflection stored for 'no-such-sprint'" in proc.stderr


def test_run_reflection_missing_project_json_exits_4(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    workdir = tmp_path / "wd"
    env = eval_env(
        db_path, workdir, project_id=project_id, write_project_json=False, llm_mock_text=_HIGH_SCORES
    )
    proc = run_cli(["eval", "run", "--kind=reflection", "--sprint=sprint-7"], env)
    assert proc.returncode == 4
    assert f"ERROR: {workdir / 'project.json'} missing — run 'shctx init' first" in proc.stderr
    assert "shctx eval: registry not initialized — run 'shctx init'" in proc.stderr


# --------------------------------------------------------------------------
# run --record.
# --------------------------------------------------------------------------
def test_run_record_writes_eval_runs_row(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    before = _eval_runs_rows(db_path)
    assert before == []

    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--sprint=sprint-9", "--input=x", "--record", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    assert "recorded" not in proc.stdout  # --json prints the raw service verdict only

    rows = _eval_runs_rows(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["project_id"] == project_id
    assert row["kind"] == "reflection"
    assert row["subject_ref"] == "sprint-9"
    assert row["score"] == 76
    assert row["threshold"] == 60
    assert row["passed"] == 1
    assert row["model"] == "opus"
    assert json.loads(row["scores_json"]) == {"specificity": 4, "actionability": 4, "grounding": 3}
    assert row["rationale"] == "a specific, actionable lesson"
    assert row["created_at"] > 0


def test_run_without_record_writes_nothing(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    run_cli(
        ["eval", "run", "--kind=reflection", "--input=x"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert _eval_runs_rows(db_path) == []


def test_run_record_text_and_md_suffixes(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(
        ["eval", "run", "--kind=reflection", "--input=x", "--record"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc.returncode == 0
    assert proc.stdout.splitlines()[0].endswith("model=opus  [recorded]")

    proc_md = run_cli(
        ["eval", "run", "--kind=reflection", "--input=y", "--record", "--md"],
        eval_env(db_path, tmp_path / "wd2", project_id=project_id, llm_mock_text=_HIGH_SCORES),
    )
    assert proc_md.returncode == 0
    assert "· recorded" in proc_md.stdout.splitlines()[0]


def test_run_record_without_project_json_exits_4(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    workdir = tmp_path / "wd"
    env = eval_env(
        db_path, workdir, project_id=project_id, write_project_json=False, llm_mock_text=_HIGH_SCORES
    )
    proc = run_cli(["eval", "run", "--kind=reflection", "--input=x", "--record"], env)
    assert proc.returncode == 4
    assert "shctx eval: registry not initialized — run 'shctx init'" in proc.stderr
    assert _eval_runs_rows(db_path) == []


# --------------------------------------------------------------------------
# report.
# --------------------------------------------------------------------------
def _seed_eval_run(
    db_path: Path,
    *,
    row_id: str,
    project_id: str,
    kind: str,
    subject_ref: str | None,
    score: int,
    threshold: int,
    passed: int,
    model: str | None,
    created_at: int,
    scores_json: str = '{"a":1}',
    rationale: str | None = "r",
) -> None:
    _insert_row(
        db_path,
        "eval_runs",
        {
            "id": row_id,
            "project_id": project_id,
            "kind": kind,
            "subject_ref": subject_ref,
            "score": score,
            "threshold": threshold,
            "passed": passed,
            "model": model,
            "scores_json": scores_json,
            "rationale": rationale,
            "created_at": created_at,
        },
    )


def test_report_no_project_registered(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    env = eval_env(db_path, tmp_path / "wd", project_id=project_id, write_project_json=False)
    proc = run_cli(["eval", "report"], env)
    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == "no evals yet"


def test_report_no_project_registered_json(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    env = eval_env(db_path, tmp_path / "wd", project_id=project_id, write_project_json=False)
    proc = run_cli(["eval", "report", "--json"], env)
    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == "[]"


def test_report_empty_but_table_and_project_present(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    env = eval_env(db_path, tmp_path / "wd", project_id=project_id)

    proc_text = run_cli(["eval", "report"], env)
    assert proc_text.returncode == 0
    assert proc_text.stdout.rstrip("\n") == "no evals recorded yet (run: shctx eval run … --record)"

    proc_md = run_cli(["eval", "report", "--md"], env)
    assert proc_md.returncode == 0
    assert proc_md.stdout.rstrip("\n") == "_no evals recorded yet._"

    proc_json = run_cli(["eval", "report", "--json"], env)
    assert proc_json.returncode == 0
    assert proc_json.stdout.rstrip("\n") == "[]"


def test_report_json_structure_and_ordering(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    now = int(time.time())
    _seed_eval_run(
        db_path, row_id="r-old", project_id=project_id, kind="reflection", subject_ref="s1",
        score=70, threshold=60, passed=1, model="opus", created_at=now - 100,
        scores_json='{"specificity":4}', rationale="older",
    )
    _seed_eval_run(
        db_path, row_id="r-new", project_id=project_id, kind="reflection", subject_ref="s2",
        score=30, threshold=60, passed=0, model=None, created_at=now,
        scores_json='{"specificity":1}', rationale="newer",
    )

    proc = run_cli(["eval", "report", "--json"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert len(payload) == 2
    # ORDER BY created_at DESC -- the newer row (r-new) comes first.
    assert [row["subject_ref"] for row in payload] == ["s2", "s1"]
    assert payload[0] == {
        "kind": "reflection",
        "subject_ref": "s2",
        "score": 30,
        "threshold": 60,
        "passed": False,
        "model": None,
        "rationale": "newer",
        "created_at": now,
    }
    assert payload[1]["passed"] is True
    assert payload[1]["model"] == "opus"


def test_report_filters_by_kind_and_sprint(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    now = int(time.time())
    _seed_eval_run(
        db_path, row_id="r1", project_id=project_id, kind="reflection", subject_ref="sprint-a",
        score=80, threshold=60, passed=1, model="opus", created_at=now,
    )
    _seed_eval_run(
        db_path, row_id="r2", project_id=project_id, kind="discovery", subject_ref="sprint-a",
        score=80, threshold=60, passed=1, model="opus", created_at=now,
    )
    _seed_eval_run(
        db_path, row_id="r3", project_id=project_id, kind="reflection", subject_ref="sprint-b",
        score=80, threshold=60, passed=1, model="opus", created_at=now,
    )

    proc = run_cli(
        ["eval", "report", "--kind=reflection", "--sprint=sprint-a", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id),
    )
    payload = json.loads(proc.stdout)
    assert len(payload) == 1
    assert payload[0]["kind"] == "reflection"
    assert payload[0]["subject_ref"] == "sprint-a"


def test_report_text_and_md_rendering(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    now = int(time.time())
    _seed_eval_run(
        db_path, row_id="r1", project_id=project_id, kind="reflection", subject_ref="sprint-x",
        score=76, threshold=60, passed=1, model="opus", created_at=now,
    )

    proc_text = run_cli(["eval", "report"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc_text.returncode == 0
    lines = proc_text.stdout.splitlines()
    assert lines[0] == "KIND         SUBJECT          SCORE  THR VERD  MODEL    AGE"
    assert lines[1].startswith("reflection   sprint-x           76%   60 PASS  opus")

    proc_md = run_cli(["eval", "report", "--md"], eval_env(db_path, tmp_path / "wd2", project_id=project_id))
    assert proc_md.returncode == 0
    md_lines = proc_md.stdout.splitlines()
    assert md_lines[0] == "### Eval scores (latest per subject)"
    assert md_lines[2] == "| kind | subject | score | thr | verdict | model |"
    assert md_lines[4] == "| reflection | sprint-x | 76 | 60 | PASS | opus |"


def test_report_renders_middle_dot_for_null_subject_and_model(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    _seed_eval_run(
        db_path, row_id="r1", project_id=project_id, kind="seed", subject_ref=None,
        score=50, threshold=60, passed=0, model=None, created_at=int(time.time()),
    )
    proc = run_cli(["eval", "report"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert "·" in proc.stdout


def test_report_unknown_arg_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "report", "--bogus"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "shctx eval: unknown arg: --bogus" in proc.stderr


# --------------------------------------------------------------------------
# list.
# --------------------------------------------------------------------------
def test_list_no_project_registered(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    env = eval_env(db_path, tmp_path / "wd", project_id=project_id, write_project_json=False)
    proc = run_cli(["eval", "list"], env)
    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == "no evals yet"

    proc_json = run_cli(["eval", "list", "--json"], env)
    assert proc_json.stdout.rstrip("\n") == "[]"


def test_list_empty_but_table_and_project_present(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "list"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 0
    assert proc.stdout.rstrip("\n") == "no evals recorded yet"


def test_list_json_structure_includes_id(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    now = int(time.time())
    _seed_eval_run(
        db_path, row_id="r1", project_id=project_id, kind="reflection", subject_ref="s1",
        score=76, threshold=60, passed=1, model="opus", created_at=now,
    )
    proc = run_cli(["eval", "list", "--json"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload == [
        {
            "id": "r1",
            "kind": "reflection",
            "subject_ref": "s1",
            "score": 76,
            "threshold": 60,
            "passed": True,
            "model": "opus",
            "created_at": now,
        }
    ]


def test_list_respects_limit_kind_filter_and_ordering(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    now = int(time.time())
    for i in range(3):
        _seed_eval_run(
            db_path, row_id=f"refl-{i}", project_id=project_id, kind="reflection", subject_ref=f"s{i}",
            score=70 + i, threshold=60, passed=1, model="opus", created_at=now + i,
        )
    _seed_eval_run(
        db_path, row_id="disc-0", project_id=project_id, kind="discovery", subject_ref="d0",
        score=80, threshold=60, passed=1, model="opus", created_at=now + 10,
    )

    proc = run_cli(
        ["eval", "list", "--kind=reflection", "--limit=2", "--json"],
        eval_env(db_path, tmp_path / "wd", project_id=project_id),
    )
    payload = json.loads(proc.stdout)
    assert len(payload) == 2
    # created_at DESC -> refl-2 (highest created_at) then refl-1.
    assert [row["id"] for row in payload] == ["refl-2", "refl-1"]
    assert all(row["kind"] == "reflection" for row in payload)


def test_list_md_flag_falls_back_to_plain_text_rendering(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # Bash quirk, preserved deliberately: `eval list` has NO dedicated markdown
    # table renderer -- `--md` silently produces the SAME plain-text row output
    # as the default (no-flag) case, unlike `eval report --md`.
    db_path, project_id = eval_db
    _seed_eval_run(
        db_path, row_id="r1", project_id=project_id, kind="reflection", subject_ref="s1",
        score=76, threshold=60, passed=1, model="opus", created_at=int(time.time()),
    )
    proc_default = run_cli(["eval", "list"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    proc_md = run_cli(["eval", "list", "--md"], eval_env(db_path, tmp_path / "wd2", project_id=project_id))
    assert proc_default.returncode == proc_md.returncode == 0
    # The rendered row embeds a relative "<N>s ago" age; the two invocations
    # can straddle a second boundary, so normalize the age token before the
    # byte comparison (the flag-parity contract under test is about the
    # RENDERER, not wall-clock timing).
    _age = re.compile(r"\b\d+[smhd] ago\b")
    assert _age.sub("AGE ago", proc_default.stdout) == _age.sub("AGE ago", proc_md.stdout)
    assert "|" not in proc_md.stdout


def test_list_bad_limit_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "list", "--limit=abc"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "shctx eval: --limit must be an integer" in proc.stderr


def test_list_negative_limit_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    # Bash parity: the `^[0-9]+$` regex rejects a leading '-' (unsigned only).
    db_path, project_id = eval_db
    proc = run_cli(["eval", "list", "--limit=-1"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "shctx eval: --limit must be an integer" in proc.stderr


def test_list_unknown_arg_exits_2(eval_db: tuple[Path, str], tmp_path: Path) -> None:
    db_path, project_id = eval_db
    proc = run_cli(["eval", "list", "--bogus"], eval_env(db_path, tmp_path / "wd", project_id=project_id))
    assert proc.returncode == 2
    assert "shctx eval: unknown arg: --bogus" in proc.stderr
