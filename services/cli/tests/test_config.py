"""Tests for `shepherd config` — native port of `cmd_config.sh` (pure config/file
ops, no DB — see `shepherd_cli/commands/config.py`'s module docstring).

Every test drives the real CLI as a subprocess with an ISOLATED `cwd` (a bare
`tmp_path` directory, generally NOT inside a git repository unless a test
explicitly `git init`s one) — mirroring `test_models.py`'s isolation pattern,
NOT `conftest.run_cli`'s fixed `cwd=CLI_ROOT` (which sits inside THIS repo's
own git working tree; using it here would make `shepherd config init`/
`claude-md` scaffold/mutate this real repository's own `.claude/shepherd.toml`
and `CLAUDE.md` as a side effect of running the test suite). An isolated
`XDG_CONFIG_HOME` is set on every invocation for the same reason `test_models.py`
sets one: so a populated real `~/.config/shepherd.toml` on the host running
this suite can never leak into a "no config" assertion.

Several tests additionally run the legacy `cmd_config.sh` directly, under the
identical `cwd`/env, asserting byte-for-byte stdout/file parity — the same
pattern `test_status.py`/`test_models.py`/`test_lock.py` established.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, clean_env_dict

CMD_CONFIG_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_config.sh"
BUNDLED_SHEPHERD_TOML = REPO_ROOT / "examples" / "minimal" / "shepherd.toml"
BUNDLED_CLAUDE_MD = REPO_ROOT / "examples" / "minimal" / "CLAUDE.md"

_USAGE_MARKER = "shctx config — scaffold / inspect the project shepherd.toml binding"
_UNKNOWN_SUBCOMMAND_ERR = "ERROR: usage: shctx config <init|claude-md|show|path|get>"


# --------------------------------------------------------------------------
# Isolation fixtures + subprocess helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory to use as the CLI's `cwd`.

    Never inside a git repository, so `resolve_repo_root()` (and bash's
    `shctx_repo_root`) both fall back to this exact directory rather than
    climbing up into this real repository's own root.
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


def _config_env(xdg_dir: Path) -> dict[str, str]:
    """A stripped-then-rebuilt environment, isolated to `xdg_dir`.

    Always sets `CLAUDE_PLUGIN_ROOT` to this real repo's root — needed by
    `init`/`claude-md` to locate the bundled `examples/minimal/` templates
    (see `config.py`'s `_plugin_root`); harmless for `get`/`show`/`path`,
    which never read it.
    """
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env


def run_config(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -m shepherd_cli config <args>` under `cwd`."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "config", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_bash_config(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_config.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(
        ["bash", str(CMD_CONFIG_SH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _init_git_repo(path: Path, *, remote_url: str | None = None) -> None:
    """`git init` (and optionally add an `origin` remote) at `path`."""
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), check=True)
    if remote_url:
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=str(path), check=True)


def _write_toml(path: Path, table: str, entries: dict[str, str]) -> None:
    """Write a minimal single-table TOML file at `path` (parents auto-created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"[{table}]"] if table else []
    lines.extend(f'{key} = "{value}"' for key, value in entries.items())
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# No-subcommand / help / unknown subcommand.
# --------------------------------------------------------------------------
def test_bare_invocation_prints_usage_and_exits_0(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)
    assert "shctx config init [--force]" in proc.stdout
    assert "shctx config get <key> [def]" in proc.stdout


@pytest.mark.parametrize("args", [["help"], ["-h"], ["--help"]])
def test_help_variants_print_usage_and_exit_0(args: list[str], work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(args, work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)


def test_bare_invocation_matches_help(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    bare = run_config([], work_dir, env)
    helped = run_config(["help"], work_dir, env)

    assert bare.returncode == helped.returncode == 0
    assert bare.stdout == helped.stdout


def test_unknown_subcommand_exits_1_with_bash_message(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["bogus"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == _UNKNOWN_SUBCOMMAND_ERR


# --------------------------------------------------------------------------
# path.
# --------------------------------------------------------------------------
def test_path_prints_canonical_location_regardless_of_existence(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["path"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{work_dir}/.claude/shepherd.toml\n"


def test_path_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    python_proc = run_config(["path"], work_dir, env)
    bash_proc = run_bash_config(["path"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# show.
# --------------------------------------------------------------------------
def test_show_no_config_prints_notice(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "(no .claude/shepherd.toml — run 'shctx config init')\n"


def test_show_only_project_config(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "project", {"name": "demo"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    dst = work_dir / ".claude" / "shepherd.toml"
    assert proc.stdout == f"# {dst}\n[project]\nname = \"demo\"\n\n"


def test_show_local_and_project_both_shown_local_first(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "project", {"name": "proj"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "project", {"name": "local"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    local_path = work_dir / ".claude" / "shepherd.local.toml"
    project_path = work_dir / ".claude" / "shepherd.toml"
    local_idx = proc.stdout.index(f"# {local_path}")
    project_idx = proc.stdout.index(f"# {project_path}")
    assert local_idx < project_idx


def test_show_never_reads_xdg_global(work_dir: Path, xdg_dir: Path) -> None:
    """`show` checks only `.claude/{shepherd,shepherd.local}.toml` — never XDG."""
    _write_toml(xdg_dir / "shepherd.toml", "project", {"name": "global"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "(no .claude/shepherd.toml — run 'shctx config init')\n"


def test_show_no_config_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    python_proc = run_config(["show"], work_dir, env)
    bash_proc = run_bash_config(["show"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_show_bash_parity_with_both_files(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "project", {"name": "proj"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "project", {"name": "local"})
    env = _config_env(xdg_dir)
    python_proc = run_config(["show"], work_dir, env)
    bash_proc = run_bash_config(["show"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# get.
# --------------------------------------------------------------------------
def test_get_missing_key_exits_1(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["get"], work_dir, env)

    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: usage: shctx config get <key> [default]"


def test_get_unset_key_prints_empty_line(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["get", "nope"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "\n"


def test_get_unset_key_prints_supplied_default(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["get", "nope", "fallback"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "fallback\n"


def test_get_project_config_value(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "spawn", {"max_parallel": "6"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "6\n"


def test_get_local_overrides_project(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "spawn", {"max_parallel": "6"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": "2"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "2\n"


def test_get_project_overrides_xdg(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "spawn", {"max_parallel": "6"})
    _write_toml(xdg_dir / "shepherd.toml", "spawn", {"max_parallel": "9"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "6\n"


def test_get_xdg_used_when_no_local_or_project(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(xdg_dir / "shepherd.toml", "spawn", {"max_parallel": "9"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "9\n"


def test_get_empty_value_falls_through_to_next_file(work_dir: Path, xdg_dir: Path) -> None:
    """An empty-string value in a higher-precedence file is treated as unset."""
    _write_toml(work_dir / ".claude" / "shepherd.toml", "spawn", {"max_parallel": "6"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": ""})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "6\n"


def test_get_strips_inline_comment_and_quotes(work_dir: Path, xdg_dir: Path) -> None:
    toml_path = work_dir / ".claude" / "shepherd.toml"
    toml_path.parent.mkdir(parents=True)
    toml_path.write_text('[spawn]\ndashboard_cadence = "3m"  # default interval\n')
    env = _config_env(xdg_dir)
    proc = run_config(["get", "dashboard_cadence"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "3m\n"


def test_get_bash_parity_missing_key(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    python_proc = run_config(["get"], work_dir, env)
    bash_proc = run_bash_config(["get"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


def test_get_bash_parity_with_precedence_chain(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", "spawn", {"max_parallel": "6", "dashboard_cadence": "3m"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": "2"})
    _write_toml(xdg_dir / "shepherd.toml", "spawn", {"lead_effort": "ultracode"})
    env = _config_env(xdg_dir)

    for key in ("max_parallel", "dashboard_cadence", "lead_effort", "unset_key"):
        python_proc = run_config(["get", key, "DEF"], work_dir, env)
        bash_proc = run_bash_config(["get", key, "DEF"], work_dir, env)
        assert python_proc.returncode == bash_proc.returncode == 0
        assert python_proc.stdout == bash_proc.stdout, key


# --------------------------------------------------------------------------
# init.
# --------------------------------------------------------------------------
def test_init_happy_path_creates_scaffold(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["init"], work_dir, env)

    dst = work_dir / ".claude" / "shepherd.toml"
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        f"shctx config: scaffolded {dst}\n"
        "  name=work  language=rust  namespace=.shepherd\n"
        '  gates: check="cargo check --workspace" lint="cargo clippy --workspace -- -D warnings" format="cargo fmt --all"\n'
        "  Review [branching] + [gates] before your first sprint.\n"
    )
    assert dst.is_file()
    with open(dst, "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["name"] == "work"
    assert parsed["project"]["language"] == "rust"
    assert parsed["gates"]["check"] == "cargo check --workspace"
    assert parsed["paths"]["plans"] == ".shepherd/docs/plans"


def test_init_idempotent_preserves_existing(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    dst = work_dir / ".claude" / "shepherd.toml"
    dst.parent.mkdir(parents=True)
    dst.write_text("# hand-edited\n[project]\nname = \"custom\"\n")
    before = dst.read_text()

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"shctx config: {dst} already exists (preserving)\n"
    assert dst.read_text() == before


def test_init_force_overwrites_existing(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    dst = work_dir / ".claude" / "shepherd.toml"
    dst.parent.mkdir(parents=True)
    dst.write_text("# hand-edited\n[project]\nname = \"custom\"\n")

    proc = run_config(["init", "--force"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    with open(dst, "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["name"] == "work"


def test_init_preserves_when_claude_local_toml_present(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    local = work_dir / ".claude" / "shepherd.local.toml"
    local.parent.mkdir(parents=True)
    local.write_text("[project]\nname = \"local-only\"\n")

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "a local-override config is present" in proc.stdout
    assert not (work_dir / ".claude" / "shepherd.toml").exists()


def test_init_preserves_when_top_level_local_toml_present(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    (work_dir / ".local.toml").write_text("[project]\nname = \"local-only\"\n")

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "a local-override config is present" in proc.stdout
    assert not (work_dir / ".claude" / "shepherd.toml").exists()


def test_init_derives_name_from_git_remote(work_dir: Path, xdg_dir: Path) -> None:
    _init_git_repo(work_dir, remote_url="git@github.com:acme/widget-factory.git")
    env = _config_env(xdg_dir)

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    dst = work_dir / ".claude" / "shepherd.toml"
    with open(dst, "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["name"] == "widget-factory"


@pytest.mark.parametrize(
    ("manifest", "expected_language", "expected_check"),
    [
        ("Cargo.toml", "rust", "cargo check --workspace"),
        ("go.mod", "go", "go build ./..."),
        ("pyproject.toml", "python", "pytest -q"),
        ("setup.py", "python", "pytest -q"),
        ("package.json", "typescript", "npm run build --if-present"),
    ],
)
def test_init_gate_detection_by_manifest(
    manifest: str, expected_language: str, expected_check: str, work_dir: Path, xdg_dir: Path
) -> None:
    (work_dir / manifest).write_text("")
    env = _config_env(xdg_dir)

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    with open(work_dir / ".claude" / "shepherd.toml", "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["language"] == expected_language
    assert parsed["gates"]["check"] == expected_check


def test_init_no_manifest_falls_back_to_rust(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    with open(work_dir / ".claude" / "shepherd.toml", "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["language"] == "rust"


def test_init_bash_parity_content(work_dir: Path, xdg_dir: Path, tmp_path: Path) -> None:
    """Same directory, sequential runs: bash first, then python, comparing
    the generated file content byte-for-byte (paths are identical since
    both tools scaffold into the SAME `work_dir`)."""
    _init_git_repo(work_dir, remote_url="https://example.com/org/parity-repo.git")
    env = _config_env(xdg_dir)
    dst = work_dir / ".claude" / "shepherd.toml"

    bash_proc = run_bash_config(["init"], work_dir, env)
    assert bash_proc.returncode == 0, bash_proc.stderr
    bash_content = dst.read_text()
    dst.unlink()

    python_proc = run_config(["init"], work_dir, env)
    assert python_proc.returncode == 0, python_proc.stderr
    python_content = dst.read_text()

    assert python_content == bash_content
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# claude-md.
# --------------------------------------------------------------------------
def test_claude_md_creates_when_absent(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["claude-md"], work_dir, env)

    dst = work_dir / "CLAUDE.md"
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"shctx config: wrote {dst} (shepherd operating doctrine)\n"
    assert dst.read_text() == BUNDLED_CLAUDE_MD.read_text()


def test_claude_md_appends_when_no_managed_block(work_dir: Path, xdg_dir: Path) -> None:
    dst = work_dir / "CLAUDE.md"
    dst.write_text("# My Project\n\nSome operator notes.\n")
    original = dst.read_text()
    env = _config_env(xdg_dir)

    proc = run_config(["claude-md"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        f"shctx config: appended the shepherd operating doctrine block to {dst} "
        "(operator content preserved)\n"
    )
    new_content = dst.read_text()
    assert new_content.startswith(original)
    assert new_content == original + "\n" + BUNDLED_CLAUDE_MD.read_text()


def test_claude_md_preserves_when_block_present_no_force(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    run_config(["claude-md"], work_dir, env)  # seed the managed block
    dst = work_dir / "CLAUDE.md"
    before = dst.read_text()

    proc = run_config(["claude-md"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "already carries the shepherd doctrine block" in proc.stdout
    assert "--force to re-sync" in proc.stdout
    assert dst.read_text() == before


def test_claude_md_force_resyncs_preserves_operator_content(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    dst = work_dir / "CLAUDE.md"
    dst.write_text("# Operator preamble\n\nDo not remove this.\n\n")
    run_config(["claude-md"], work_dir, env)

    # Hand-edit inside the block to prove --force actually rewrites it.
    content = dst.read_text()
    mutated = content.replace("How to work", "How to work (STALE COPY)")
    dst.write_text(mutated)

    proc = run_config(["claude-md", "--force"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    final = dst.read_text()
    assert "Operator preamble" in final
    assert "Do not remove this." in final
    assert "STALE COPY" not in final
    assert "How to work" in final


def test_claude_md_begin_without_end_refuses_and_leaves_file_untouched(work_dir: Path, xdg_dir: Path) -> None:
    dst = work_dir / "CLAUDE.md"
    dst.write_text("# Ops\n\n<!-- BEGIN shepherd:operating-doctrine (managed block) -->\nno end marker here\n")
    before = dst.read_text()
    env = _config_env(xdg_dir)

    proc = run_config(["claude-md", "--force"], work_dir, env)

    assert proc.returncode == 1
    assert "refusing to re-sync" in proc.stderr
    assert dst.read_text() == before


def test_claude_md_bash_parity_fresh(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    python_proc = run_config(["claude-md"], work_dir, env)

    dst = work_dir / "CLAUDE.md"
    python_content = dst.read_text()
    dst.unlink()

    bash_proc = run_bash_config(["claude-md"], work_dir, env)
    bash_content = dst.read_text()

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_content == bash_content


def test_claude_md_bash_parity_preserve_message(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    run_config(["claude-md"], work_dir, env)

    python_proc = run_config(["claude-md"], work_dir, env)
    bash_proc = run_bash_config(["claude-md"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
