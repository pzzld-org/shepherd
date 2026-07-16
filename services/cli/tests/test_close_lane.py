"""Subprocess parity tests for ``shepherd close-lane``.

Bash parity target: ``skills/context/scripts/cmd_close-lane.sh``. Every
test drives the real CLI as a subprocess (``${PY} -m shepherd_cli
close-lane ...``), exactly like ``test_search.py``/``test_sprint.py`` --
never by importing ``shepherd_cli`` into the pytest process itself.

Like ``shctx search``/``shctx query`` (see ``test_search.py``'s module
docstring), ``shctx close-lane``'s project-id resolution does NOT read the
``projects`` table -- it reads a ``project.json`` FILE in the resolved
shepherd work directory, independently of ``SHCTX_DB``. So every test
here sets ``SHEPHERD_WORKDIR`` to an isolated tmp directory (via
:func:`close_lane_env`) containing a ``project.json`` whose ``id`` matches
the fixture DB's seeded ``projects.id`` row.

``cmd_close-lane.sh``'s only external-process dependency is the ``gh``
CLI (for the ``--issues=`` GH-issue-state probe). Per the "deterministic,
local, free, <2s, never flaky" gate-test contract (CLAUDE.md), the
``gh``-probing tests below never touch the real network: they build a
throwaway ``bin/`` directory containing a tiny, fully-scripted ``gh``
stand-in (see :func:`_write_fake_gh`) and prepend it to ``PATH``, giving
full, fast, deterministic control over each probed issue's exit code and
output -- exactly ``test_sprint.py``'s fake-sibling-script technique,
applied to a real external BINARY (``gh``) instead of a sibling
``cmd_*.sh``. Every ``close_lane_env()`` call also pins
``SHCTX_GH_RETRY_BACKOFF=0`` so a transient-failure-then-retry test never
actually sleeps (``0 ** attempt == 0`` for every attempt >= 1).

The one non-deterministic byte in this command's own output is the
carry-forward patch's ``_Generated <UTC timestamp>_`` line (captured at
print time via a fresh ``date -u`` equivalent, NOT the earlier epoch-
seconds value used for the DB write) -- :func:`_normalize_ts` replaces it
with a fixed ``<TS>`` placeholder before every exact-string stdout
assertion, mirroring ``test_search.py``'s ``_normalize_ranks`` technique
for BM25's own non-reproducible-by-hand numeric output.
"""

from __future__ import annotations

import json
import re
import sqlite3
import stat
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import build_full_schema_db, cli_env, insert_project, run_cli

#: Verbatim bash-parity usage text -- must stay byte-for-byte identical to
#: shepherd_cli/commands/close-lane.py's own `_USAGE` constant.
_USAGE = (
    "shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] "
    "[--status=clean|partial|failed] [--acceptance=<path>]\n"
    "\n"
    "Record a mid-sprint lane closure. Auto-resolves carry-forward ledger items\n"
    "whose underlying GH issues have transitioned to closed.\n"
    "\n"
    '  <lane-id>           short identifier (e.g. "lane-3", "wave-2-lane-b")\n'
    "  --sprint=<branch>   sprint branch this lane closed under\n"
    "  --issues=#a,#b      GH issue numbers the lane was supposed to resolve\n"
    "  --status=...        clean (gates green) | partial (gates green w/ scope cuts) | failed\n"
    "  --acceptance=<path> optional path to the lane's [ACCEPTANCE] markdown to record\n"
    "\n"
    "Output: markdown patch for the carry-forward ledger (apply manually or via diff)."
)

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _normalize_ts(text: str) -> str:
    """Replace the carry-forward patch's live UTC timestamp with a fixed placeholder."""
    return _TS_RE.sub("<TS>", text)


# --------------------------------------------------------------------------
# Fixture DB + workdir/project.json + CLI-invocation helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row, matched by ``project.json`` in every test's workdir."""
    return insert_project(db_path)


def close_lane_env(
    db_path: Path,
    workdir: Path,
    *,
    project_id: str | None = None,
    write_project_json: bool = True,
    path_override: str | None = None,
    bin_dir: Path | None = None,
    call_log: Path | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the subprocess environment for a ``shepherd close-lane`` test.

    Args:
        db_path: The fixture DB (``SHCTX_DB``, via ``cli_env``).
        workdir: An isolated tmp directory used as ``SHEPHERD_WORKDIR`` --
            where ``project.json`` is read from, independently of
            ``SHCTX_DB``.
        project_id: The id to write into ``project.json``'s ``"id"``
            field, when ``write_project_json`` is True.
        write_project_json: When False, ``workdir`` is created but no
            ``project.json`` is written (drives the "not initialized"
            error path).
        path_override: When given, REPLACES ``PATH`` entirely (used to
            simulate "no `gh` binary anywhere on PATH").
        bin_dir: When given, PREPENDED to the inherited ``PATH`` (used to
            put a fake ``gh`` stand-in ahead of any real one).
        call_log: When given, sets ``CALL_LOG`` -- the fake ``gh``
            stand-in appends one line per invocation to this path.
        extra: Any additional env vars to set/override last.

    Returns:
        A full subprocess environment ready for ``conftest.run_cli``.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if write_project_json:
        (workdir / "project.json").write_text(json.dumps({"id": project_id}))
    env = cli_env(db_path)
    env["SHEPHERD_WORKDIR"] = str(workdir)
    # Keep any gh-retry-with-backoff test fast and deterministic:
    # 0 ** attempt == 0 for every attempt >= 1, so no real sleep happens.
    env["SHCTX_GH_RETRY_BACKOFF"] = "0"
    if path_override is not None:
        env["PATH"] = path_override
    elif bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if call_log is not None:
        env["CALL_LOG"] = str(call_log)
    if extra:
        env.update(extra)
    return env


def _run_close_lane(args: Sequence[str], env: dict[str, str]) -> object:
    return run_cli(["close-lane", *args], env)


def _write_fake_gh(bin_dir: Path, script_body: str) -> None:
    """Write a throwaway, fully-scripted ``gh`` stand-in to ``bin_dir``.

    Args:
        bin_dir: Directory to create the ``gh`` file in (created if
            missing).
        script_body: The bash script body AFTER the shebang line.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh_path = bin_dir / "gh"
    gh_path.write_text(f"#!/usr/bin/env bash\n{script_body}")
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC)


def _read_lane_closures(db_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM lane_closures ORDER BY lane_id"))
    finally:
        conn.close()


def _read_close_lane_events(db_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM logs_events WHERE source='close-lane' ORDER BY id"))
    finally:
        conn.close()


def _read_call_log(call_log: Path) -> list[str]:
    if not call_log.is_file():
        return []
    return [line.rstrip() for line in call_log.read_text().splitlines() if line.strip()]


def _expected_patch_stdout(
    lane_id: str, sprint_branch: str, resolved: list[str], still_open: list[str], status: str
) -> str:
    """Build the exact (post-``rstrip("\\n")``, ``<TS>``-normalized) stdout the port should print."""
    echoed: list[str] = [
        f"# carry-forward patch — lane `{lane_id}` (sprint `{sprint_branch}`)",
        "",
        "_Generated <TS> by shctx close-lane._",
        "",
    ]
    if resolved:
        echoed.append("## Resolved (move from Pending → Resolved)")
        for n in resolved:
            echoed.append(f"- [#{n}] ✅ Resolved by lane `{lane_id}` (status: {status})")
        echoed.append("")
    if still_open:
        echoed.append("## Still open (keep in Pending)")
        for n in still_open:
            echoed.append(f"- [#{n}] ⏳ Lane `{lane_id}` closed but issue still open — verify manually")
    if not resolved and not still_open:
        echoed.append("_No issues recorded for this lane closure._")
    echoed.append("")
    raw = "".join(line + "\n" for line in echoed)
    return raw.rstrip("\n")


def _expected_summary(lane_id: str, sprint_branch: str, resolved: list[str], still_open: list[str], status: str) -> str:
    return (
        f"shctx close-lane: recorded {lane_id} under {sprint_branch} "
        f"(resolved={len(resolved)}, still-open={len(still_open)}, status={status})"
    )


# --------------------------------------------------------------------------
# Usage / validation / not-found -- every non-happy exit-code branch.
# --------------------------------------------------------------------------
def test_no_args_shows_lane_id_required_and_usage_exits_1(db_path: Path, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane([], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == f"ERROR: lane-id required\n{_USAGE}"


def test_missing_sprint_shows_error_and_usage_exits_1(db_path: Path, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane(["lane-1"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == f"ERROR: --sprint= required\n{_USAGE}"


def test_invalid_status_shows_error_only_no_usage_exits_1(db_path: Path, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--status=bogus"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: --status must be clean|partial|failed"


@pytest.mark.parametrize("help_flag", ["-h", "--help"])
def test_help_flag_prints_usage_to_stdout_and_exits_0(db_path: Path, tmp_path: Path, help_flag: str) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane([help_flag], env)
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout.rstrip("\n") == _USAGE


def test_help_flag_short_circuits_before_later_tokens_examined(db_path: Path, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane(["lane-1", "--sprint=x", "-h", "--totally-bogus-flag"], env)
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout.rstrip("\n") == _USAGE


def test_unknown_flag_shows_error_and_usage_exits_1(db_path: Path, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane(["lane-1", "--sprint=x", "--bogus-flag"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == f"ERROR: unknown flag: --bogus-flag\n{_USAGE}"


def test_extra_positional_arg_shows_error_only_no_usage_exits_1(db_path: Path, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane(["lane-1", "extra-thing", "--sprint=x"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: extra arg: extra-thing"


def test_lane_closures_table_missing_exits_2(tmp_path: Path) -> None:
    """Bash parity: a DB predating migration 0003 has no ``lane_closures`` table.

    Simulated with a DB file that does not exist yet at all (zero tables)
    -- ``ensure_migrated``'s self-heal only runs against an EXISTING file
    per ``shepherd_cli.db``'s own contract, mirroring
    ``test_sprint.py::test_close_lane_closures_table_missing_skips_lane_step_without_error``'s
    identical technique for the SAME underlying guard.
    """
    fresh_db = tmp_path / "not-yet-created.db"
    assert not fresh_db.exists()
    env = close_lane_env(fresh_db, tmp_path / "wd", write_project_json=False)
    proc = _run_close_lane(["lane-1", "--sprint=feature-x"], env)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == (
        "ERROR: lane_closures table missing. Run `shctx migrate` to apply 0003_canonical_types_filter.sql."
    )


def test_missing_project_json_exits_1(db_path: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    env = close_lane_env(db_path, workdir, write_project_json=False)
    proc = _run_close_lane(["lane-1", "--sprint=feature-x"], env)
    assert proc.returncode == 1
    assert proc.stdout == ""
    expected_path = str(workdir / "project.json")
    assert proc.stderr.rstrip("\n") == f"ERROR: {expected_path} missing — run 'shctx init' first"


# --------------------------------------------------------------------------
# Happy path -- DB writes, markdown patch, stderr summary.
# --------------------------------------------------------------------------
def test_happy_path_no_issues_inserts_rows_and_prints_patch(db_path: Path, project_id: str, tmp_path: Path) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id)
    before = int(time.time())
    proc = _run_close_lane(["lane-7", "--sprint=feature-x"], env)
    after = int(time.time())

    assert proc.returncode == 0, proc.stderr
    assert _normalize_ts(proc.stdout.rstrip("\n")) == _expected_patch_stdout("lane-7", "feature-x", [], [], "clean")
    assert proc.stderr.rstrip("\n") == _expected_summary("lane-7", "feature-x", [], [], "clean")

    rows = _read_lane_closures(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["project_id"] == project_id
    assert row["sprint_branch"] == "feature-x"
    assert row["lane_id"] == "lane-7"
    assert before <= row["closed_at"] <= after
    assert row["resolved_issues"] == "[]"
    assert row["acceptance_log"] is None
    assert row["status"] == "clean"
    assert row["notes"] is None
    # UUIDv7-shaped id: 8-4-4-4-12 hex groups, version nibble '7'.
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", row["id"])

    events = _read_close_lane_events(db_path)
    assert len(events) == 1
    event = events[0]
    assert event["project_id"] == project_id
    assert event["level"] == "audit"
    assert event["source"] == "close-lane"
    assert event["event"] == "lane-closed"
    assert event["sprint_branch"] == "feature-x"
    assert event["payload"] == '{"lane":"lane-7","sprint":"feature-x","status":"clean","resolved":[]}'
    assert before <= event["ts"] <= after


@pytest.mark.parametrize("status", ["clean", "partial", "failed"])
def test_status_variants_accepted_and_stored(db_path: Path, project_id: str, tmp_path: Path, status: str) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id)
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", f"--status={status}"], env)
    assert proc.returncode == 0, proc.stderr
    rows = _read_lane_closures(db_path)
    assert rows[0]["status"] == status


def test_upsert_second_call_updates_existing_row_not_duplicate(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id)

    first = _run_close_lane(["lane-1", "--sprint=feature-x", "--status=partial"], env)
    assert first.returncode == 0, first.stderr
    second = _run_close_lane(["lane-1", "--sprint=feature-x", "--status=clean"], env)
    assert second.returncode == 0, second.stderr

    rows = _read_lane_closures(db_path)
    assert len(rows) == 1, "UNIQUE(project_id, sprint_branch, lane_id) must upsert, not duplicate"
    assert rows[0]["status"] == "clean"

    # Both calls still logged their own independent audit event (no upsert there).
    events = _read_close_lane_events(db_path)
    assert len(events) == 2


def test_acceptance_file_content_stored_trailing_newlines_stripped(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    acceptance_path = tmp_path / "acceptance.md"
    acceptance_path.write_text("[ACCEPTANCE]\nLooks good.\n\n\n")
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id)

    proc = _run_close_lane(["lane-1", "--sprint=feature-x", f"--acceptance={acceptance_path}"], env)
    assert proc.returncode == 0, proc.stderr

    rows = _read_lane_closures(db_path)
    assert rows[0]["acceptance_log"] == "[ACCEPTANCE]\nLooks good."


def test_acceptance_missing_file_reads_as_null_not_error(db_path: Path, project_id: str, tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist.md"
    assert not missing_path.exists()
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id)

    proc = _run_close_lane(["lane-1", "--sprint=feature-x", f"--acceptance={missing_path}"], env)
    assert proc.returncode == 0, proc.stderr

    rows = _read_lane_closures(db_path)
    assert rows[0]["acceptance_log"] is None


# --------------------------------------------------------------------------
# GH issue-state probe -- fake `gh` binary on PATH.
# --------------------------------------------------------------------------
def test_issues_flag_absent_no_gh_probe_no_issues_message(db_path: Path, project_id: str, tmp_path: Path) -> None:
    """No --issues= at all: neither bucket populated, no gh CLI invoked, no warning."""
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id, path_override="/nonexistent-bin-dir")
    proc = _run_close_lane(["lane-1", "--sprint=feature-x"], env)
    assert proc.returncode == 0, proc.stderr
    assert "gh CLI not found" not in proc.stderr
    assert "_No issues recorded for this lane closure._" in proc.stdout


def test_issues_all_commas_no_valid_numbers_treated_as_no_issues(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """--issues=",," parses to zero issue numbers -- same "no issues" shape as omitting the flag."""
    env = close_lane_env(db_path, tmp_path / "wd", project_id=project_id, path_override="/nonexistent-bin-dir")
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=,,"], env)
    assert proc.returncode == 0, proc.stderr
    # Bash parity: `--issues=,,` is a NON-EMPTY issues_csv, so cmd_close-lane.sh's
    # `elif [[ -n "$issues_csv" ]]` still fires the gh-absent probe warning (the
    # zero-valid-numbers filtering happens AFTER the warning). Only OMITTING the
    # flag entirely is truly silent. The lane still records zero resolved issues.
    assert "gh CLI not found" in proc.stderr
    assert "_No issues recorded for this lane closure._" in proc.stdout
    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == "[]"


def test_issues_gh_not_on_path_all_treated_still_open(db_path: Path, project_id: str, tmp_path: Path) -> None:
    env = close_lane_env(
        db_path, tmp_path / "wd", project_id=project_id, path_override="/nonexistent-bin-dir-for-tests"
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=#12,#34"], env)
    assert proc.returncode == 0, proc.stderr
    assert (
        "shctx close-lane: gh CLI not found; skipping issue-state probe (treating all listed as still-open)"
        in proc.stderr
    )
    assert _normalize_ts(proc.stdout.rstrip("\n")) == _expected_patch_stdout(
        "lane-1", "feature-x", [], ["12", "34"], "clean"
    )
    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == "[]"


def test_issues_resolved_and_still_open_buckets_via_fake_gh(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    _write_fake_gh(
        bin_dir,
        'echo "$*" >> "$CALL_LOG"\n'
        'n="$3"\n'
        'case "$n" in\n'
        '  12) echo "CLOSED" ;;\n'
        '  34) echo "OPEN" ;;\n'
        '  *)  echo "OPEN" ;;\n'
        "esac\n"
        "exit 0\n",
    )
    env = close_lane_env(
        db_path, tmp_path / "wd", project_id=project_id, bin_dir=bin_dir, call_log=call_log
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=#12,#34"], env)
    assert proc.returncode == 0, proc.stderr

    assert _normalize_ts(proc.stdout.rstrip("\n")) == _expected_patch_stdout(
        "lane-1", "feature-x", ["12"], ["34"], "clean"
    )
    assert proc.stderr.rstrip("\n") == _expected_summary("lane-1", "feature-x", ["12"], ["34"], "clean")

    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == '["12"]'

    events = _read_close_lane_events(db_path)
    payload = json.loads(events[0]["payload"])
    assert payload == {"lane": "lane-1", "sprint": "feature-x", "status": "clean", "resolved": ["12"]}

    calls = _read_call_log(call_log)
    assert calls == ["issue view 12 --json state -q .state", "issue view 34 --json state -q .state"]


def test_issue_number_parsing_strips_hash_and_internal_spaces(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """``"# 12,#34,,56"`` -> ``["12", "34", "56"]``: one leading ``#`` stripped per
    entry (bash: ``${raw#\\#}``), then every space removed (bash: ``${n// /}``),
    and the empty entry between the two commas dropped."""
    bin_dir = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    _write_fake_gh(bin_dir, 'echo "$*" >> "$CALL_LOG"\necho "CLOSED"\nexit 0\n')
    env = close_lane_env(
        db_path, tmp_path / "wd", project_id=project_id, bin_dir=bin_dir, call_log=call_log
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=# 12,#34,,56"], env)
    assert proc.returncode == 0, proc.stderr

    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == '["12","34","56"]'
    calls = _read_call_log(call_log)
    assert [c.split()[2] for c in calls] == ["12", "34", "56"]


def test_issue_number_leading_space_before_hash_preserves_hash_bash_quirk(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    """Bash-parity quirk, preserved deliberately (not "fixed"): ``${raw#\\#}``
    only strips a leading ``#`` when it is the pattern's FIRST character.
    An entry like ``" #34"`` (a SPACE before the ``#``) does not match that
    prefix-strip, so the subsequent ``${n// /}`` space-removal leaves the
    ``#`` in place -- the resulting "issue number" bash's own tooling would
    pass to ``gh issue view`` is the literal string ``"#34"``, hash and
    all."""
    bin_dir = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    _write_fake_gh(bin_dir, 'echo "$*" >> "$CALL_LOG"\necho "OPEN"\nexit 0\n')
    env = close_lane_env(
        db_path, tmp_path / "wd", project_id=project_id, bin_dir=bin_dir, call_log=call_log
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues= #34"], env)
    assert proc.returncode == 0, proc.stderr

    calls = _read_call_log(call_log)
    assert calls == ["issue view #34 --json state -q .state"]


def test_gh_transient_failure_retries_then_succeeds(db_path: Path, project_id: str, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    attempt_marker = tmp_path / "attempts"
    _write_fake_gh(
        bin_dir,
        'echo "$*" >> "$CALL_LOG"\n'
        f'count_file="{attempt_marker}"\n'
        'count=0\n'
        '[[ -f "$count_file" ]] && count=$(cat "$count_file")\n'
        'count=$((count + 1))\n'
        'echo "$count" > "$count_file"\n'
        'if (( count < 2 )); then\n'
        '  echo "HTTP 503 Service Unavailable"\n'
        "  exit 1\n"
        "fi\n"
        'echo "CLOSED"\n'
        "exit 0\n",
    )
    env = close_lane_env(
        db_path, tmp_path / "wd", project_id=project_id, bin_dir=bin_dir, call_log=call_log
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=#55"], env)
    assert proc.returncode == 0, proc.stderr

    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == '["55"]'
    # Two gh invocations: the first transient failure, then the retry that succeeded.
    assert len(_read_call_log(call_log)) == 2


def test_gh_non_transient_failure_fails_fast_no_retry(db_path: Path, project_id: str, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    _write_fake_gh(
        bin_dir,
        'echo "$*" >> "$CALL_LOG"\n'
        'echo "gh: issue not found (HTTP 404)"\n'
        "exit 1\n",
    )
    env = close_lane_env(
        db_path, tmp_path / "wd", project_id=project_id, bin_dir=bin_dir, call_log=call_log
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=#99"], env)
    assert proc.returncode == 0, proc.stderr

    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == "[]"
    assert _normalize_ts(proc.stdout.rstrip("\n")) == _expected_patch_stdout(
        "lane-1", "feature-x", [], ["99"], "clean"
    )
    # A non-transient failure fails immediately -- exactly one gh invocation.
    assert len(_read_call_log(call_log)) == 1


def test_gh_exhausts_retries_on_persistent_transient_failure_stays_still_open(
    db_path: Path, project_id: str, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    call_log = tmp_path / "calls.log"
    _write_fake_gh(
        bin_dir,
        'echo "$*" >> "$CALL_LOG"\n'
        'echo "HTTP 504 Gateway Timeout"\n'
        "exit 1\n",
    )
    env = close_lane_env(
        db_path,
        tmp_path / "wd",
        project_id=project_id,
        bin_dir=bin_dir,
        call_log=call_log,
        extra={"SHCTX_GH_RETRY_MAX": "2"},
    )
    proc = _run_close_lane(["lane-1", "--sprint=feature-x", "--issues=#77"], env)
    assert proc.returncode == 0, proc.stderr

    rows = _read_lane_closures(db_path)
    assert rows[0]["resolved_issues"] == "[]"
    # Every one of the 2 allowed attempts was used (both transient, both exhausted).
    assert len(_read_call_log(call_log)) == 2
