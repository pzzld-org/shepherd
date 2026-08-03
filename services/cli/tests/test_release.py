"""Subprocess parity tests for ``shepherd release`` (gear-cascade release pipeline).

Bash parity target: ``skills/context/scripts/cmd_release.sh``; every
load-bearing assertion of ``skills/context/tests/test_release.sh`` is
migrated below (modes A-D, the skip flags, and the unknown-branch error),
plus real-execution coverage the bash suite never had: the full cascade
run against a throwaway repo with a bare ``origin`` remote, the mid-patch
sprint close, the tag-exists / already-merged skip paths, release-notes
extraction + fallbacks, the ported ``shctx_gh_retry`` backoff behavior,
and the additive run-scoped notes-file shim.

Drives the module's Typer app DIRECTLY via a ``${PY} -c`` subprocess
snippet (``shepherd_cli.commands.release.app``) — the sub-app is not yet
registered in ``shepherd_cli.app``, so module-level invocation is what
works both BEFORE and AFTER the integrator flips registration (same note
as ``test_graph.py``/``test_plan.py``).

No network anywhere: ``gh`` is stubbed with a PATH shim that records its
argv (and can inject scripted failures for the retry tests); every git
remote is a local bare repo under ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from conftest import PY, clean_env_dict

_RELEASE_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.release import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd release')\n"
)

_SKILL_MD = "---\nname: x\nslug: x\nversion: 0.0.0\n---\n"

_CHANGELOG = (
    "# Changelog\n"
    "\n"
    "## v5.0.0 — cascade release\n"
    "- added the gear cascade\n"
    "- fixed the trigger\n"
    "\n"
    "## v4.9.9\n"
    "- old stuff\n"
)

#: What `_extract_release_notes` must produce from _CHANGELOG for v5.0.0:
#: every line after the matching `## ` heading up to (not including) the
#: next one — INCLUDING the trailing blank separator line (awk parity).
_EXPECTED_NOTES = "- added the gear cascade\n- fixed the trigger\n\n"


# --------------------------------------------------------------------------
# Environment / fixture-repo / stub helpers.
# --------------------------------------------------------------------------
def _env(**extra: str) -> dict[str, str]:
    """A stripped env with commit signing disabled (mirrors tests/_setup.sh).

    ``GIT_CONFIG_*`` neutralizes any host-level ``commit.gpgsign`` so
    throwaway-repo commits (both fixture setup and the CLI's own
    ``git commit`` steps) never depend on a signing setup. ``SHEPHERD_RUN``
    is popped so the run-scoped shim only activates when a test opts in.
    """
    env = clean_env_dict()
    env.pop("SHEPHERD_RUN", None)
    env.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "commit.gpgsign",
            "GIT_CONFIG_VALUE_0": "false",
        }
    )
    env.update(extra)
    return env


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd`` under the neutralized env, raising on failure."""
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=_env(), check=True, capture_output=True, text=True
    )


def _seed_version_files(repo: Path) -> None:
    """Seed every VERSION_FILES entry (bash test parity, plus a nested
    ``plugins[].version`` in marketplace.json to exercise the guarded jq
    branch the bash fixture left dormant)."""
    (repo / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (repo / "skills" / "shepherd").mkdir(parents=True, exist_ok=True)
    (repo / "skills" / "context").mkdir(parents=True, exist_ok=True)
    (repo / ".claude-plugin" / "plugin.json").write_text('{"version":"0.0.0"}\n')
    (repo / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"version": "0.0.0", "plugins": [{"name": "shepherd", "version": "0.0.0"}]}) + "\n"
    )
    (repo / "skills" / "shepherd" / "SKILL.md").write_text(_SKILL_MD)
    (repo / "skills" / "context" / "SKILL.md").write_text(_SKILL_MD)
    (repo / "README.md").write_text("# README\n\nCurrent version: **0.0.0**\n")


def _init_repo(tmp_path: Path) -> Path:
    """A throwaway git repo on branch ``main`` with the version files committed.

    The path is resolved to its physical form so every expected-path
    assertion agrees with what git itself (and thus the CLI's
    ``resolve_repo_root``) reports through any symlinked temp dir.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    repo = repo.resolve()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _seed_version_files(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed version files")
    return repo


def _add_origin(repo: Path, tmp_path: Path, *push_branches: str) -> Path:
    """Create a local bare ``origin`` and push ``main`` + any extra branches."""
    bare = (tmp_path / "origin.git").resolve()
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], env=_env(), check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")
    for branch in push_branches:
        _git(repo, "push", "-q", "-u", "origin", branch)
    return bare


def _install_gh_stub(
    bindir: Path, log: Path, *, count: Path | None = None, fail_n: int = 0, fail_msg: str = "HTTP 502"
) -> None:
    """Install an executable ``gh`` PATH shim recording every invocation.

    With ``fail_n`` > 0 the first ``fail_n`` invocations print ``fail_msg``
    to stderr and exit 1 (invocation count persisted in ``count``), so the
    retry tests can script transient vs. terminal failures.
    """
    bindir.mkdir(parents=True, exist_ok=True)
    script = f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\n'
    if fail_n:
        assert count is not None
        script += (
            f'c=$(cat "{count}" 2>/dev/null || echo 0)\n'
            f'c=$((c+1))\n'
            f'printf \'%s\\n\' "$c" > "{count}"\n'
            f'if [ "$c" -le {fail_n} ]; then\n'
            f"  printf '%s\\n' \"{fail_msg}\" >&2\n"
            f"  exit 1\n"
            f"fi\n"
        )
    script += "exit 0\n"
    gh = bindir / "gh"
    gh.write_text(script)
    gh.chmod(0o755)


def _gh_less_path(tmp_path: Path, env: dict[str, str]) -> None:
    """Point PATH at a minimal bin dir WITHOUT gh (for the ``command -v gh``
    miss branch — a prepended stub can't simulate absence, and dropping
    whole PATH entries would also drop git). Only ``git`` is linked in:
    it is the sole PATH-resolved binary the pipeline needs besides gh."""
    bindir = tmp_path / "no-gh-bin"
    bindir.mkdir(exist_ok=True)
    git_path = shutil.which("git", path=env.get("PATH"))
    assert git_path, "git not found on PATH"
    (bindir / "git").symlink_to(git_path)
    env["PATH"] = str(bindir)


def _run_release(
    args: list[str], cwd: Path, *, env: dict[str, str] | None = None, timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    """Run the release module app as a real subprocess from ``cwd``."""
    return subprocess.run(
        [PY, "-c", _RELEASE_SNIPPET, *args],
        cwd=str(cwd),
        env=env if env is not None else _env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _exec_fixture(tmp_path: Path, *, changelog: str | None = _CHANGELOG) -> tuple[Path, Path, dict[str, str]]:
    """A repo on branch v5.0.0 (one commit past main) + origin + gh stub.

    Returns (repo, gh_log, env-with-stub-PATH) — the standard shape for
    every full-cascade real-execution test.
    """
    repo = _init_repo(tmp_path)
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog)
        _git(repo, "add", "CHANGELOG.md")
        _git(repo, "commit", "-qm", "changelog")
    _add_origin(repo, tmp_path)
    _git(repo, "checkout", "-q", "-b", "v5.0.0")
    (repo / "feature.txt").write_text("the feature\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-qm", "feat: the feature")
    bindir = tmp_path / "bin"
    gh_log = tmp_path / "gh.log"
    _install_gh_stub(bindir, gh_log)
    env = _env()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    return repo, gh_log, env


# --------------------------------------------------------------------------
# Mode A: lighter-pattern dry-run (bash test_release.sh block 1).
# --------------------------------------------------------------------------
def test_lighter_pattern_dry_run_plan(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v5.0.0")

    proc = _run_release(["--dry-run"], repo)
    out = proc.stdout

    assert proc.returncode == 0, proc.stderr
    # Mode detection.
    assert "lighter-pattern mode: patch 5.0.0 ready for release" in out
    # Core cascade plan steps.
    assert "git merge --squash v5.0.0" in out
    assert "git tag -a v5.0.0" in out
    assert "git tag -f v5.0\n" in out
    assert "git tag -f v5\n" in out
    assert "gh release create v5.0.0" in out
    # Cascade: 5.0.0 -> 5.0.1 (Z<9 increments Z).
    assert "git checkout -b v5.0.1 main" in out
    assert "git checkout -b v5.0.1-dev.0" in out
    assert "bump (json) .claude-plugin/plugin.json" in out
    assert "bump (readme) README.md" in out
    assert "release pipeline complete: v5.0.0 released" in out
    # Legacy (no-run) notes path.
    assert ".shepherd/tmp/release-notes-v5.0.0.md" in out
    # Dry-run is read-only: nothing moved, nothing tagged, nothing bumped.
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "v5.0.0"
    assert _git(repo, "tag", "--list").stdout.strip() == ""
    assert json.loads((repo / ".claude-plugin" / "plugin.json").read_text())["version"] == "0.0.0"


# --------------------------------------------------------------------------
# Mode B: sprint-end, mid-patch (bash block 2).
# --------------------------------------------------------------------------
def test_sprint_mid_patch_dry_run(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v0.2.9")
    _git(repo, "checkout", "-q", "-b", "v0.2.9-dev.5")

    proc = _run_release(["--dry-run"], repo)
    out = proc.stdout

    assert proc.returncode == 0, proc.stderr
    assert "sprint-end mode: dev.5 of patch 0.2.9" in out
    assert "mid-patch sprint close: rebase dev.5" in out
    assert "git rebase v0.2.9-dev.5" in out
    assert "git checkout -b v0.2.9-dev.6 v0.2.9" in out
    assert "done. now on v0.2.9-dev.6." in out
    # Mid-patch must NOT run the cascade.
    assert "git tag -a v0.2.9" not in out
    assert "gh release create v0.2.9" not in out


# --------------------------------------------------------------------------
# Mode C: sprint-end, end of patch — cascade fires (bash block 3).
# --------------------------------------------------------------------------
def test_sprint_patch_end_dry_run(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v0.2.9")
    _git(repo, "checkout", "-q", "-b", "v0.2.9-dev.9")

    proc = _run_release(["--dry-run"], repo)
    out = proc.stdout

    assert proc.returncode == 0, proc.stderr
    assert "sprint-end mode: dev.9 of patch 0.2.9" in out
    assert "patch-end sprint: rebase dev.9 → v0.2.9, then run full cascade" in out
    # After the fall-through the cascade fires (Z=9, Y=2 -> 0.3.0).
    assert "git tag -a v0.2.9" in out
    assert "git checkout -b v0.3.0 main" in out
    assert "git checkout -b v0.3.0-dev.0" in out


# --------------------------------------------------------------------------
# Mode D: cascade boundary — Z=9, Y=9 rolls the major gear (bash block 4).
# --------------------------------------------------------------------------
def test_major_bump_cascade_dry_run(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v1.9.9")

    proc = _run_release(["--dry-run"], repo)

    assert proc.returncode == 0, proc.stderr
    assert "git checkout -b v2.0.0 main" in proc.stdout
    assert "git checkout -b v2.0.0-dev.0" in proc.stdout


# --------------------------------------------------------------------------
# Skip flags (bash block 5).
# --------------------------------------------------------------------------
def test_skip_flags_dry_run(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v3.0.0")

    proc = _run_release(["--dry-run", "--skip=tag,gh,bump,push"], repo)
    out = proc.stdout

    assert proc.returncode == 0, proc.stderr
    assert "skip tag (--skip=tag): v3.0.0" in out
    assert "skip mutable tags (--skip=tag): v3.0, v3" in out
    assert "skip gh release (--skip=gh): v3.0.0" in out
    assert "skip version bump (--skip=bump)" in out
    # With --skip=push (and bump skipped) no push or pull line appears at all.
    assert "git push" not in out
    assert "git pull" not in out


def test_dry_run_push_plan_quirk(tmp_path: Path) -> None:
    """Bash quirk (preserved exactly): in dry-run WITHOUT --skip=bump, the
    bump block's ``git push origin <next-dev>`` plan line prints even under
    ``--skip=push`` (that else-arm has no SKIP_PUSH guard in bash), while
    every OTHER push/pull plan line is correctly suppressed."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v5.0.0")

    proc = _run_release(["--dry-run", "--skip=push"], repo)
    out = proc.stdout

    assert proc.returncode == 0, proc.stderr
    assert "  PLAN: git push origin v5.0.1-dev.0" in out  # the quirk
    assert "  PLAN: git push origin main" not in out
    assert "  PLAN: git pull --ff-only origin main" not in out
    assert "  PLAN: git push -u origin v5.0.1" not in out
    assert "  PLAN: git push origin refs/tags/v5.0.0" not in out


def test_version_file_missing_dry_run(tmp_path: Path) -> None:
    """A missing version file plans ``skip bump (not found)`` (existence is
    checked before the dry-run short-circuit, bash-exact)."""
    repo = _init_repo(tmp_path)
    (repo / ".claude-plugin" / "marketplace.json").unlink()
    _git(repo, "checkout", "-q", "-b", "v5.0.0")

    proc = _run_release(["--dry-run"], repo)
    out = proc.stdout

    assert proc.returncode == 0, proc.stderr
    assert "  PLAN: skip bump (not found): .claude-plugin/marketplace.json" in out
    assert "bump (json) .claude-plugin/plugin.json" in out  # the rest still plan


# --------------------------------------------------------------------------
# Unknown branch shape (bash block 6) + flag-parsing error paths.
# --------------------------------------------------------------------------
def test_unknown_branch_error(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "not-a-version")

    proc = _run_release(["--dry-run"], repo)

    assert proc.returncode == 1
    assert "shctx release: current branch: not-a-version (mode: none)" in proc.stdout
    assert "ERROR: current branch 'not-a-version' does not match a known release pattern" in proc.stderr
    assert "expected v<X>.<Y>.<Z> or v<X>.<Y>.<Z>-dev.<N>" in proc.stderr


def test_help_flag(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    for args in (["-h"], ["--help"], ["--dry-run", "-h"]):
        proc = _run_release(args, repo)
        assert proc.returncode == 0, (args, proc.stderr)
        assert proc.stdout.startswith("shctx release [--dry-run] [--skip=tag,gh,bump,push]")
        assert "Use --dry-run to print the plan without executing." in proc.stdout
    # Bare `help` is NOT special in cmd_release.sh — it's an unknown flag.
    proc = _run_release(["help"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown flag: help" in proc.stderr


def test_unknown_flag_error(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    proc = _run_release(["--wat"], repo)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert "ERROR: unknown flag: --wat" in proc.stderr
    # Usage goes to stderr on this path (bash: `usage >&2`).
    assert "shctx release [--dry-run] [--skip=tag,gh,bump,push]" in proc.stderr


def test_skip_step_parsing(tmp_path: Path) -> None:
    """`--skip=` splitting parity with bash's ``IFS=, read -r -a``."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v3.0.0")

    # One trailing empty field is dropped: `--skip=tag,` == `--skip=tag`.
    proc = _run_release(["--dry-run", "--skip=tag,"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "skip tag (--skip=tag): v3.0.0" in proc.stdout

    # An INTERIOR empty field errors (with an empty step name, bash-exact).
    proc = _run_release(["--dry-run", "--skip=tag,,gh"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown skip step: " in proc.stderr

    # `--skip=` alone is a no-op.
    proc = _run_release(["--dry-run", "--skip="], repo)
    assert proc.returncode == 0, proc.stderr

    # The space-separated form is NOT recognized (bash `--skip=*` glob).
    proc = _run_release(["--skip", "tag"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown flag: --skip" in proc.stderr

    # Unknown step name.
    proc = _run_release(["--dry-run", "--skip=publish"], repo)
    assert proc.returncode == 1
    assert "ERROR: unknown skip step: publish" in proc.stderr


# --------------------------------------------------------------------------
# sprints_per_patch config wiring (the dev.{last} release-trigger fix).
# --------------------------------------------------------------------------
def test_sprints_per_patch_config(tmp_path: Path) -> None:
    """``sprints_per_patch`` is read section-agnostically (it lives under
    ``[branching]``) with local-over-project precedence, and moves the
    patch-end trigger to ``dev.{N-1}``."""
    repo = _init_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "shepherd.toml").write_text("[branching]\nsprints_per_patch = 5\n")
    _git(repo, "checkout", "-q", "-b", "v0.2.9")

    # dev.4 of a 5-sprint patch is the LAST sprint -> full cascade.
    _git(repo, "checkout", "-q", "-b", "v0.2.9-dev.4")
    proc = _run_release(["--dry-run"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "patch-end sprint: rebase dev.4 → v0.2.9, then run full cascade" in proc.stdout

    # dev.3 is still mid-patch under sprints_per_patch=5.
    _git(repo, "checkout", "-q", "v0.2.9")
    _git(repo, "checkout", "-q", "-b", "v0.2.9-dev.3")
    proc = _run_release(["--dry-run"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "mid-patch sprint close: rebase dev.3 → v0.2.9, then cut dev.4" in proc.stdout

    # shepherd.local.toml overrides the project file (cfg_get precedence):
    # with 7 sprints, dev.4 goes back to being mid-patch.
    (repo / ".claude" / "shepherd.local.toml").write_text("[branching]\nsprints_per_patch = 7\n")
    _git(repo, "checkout", "-q", "v0.2.9")
    _git(repo, "checkout", "-q", "-B", "v0.2.9-dev.4")
    proc = _run_release(["--dry-run"], repo)
    assert proc.returncode == 0, proc.stderr
    assert "mid-patch sprint close: rebase dev.4 → v0.2.9, then cut dev.5" in proc.stdout


# --------------------------------------------------------------------------
# Real execution: the full cascade against a bare origin + gh stub.
# --------------------------------------------------------------------------
def test_full_pipeline_execution(tmp_path: Path) -> None:
    repo, gh_log, env = _exec_fixture(tmp_path)

    proc = _run_release([], repo, env=env)
    out = proc.stdout

    assert proc.returncode == 0, (out, proc.stderr)
    assert "release pipeline complete: v5.0.0 released; now on v5.0.1-dev.0" in out

    # Squash landed on main with the release commit message + content.
    assert _git(repo, "log", "-1", "--format=%s", "main").stdout.strip() == "release: shepherd v5.0.0"
    assert _git(repo, "show", "main:feature.txt").stdout == "the feature\n"

    # Tags: immutable patch tag + mutable minor/major, all present locally...
    tags = set(_git(repo, "tag", "--list").stdout.split())
    assert {"v5.0.0", "v5.0", "v5"} <= tags
    # ...and pushed to origin (explicit refs/tags refspecs).
    remote_tags = _git(repo, "ls-remote", "--tags", "origin").stdout
    for tag_ref in ("refs/tags/v5.0.0", "refs/tags/v5.0", "refs/tags/v5"):
        assert tag_ref in remote_tags

    # gh stub got exactly one release-create invocation.
    gh_calls = gh_log.read_text().splitlines()
    assert len(gh_calls) == 1
    assert gh_calls[0].startswith("release create v5.0.0 --notes-file=")
    assert gh_calls[0].endswith("--title=shepherd v5.0.0")

    # Notes were extracted from the CHANGELOG section (legacy workdir path).
    notes = repo / ".shepherd" / "tmp" / "release-notes-v5.0.0.md"
    assert notes.read_text() == _EXPECTED_NOTES

    # Cascade cut v5.0.1 + v5.0.1-dev.0 and left us on the dev branch.
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "v5.0.1-dev.0"
    remote_heads = _git(repo, "ls-remote", "--heads", "origin").stdout
    for head in ("refs/heads/main", "refs/heads/v5.0.1", "refs/heads/v5.0.1-dev.0"):
        assert head in remote_heads

    # Version files all bumped to 5.0.1 (json incl. nested plugins, yaml, readme).
    assert json.loads((repo / ".claude-plugin" / "plugin.json").read_text())["version"] == "5.0.1"
    marketplace = json.loads((repo / ".claude-plugin" / "marketplace.json").read_text())
    assert marketplace["version"] == "5.0.1"
    assert marketplace["plugins"][0]["version"] == "5.0.1"
    assert "version: 5.0.1" in (repo / "skills" / "shepherd" / "SKILL.md").read_text()
    assert "version: 5.0.1" in (repo / "skills" / "context" / "SKILL.md").read_text()
    assert "Current version: **5.0.1**" in (repo / "README.md").read_text()
    assert (
        _git(repo, "log", "-1", "--format=%s").stdout.strip()
        == "chore: bump shepherd to v5.0.1 (next patch working branch)"
    )


def test_mid_patch_execution(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v0.2.9")
    _git(repo, "checkout", "-q", "-b", "v0.2.9-dev.5")
    (repo / "sprint.txt").write_text("sprint work\n")
    _git(repo, "add", "sprint.txt")
    _git(repo, "commit", "-qm", "sprint work")
    _add_origin(repo, tmp_path, "v0.2.9", "v0.2.9-dev.5")

    proc = _run_release([], repo)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "done. now on v0.2.9-dev.6." in proc.stdout
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "v0.2.9-dev.6"
    # The dev branch's work was rebased into the patch branch.
    assert _git(repo, "show", "v0.2.9:sprint.txt").stdout == "sprint work\n"
    # dev.5 deleted locally and on origin; dev.6 pushed; patch branch pushed.
    local_branches = _git(repo, "branch", "--list", "--format=%(refname:short)").stdout.split()
    assert "v0.2.9-dev.5" not in local_branches
    remote_heads = _git(repo, "ls-remote", "--heads", "origin").stdout
    assert "refs/heads/v0.2.9-dev.5" not in remote_heads
    assert "refs/heads/v0.2.9-dev.6" in remote_heads
    assert _git(repo, "rev-parse", "v0.2.9").stdout.strip() in remote_heads
    # Mid-patch never tags or gh-releases.
    assert _git(repo, "tag", "--list").stdout.strip() == ""


def test_tag_exists_skip(tmp_path: Path) -> None:
    """A pre-existing patch tag is left untouched (immutable), the pipeline
    logs the skip and still completes; mutable tags are still forced.

    Reaching this path requires starting from a branch NOT named like the
    tag: once tag and branch share a name, ``git rev-parse --abbrev-ref
    HEAD`` disambiguates to ``heads/<name>`` (mode: none — bash fails the
    same way), and a bare ``git push origin <name>`` becomes refspec-
    ambiguous (the very footgun cmd_release.sh's refs/tags/ comment
    documents). So: sprint patch-end mode (dev.9), tag pre-created at the
    dev tip (== the rebased patch-branch tip, so the tag-resolved squash
    still stages real changes), pushes skipped."""
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "v0.2.9")
    _git(repo, "checkout", "-q", "-b", "v0.2.9-dev.9")
    (repo / "sprint.txt").write_text("sprint work\n")
    _git(repo, "add", "sprint.txt")
    _git(repo, "commit", "-qm", "sprint work")
    dev_tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "tag", "-a", "v0.2.9", "-m", "pre-existing", dev_tip)
    bindir = tmp_path / "bin"
    _install_gh_stub(bindir, tmp_path / "gh.log")
    env = _env()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"

    proc = _run_release(["--skip=push"], repo, env=env)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "shctx release: skip tag: v0.2.9 already exists" in proc.stdout
    assert "release pipeline complete: v0.2.9 released; now on v0.3.0-dev.0" in proc.stdout
    # Immutable tag still points at the pre-existing (dev-tip) commit...
    assert _git(repo, "rev-parse", "v0.2.9^{commit}").stdout.strip() == dev_tip
    # ...while the mutable tags were force-moved to the new release commit.
    release_commit = _git(repo, "rev-parse", "main").stdout.strip()
    assert _git(repo, "rev-parse", "v0.2^{commit}").stdout.strip() == release_commit
    assert release_commit != dev_tip


def test_already_merged_skips_squash(tmp_path: Path) -> None:
    """A patch branch already ancestral to main skips the squash step."""
    repo = _init_repo(tmp_path)
    _add_origin(repo, tmp_path)
    _git(repo, "checkout", "-q", "-b", "v5.0.0")  # same commit as main
    bindir = tmp_path / "bin"
    _install_gh_stub(bindir, tmp_path / "gh.log")
    env = _env()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"

    proc = _run_release([], repo, env=env)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert "shctx release: skip squash: v5.0.0 already an ancestor of main" in proc.stdout
    assert "git merge --squash" not in proc.stdout
    assert "release pipeline complete: v5.0.0 released" in proc.stdout


# --------------------------------------------------------------------------
# Release notes: extraction, fallbacks, and the gh-missing branch.
# --------------------------------------------------------------------------
def _minimal_gh_repo(tmp_path: Path, *, changelog: str | None) -> tuple[Path, dict[str, str], Path]:
    """The cheapest real-exec shape that reaches the gh step: patch branch at
    main's HEAD (squash auto-skips) + ``--skip=tag,bump,push`` — no origin
    needed. Returns (repo, env-with-stub, gh_log)."""
    repo = _init_repo(tmp_path)
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog)
        _git(repo, "add", "CHANGELOG.md")
        _git(repo, "commit", "-qm", "changelog")
    _git(repo, "checkout", "-q", "-b", "v5.0.0")
    bindir = tmp_path / "bin"
    gh_log = tmp_path / "gh.log"
    _install_gh_stub(bindir, gh_log)
    env = _env()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    return repo, env, gh_log


def test_notes_fallback_no_section(tmp_path: Path) -> None:
    """CHANGELOG present but no matching section -> `shepherd <tag>` fallback."""
    repo, env, _gh_log = _minimal_gh_repo(tmp_path, changelog="# Changelog\n\n## v0.0.1\n- ancient\n")

    proc = _run_release(["--skip=tag,bump,push"], repo, env=env)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    notes = repo / ".shepherd" / "tmp" / "release-notes-v5.0.0.md"
    assert notes.read_text() == "shepherd v5.0.0\n"


def test_notes_missing_changelog(tmp_path: Path) -> None:
    """No CHANGELOG.md at all -> the placeholder line becomes the notes
    (bash parity: the placeholder makes the file non-empty, so the
    `shepherd <tag>` fallback does NOT fire)."""
    repo, env, _gh_log = _minimal_gh_repo(tmp_path, changelog=None)

    proc = _run_release(["--skip=tag,bump,push"], repo, env=env)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    notes = repo / ".shepherd" / "tmp" / "release-notes-v5.0.0.md"
    assert notes.read_text() == f"(no CHANGELOG.md found at {repo}/CHANGELOG.md)\n"


def test_gh_missing(tmp_path: Path) -> None:
    """No gh on PATH: the release step is skipped with the bash log line,
    the notes file is still written, and the pipeline completes."""
    repo, env, _gh_log = _minimal_gh_repo(tmp_path, changelog=_CHANGELOG)
    _gh_less_path(tmp_path, env)  # replaces the stub PATH with a gh-less one

    proc = _run_release(["--skip=tag,bump,push"], repo, env=env)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    notes = repo / ".shepherd" / "tmp" / "release-notes-v5.0.0.md"
    assert f"shctx release: gh missing; skipped gh release (notes at {notes})" in proc.stdout
    assert notes.read_text() == _EXPECTED_NOTES


# --------------------------------------------------------------------------
# The ported shctx_gh_retry: transient backoff vs fail-fast.
# --------------------------------------------------------------------------
def test_gh_retry_transient_then_success(tmp_path: Path) -> None:
    repo, env, gh_log = _minimal_gh_repo(tmp_path, changelog=_CHANGELOG)
    count = tmp_path / "gh.count"
    _install_gh_stub(tmp_path / "bin", gh_log, count=count, fail_n=1, fail_msg="HTTP 502 upstream")
    env["SHCTX_GH_RETRY_BACKOFF"] = "0"  # keep the test instant

    proc = _run_release(["--skip=tag,bump,push"], repo, env=env)

    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert count.read_text().strip() == "2"  # failed once, retried once
    assert "shctx_gh_retry: transient failure (attempt 1/3); retrying in 0s..." in proc.stderr
    assert "release pipeline complete: v5.0.0 released" in proc.stdout


def test_gh_retry_non_transient_fails_fast(tmp_path: Path) -> None:
    repo, env, gh_log = _minimal_gh_repo(tmp_path, changelog=_CHANGELOG)
    count = tmp_path / "gh.count"
    _install_gh_stub(tmp_path / "bin", gh_log, count=count, fail_n=99, fail_msg="release create failed: boom")
    env["SHCTX_GH_RETRY_BACKOFF"] = "0"

    proc = _run_release(["--skip=tag,bump,push"], repo, env=env)

    assert proc.returncode == 1
    assert count.read_text().strip() == "1"  # no retry on a non-transient error
    assert "release create failed: boom" in proc.stderr
    assert "release pipeline complete" not in proc.stdout


# --------------------------------------------------------------------------
# Run-scoped notes-file shim (additive; see release.py documented deviation 1).
# --------------------------------------------------------------------------
def test_run_scoped_notes_shim(tmp_path: Path) -> None:
    repo, env, _gh_log = _minimal_gh_repo(tmp_path, changelog=_CHANGELOG)

    # (a) --run flag, dry-run: the planned notes path is run-scoped.
    proc = _run_release(["--dry-run", "--run=myrun"], repo, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "/runs/myrun/tmp/release-notes-v5.0.0.md" in proc.stdout

    # (b) SHEPHERD_RUN env, real execution: notes written under runs/<run>/.
    env_run = dict(env)
    env_run["SHEPHERD_RUN"] = "r2"
    proc = _run_release(["--skip=tag,bump,push"], repo, env=env_run)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    scoped = repo / ".shepherd" / "runs" / "r2" / "tmp" / "release-notes-v5.0.0.md"
    assert scoped.read_text() == _EXPECTED_NOTES
    assert not (repo / ".shepherd" / "tmp" / "release-notes-v5.0.0.md").exists()

    # (c) <workdir>/runs/current marker, dry-run: same shim, lowest
    # precedence. Run (b) executed the real cascade and left the repo on
    # v5.0.1-dev.0 (a mid-patch sprint branch with no gh step) — move back
    # to the patch branch first so the gh plan lines appear again.
    _git(repo, "checkout", "-q", "v5.0.0")
    marker = repo / ".shepherd" / "runs" / "current"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("r3\n")
    proc = _run_release(["--dry-run"], repo, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "/runs/r3/tmp/release-notes-v5.0.0.md" in proc.stdout
    # ...and the explicit --run flag still wins over the marker.
    proc = _run_release(["--dry-run", "--run=myrun"], repo, env=env)
    assert "/runs/myrun/tmp/release-notes-v5.0.0.md" in proc.stdout
