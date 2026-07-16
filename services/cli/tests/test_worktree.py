"""Subprocess parity tests for ``shepherd worktree`` (git worktree hygiene).

Bash parity target: ``skills/context/scripts/cmd_worktree.sh``. This
command touches ONLY real git state — no sqlite registry at all (see the
module docstring in ``shepherd_cli/commands/worktree.py``: the
``worktrees`` table is written by a completely separate hook, never read
or written here) — so every test below builds a throwaway git repo with
``git init`` and drives real ``git`` subprocesses through the CLI. No fake
sibling-script harness (unlike ``test_sync.py``/``test_audit.py``), no
fixture database (unlike most other suites in this package).

``conftest.run_cli`` is deliberately NOT reused: it hard-codes
``cwd=CLI_ROOT``, but ``shepherd worktree`` resolves its repo root from the
subprocess's OWN cwd (``git rev-parse --show-toplevel``), which every test
below needs pointed at its own throwaway repo — matching the posture
``test_dups.py``/``test_handoff.py``'s ``run_cli_cwd`` already established
for other cwd-sensitive ports.

Every worktree path a test needs to assert against is built from the
git-reported toplevel (:func:`_toplevel`), not from ``tmp_path`` directly —
git's own path resolution (through any symlinked ``/tmp``) must exactly
match what the CLI's own ``resolve_repo_root()`` resolves, or a strict
prefix-based display-path assertion would spuriously fail.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from conftest import PY, clean_env_dict


# --------------------------------------------------------------------------
# git / CLI invocation helpers.
# --------------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd``, raising on failure. Returns the CompletedProcess."""
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _commit_with_timestamp(cwd: Path, epoch: int, message: str) -> None:
    """Create an empty commit in ``cwd`` with an EXPLICIT author+committer epoch.

    ``git log -1 --format=%ct`` (what ``_list_worktrees``'s age calculation
    reads) is the COMMITTER date, so both ``GIT_AUTHOR_DATE`` and
    ``GIT_COMMITTER_DATE`` are set — used to deterministically backdate a
    worktree's "last commit" for the ``gc`` age-threshold tests, without
    depending on wall-clock sleeps.
    """
    env = clean_env_dict()
    env["GIT_AUTHOR_DATE"] = str(epoch)
    env["GIT_COMMITTER_DATE"] = str(epoch)
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", message],
        cwd=str(cwd),
        env=env,
        check=True,
    )


def _toplevel(repo: Path) -> str:
    """The repo root as GIT itself resolves it from ``repo`` — the same value
    ``resolve_repo_root()`` (``git rev-parse --show-toplevel``) computes."""
    return _git(repo, "rev-parse", "--show-toplevel").stdout.strip()


def _run(args: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run ``shepherd worktree <args>`` as a real subprocess, cwd pinned to ``cwd``."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "worktree", *args],
        cwd=str(cwd),
        env=env if env is not None else clean_env_dict(),
        capture_output=True,
        text=True,
        timeout=15,
    )


def _expected_header() -> str:
    return f"{'PATH':<60} {'BRANCH':<30} {'HEAD':<12} AGE"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo on branch 'main', one commit, no worktrees yet."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "init")
    return root


# --------------------------------------------------------------------------
# `list` (and bare-invocation default-to-list).
# --------------------------------------------------------------------------
def test_bare_invocation_defaults_to_list(repo: Path) -> None:
    """Bash parity: `sub="${1:-list}"` — no subcommand means `list`, not usage."""
    proc = _run([], repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _expected_header()


def test_list_subcommand_explicit_matches_bare_invocation(repo: Path) -> None:
    proc = _run(["list"], repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _expected_header()


def test_list_ignores_trailing_args_including_help_flag(repo: Path) -> None:
    """Bash: `list)`'s case body never reads "$@" — trailing tokens (even
    -h) are silently ignored and a normal listing still runs."""
    proc = _run(["list", "-h", "--bogus", "extra"], repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.rstrip("\n") == _expected_header()


def test_list_shows_worktree_with_branch_and_head_prefix(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _git(repo, "branch", "feature")
    wt_path = Path(toplevel) / ".claude" / "worktrees" / "agent-1"
    wt_path.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", str(wt_path), "feature")
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    proc = _run(["list"], repo)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0] == _expected_header()
    assert len(lines) == 2
    display_path = ".claude/worktrees/agent-1"
    assert lines[1].startswith(f"{display_path:<60} {'feature':<30} {head_sha[:10]:<12}")
    assert lines[1].rstrip().endswith("h")


def test_list_excludes_the_main_worktree(repo: Path) -> None:
    _git(repo, "branch", "feature")
    toplevel = _toplevel(repo)
    wt_path = Path(toplevel) / ".claude" / "worktrees" / "agent-2"
    wt_path.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", str(wt_path), "feature")

    proc = _run(["list"], repo)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    # Exactly one data row (the extra worktree) — the main worktree itself
    # (== repo) is never printed.
    assert len(lines) == 2


# --------------------------------------------------------------------------
# `create-batch`.
# --------------------------------------------------------------------------
def test_create_batch_requires_at_least_one_lane(repo: Path) -> None:
    proc = _run(["create-batch"], repo)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: at least one lane-id required" in proc.stderr


def test_create_batch_from_current_branch_default(repo: Path) -> None:
    toplevel = _toplevel(repo)
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()

    proc = _run(["create-batch", "lane1"], repo)
    assert proc.returncode == 0, proc.stderr

    wt_path = f"{toplevel}/.claude/worktrees/agent-lane1"
    # `git worktree add` prints its own "HEAD is now at <sha> <msg>" to stdout
    # (bash parity: cmd_worktree.sh does not redirect it) — filter it before
    # comparing the shctx-authored lines.
    lines = [ln for ln in proc.stdout.rstrip("\n").splitlines() if not ln.startswith("HEAD is now at")]
    assert lines == [
        f"created agent-lane1: {wt_path} (base={base_sha[:10]})",
        f"shctx worktree create-batch: created 1 worktrees from main ({base_sha[:10]})",
        f"[BASE-COMMIT-EXPECTED] for coder briefs: {base_sha}",
    ]
    assert Path(wt_path).is_dir()


def test_create_batch_multiple_lanes_and_custom_prefix(repo: Path) -> None:
    toplevel = _toplevel(repo)

    proc = _run(["create-batch", "a", "b", "--prefix=w-"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"created w-a: {toplevel}/.claude/worktrees/w-a" in proc.stdout
    assert f"created w-b: {toplevel}/.claude/worktrees/w-b" in proc.stdout
    assert "shctx worktree create-batch: created 2 worktrees from main" in proc.stdout
    assert (Path(toplevel) / ".claude" / "worktrees" / "w-a").is_dir()
    assert (Path(toplevel) / ".claude" / "worktrees" / "w-b").is_dir()


def test_create_batch_prefix_flag_bare_form_consumes_next_token(repo: Path) -> None:
    """`--prefix <val>` (no `=`) must consume the NEXT token as its value,
    not be treated as a bare/lane positional."""
    toplevel = _toplevel(repo)
    proc = _run(["create-batch", "x", "--prefix", "custom-"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"created custom-x: {toplevel}/.claude/worktrees/custom-x" in proc.stdout


def test_create_batch_explicit_from_branch(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "dev")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "dev commit")
    _git(repo, "checkout", "-q", "main")
    dev_sha = _git(repo, "rev-parse", "dev").stdout.strip()

    proc = _run(["create-batch", "x", "--from=dev"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"shctx worktree create-batch: created 1 worktrees from dev ({dev_sha[:10]})" in proc.stdout


def test_create_batch_from_nonexistent_branch_errors(repo: Path) -> None:
    proc = _run(["create-batch", "x", "--from=does-not-exist"], repo)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: --from=does-not-exist does not exist" in proc.stderr


def test_create_batch_detached_head_without_from_errors(repo: Path) -> None:
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", head_sha)

    proc = _run(["create-batch", "x"], repo)
    assert proc.returncode == 1
    assert "ERROR: detached HEAD; pass --from=<branch>" in proc.stderr


def test_create_batch_skips_existing_worktree_dir(repo: Path) -> None:
    toplevel = _toplevel(repo)
    existing = Path(toplevel) / ".claude" / "worktrees" / "agent-dup"
    existing.mkdir(parents=True)

    proc = _run(["create-batch", "dup"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"skip agent-dup: {toplevel}/.claude/worktrees/agent-dup already exists" in proc.stdout
    assert "shctx worktree create-batch: created 0 worktrees from main" in proc.stdout


def test_create_batch_reuses_existing_branch_matching_base(repo: Path) -> None:
    toplevel = _toplevel(repo)
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()
    _git(repo, "branch", "agent-reuse", base_sha)

    proc = _run(["create-batch", "reuse"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "WARN" not in proc.stdout
    assert f"created agent-reuse: {toplevel}/.claude/worktrees/agent-reuse" in proc.stdout


def test_create_batch_warns_when_reused_branch_diverges_from_base(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "agent-drift")
    (repo / "c.txt").write_text("c\n")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "drift")
    drift_sha = _git(repo, "rev-parse", "agent-drift").stdout.strip()
    _git(repo, "checkout", "-q", "main")
    base_sha = _git(repo, "rev-parse", "main").stdout.strip()

    proc = _run(["create-batch", "drift"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"WARN agent-drift: branch exists at {drift_sha} (expected {base_sha})" in proc.stdout


def test_create_batch_unknown_flag_errors(repo: Path) -> None:
    proc = _run(["create-batch", "lane1", "--bogus"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown flag: --bogus" in proc.stderr


def test_create_batch_help_prints_to_stderr_exit_0(repo: Path) -> None:
    proc = _run(["create-batch", "-h"], repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert "shctx worktree create-batch <lane-id…> [--from=<branch>] [--prefix=agent-]" in proc.stderr
    assert "Pre-creates one worktree per lane-id" in proc.stderr


# --------------------------------------------------------------------------
# `gc`.
# --------------------------------------------------------------------------
def test_gc_default_threshold_prunes_stale_and_keeps_fresh(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "stale", "fresh"], repo)
    stale_wt = Path(toplevel) / ".claude" / "worktrees" / "agent-stale"
    fresh_wt = Path(toplevel) / ".claude" / "worktrees" / "agent-fresh"
    two_days_ago = int(time.time()) - 2 * 24 * 3600
    _commit_with_timestamp(stale_wt, two_days_ago, "backdated")

    proc = _run(["gc"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"pruning {stale_wt} (branch=agent-stale, age=" in proc.stdout
    assert "agent-fresh" not in proc.stdout
    assert "shctx worktree gc: pruned 1 (threshold 24h)" in proc.stdout
    assert not stale_wt.exists()
    assert fresh_wt.is_dir()

    branches = _git(repo, "branch", "--list").stdout
    assert "agent-stale" not in branches
    assert "agent-fresh" in branches


def test_gc_dry_run_does_not_remove(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "stale"], repo)
    stale_wt = Path(toplevel) / ".claude" / "worktrees" / "agent-stale"
    two_days_ago = int(time.time()) - 2 * 24 * 3600
    _commit_with_timestamp(stale_wt, two_days_ago, "backdated")

    proc = _run(["gc", "--dry-run"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"[dry-run] would prune {stale_wt} (branch=agent-stale, age=" in proc.stdout
    assert "shctx worktree gc: pruned 1 (threshold 24h)" in proc.stdout
    assert stale_wt.is_dir()


def test_gc_all_flag_prunes_regardless_of_age(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "brandnew"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-brandnew"

    proc = _run(["gc", "--all"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"pruning {wt} (branch=agent-brandnew, age=" in proc.stdout
    assert "shctx worktree gc: pruned 1 (threshold 0h)" in proc.stdout
    assert not wt.exists()


def test_gc_older_than_flag_overrides_default(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "midage"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-midage"
    twelve_hours_ago = int(time.time()) - 12 * 3600
    _commit_with_timestamp(wt, twelve_hours_ago, "backdated")

    proc_default = _run(["gc"], repo)
    assert proc_default.returncode == 0, proc_default.stderr
    assert "shctx worktree gc: pruned 0 (threshold 24h)" in proc_default.stdout
    assert wt.is_dir()

    proc_short = _run(["gc", "--older-than=6"], repo)
    assert proc_short.returncode == 0, proc_short.stderr
    assert "shctx worktree gc: pruned 1 (threshold 6h)" in proc_short.stdout
    assert not wt.exists()


def test_gc_ignores_non_agent_worktrees(repo: Path) -> None:
    """Only paths containing /.claude/worktrees/agent-* are eligible for gc."""
    toplevel = _toplevel(repo)
    other = Path(toplevel) / "other-worktree"
    _git(repo, "branch", "side")
    _git(repo, "worktree", "add", str(other), "side")
    two_days_ago = int(time.time()) - 2 * 24 * 3600
    _commit_with_timestamp(other, two_days_ago, "backdated")

    proc = _run(["gc"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "shctx worktree gc: pruned 0 (threshold 24h)" in proc.stdout
    assert other.is_dir()


def test_gc_unknown_flag_errors(repo: Path) -> None:
    proc = _run(["gc", "--bogus"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown flag: --bogus" in proc.stderr


def test_gc_bare_positional_is_unknown_flag(repo: Path) -> None:
    """Bash: gc's catch-all is a bare `*)`, not `--*)` — a non-flag
    positional token is ALSO an unknown-flag error (unlike create-batch's
    and merge's `--*)`-only catch-alls, which collect bare tokens as data)."""
    proc = _run(["gc", "some-lane"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown flag: some-lane" in proc.stderr


def test_gc_invalid_older_than_errors(repo: Path) -> None:
    proc = _run(["gc", "--older-than=notanumber"], repo)
    assert proc.returncode == 1
    assert "ERROR: --older-than must be an integer, got: notanumber" in proc.stderr


def test_gc_help_prints_to_stderr_exit_0(repo: Path) -> None:
    proc = _run(["gc", "-h"], repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr.rstrip("\n") == "shctx worktree gc [--older-than=<hours> | --all] [--dry-run]"


# --------------------------------------------------------------------------
# `merge`.
# --------------------------------------------------------------------------
def test_merge_requires_agent_id(repo: Path) -> None:
    proc = _run(["merge"], repo)
    assert proc.returncode == 1
    assert "ERROR: agent-id required" in proc.stderr


def test_merge_invalid_strategy_errors(repo: Path) -> None:
    proc = _run(["merge", "x", "--strategy=bogus"], repo)
    assert proc.returncode == 1
    assert "ERROR: --strategy must be theirs|prompt" in proc.stderr


def test_merge_no_matching_worktree_errors(repo: Path) -> None:
    proc = _run(["merge", "nope"], repo)
    assert proc.returncode == 1
    assert "ERROR: no worktree matching agent-id 'nope'" in proc.stderr


def test_merge_worktree_path_missing_errors(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "ghost"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-ghost"
    # Remove the directory WITHOUT telling git — it still shows up in
    # `git worktree list --porcelain`, just no longer exists on disk.
    shutil.rmtree(wt)

    proc = _run(["merge", "ghost"], repo)
    assert proc.returncode == 1
    assert f"ERROR: worktree path missing: {wt}" in proc.stderr


def test_merge_cherry_picks_and_cleans_up_worktree(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "ok"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-ok"
    (wt / "feature.txt").write_text("feature\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-q", "-m", "agent commit")
    head_sha = _git(wt, "rev-parse", "HEAD").stdout.strip()

    proc = _run(["merge", "ok"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"shctx worktree merge: cherry-picking {head_sha} from {wt}" in proc.stdout
    assert f"shctx worktree merge: cleanup — removing {wt}" in proc.stdout
    assert "shctx worktree merge: ok" in proc.stdout
    assert not wt.exists()
    assert (repo / "feature.txt").read_text() == "feature\n"
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "agent commit"


def test_merge_no_cleanup_keeps_worktree(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "keep"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-keep"
    (wt / "feature.txt").write_text("feature\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-q", "-m", "agent commit")

    proc = _run(["merge", "keep", "--no-cleanup"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "shctx worktree merge: ok" in proc.stdout
    # Assert the specific cleanup ACTION message is absent — not the bare word
    # "cleanup", which git's own output echoes as part of the worktree path
    # (the pytest tmpdir is named ".../test_merge_no_cleanup_keeps_wo0/...").
    assert "cleanup — removing" not in proc.stdout
    assert wt.is_dir()


def test_merge_strategy_theirs_resolves_conflict_automatically(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "conflict"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-conflict"

    (repo / "a.txt").write_text("main-side\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "main edits a.txt")

    (wt / "a.txt").write_text("agent-side\n")
    _git(wt, "add", "a.txt")
    _git(wt, "commit", "-q", "-m", "agent edits a.txt")

    proc = _run(["merge", "conflict", "--strategy=theirs"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "shctx worktree merge: ok" in proc.stdout
    assert (repo / "a.txt").read_text() == "agent-side\n"
    assert not wt.exists()


def test_merge_default_strategy_prompt_halts_on_conflict(repo: Path) -> None:
    toplevel = _toplevel(repo)
    _run(["create-batch", "conflict2"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-conflict2"

    (repo / "a.txt").write_text("main-side\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "main edits a.txt")

    (wt / "a.txt").write_text("agent-side\n")
    _git(wt, "add", "a.txt")
    _git(wt, "commit", "-q", "-m", "agent edits a.txt")

    try:
        proc = _run(["merge", "conflict2"], repo)
        assert proc.returncode != 0
        assert "shctx worktree merge: cherry-pick had conflicts" in proc.stderr
        assert "Resolve, then run `git cherry-pick --continue`." in proc.stderr
        assert "Worktree NOT cleaned up" in proc.stderr
        assert "shctx worktree merge conflict2 --no-cleanup" in proc.stderr
        # Worktree NOT cleaned up on conflict.
        assert wt.is_dir()
    finally:
        subprocess.run(["git", "cherry-pick", "--abort"], cwd=str(repo), check=False)


def test_merge_agent_id_last_bare_token_wins(repo: Path) -> None:
    """Bash: `merge`'s bare-token arm is plain reassignment (`agent="$1"`)
    — the LAST bare token given wins, unlike create-batch's accumulating
    lane list."""
    toplevel = _toplevel(repo)
    _run(["create-batch", "second"], repo)
    wt = Path(toplevel) / ".claude" / "worktrees" / "agent-second"
    # The worktree needs a real, non-empty commit or the merge's cherry-pick is
    # empty and (bash parity) exits 1 "cherry-pick is now empty" — unrelated to
    # the bare-token arg-parsing this test actually exercises.
    (wt / "feature.txt").write_text("feature\n")
    _git(wt, "add", "feature.txt")
    _git(wt, "commit", "-q", "-m", "agent commit")

    proc = _run(["merge", "first-ignored", "second"], repo)
    assert proc.returncode == 0, proc.stderr
    assert f"cherry-picking" in proc.stdout
    assert not wt.exists()


def test_merge_unknown_flag_errors(repo: Path) -> None:
    proc = _run(["merge", "x", "--bogus"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown flag: --bogus" in proc.stderr


def test_merge_help_prints_to_stderr_exit_0(repo: Path) -> None:
    proc = _run(["merge", "-h"], repo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert (
        proc.stderr.rstrip("\n")
        == "shctx worktree merge <agent-id> [--strategy=theirs|prompt] [--no-cleanup]"
    )


# --------------------------------------------------------------------------
# Top-level dispatch: -h / --help / help / unknown subcommand.
# --------------------------------------------------------------------------
def test_top_level_help_flags_print_to_stdout_exit_0(repo: Path) -> None:
    for flag in ("-h", "--help", "help"):
        proc = _run([flag], repo)
        assert proc.returncode == 0, proc.stderr
        assert "shctx worktree <subcommand>" in proc.stdout
        assert "create-batch <lane-id" in proc.stdout
        assert "gc   [--older-than=<hours> | --all] [--dry-run]" in proc.stdout
        assert "merge <agent-id> [--strategy=...] [--no-cleanup]" in proc.stdout
        assert proc.stderr == ""


def test_unknown_subcommand_errors(repo: Path) -> None:
    proc = _run(["bogus-sub"], repo)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown subcommand: bogus-sub" in proc.stderr
