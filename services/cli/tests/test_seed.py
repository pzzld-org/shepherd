"""Subprocess parity tests for ``shepherd seed`` (bash: ``cmd_seed.sh``).

Bash parity target: ``skills/context/scripts/cmd_seed.sh`` (v6.2.1),
subcommand ``verify``. Every test drives the real CLI as a subprocess
(``${PY} -m shepherd_cli seed ...``), exactly like ``test_lint.py`` —
never by importing ``shepherd_cli`` into the pytest process.

**NO DATABASE.** ``cmd_seed.sh`` never touches ``sqlite3``/``shctx_sql`` —
it is pure text processing over one file path — so these tests never build
a fixture DB, never set ``SHCTX_DB``, and never seed any table. The only
environment concern is ``SHEPHERD_WORKDIR``: unlike ``lint``, ``seed
verify`` never reads it either (see ``shepherd_cli/commands/seed.py``'s
module docstring — the bash header is explicit: "no DB, no _lib, no
network"), so :func:`seed_env` sets it anyway purely defensively (matching
the rest of this suite's isolation convention) even though nothing in the
command path consults it.

**``git rev-parse --show-toplevel`` runs from the subprocess's REAL cwd.**
``conftest.run_cli`` always launches the CLI with ``cwd=CLI_ROOT``
(``services/cli/``, inside this actual checkout's git repository), so
every test below that exercises ``file_scope`` resolution uses ABSOLUTE
paths into ``tmp_path`` for its scope entries — never a bare relative
token — so the outcome never depends on this checkout's own real file
tree. A relative-path resolution mode exists in the port (mirroring bash
exactly) but is not exercised here for that reason; :mod:`test_lint`'s
sibling isolation note documents the same category of concern for a
different command.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import clean_env_dict, run_cli


# --------------------------------------------------------------------------
# Env/workdir helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """An isolated scratch dir — never the real checked-in ``.artifacts/``."""
    path = tmp_path / "workdir"
    path.mkdir()
    return path


def seed_env(workdir: Path) -> dict[str, str]:
    """The environment for driving ``shepherd seed``, isolated from the real repo.

    Args:
        workdir: An isolated scratch directory (sets ``SHEPHERD_WORKDIR``
            defensively — see the module docstring; ``seed verify`` never
            actually consults it).

    Returns:
        The full environment dict for :func:`conftest.run_cli`. No
        ``SHCTX_DB``/``CLAUDE_PLUGIN_ROOT`` needed — ``seed`` touches
        neither the database nor any bundled skill asset.
    """
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def write(path: Path, content: str) -> Path:
    """Write ``content`` to ``path`` (parents created as needed) and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


_USAGE = (
    "shctx seed verify <path> [--quiet]\n"
    "  Deterministic pre-flight gate for a *.seed.md.\n"
    "  Exit 1 on >=1 HARD failure (blocks the SEED-GATE); 0 otherwise (warnings allowed)."
)


# --------------------------------------------------------------------------
# No-subcommand / help / unknown-subcommand dispatch.
# --------------------------------------------------------------------------
def test_no_subcommand_prints_usage_and_exits_0(workdir: Path) -> None:
    """A bare ``shepherd seed`` prints usage to stdout and exits 0 (bash parity)."""
    result = run_cli(["seed"], seed_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == _USAGE
    assert result.stderr == ""


@pytest.mark.parametrize("token", ["help", "--help", "-h"])
def test_help_aliases_print_usage_and_exit_0(workdir: Path, token: str) -> None:
    """``help``/``--help``/``-h`` in the subcommand-name slot alias the usage branch."""
    result = run_cli(["seed", token], seed_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == _USAGE
    assert result.stderr == ""


def test_unknown_subcommand_exits_2(workdir: Path) -> None:
    """An unrecognized subcommand name prints an error + usage to stderr, exit 2."""
    result = run_cli(["seed", "bogus"], seed_env(workdir))
    assert result.returncode == 2
    assert result.stdout == ""
    expected_stderr = "unknown subcommand: bogus\n" + _USAGE
    assert result.stderr.rstrip("\n") == expected_stderr


# --------------------------------------------------------------------------
# verify: usage-error branches (exit 2).
# --------------------------------------------------------------------------
def test_verify_missing_path_exits_2(workdir: Path) -> None:
    """``seed verify`` with no path prints an error to stderr, exit 2 (no usage text)."""
    result = run_cli(["seed", "verify"], seed_env(workdir))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.rstrip("\n") == "ERR: seed verify needs a <path>"


def test_verify_nonexistent_file_exits_2(workdir: Path) -> None:
    """A path that does not exist on disk exits 2 with a specific error."""
    missing = str(workdir / "nope.seed.md")
    result = run_cli(["seed", "verify", missing], seed_env(workdir))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.rstrip("\n") == f"ERR: no such file: {missing}"


def test_verify_directory_path_is_not_a_file_exits_2(workdir: Path) -> None:
    """A directory fails the ``-f`` (regular file) test, exactly like a missing path."""
    directory = workdir / "a_directory"
    directory.mkdir()
    result = run_cli(["seed", "verify", str(directory)], seed_env(workdir))
    assert result.returncode == 2
    assert result.stderr.rstrip("\n") == f"ERR: no such file: {directory}"


def test_verify_unknown_flag_exits_2_without_usage(workdir: Path) -> None:
    """An unrecognized ``-``-prefixed token is ``unknown flag:``, exit 2, no usage text."""
    result = run_cli(["seed", "verify", "--bogus"], seed_env(workdir))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.rstrip("\n") == "unknown flag: --bogus"


def test_verify_last_positional_token_wins(workdir: Path) -> None:
    """Two positional tokens: bash's ``*) path="$1"`` loop means the LAST one wins."""
    good = write(workdir / "good.seed.md", "kind: patch-seed\nmilestone: v1\nbody\n")
    missing = str(workdir / "does-not-exist.seed.md")
    # First token is the real file, second is missing -> the missing one wins -> exit 2.
    result = run_cli(["seed", "verify", str(good), missing], seed_env(workdir))
    assert result.returncode == 2
    assert result.stderr.rstrip("\n") == f"ERR: no such file: {missing}"


# --------------------------------------------------------------------------
# verify: happy path + --quiet.
# --------------------------------------------------------------------------
def test_verify_happy_path_ok(workdir: Path) -> None:
    """A clean, small, non-canonical seed passes with zero hard failures, zero warnings."""
    path = write(workdir / "clean.seed.md", "kind: patch-seed\n\nJust some prose, no gates tripped.\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "OK: 0 hard failures, 0 warning(s)"
    assert result.stderr == ""


def test_verify_quiet_suppresses_all_output_but_exit_code_is_unchanged(workdir: Path) -> None:
    """``--quiet`` suppresses every printed line; the exit code is unaffected."""
    path = write(workdir / "todo.seed.md", "kind: patch-seed\nTODO: fix this\n")
    loud = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    quiet = run_cli(["seed", "verify", str(path), "--quiet"], seed_env(workdir))
    assert loud.returncode == 1
    assert loud.stdout != ""
    assert quiet.returncode == 1
    assert quiet.stdout == ""
    assert quiet.stderr == ""


def test_verify_quiet_flag_before_path_also_works(workdir: Path) -> None:
    """``--quiet`` and ``<path>`` may appear in either order (bash's flag loop is order-agnostic)."""
    path = write(workdir / "clean.seed.md", "kind: patch-seed\nbody\n")
    result = run_cli(["seed", "verify", "--quiet", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert result.stdout == ""


# --------------------------------------------------------------------------
# Universal HARD checks: footprint, TODO/FIXME, Lane-N.
# --------------------------------------------------------------------------
def test_verify_todo_marker_is_hard_failure(workdir: Path) -> None:
    path = write(workdir / "todo.seed.md", "kind: patch-seed\nTODO: fix this later\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "HARD  TODO:/FIXME: marker(s) present" in result.stdout
    assert result.stdout.rstrip("\n").endswith("FAIL: 1 hard failure(s), 0 warning(s)")


def test_verify_fixme_marker_is_hard_failure(workdir: Path) -> None:
    path = write(workdir / "fixme.seed.md", "kind: patch-seed\nFIXME: broken\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "HARD  TODO:/FIXME: marker(s) present" in result.stdout


def test_verify_todo_without_colon_is_not_flagged(workdir: Path) -> None:
    """Bash's pattern requires a trailing colon: ``TODO list`` (no colon) does not trip it."""
    path = write(workdir / "ok.seed.md", "kind: patch-seed\nOur TODO list is short.\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


def test_verify_lane_n_numbering_is_hard_failure(workdir: Path) -> None:
    path = write(workdir / "lane.seed.md", "kind: sprint-seed\nLane 3 does the frontend work.\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "prescriptive 'Lane N' numbering present" in result.stdout


def test_verify_footprint_over_sprint_cap_is_hard_failure(workdir: Path) -> None:
    """Sprint-seed (default kind) footprint cap is 400 lines."""
    body = "\n".join(f"line {i}" for i in range(410))
    path = write(workdir / "big.seed.md", f"kind: sprint-seed\n{body}\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "footprint 411 lines > cap 400 (kind=sprint-seed)" in result.stdout


def test_verify_footprint_over_patch_cap_is_hard_failure(workdir: Path) -> None:
    """``kind: patch-seed`` lowers the footprint cap to 200 lines."""
    body = "\n".join(f"line {i}" for i in range(205))
    path = write(workdir / "big-patch.seed.md", f"kind: patch-seed\n{body}\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "footprint 206 lines > cap 200 (kind=patch-seed)" in result.stdout


def test_verify_footprint_smell_threshold_is_warn_only(workdir: Path) -> None:
    """Over the 75%-of-cap smell threshold but under the cap itself: WARN, exit 0."""
    # cap=400 for sprint (default kind), warn_at = 300. 305 body lines + 1 kind line = 306.
    body = "\n".join(f"line {i}" for i in range(305))
    path = write(workdir / "smelly.seed.md", f"kind: sprint-seed\n{body}\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "footprint 306 lines > smell threshold 300" in result.stdout
    assert result.stdout.rstrip("\n").endswith("OK: 0 hard failures, 1 warning(s)")


def test_verify_default_kind_treated_as_sprint_in_message(workdir: Path) -> None:
    """No ``kind:`` frontmatter at all -> footprint message shows ``kind=sprint``."""
    body = "\n".join(f"line {i}" for i in range(410))
    path = write(workdir / "no-kind.seed.md", body + "\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "kind=sprint)" in result.stdout


# --------------------------------------------------------------------------
# Sequencing / semver judgment WARN checks.
# --------------------------------------------------------------------------
def test_verify_sequencing_directive_is_warn(workdir: Path) -> None:
    path = write(workdir / "seq.seed.md", "kind: patch-seed\n**Sequencing:** do A before B\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "'Sequencing:' directive present" in result.stdout


def test_verify_semver_judgment_is_warn(workdir: Path) -> None:
    path = write(workdir / "semver.seed.md", "kind: patch-seed\nThis is really a minor bump.\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "semver-content judgment present" in result.stdout


# --------------------------------------------------------------------------
# file_scope resolution (HARD).
# --------------------------------------------------------------------------
def test_verify_file_scope_resolving_path_passes(workdir: Path) -> None:
    real_file = write(workdir / "real.py", "x = 1\n")
    seed_body = f"kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - {real_file}\n---\nbody\n"
    path = write(workdir / "scope-ok.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


def test_verify_file_scope_missing_path_is_hard_failure(workdir: Path) -> None:
    missing = workdir / "nope.py"
    seed_body = f"kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - {missing}\n---\nbody\n"
    path = write(workdir / "scope-bad.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert f"file_scope path does not resolve and is not marked (NEW): {missing}" in result.stdout


def test_verify_file_scope_new_marker_is_exempt(workdir: Path) -> None:
    new_file = workdir / "brand-new.py"  # deliberately never created
    seed_body = f"kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - {new_file} (NEW - added this sprint)\n---\nbody\n"
    path = write(workdir / "scope-new.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


def test_verify_file_scope_template_placeholder_is_exempt(workdir: Path) -> None:
    seed_body = "kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - <path/to/file>\n---\nbody\n"
    path = write(workdir / "scope-placeholder.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


def test_verify_file_scope_flow_style_list(workdir: Path) -> None:
    real_a = write(workdir / "a.py", "a = 1\n")
    missing_b = workdir / "b.py"
    seed_body = f"kind: sprint-seed\nmilestone: v1\nfile_scope:\n  exclusive: [{real_a}, {missing_b}]\n---\nbody\n"
    path = write(workdir / "scope-flow.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert f"file_scope path does not resolve and is not marked (NEW): {missing_b}" in result.stdout


def test_verify_file_scope_glob_matching_at_least_one_file_passes(workdir: Path) -> None:
    write(workdir / "src" / "a.rs", "// a\n")
    glob_token = str(workdir / "src" / "*.rs")
    seed_body = f"kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - {glob_token}\n---\nbody\n"
    path = write(workdir / "scope-glob.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


def test_verify_file_scope_glob_matching_zero_files_is_hard_failure(workdir: Path) -> None:
    glob_token = str(workdir / "src" / "*.rs")  # src/ never created
    seed_body = f"kind: sprint-seed\nmilestone: v1\nfile_scope:\n  - {glob_token}\n---\nbody\n"
    path = write(workdir / "scope-glob-empty.seed.md", seed_body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert f"file_scope path does not resolve and is not marked (NEW): {glob_token}" in result.stdout


def test_verify_no_file_scope_section_skips_the_check_entirely(workdir: Path) -> None:
    path = write(workdir / "no-scope.seed.md", "kind: patch-seed\nmilestone: v1\nno file_scope here\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "file_scope" not in result.stdout


# --------------------------------------------------------------------------
# Deliverable **GH:** anchor (HARD, conditional).
# --------------------------------------------------------------------------
def test_verify_deliverable_block_missing_gh_anchor_is_hard_failure(workdir: Path) -> None:
    body = (
        "kind: sprint-seed\n"
        "milestone: v1\n\n"
        "### Deliverable A [CRITICAL]\n"
        "**Priority:** CRITICAL\n"
        "No GH anchor here.\n"
    )
    path = write(workdir / "no-gh.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    assert "1 deliverable block(s) carry a priority but no **GH:** anchor" in result.stdout


def test_verify_deliverable_block_with_gh_anchor_passes(workdir: Path) -> None:
    body = (
        "kind: sprint-seed\n"
        "milestone: v1\n\n"
        "### Deliverable A [CRITICAL]\n"
        "**Priority:** CRITICAL\n"
        "**GH:** #123\n"
    )
    path = write(workdir / "with-gh.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


def test_verify_non_deliverable_heading_never_needs_gh(workdir: Path) -> None:
    """A ``### `` heading with no priority tag/marker is not a deliverable block at all."""
    body = "kind: sprint-seed\nmilestone: v1\n\n### Just a section\nSome prose.\n"
    path = write(workdir / "plain-heading.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0


# --------------------------------------------------------------------------
# Canonical-only WARN checks (mesh rows, CRITICAL/HIGH, frontmatter).
# --------------------------------------------------------------------------
def test_verify_thin_mesh_is_warn(workdir: Path) -> None:
    body = "kind: sprint-seed\nmilestone: v1\nPhase 0 mesh\n| 1 | a |\n| 2 | b |\n"
    path = write(workdir / "thin-mesh.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "Phase 0 mesh has 2 row(s) (< 8 recommended)" in result.stdout


def test_verify_sufficient_mesh_rows_no_warning(workdir: Path) -> None:
    rows = "\n".join(f"| {i} | row |" for i in range(1, 9))
    body = f"kind: sprint-seed\nmilestone: v1\nPhase 0 mesh\n{rows}\n"
    path = write(workdir / "full-mesh.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "Phase 0 mesh has" not in result.stdout


def test_verify_no_critical_or_high_deliverable_is_warn(workdir: Path) -> None:
    body = (
        "kind: sprint-seed\n"
        "milestone: v1\n\n"
        "### Deliverable A [MEDIUM]\n"
        "**Priority:** MEDIUM\n"
        "**GH:** #1\n"
    )
    path = write(workdir / "no-crit.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "no deliverable ranked CRITICAL or HIGH" in result.stdout


def test_verify_missing_milestone_frontmatter_is_warn_for_canonical_seed(workdir: Path) -> None:
    """``**GH:**`` alone is enough to mark the file canonical (see is_canonical detection)."""
    body = "kind: sprint-seed\n\n### Deliverable A\n**GH:** #1\n"
    path = write(workdir / "no-milestone.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "frontmatter missing 'milestone:'" in result.stdout


def test_verify_missing_kind_frontmatter_is_warn_for_canonical_seed(workdir: Path) -> None:
    body = "milestone: v1\n\n### Deliverable A\n**GH:** #1\n"
    path = write(workdir / "no-kind-field.seed.md", body)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert "frontmatter missing 'kind:'" in result.stdout


def test_verify_noncanonical_freeform_file_skips_canonical_warnings(workdir: Path) -> None:
    """A file with none of the canonical markers gets NO milestone/kind/mesh warnings."""
    path = write(workdir / "freeform.seed.md", "Just some old-format free-text notes.\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "OK: 0 hard failures, 0 warning(s)"


# --------------------------------------------------------------------------
# Bash command-substitution quirks (trailing-newline stripping).
# --------------------------------------------------------------------------
def test_verify_empty_file_counts_as_one_line(workdir: Path) -> None:
    """Bash's ``printf '%s\\n' "" | grep -c ''`` quirk: an empty file counts as 1 line."""
    path = write(workdir / "empty.seed.md", "")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    assert result.stdout.rstrip("\n") == "OK: 0 hard failures, 0 warning(s)"


def test_verify_trailing_blank_lines_do_not_count_toward_footprint(workdir: Path) -> None:
    """Command substitution strips ALL trailing newlines, so trailing blank lines vanish."""
    # 3 real content lines + a pile of trailing blank lines that must NOT be counted.
    path = write(workdir / "trailing.seed.md", "kind: patch-seed\nline a\nline b\n\n\n\n\n\n\n\n\n\n")
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 0
    # 3 lines total (kind:, line a, line b) -- no smell/cap warning triggered.
    assert result.stdout.rstrip("\n") == "OK: 0 hard failures, 0 warning(s)"


# --------------------------------------------------------------------------
# Ordering + stderr-is-always-empty-on-verdict-output.
# --------------------------------------------------------------------------
def test_verify_check_order_footprint_then_todo_then_lane(workdir: Path) -> None:
    """Multiple simultaneous HARD failures print in the bash script's own check order."""
    body = "\n".join(f"line {i}" for i in range(410))
    content = f"kind: sprint-seed\nTODO: fix\nLane 3 work\n{body}\n"
    path = write(workdir / "multi-fail.seed.md", content)
    result = run_cli(["seed", "verify", str(path)], seed_env(workdir))
    assert result.returncode == 1
    lines = [line for line in result.stdout.splitlines() if line.startswith("  HARD")]
    assert len(lines) == 3
    assert "footprint" in lines[0]
    assert "TODO:/FIXME:" in lines[1]
    assert "Lane N" in lines[2]
    assert result.stdout.rstrip("\n").endswith("FAIL: 3 hard failure(s), 0 warning(s)")


def test_verify_stderr_is_empty_on_normal_verdict_output(workdir: Path) -> None:
    """Both a passing and a failing verify write only to stdout, never stderr."""
    ok_path = write(workdir / "ok.seed.md", "kind: patch-seed\nbody\n")
    fail_path = write(workdir / "fail.seed.md", "kind: patch-seed\nTODO: x\n")
    ok_result = run_cli(["seed", "verify", str(ok_path)], seed_env(workdir))
    fail_result = run_cli(["seed", "verify", str(fail_path)], seed_env(workdir))
    assert ok_result.stderr == ""
    assert fail_result.stderr == ""
