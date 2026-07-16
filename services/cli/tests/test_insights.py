"""Tests for `shepherd insights` — native port of `cmd_insights.sh` (pure
filesystem JSON store, no DB — see `shepherd_cli/commands/insights.py`'s
module docstring).

Every test drives the real CLI as a subprocess with an ISOLATED work
directory: `SHEPHERD_WORKDIR` is set to an absolute `tmp_path` subdirectory
(resolve_workdir() honors an absolute `SHEPHERD_WORKDIR` as-is, per
`resolution.py`), so `<workdir>/insights/` never touches this real repo's
own `.shepherd/`. `cwd` is a bare, non-git directory for the same isolation
reason `test_config.py::work_dir` documents.

Several tests additionally run the legacy `cmd_insights.sh` directly, under
the identical env, asserting byte-for-byte stdout/exit-code parity — the
same pattern `test_config.py`/`test_models.py`/`test_search.py` established.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, clean_env_dict

CMD_INSIGHTS_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_insights.sh"

_USAGE_MARKER = "shctx insights <list|show|export|clear> [args]"


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

    Kept SEPARATE from `work_dir` (the CLI's `cwd`) deliberately: bash's
    own `resolve_workdir()`/`shctx_artifacts_root()` never assume the
    namespace lives under `cwd` — only `SHEPHERD_WORKDIR` (or repo-root
    auto-detection, bypassed here) determines it.
    """
    d = tmp_path / "ns"
    d.mkdir()
    return d


def _insights_env(workdir_root: Path) -> dict[str, str]:
    """A stripped-then-rebuilt environment pointed at an isolated namespace."""
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir_root)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env


def run_insights(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -m shepherd_cli insights <args>` under `cwd`."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "insights", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_bash_insights(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_insights.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(
        ["bash", str(CMD_INSIGHTS_SH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write_insight(
    workdir_root: Path,
    sprint: str,
    insight_id: str,
    *,
    kind: str = "gap",
    subject: str = "some subject",
    observation: str = "an observation",
    rationale: str = "a rationale",
    captured_at: int | None = None,
    actioned: bool = False,
    actioned_in: str | None = None,
    extra: dict[str, object] | None = None,
) -> Path:
    """Write one insight JSON record at `<workdir_root>/insights/<sprint>/<id>.json`."""
    root = workdir_root / "insights" / sprint
    root.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "id": insight_id,
        "sprint": sprint,
        "kind": kind,
        "subject": subject,
        "observation": observation,
        "rationale": rationale,
        "captured_at": captured_at if captured_at is not None else int(time.time()),
        "actioned": actioned,
        "actioned_in": actioned_in,
    }
    if extra:
        record.update(extra)
    path = root / f"{insight_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


# --------------------------------------------------------------------------
# No-subcommand / help / unknown subcommand.
# --------------------------------------------------------------------------
def test_bare_invocation_prints_usage_and_exits_0(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)
    assert "list [--sprint=BRANCH]" in proc.stdout
    assert "show <id> [--json]" in proc.stdout
    assert "clear [--older-than-days=N]" in proc.stdout


@pytest.mark.parametrize("args", [[], ["-h"], ["--help"]])
def test_help_variants_print_usage_and_exit_0(args: list[str], work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(args, work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)


def test_bare_matches_help_exactly(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    bare = run_insights([], work_dir, env)
    helped = run_insights(["--help"], work_dir, env)

    assert bare.returncode == helped.returncode == 0
    assert bare.stdout == helped.stdout


def test_unknown_subcommand_exits_1_with_error_and_usage_on_stderr(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(["bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("ERROR: unknown subcommand: bogus\n")
    assert _USAGE_MARKER in proc.stderr


def test_bare_bash_parity(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    python_proc = run_insights([], work_dir, env)
    bash_proc = run_bash_insights([], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_unknown_subcommand_bash_parity(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    python_proc = run_insights(["bogus"], work_dir, env)
    bash_proc = run_bash_insights(["bogus"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# list.
# --------------------------------------------------------------------------
def test_list_no_store_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(["list"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "No insights recorded yet."


def test_list_missing_sprint_dir_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)
    proc = run_insights(["list", "--sprint=nope"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "No insights for sprint nope."


def test_list_empty_store_prints_no_records(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights" / "some-sprint").mkdir(parents=True)
    env = _insights_env(workdir_root)
    proc = run_insights(["list"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "No insight records."


def test_list_happy_path_text_ordered_newest_first(work_dir: Path, workdir_root: Path) -> None:
    now = int(time.time())
    _write_insight(workdir_root, "sprint-a", "ins-old", subject="old one", captured_at=now - 1000)
    _write_insight(workdir_root, "sprint-a", "ins-new", subject="new one", captured_at=now)
    env = _insights_env(workdir_root)

    proc = run_insights(["list"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0].startswith("ID")
    assert lines[1].startswith("-")
    assert "ins-new" in lines[2]
    assert "ins-old" in lines[3]


def test_list_json_output(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-1", subject="subj-1")
    env = _insights_env(workdir_root)

    proc = run_insights(["list", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert len(parsed) == 1
    assert parsed[0]["id"] == "ins-1"
    assert parsed[0]["subject"] == "subj-1"


def test_list_md_output(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-1", subject="subj-1")
    env = _insights_env(workdir_root)

    proc = run_insights(["list", "--md"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == (
        "| ID | Sprint | Kind | Subject | Actioned |\n"
        "|---|---|---|---|---|\n"
        "| `ins-1` | sprint-a | gap | subj-1 | — |"
    )


def test_list_kind_filter(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-relo", kind="relocation")
    _write_insight(workdir_root, "sprint-a", "ins-gap", kind="gap")
    env = _insights_env(workdir_root)

    proc = run_insights(["list", "--kind=relocation", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert [r["id"] for r in parsed] == ["ins-relo"]


def test_list_actioned_filter(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-done", actioned=True, actioned_in="pr-1")
    _write_insight(workdir_root, "sprint-a", "ins-open", actioned=False)
    env = _insights_env(workdir_root)

    proc = run_insights(["list", "--actioned", "--json"], work_dir, env)
    parsed = json.loads(proc.stdout)
    assert [r["id"] for r in parsed] == ["ins-done"]

    proc2 = run_insights(["list", "--unactioned", "--json"], work_dir, env)
    parsed2 = json.loads(proc2.stdout)
    assert [r["id"] for r in parsed2] == ["ins-open"]


def test_list_no_match_after_filter_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-1", kind="gap")
    env = _insights_env(workdir_root)

    proc = run_insights(["list", "--kind=nit"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "(no insights match the filters)"


def test_list_unknown_arg_exits_1(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)
    proc = run_insights(["list", "--bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"


def test_list_help_flag_prints_usage_and_exits_0(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(["list", "-h"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)


def test_list_bash_parity_happy_path(work_dir: Path, workdir_root: Path) -> None:
    now = int(time.time())
    _write_insight(workdir_root, "sprint-a", "ins-old", subject="old one", captured_at=now - 1000)
    _write_insight(workdir_root, "sprint-a", "ins-new", subject="new one", captured_at=now)
    env = _insights_env(workdir_root)

    python_proc = run_insights(["list"], work_dir, env)
    bash_proc = run_bash_insights(["list"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_list_bash_parity_json(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-1", subject="subj-1", kind="extension")
    env = _insights_env(workdir_root)

    python_proc = run_insights(["list", "--json"], work_dir, env)
    bash_proc = run_bash_insights(["list", "--json"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert json.loads(python_proc.stdout) == json.loads(bash_proc.stdout)


def test_list_bash_parity_no_store(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    python_proc = run_insights(["list"], work_dir, env)
    bash_proc = run_bash_insights(["list"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# show.
# --------------------------------------------------------------------------
def test_show_missing_id_exits_1(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(["show"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: usage: shctx insights show <id>"


def test_show_not_found_exits_2(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights" / "sprint-a").mkdir(parents=True)
    env = _insights_env(workdir_root)
    proc = run_insights(["show", "nope"], work_dir, env)

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: insight nope not found"


def test_show_happy_path_text(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(
        workdir_root,
        "sprint-a",
        "ins-1",
        kind="gap",
        subject="the subject",
        observation="the observation",
        rationale="the rationale",
        captured_at=1_700_000_000,
        actioned=True,
        actioned_in="pr-42",
    )
    env = _insights_env(workdir_root)

    proc = run_insights(["show", "ins-1"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "Insight:      ins-1" in out
    assert "Sprint:       sprint-a" in out
    assert "Kind:         gap" in out
    assert "Actioned:     yes (in pr-42)" in out
    assert "Subject:" in out
    assert "  the subject" in out
    assert "Observation:" in out
    assert "  the observation" in out
    assert "Rationale:" in out
    assert "  the rationale" in out


def test_show_json_prints_raw_file_bytes(work_dir: Path, workdir_root: Path) -> None:
    path = _write_insight(workdir_root, "sprint-a", "ins-1", subject="subj")
    env = _insights_env(workdir_root)

    proc = run_insights(["show", "ins-1", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == path.read_text()


def test_show_id_taken_literally_even_if_flag_shaped(work_dir: Path, workdir_root: Path) -> None:
    """`show`'s first token is the id no matter what it looks like — bash parity."""
    env = _insights_env(workdir_root)
    proc = run_insights(["show", "--json"], work_dir, env)

    assert proc.returncode == 2
    assert proc.stderr.rstrip("\n") == "ERROR: insight --json not found"


def test_show_ignores_unrecognized_trailing_args(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-1", subject="subj")
    env = _insights_env(workdir_root)

    proc = run_insights(["show", "ins-1", "--bogus", "--whatever"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "Insight:      ins-1" in proc.stdout


def test_show_bash_parity_text(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(
        workdir_root,
        "sprint-a",
        "ins-1",
        kind="gap",
        subject="subj",
        observation="obs",
        rationale="rat",
        captured_at=1_700_000_000,
    )
    env = _insights_env(workdir_root)

    python_proc = run_insights(["show", "ins-1"], work_dir, env)
    bash_proc = run_bash_insights(["show", "ins-1"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_show_bash_parity_not_found(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)

    python_proc = run_insights(["show", "nope"], work_dir, env)
    bash_proc = run_bash_insights(["show", "nope"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 2
    assert python_proc.stderr == bash_proc.stderr


# --------------------------------------------------------------------------
# export.
# --------------------------------------------------------------------------
def test_export_no_store_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(["export"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "(no insights)"


def test_export_missing_sprint_dir_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)
    proc = run_insights(["export", "--sprint=nope"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "(no insights for nope)"


def test_export_empty_store_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights" / "sprint-a").mkdir(parents=True)
    env = _insights_env(workdir_root)
    proc = run_insights(["export"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "(no insight records)"


def test_export_groups_by_kind_skips_actioned(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(
        workdir_root, "sprint-a", "ins-relo", kind="relocation", subject="move me",
        observation="obs-1", rationale="rat-1", captured_at=100,
    )
    _write_insight(
        workdir_root, "sprint-a", "ins-gap", kind="gap", subject="fill me",
        observation="", rationale="", captured_at=200,
    )
    _write_insight(
        workdir_root, "sprint-a", "ins-done", kind="gap", subject="already handled",
        actioned=True, actioned_in="pr-9", captured_at=300,
    )
    env = _insights_env(workdir_root)

    proc = run_insights(["export"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert out.startswith("## Cross-lane insights — all sprints\n")
    assert "### relocation (1)" in out
    assert "- **move me**" in out
    assert "observation: obs-1" in out
    assert "rationale:   rat-1" in out
    assert "### gap (1)" in out
    assert "- **fill me**" in out
    assert "already handled" not in out
    # relocation section must appear before gap (fixed order).
    assert out.index("### relocation") < out.index("### gap")


def test_export_no_unactioned_insights(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-done", actioned=True, actioned_in="pr-1")
    env = _insights_env(workdir_root)

    proc = run_insights(["export"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "_(no unactioned insights)_" in proc.stdout


def test_export_sprint_filter_label(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(workdir_root, "sprint-a", "ins-1", kind="nit", subject="s1")
    env = _insights_env(workdir_root)

    proc = run_insights(["export", "--sprint=sprint-a"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("## Cross-lane insights — sprint-a\n")


def test_export_unknown_arg_exits_1(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)
    proc = run_insights(["export", "--bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"


def test_export_bash_parity(work_dir: Path, workdir_root: Path) -> None:
    _write_insight(
        workdir_root, "sprint-a", "ins-relo", kind="relocation", subject="move me",
        observation="obs-1", rationale="rat-1", captured_at=100,
    )
    _write_insight(
        workdir_root, "sprint-a", "ins-done", kind="gap", subject="already handled",
        actioned=True, actioned_in="pr-9", captured_at=300,
    )
    env = _insights_env(workdir_root)

    python_proc = run_insights(["export"], work_dir, env)
    bash_proc = run_bash_insights(["export"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_export_bash_parity_no_insights(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    python_proc = run_insights(["export"], work_dir, env)
    bash_proc = run_bash_insights(["export"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# clear.
# --------------------------------------------------------------------------
def test_clear_no_store_prints_notice(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    proc = run_insights(["clear"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "(nothing to clear)"


def test_clear_removes_old_actioned_keeps_rest(work_dir: Path, workdir_root: Path) -> None:
    now = int(time.time())
    old_ts = now - 90 * 86400  # 90 days ago: past the default 60-day cutoff
    recent_ts = now - 5 * 86400  # 5 days ago: within the default cutoff

    old_actioned = _write_insight(
        workdir_root, "sprint-a", "ins-old-actioned", actioned=True, actioned_in="pr-1", captured_at=old_ts
    )
    recent_actioned = _write_insight(
        workdir_root, "sprint-a", "ins-recent-actioned", actioned=True, actioned_in="pr-2", captured_at=recent_ts
    )
    old_unactioned = _write_insight(
        workdir_root, "sprint-a", "ins-old-unactioned", actioned=False, captured_at=old_ts
    )
    env = _insights_env(workdir_root)

    proc = run_insights(["clear"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == "Removed 1 actioned insight(s) older than 60 days."
    assert not old_actioned.exists()
    assert recent_actioned.exists()
    assert old_unactioned.exists()


def test_clear_custom_older_than_days(work_dir: Path, workdir_root: Path) -> None:
    now = int(time.time())
    ts = now - 10 * 86400  # 10 days ago

    path = _write_insight(workdir_root, "sprint-a", "ins-1", actioned=True, actioned_in="pr-1", captured_at=ts)
    env = _insights_env(workdir_root)

    # 30-day cutoff: 10-day-old record is kept.
    proc_keep = run_insights(["clear", "--older-than-days=30"], work_dir, env)
    assert proc_keep.returncode == 0, proc_keep.stderr
    assert proc_keep.stdout.rstrip("\n") == "Removed 0 actioned insight(s) older than 30 days."
    assert path.exists()

    # 5-day cutoff: 10-day-old record is removed.
    proc_remove = run_insights(["clear", "--older-than-days=5"], work_dir, env)
    assert proc_remove.returncode == 0, proc_remove.stderr
    assert proc_remove.stdout.rstrip("\n") == "Removed 1 actioned insight(s) older than 5 days."
    assert not path.exists()


def test_clear_unknown_arg_exits_1(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)
    proc = run_insights(["clear", "--bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "ERROR: unknown arg: --bogus"


def test_clear_non_integer_days_exits_1(work_dir: Path, workdir_root: Path) -> None:
    (workdir_root / "insights").mkdir()
    env = _insights_env(workdir_root)
    proc = run_insights(["clear", "--older-than-days=abc"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: --older-than-days must be an integer, got: abc" in proc.stderr


def test_clear_bash_parity(work_dir: Path, workdir_root: Path) -> None:
    now = int(time.time())
    old_ts = now - 90 * 86400
    recent_ts = now - 5 * 86400
    _write_insight(workdir_root, "sprint-a", "ins-old-actioned", actioned=True, actioned_in="pr-1", captured_at=old_ts)
    _write_insight(
        workdir_root, "sprint-a", "ins-recent-actioned", actioned=True, actioned_in="pr-2", captured_at=recent_ts
    )
    _write_insight(workdir_root, "sprint-a", "ins-old-unactioned", actioned=False, captured_at=old_ts)
    env = _insights_env(workdir_root)

    python_proc = run_insights(["clear"], work_dir, env)

    assert python_proc.returncode == 0, python_proc.stderr
    assert python_proc.stdout.rstrip("\n") == "Removed 1 actioned insight(s) older than 60 days."

    # Re-seed identical fixtures for the bash twin (python run already deleted the old-actioned file).
    _write_insight(workdir_root, "sprint-a", "ins-old-actioned", actioned=True, actioned_in="pr-1", captured_at=old_ts)
    bash_proc = run_bash_insights(["clear"], work_dir, env)

    assert bash_proc.returncode == 0, bash_proc.stderr
    assert bash_proc.stdout.rstrip("\n") == "Removed 1 actioned insight(s) older than 60 days."


def test_clear_bash_parity_no_store(work_dir: Path, workdir_root: Path) -> None:
    env = _insights_env(workdir_root)
    python_proc = run_insights(["clear"], work_dir, env)
    bash_proc = run_bash_insights(["clear"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
