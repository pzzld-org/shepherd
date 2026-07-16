"""Tests for `shepherd discovery` — native port of `cmd_discovery.sh`.

Bash parity target: `skills/context/scripts/cmd_discovery.sh`. This
command is MIXED filesystem + database (see
`shepherd_cli/commands/discovery.py`'s module docstring):

* `list`/`show`/`search`/`clear` are pure filesystem — one JSON record per
  discovery at `<workdir>/discoveries/<sprint>/<id>.json`. These tests
  drive the real CLI as a subprocess with an ISOLATED work directory
  (`SHEPHERD_WORKDIR` set to an absolute `tmp_path` subdirectory), exactly
  like `test_insights.py` (the closest structural precedent — same
  filesystem shape, same JSON-per-record store).
* `insert` is the one subcommand that touches SQLite (writes a
  `discovery_findings` row). Those tests seed a full-schema fixture DB via
  raw `sqlite3` (`conftest.build_full_schema_db` + `insert_project`) and
  assert on the resulting row via `PRAGMA table_info`-tolerant raw reads,
  the same pattern `test_query.py`/`test_handoff.py` use for tables with no
  writable Tortoise model.

Several tests additionally run the legacy `cmd_discovery.sh` directly,
under the identical env, asserting byte-for-byte stdout/exit-code parity —
the same pattern `test_insights.py`/`test_config.py`/`test_search.py`
established. This is possible for every subcommand including `insert`
since bash's own `insert` intercept, like this port's, only needs
`SHCTX_DB` (no namespace/git resolution at all).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Sequence

import pytest
from conftest import PY, REPO_ROOT, build_full_schema_db, clean_env_dict, insert_project

CMD_DISCOVERY_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_discovery.sh"

_USAGE_MARKER = "shctx discovery — discovery report registry"


# --------------------------------------------------------------------------
# Isolation fixtures + subprocess helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory to use as the CLI's `cwd`."""
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def workdir_root(tmp_path: Path) -> Path:
    """The `.shepherd`-equivalent namespace directory `SHEPHERD_WORKDIR` points at.

    Kept separate from `work_dir` (the CLI's `cwd`) deliberately — bash's
    own `resolve_workdir()`/`shctx_artifacts_root()` never assume the
    namespace lives under `cwd`, only `SHEPHERD_WORKDIR` (or repo-root
    auto-detection, bypassed here) determines it.
    """
    d = tmp_path / "ns"
    d.mkdir()
    return d


def _discovery_env(workdir_root: Path, *, db_path: Path | None = None) -> dict[str, str]:
    """A stripped-then-rebuilt environment pointed at an isolated namespace.

    Args:
        workdir_root: Sets `SHEPHERD_WORKDIR`.
        db_path: When given, sets `SHCTX_DB` (only `insert` tests need
            this — `list`/`show`/`search`/`clear` never open the database).
    """
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir_root)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    if db_path is not None:
        env["SHCTX_DB"] = str(db_path)
    return env


def run_discovery(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -m shepherd_cli discovery <args>` under `cwd`."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_bash_discovery(args: list[str], cwd: Path, env: dict[str, str], *, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_discovery.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(
        ["bash", str(CMD_DISCOVERY_SH), *args],
        cwd=str(cwd),
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write_discovery(
    workdir_root: Path,
    sprint: str,
    disc_id: str,
    *,
    question: object = "What is the canonical type freshness policy?",
    sources_count: object = "3",
    tool_calls: object = "5",
    time_used: object = "2m",
    report_path: object = "",
    confidence: object = "high",
    status: object = "done",
    anomalies: object = "",
    reporter: object = "discovery-agent",
    captured_at: int | None = None,
    consumed: bool = False,
    consumed_by: object = None,
    extra: dict[str, object] | None = None,
) -> Path:
    """Write one discovery JSON record at `<workdir_root>/discoveries/<sprint>/<id>.json`.

    Mirrors the exact field shape `hooks/scripts/discovery_capture.sh`
    writes (see that script's inline `python3` heredoc).
    """
    root = workdir_root / "discoveries" / sprint
    root.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "id": disc_id,
        "schema_version": 1,
        "sprint": sprint,
        "captured_at": captured_at if captured_at is not None else int(time.time()),
        "question": question,
        "sources_count": sources_count,
        "tool_calls": tool_calls,
        "time_used": time_used,
        "report_path": report_path,
        "confidence": confidence,
        "status": status,
        "anomalies": anomalies,
        "reporter": reporter,
        "consumed": consumed,
        "consumed_by": consumed_by,
    }
    if extra:
        record.update(extra)
    path = root / f"{disc_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """An isolated, throwaway git repo checked out on `feature-x` — for the
    "default --sprint is the current git branch" scenario."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "first commit")
    _git(repo, "checkout", "-q", "-b", "feature-x")
    return repo


# --------------------------------------------------------------------------
# Top-level dispatch: bare / -h / --help / help / unknown subcommand.
# --------------------------------------------------------------------------
def test_bare_invocation_prints_usage_and_exits_0(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)
    assert "shctx discovery list [--sprint=<branch>] [--json|--md]" in proc.stdout
    assert "shctx discovery show <id> [--md|--json|--report]" in proc.stdout
    assert 'shctx discovery search --question="<paraphrase>"' in proc.stdout
    assert "shctx discovery clear --sprint=<branch> [--force]" in proc.stdout
    assert "shctx discovery insert --run=<id> --title=<t>" in proc.stdout


@pytest.mark.parametrize("args", [[], ["-h"], ["--help"], ["help"]])
def test_help_variants_print_usage_and_exit_0(args: list[str], work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(args, work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)


def test_help_variants_all_match_bare_exactly(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    bare = run_discovery([], work_dir, env)
    for args in (["-h"], ["--help"], ["help"]):
        variant = run_discovery(args, work_dir, env)
        assert variant.returncode == bare.returncode == 0
        assert variant.stdout == bare.stdout


def test_unknown_subcommand_exits_1_with_error_and_usage_on_stderr(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(["bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("ERROR: unknown shctx discovery subcommand: bogus\n")
    assert _USAGE_MARKER in proc.stderr


def test_bare_bash_parity(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    python_proc = run_discovery([], work_dir, env)
    bash_proc = run_bash_discovery([], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_unknown_subcommand_bash_parity(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    python_proc = run_discovery(["bogus"], work_dir, env)
    bash_proc = run_bash_discovery(["bogus"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# list.
# --------------------------------------------------------------------------
def test_list_no_discoveries_dir_prints_notice_with_dir_path(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(["list", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    expected_dir = workdir_root / "discoveries" / "sprint-a"
    assert proc.stdout.rstrip("\n") == f"[shctx discovery] no discoveries for sprint 'sprint-a' (dir: {expected_dir})"


def test_list_empty_sprint_dir_prints_notice_without_dir_suffix(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "discoveries" / "sprint-a").mkdir(parents=True)
    env = _discovery_env(workdir_root)
    proc = run_discovery(["list", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "[shctx discovery] no discoveries for sprint 'sprint-a'"


def test_list_default_format_is_markdown_ordered_by_id(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T020000-cccc", question="third")
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="first")
    _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb", question="second")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["list", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0] == "| id | question | confidence | sources | reporter |"
    assert lines[1] == "|---|---|---|---|---|"
    assert lines[2].startswith("| 20260101T000000-aaaa | first |")
    assert lines[3].startswith("| 20260101T010000-bbbb | second |")
    assert lines[4].startswith("| 20260101T020000-cccc | third |")


def test_list_md_row_truncates_question_to_60_chars_and_renders_null_fields(
    work_dir: Path, workdir_root: Path
) -> None:
    long_question = "x" * 100
    _write_discovery(
        workdir_root,
        "sprint-a",
        "20260101T000000-aaaa",
        question=long_question,
        confidence=None,
        sources_count=None,
        reporter=None,
    )
    env = _discovery_env(workdir_root)

    proc = run_discovery(["list", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    row = proc.stdout.rstrip("\n").splitlines()[2]
    assert row == f"| 20260101T000000-aaaa | {'x' * 60} | null | null | null |"


def test_list_json_output_is_array_of_raw_records(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="q1")
    _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb", question="q2")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["list", "--sprint=sprint-a", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert [row["id"] for row in parsed] == ["20260101T000000-aaaa", "20260101T010000-bbbb"]
    assert parsed[0]["question"] == "q1"
    assert parsed[1]["question"] == "q2"


def test_list_explicit_md_flag(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["list", "--sprint=sprint-a", "--json", "--md"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("| id | question |")


def test_list_unrecognized_flag_silently_ignored(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["list", "--sprint=sprint-a", "--whatever", "-x"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "20260101T000000-aaaa" in proc.stdout


def test_list_default_sprint_is_current_git_branch(git_repo: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "feature-x", "20260101T000000-aaaa", question="on-branch")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["list"], git_repo, env)

    assert proc.returncode == 0, proc.stderr
    assert "on-branch" in proc.stdout


def test_list_bash_parity_json(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="q1", confidence=None)
    _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb", question="q2")
    env = _discovery_env(workdir_root)

    python_proc = run_discovery(["list", "--sprint=sprint-a", "--json"], work_dir, env)
    bash_proc = run_bash_discovery(["list", "--sprint=sprint-a", "--json"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_list_bash_parity_markdown(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="q1", confidence=None)
    _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb", question="q2", sources_count=0)
    env = _discovery_env(workdir_root)

    python_proc = run_discovery(["list", "--sprint=sprint-a"], work_dir, env)
    bash_proc = run_bash_discovery(["list", "--sprint=sprint-a"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_list_bash_parity_no_dir(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    python_proc = run_discovery(["list", "--sprint=nope"], work_dir, env)
    bash_proc = run_bash_discovery(["list", "--sprint=nope"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# show.
# --------------------------------------------------------------------------
def test_show_missing_id_exits_1(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(["show"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: shctx discovery show <id>"


def test_show_not_found_exits_1(work_dir: Path, workdir_root: Path) -> None:
    # The `discoveries/` root must already exist (any prior discovery, any
    # sprint) for the friendly "id not found" message to fire -- see
    # test_show_missing_discoveries_dir_silently_exits_1 for the bash-bug
    # case where it does not exist at all.
    _write_discovery(workdir_root, "sprint-other", "20260101T000000-zzzz")
    env = _discovery_env(workdir_root)
    proc = run_discovery(["show", "nope-id"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "[shctx discovery] id not found: nope-id"


def test_show_missing_discoveries_dir_silently_exits_1(work_dir: Path, workdir_root: Path) -> None:
    """Bash-bug parity: when `<ns>/discoveries` was never created at all (no
    discovery has EVER been captured, for any sprint), `cmd_show()`'s
    `find` call fails on its own missing top-level path, which — combined
    with `pipefail` and a bare command-substitution assignment — trips
    `set -e` and aborts the whole bash script SILENTLY (exit 1, no stdout,
    no stderr) before the "id not found" message is ever reached. See the
    module docstring's "BASH BUG MIRRORED DELIBERATELY" note in
    `_do_show`.
    """
    assert not (workdir_root / "discoveries").exists()
    env = _discovery_env(workdir_root)
    proc = run_discovery(["show", "nope-id"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_show_json_prints_raw_file_bytes(work_dir: Path, workdir_root: Path) -> None:
    path = _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["show", "20260101T000000-aaaa", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == path.read_text()


def test_show_default_format_is_json(work_dir: Path, workdir_root: Path) -> None:
    path = _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["show", "20260101T000000-aaaa"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == path.read_text()


def test_show_md_renders_structured_record(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(
        workdir_root,
        "sprint-a",
        "20260101T000000-aaaa",
        question="What is the freshness policy?",
        confidence="high",
        sources_count="3",
        tool_calls="5",
        time_used="2m",
        report_path="/tmp/report.md",
        status="done",
        reporter="discovery-agent",
        consumed=False,
    )
    env = _discovery_env(workdir_root)

    proc = run_discovery(["show", "20260101T000000-aaaa", "--md"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "# Discovery 20260101T000000-aaaa\n"
        "\n"
        "- Sprint:       sprint-a\n"
        "- Question:     What is the freshness policy?\n"
        "- Confidence:   high\n"
        "- Sources:      3\n"
        "- Tool calls:   5\n"
        "- Time used:    2m\n"
        "- Report:       /tmp/report.md\n"
        "- Status:       done\n"
        "- Reporter:     discovery-agent\n"
        "- Consumed:     false\n"
        "\n"
    )


def test_show_report_prints_report_file_content(work_dir: Path, workdir_root: Path, tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("# The report\n\nBody text.\n")
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", report_path=str(report))
    env = _discovery_env(workdir_root)

    proc = run_discovery(["show", "20260101T000000-aaaa", "--report"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == report.read_text()


def test_show_report_missing_file_exits_1(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", report_path="/no/such/report.md")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["show", "20260101T000000-aaaa", "--report"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "[shctx discovery] report file not found: /no/such/report.md"


def test_show_id_taken_literally_when_flag_shaped_but_unrecognized(work_dir: Path, workdir_root: Path) -> None:
    """A token that LOOKS like a flag but isn't `--md`/`--json`/`--report`
    is captured as the id itself — bash parity (see the module docstring's
    `_do_show` note)."""
    _write_discovery(workdir_root, "sprint-other", "20260101T000000-zzzz")
    env = _discovery_env(workdir_root)
    proc = run_discovery(["show", "--bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stderr.rstrip("\n") == "[shctx discovery] id not found: --bogus"


def test_show_ignores_extra_trailing_args(work_dir: Path, workdir_root: Path) -> None:
    path = _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["show", "20260101T000000-aaaa", "extra-token", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == path.read_text()


def test_show_bash_parity_md(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(
        workdir_root,
        "sprint-a",
        "20260101T000000-aaaa",
        question=None,
        confidence="high",
        sources_count=3,
        consumed=True,
    )
    env = _discovery_env(workdir_root)

    python_proc = run_discovery(["show", "20260101T000000-aaaa", "--md"], work_dir, env)
    bash_proc = run_bash_discovery(["show", "20260101T000000-aaaa", "--md"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_show_bash_parity_missing_discoveries_dir(work_dir: Path, workdir_root: Path) -> None:
    """Bash-bug parity (see `_do_show`'s docstring): `discoveries/` never
    created at all -> both sides silently exit 1, no output."""
    env = _discovery_env(workdir_root)
    python_proc = run_discovery(["show", "nope"], work_dir, env)
    bash_proc = run_bash_discovery(["show", "nope"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr == ""


def test_show_bash_parity_not_found_with_discoveries_dir_present(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-other", "20260101T000000-zzzz")
    env = _discovery_env(workdir_root)
    python_proc = run_discovery(["show", "nope"], work_dir, env)
    bash_proc = run_bash_discovery(["show", "nope"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# search.
# --------------------------------------------------------------------------
def test_search_missing_question_exits_1(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(["search"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == 'ERROR: shctx discovery search --question="<text>"'


def test_search_no_matches_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="unrelated topic")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["search", "--question=canonical types"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "[shctx discovery] no matches for: canonical types"


def test_search_case_insensitive_substring_match(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(
        workdir_root, "sprint-a", "20260101T000000-aaaa", question="Canonical Types freshness policy"
    )
    env = _discovery_env(workdir_root)

    proc = run_discovery(["search", "--question=CANONICAL types"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0] == "| id | sprint | question | confidence | report |"
    assert lines[1] == "|---|---|---|---|---|"
    assert "20260101T000000-aaaa" in lines[2]


def test_search_orders_matches_across_sprints(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-b", "20260101T020000-cccc", question="canonical third")
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="canonical first")
    _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb", question="canonical second")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["search", "--question=canonical"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    rows = proc.stdout.rstrip("\n").splitlines()[2:]
    ids = [row.split("|")[1].strip() for row in rows]
    assert ids == ["20260101T000000-aaaa", "20260101T010000-bbbb", "20260101T020000-cccc"]


def test_search_dead_flags_accepted_and_have_no_effect(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="canonical types")
    _write_discovery(workdir_root, "sprint-b", "20260101T010000-bbbb", question="canonical types too")
    env = _discovery_env(workdir_root)

    proc = run_discovery(
        ["search", "--question=canonical", "--sprint=sprint-a", "--max-age-sprints=1"], work_dir, env
    )

    assert proc.returncode == 0, proc.stderr
    # --sprint here is a DEAD flag for search (bash parses but never uses
    # it) -- both sprints' matches show up despite --sprint=sprint-a.
    assert "20260101T000000-aaaa" in proc.stdout
    assert "20260101T010000-bbbb" in proc.stdout


def test_search_bash_parity_happy_path(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa", question="canonical types freshness")
    _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb", question="unrelated")
    env = _discovery_env(workdir_root)

    python_proc = run_discovery(["search", "--question=canonical"], work_dir, env)
    bash_proc = run_bash_discovery(["search", "--question=canonical"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_search_bash_parity_no_matches(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    python_proc = run_discovery(["search", "--question=nothing"], work_dir, env)
    bash_proc = run_bash_discovery(["search", "--question=nothing"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# clear.
# --------------------------------------------------------------------------
def test_clear_missing_sprint_exits_1(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(["clear"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: shctx discovery clear --sprint=<branch>"


def test_clear_no_records_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    env = _discovery_env(workdir_root)
    proc = run_discovery(["clear", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "[shctx discovery] no records to clear for sprint 'sprint-a'"


def test_clear_dry_run_reports_count_and_does_not_remove_files(work_dir: Path, workdir_root: Path) -> None:
    path_a = _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    path_b = _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["clear", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    expected_dir = workdir_root / "discoveries" / "sprint-a"
    assert proc.stdout.rstrip("\n") == f"[shctx discovery] would clear 2 records in {expected_dir}; pass --force to execute"
    assert path_a.exists()
    assert path_b.exists()


def test_clear_force_removes_files_and_reports_count(work_dir: Path, workdir_root: Path) -> None:
    path_a = _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    path_b = _write_discovery(workdir_root, "sprint-a", "20260101T010000-bbbb")
    other_sprint = _write_discovery(workdir_root, "sprint-b", "20260101T020000-cccc")
    env = _discovery_env(workdir_root)

    proc = run_discovery(["clear", "--sprint=sprint-a", "--force"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "[shctx discovery] cleared 2 records for sprint 'sprint-a'"
    assert not path_a.exists()
    assert not path_b.exists()
    assert other_sprint.exists()  # a different sprint's records are untouched


def test_clear_bash_parity_dry_run(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    python_proc = run_discovery(["clear", "--sprint=sprint-a"], work_dir, env)
    bash_proc = run_bash_discovery(["clear", "--sprint=sprint-a"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_clear_bash_parity_force(work_dir: Path, workdir_root: Path) -> None:
    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")
    env = _discovery_env(workdir_root)

    python_proc = run_discovery(["clear", "--sprint=sprint-a", "--force"], work_dir, env)
    assert python_proc.returncode == 0, python_proc.stderr

    _write_discovery(workdir_root, "sprint-a", "20260101T000000-aaaa")  # re-seed for the bash run
    bash_proc = run_bash_discovery(["clear", "--sprint=sprint-a", "--force"], work_dir, env)

    assert bash_proc.returncode == 0, bash_proc.stderr
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# insert.
# --------------------------------------------------------------------------
def _insert_row(db_path: Path, table: str, values: dict[str, object]) -> None:
    """Insert one row into ``table``, keeping only columns that actually exist."""
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


def _discovery_findings_rows(db_path: Path, discovery_run: str) -> list[dict[str, object]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT id, project_id, sprint_branch, discovery_run, section, title, body, sources, created_at "
            "FROM discovery_findings WHERE discovery_run = ? ORDER BY id;",
            (discovery_run,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh full-schema (0001_init.sql + every migrations/*.sql) fixture DB."""
    path = tmp_path / "shepherd.db"
    build_full_schema_db(path)
    return path


@pytest.fixture
def project_id(db_path: Path) -> str:
    """One seeded ``projects`` row."""
    return insert_project(db_path)


def test_insert_unknown_flag_exits_2(work_dir: Path, workdir_root: Path, db_path: Path, project_id: str) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert", "--run=D-1", "--title=x", "--nope=1"],
        cwd=str(work_dir), env=env, input="body", capture_output=True, text=True, timeout=15,
    )

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "unknown flag: --nope=1"


def test_insert_missing_run_and_title_exits_2(
    work_dir: Path, workdir_root: Path, db_path: Path, project_id: str
) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert"],
        cwd=str(work_dir), env=env, input="body", capture_output=True, text=True, timeout=15,
    )

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERR: --run and --title required"


def test_insert_missing_db_exits_1(work_dir: Path, workdir_root: Path, tmp_path: Path) -> None:
    missing_db = tmp_path / "does-not-exist.db"
    env = _discovery_env(workdir_root, db_path=missing_db)
    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert", "--run=D-1", "--title=x"],
        cwd=str(work_dir), env=env, input="body", capture_output=True, text=True, timeout=15,
    )

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == f"ERR: registry DB not found at {missing_db}"


def test_insert_happy_path_writes_row_and_prints_id(
    work_dir: Path, workdir_root: Path, db_path: Path, project_id: str
) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    # created_at is `int(time.time()) * 1000` (bash: `$(($(date +%s) * 1000))`
    # -- truncated to whole SECONDS first, then scaled) -- match that same
    # truncation here rather than millisecond-precision bounds, which could
    # otherwise spuriously fail right at a second boundary.
    before = int(time.time()) * 1000
    proc = subprocess.run(
        [
            PY, "-m", "shepherd_cli", "discovery", "insert",
            "--run=D-AUTH", "--section=confirmed", "--title=Auth probe",
            '--sources=["a","b"]', "--sprint=sprint-x",
        ],
        cwd=str(work_dir), env=env, input="Auth probe body text", capture_output=True, text=True, timeout=15,
    )
    after = int(time.time()) * 1000

    assert proc.returncode == 0, proc.stderr
    new_id = int(proc.stdout.strip())
    assert new_id >= 1

    rows = _discovery_findings_rows(db_path, "D-AUTH")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == new_id
    assert row["project_id"] == project_id
    assert row["sprint_branch"] == "sprint-x"
    assert row["discovery_run"] == "D-AUTH"
    assert row["section"] == "confirmed"
    assert row["title"] == "Auth probe"
    assert row["body"] == "Auth probe body text"
    assert row["sources"] == '["a","b"]'
    assert before <= row["created_at"] <= after  # epoch-milliseconds


def test_insert_empty_optional_fields_stored_as_null(
    work_dir: Path, workdir_root: Path, db_path: Path, project_id: str
) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert", "--run=D-EMPTY", "--title=NoSection"],
        cwd=str(work_dir), env=env, input="body2", capture_output=True, text=True, timeout=15,
    )

    assert proc.returncode == 0, proc.stderr
    rows = _discovery_findings_rows(db_path, "D-EMPTY")
    assert len(rows) == 1
    row = rows[0]
    assert row["sprint_branch"] is None
    assert row["section"] is None
    assert row["sources"] is None
    assert row["title"] == "NoSection"
    assert row["body"] == "body2"


def test_insert_no_project_row_raises_integrity_error(
    work_dir: Path, workdir_root: Path, db_path: Path
) -> None:
    """No `projects` row seeded — bash's raw `sqlite3` CLI runs with
    `foreign_keys` OFF (its own per-connection default), so bash silently
    writes an orphaned `project_id=''` row. Tortoise's sqlite backend sets
    `foreign_keys = ON` by default (shared by every other ported write
    path), so this port's INSERT instead fails its FK constraint — caught
    and converted to a clean `ERROR: ...` / exit 1, never a raw crash. See
    `_insert_async`'s docstring for the full deviation rationale (mirrors
    `shepherd_cli.commands.audit`'s identical, already-documented
    precedent for the sibling `audit_findings` table)."""
    env = _discovery_env(workdir_root, db_path=db_path)
    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert", "--run=D-NOPROJ", "--title=x"],
        cwd=str(work_dir), env=env, input="body", capture_output=True, text=True, timeout=15,
    )

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("ERROR: ")
    assert "FOREIGN KEY" in proc.stderr
    assert _discovery_findings_rows(db_path, "D-NOPROJ") == []


def test_insert_sequential_ids_increment(
    work_dir: Path, workdir_root: Path, db_path: Path, project_id: str
) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    ids = []
    for run in ("D-1", "D-2"):
        proc = subprocess.run(
            [PY, "-m", "shepherd_cli", "discovery", "insert", f"--run={run}", "--title=x"],
            cwd=str(work_dir), env=env, input="body", capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0, proc.stderr
        ids.append(int(proc.stdout.strip()))
    assert ids[1] == ids[0] + 1


def test_insert_bash_parity_happy_path(
    work_dir: Path, workdir_root: Path, db_path: Path, project_id: str
) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    python_proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert", "--run=D-PY", "--title=Python insert"],
        cwd=str(work_dir), env=env, input="py body", capture_output=True, text=True, timeout=15,
    )
    bash_proc = run_bash_discovery(
        ["insert", "--run=D-BASH", "--title=Bash insert"], work_dir, env, stdin="bash body"
    )

    assert python_proc.returncode == bash_proc.returncode == 0
    py_rows = _discovery_findings_rows(db_path, "D-PY")
    bash_rows = _discovery_findings_rows(db_path, "D-BASH")
    assert len(py_rows) == 1
    assert len(bash_rows) == 1
    # Same shape modulo id/created_at, which naturally differ per insert.
    for key in ("project_id", "sprint_branch", "section", "sources"):
        assert py_rows[0][key] == bash_rows[0][key]


def test_insert_bash_parity_missing_required(
    work_dir: Path, workdir_root: Path, db_path: Path, project_id: str
) -> None:
    env = _discovery_env(workdir_root, db_path=db_path)
    python_proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "discovery", "insert"],
        cwd=str(work_dir), env=env, input="", capture_output=True, text=True, timeout=15,
    )
    bash_proc = run_bash_discovery(["insert"], work_dir, env, stdin="")

    assert python_proc.returncode == bash_proc.returncode == 2
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# resolve_namespace() split-brain-warning suppression (list/show/search/
# clear only) -- see the module docstring's "resolve_namespace() PARITY
# DETAIL" section.
# --------------------------------------------------------------------------
def test_list_suppresses_split_brain_warning(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".shepherd").mkdir()
    (repo / ".artifacts").mkdir()
    env = clean_env_dict()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    # Deliberately no SHEPHERD_WORKDIR override -- forces resolve_workdir()
    # to auto-detect off the git repo root, which is where the split-brain
    # check (both .shepherd/ and .artifacts/ present) would otherwise fire.

    proc = run_discovery(["list", "--sprint=sprint-a"], repo, env)

    assert proc.returncode == 0, proc.stderr
    assert "WARNING" not in proc.stderr
