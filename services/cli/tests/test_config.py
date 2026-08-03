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

v6.4.2 PRECEDENCE CONTRACT — what this file additionally covers
===================================================================
`config.py` moved from a 3-tier chain (`.claude/shepherd.local.toml` ->
`.claude/shepherd.toml` -> `$XDG_CONFIG_HOME/shepherd.toml`) to a 5-tier one
that adds two NEW tiers ahead of it, resolved through the project's active
namespace (`.shepherd/` by default, `.artifacts/` for a legacy project) rather
than a hardcoded `.shepherd`:

    1. <workdir>/shepherd.local.toml   NEW
    2. <workdir>/shepherd.toml         NEW canonical (write target)
    3. .claude/shepherd.local.toml     unchanged
    4. .claude/shepherd.toml           unchanged
    5. $XDG_CONFIG_HOME/shepherd.toml  unchanged

The `test_get_*`/`test_path_*`/`test_show_*` groups below are extended (not
just amended) to prove: tiers 1-2 win over 3-5; tiers 3-5 keep working
FOREVER — a project with only `.claude/shepherd.toml` sees ZERO behavior
change (the explicit, loud backward-compat guarantee); the legacy
`.artifacts/` namespace resolves tiers 1-2 correctly, never a hardcoded
`.shepherd` path; and `is_shepherd_project()` reflects either canonical
location. Several `*_bash_parity` tests below now compare against a NEWER
`cmd_config.sh` contract than the one checked into this branch at any given
moment — `skills/context/scripts/cmd_config.sh`/`_lib.sh` are being ported to
the SAME 5-tier contract in a concurrent, separately-landed change; once both
land these tests hold, and until then a `path`/`init`/`show`-no-config parity
failure here reflects that landing order, not a defect in either side (see
each such test's docstring for exactly which ones are affected).
"""

from __future__ import annotations

import json
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


def _canonical_dst(work_dir: Path) -> Path:
    """Tier 2: `<work_dir>/.shepherd/shepherd.toml` — the DEFAULT active namespace.

    Valid whenever the test hasn't set up a `.artifacts/` namespace itself
    (a bare `work_dir` with neither `.shepherd/` nor `.artifacts/` on disk
    resolves to `.shepherd/` — `resolve_workdir()`'s final fallback).
    """
    return work_dir / ".shepherd" / "shepherd.toml"


def _legacy_dst(work_dir: Path) -> Path:
    """Tier 4: `<work_dir>/.claude/shepherd.toml` — the pre-v6.4.2 canonical location."""
    return work_dir / ".claude" / "shepherd.toml"


def _is_shepherd_project(work_dir: Path, env: dict[str, str]) -> bool:
    """Call `shepherd_cli.commands.config.is_shepherd_project()` in a fresh subprocess.

    Mirrors `conftest.resolve_fields`'s "never import shepherd_cli into the
    pytest process" convention, scoped to this one function since it lives
    outside `shepherd_cli.resolution`.
    """
    code = (
        "import json\n"
        "from shepherd_cli.commands.config import is_shepherd_project\n"
        "print(json.dumps(is_shepherd_project()))\n"
    )
    proc = subprocess.run([PY, "-c", code], cwd=str(work_dir), env=env, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"is_shepherd_project() snippet failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


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


def test_help_lists_the_v642_python_only_additions(work_dir: Path, xdg_dir: Path) -> None:
    """`migrate`/`validate` (no bash counterpart) are still documented in `help`."""
    env = _config_env(xdg_dir)
    proc = run_config(["help"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "shctx config migrate [--dry-run]" in proc.stdout
    assert "shctx config validate [--json]" in proc.stdout


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
def test_path_prints_new_canonical_location_regardless_of_existence(work_dir: Path, xdg_dir: Path) -> None:
    """v6.4.2: `path` now echoes `<workdir>/shepherd.toml` (tier 2), not `.claude/shepherd.toml`."""
    env = _config_env(xdg_dir)
    proc = run_config(["path"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{_canonical_dst(work_dir)}\n"


def test_path_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    """Holds once `cmd_config.sh`'s concurrent v6.4.2 port lands (see module docstring)."""
    env = _config_env(xdg_dir)
    python_proc = run_config(["path"], work_dir, env)
    bash_proc = run_bash_config(["path"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_path_uses_active_artifacts_namespace_when_present(work_dir: Path, xdg_dir: Path) -> None:
    """Tier 2 resolves through `resolve_workdir()` — never a hardcoded `.shepherd`.

    A project that pre-existing `.artifacts/` (the legacy namespace, e.g.
    `shctx init --artifacts`) gets tier 2 at `.artifacts/shepherd.toml`.
    """
    (work_dir / ".artifacts").mkdir()
    env = _config_env(xdg_dir)
    proc = run_config(["path"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{work_dir / '.artifacts' / 'shepherd.toml'}\n"


def test_path_respects_shepherd_workdir_env_override(work_dir: Path, xdg_dir: Path) -> None:
    """`$SHEPHERD_WORKDIR` (public, first-class) still wins ahead of namespace auto-detect."""
    env = _config_env(xdg_dir)
    env["SHEPHERD_WORKDIR"] = "custom-ns"
    proc = run_config(["path"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{work_dir / 'custom-ns' / 'shepherd.toml'}\n"


# --------------------------------------------------------------------------
# show.
# --------------------------------------------------------------------------
def test_show_no_config_prints_notice_naming_new_canonical_target(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"(no {_canonical_dst(work_dir)} — run 'shctx config init')\n"


def test_show_only_project_config_backward_compat_claude_only(work_dir: Path, xdg_dir: Path) -> None:
    """BACKWARD-COMPAT GUARANTEE: a project with ONLY `.claude/shepherd.toml` (no
    `.shepherd/` tier at all) sees `show` behave EXACTLY as it did pre-v6.4.2 —
    same path, same content, same framing. Zero behavior change."""
    _write_toml(_legacy_dst(work_dir), "project", {"name": "demo"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"# {_legacy_dst(work_dir)}\n[project]\nname = \"demo\"\n\n"


def test_show_local_and_project_both_shown_local_first(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(_legacy_dst(work_dir), "project", {"name": "proj"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "project", {"name": "local"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    local_path = work_dir / ".claude" / "shepherd.local.toml"
    project_path = _legacy_dst(work_dir)
    local_idx = proc.stdout.index(f"# {local_path}")
    project_idx = proc.stdout.index(f"# {project_path}")
    assert local_idx < project_idx


def test_show_includes_all_four_non_xdg_tiers_new_beats_legacy(work_dir: Path, xdg_dir: Path) -> None:
    """v6.4.2: `show` now walks all 4 non-XDG tiers, new (`.shepherd/`) before legacy (`.claude/`)."""
    _write_toml(_canonical_dst(work_dir), "project", {"name": "new-canonical"})
    _write_toml(_legacy_dst(work_dir), "project", {"name": "legacy"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    new_idx = proc.stdout.index(f"# {_canonical_dst(work_dir)}")
    legacy_idx = proc.stdout.index(f"# {_legacy_dst(work_dir)}")
    assert new_idx < legacy_idx


def test_show_never_reads_xdg_global(work_dir: Path, xdg_dir: Path) -> None:
    """`show` checks only the 4 non-XDG tiers — never tier 5 (XDG)."""
    _write_toml(xdg_dir / "shepherd.toml", "project", {"name": "global"})
    env = _config_env(xdg_dir)
    proc = run_config(["show"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"(no {_canonical_dst(work_dir)} — run 'shctx config init')\n"


def test_show_no_config_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    """Diverges from bash until its concurrent v6.4.2 port lands — see module docstring
    (the "no config" message now names the new canonical target)."""
    env = _config_env(xdg_dir)
    python_proc = run_config(["show"], work_dir, env)
    bash_proc = run_bash_config(["show"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_show_bash_parity_with_both_files(work_dir: Path, xdg_dir: Path) -> None:
    """Only tiers 3-4 (`.claude/`) are populated here, which bash's unmodified `show`
    already understands byte-for-byte — this scenario holds regardless of the
    concurrent bash port's landing order, unlike the no-config case above."""
    _write_toml(_legacy_dst(work_dir), "project", {"name": "proj"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "project", {"name": "local"})
    env = _config_env(xdg_dir)
    python_proc = run_config(["show"], work_dir, env)
    bash_proc = run_bash_config(["show"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


# --------------------------------------------------------------------------
# get — precedence.
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


def test_get_project_config_value_backward_compat_claude_only(work_dir: Path, xdg_dir: Path) -> None:
    """BACKWARD-COMPAT GUARANTEE (loud, explicit): a project with ONLY
    `.claude/shepherd.toml` — no `.shepherd/` tier anywhere — resolves exactly as
    it did pre-v6.4.2. Nothing about `get`'s behavior changes for it."""
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "6\n"


def test_get_local_overrides_project_backward_compat_claude_only(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": "2"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "2\n"


def test_get_project_overrides_xdg_backward_compat_claude_only(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6"})
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
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": ""})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "6\n"


def test_get_strips_inline_comment_and_quotes(work_dir: Path, xdg_dir: Path) -> None:
    toml_path = _legacy_dst(work_dir)
    toml_path.parent.mkdir(parents=True)
    toml_path.write_text('[spawn]\ndashboard_cadence = "3m"  # default interval\n')
    env = _config_env(xdg_dir)
    proc = run_config(["get", "dashboard_cadence"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "3m\n"


def test_get_workdir_local_beats_everything(work_dir: Path, xdg_dir: Path) -> None:
    """Tier 1 (`<workdir>/shepherd.local.toml`) outranks all 4 lower tiers."""
    _write_toml(_canonical_dst(work_dir), "spawn", {"max_parallel": "3"})
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": "2"})
    _write_toml(xdg_dir / "shepherd.toml", "spawn", {"max_parallel": "9"})
    _write_toml(work_dir / ".shepherd" / "shepherd.local.toml", "spawn", {"max_parallel": "1"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "1\n"


def test_get_workdir_project_beats_claude_tiers(work_dir: Path, xdg_dir: Path) -> None:
    """Tier 2 (`<workdir>/shepherd.toml`) outranks tiers 3-5 — `.shepherd/` beats `.claude/`."""
    _write_toml(_canonical_dst(work_dir), "spawn", {"max_parallel": "3"})
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "3\n"


def test_get_precedence_across_all_five_tiers(work_dir: Path, xdg_dir: Path) -> None:
    """Each of the 5 tiers sets a DISTINCT key; `get` resolves each to its own
    tier's value, proving the full chain — not just adjacent pairs — is wired
    in the right order end to end."""
    _write_toml(work_dir / ".shepherd" / "shepherd.local.toml", "spawn", {"tier1_only": "one"})
    _write_toml(_canonical_dst(work_dir), "spawn", {"tier2_only": "two"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"tier3_only": "three"})
    _write_toml(_legacy_dst(work_dir), "spawn", {"tier4_only": "four"})
    _write_toml(xdg_dir / "shepherd.toml", "spawn", {"tier5_only": "five"})
    env = _config_env(xdg_dir)

    for key, expected in (
        ("tier1_only", "one"),
        ("tier2_only", "two"),
        ("tier3_only", "three"),
        ("tier4_only", "four"),
        ("tier5_only", "five"),
        ("unset_anywhere", "DEF"),
    ):
        proc = run_config(["get", key, "DEF"], work_dir, env)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == f"{expected}\n", key


def test_get_legacy_artifacts_namespace_resolves_tiers_1_and_2(work_dir: Path, xdg_dir: Path) -> None:
    """A project using the legacy `.artifacts/` namespace (and NO `.shepherd/`
    directory at all — the split-brain-free case) gets tiers 1-2 at
    `.artifacts/shepherd{.local,}.toml` via `resolve_workdir()`'s real
    auto-detect, never a hardcoded `.shepherd/` path that would silently miss
    it. (Once BOTH `.shepherd/` and `.artifacts/` exist on disk,
    `resolve_workdir()`'s own documented split-brain precedence takes over and
    prefers `.shepherd/` — that is `resolve_workdir()`'s contract, exercised
    in `test_resolution.py`, not something this module re-decides.)"""
    (work_dir / ".artifacts").mkdir()
    _write_toml(work_dir / ".artifacts" / "shepherd.toml", "spawn", {"max_parallel": "4"})
    env = _config_env(xdg_dir)
    proc = run_config(["get", "max_parallel"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "4\n"

    _write_toml(work_dir / ".artifacts" / "shepherd.local.toml", "spawn", {"max_parallel": "1"})
    proc = run_config(["get", "max_parallel"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "1\n"


def test_get_bash_parity_missing_key(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    python_proc = run_config(["get"], work_dir, env)
    bash_proc = run_bash_config(["get"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 1
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


def test_get_bash_parity_with_precedence_chain(work_dir: Path, xdg_dir: Path) -> None:
    """Only tiers 3-5 populated here — the pre-v6.4.2 chain bash already understands
    — so this holds regardless of the concurrent bash port's landing order."""
    _write_toml(_legacy_dst(work_dir), "spawn", {"max_parallel": "6", "dashboard_cadence": "3m"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", "spawn", {"max_parallel": "2"})
    _write_toml(xdg_dir / "shepherd.toml", "spawn", {"lead_effort": "ultracode"})
    env = _config_env(xdg_dir)

    for key in ("max_parallel", "dashboard_cadence", "lead_effort", "unset_key"):
        python_proc = run_config(["get", key, "DEF"], work_dir, env)
        bash_proc = run_bash_config(["get", key, "DEF"], work_dir, env)
        assert python_proc.returncode == bash_proc.returncode == 0
        assert python_proc.stdout == bash_proc.stdout, key


# --------------------------------------------------------------------------
# is_shepherd_project().
# --------------------------------------------------------------------------
def test_is_shepherd_project_false_when_neither_location_exists(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    assert _is_shepherd_project(work_dir, env) is False


def test_is_shepherd_project_true_via_new_canonical_location(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(_canonical_dst(work_dir), "project", {"name": "x"})
    env = _config_env(xdg_dir)
    assert _is_shepherd_project(work_dir, env) is True


def test_is_shepherd_project_true_via_legacy_location_backward_compat(work_dir: Path, xdg_dir: Path) -> None:
    """BACKWARD-COMPAT GUARANTEE: an un-migrated project (`.claude/shepherd.toml`
    only) still reads as a shepherd project."""
    _write_toml(_legacy_dst(work_dir), "project", {"name": "x"})
    env = _config_env(xdg_dir)
    assert _is_shepherd_project(work_dir, env) is True


def test_is_shepherd_project_ignores_local_override_only(work_dir: Path, xdg_dir: Path) -> None:
    """A `.local.toml` alone (tier 1/3), with no canonical file at tier 2/4, does
    NOT count — `is_shepherd_project` checks the canonical locations, not every
    tier `cfg_get` reads."""
    _write_toml(work_dir / ".shepherd" / "shepherd.local.toml", "project", {"name": "x"})
    env = _config_env(xdg_dir)
    assert _is_shepherd_project(work_dir, env) is False


# --------------------------------------------------------------------------
# init.
# --------------------------------------------------------------------------
def test_init_happy_path_creates_scaffold_at_new_canonical_location(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["init"], work_dir, env)

    dst = _canonical_dst(work_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        f"shctx config: scaffolded {dst}\n"
        "  name=work  language=rust  namespace=.shepherd\n"
        '  gates: check="cargo check --workspace" lint="cargo clippy --workspace -- -D warnings" format="cargo fmt --all"\n'
        "  Review [branching] + [gates] before your first sprint.\n"
    )
    assert dst.is_file()
    assert not _legacy_dst(work_dir).exists()
    with open(dst, "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["name"] == "work"
    assert parsed["project"]["language"] == "rust"
    assert parsed["gates"]["check"] == "cargo check --workspace"
    assert parsed["paths"]["plans"] == ".shepherd/docs/plans"


def test_init_idempotent_preserves_existing(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    dst = _canonical_dst(work_dir)
    dst.parent.mkdir(parents=True)
    dst.write_text("# hand-edited\n[project]\nname = \"custom\"\n")
    before = dst.read_text()

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"shctx config: {dst} already exists (preserving)\n"
    assert dst.read_text() == before


def test_init_force_overwrites_existing(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    dst = _canonical_dst(work_dir)
    dst.parent.mkdir(parents=True)
    dst.write_text("# hand-edited\n[project]\nname = \"custom\"\n")

    proc = run_config(["init", "--force"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    with open(dst, "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["name"] == "work"


def test_init_preserves_when_legacy_claude_shepherd_toml_present(work_dir: Path, xdg_dir: Path) -> None:
    """NEW v6.4.2 guard: an un-migrated project (`.claude/shepherd.toml` only, no
    `<workdir>/shepherd.toml` yet) preserves rather than silently scaffolding a
    SECOND, shadowing binding at the new canonical location — the operator is
    pointed at `shctx config migrate` instead."""
    legacy = _legacy_dst(work_dir)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[project]\nname = \"legacy\"\n")

    proc = run_config(["init"], work_dir, env=_config_env(xdg_dir))

    assert proc.returncode == 0, proc.stderr
    assert str(legacy) in proc.stdout
    assert "shctx config migrate" in proc.stdout
    assert not _canonical_dst(work_dir).exists()


def test_init_preserves_when_workdir_local_toml_present(work_dir: Path, xdg_dir: Path) -> None:
    """NEW v6.4.2 guard: a tier-1 local override (`<workdir>/shepherd.local.toml`)
    also counts as "a local-override config is present"."""
    local = work_dir / ".shepherd" / "shepherd.local.toml"
    local.parent.mkdir(parents=True)
    local.write_text("[project]\nname = \"local-only\"\n")

    proc = run_config(["init"], work_dir, env=_config_env(xdg_dir))

    assert proc.returncode == 0, proc.stderr
    assert "a local-override config is present" in proc.stdout
    assert not _canonical_dst(work_dir).exists()


def test_init_preserves_when_claude_local_toml_present(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    local = work_dir / ".claude" / "shepherd.local.toml"
    local.parent.mkdir(parents=True)
    local.write_text("[project]\nname = \"local-only\"\n")

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "a local-override config is present" in proc.stdout
    assert not _canonical_dst(work_dir).exists()


def test_init_preserves_when_top_level_local_toml_present(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    (work_dir / ".local.toml").write_text("[project]\nname = \"local-only\"\n")

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "a local-override config is present" in proc.stdout
    assert not _canonical_dst(work_dir).exists()


def test_init_derives_name_from_git_remote(work_dir: Path, xdg_dir: Path) -> None:
    _init_git_repo(work_dir, remote_url="git@github.com:acme/widget-factory.git")
    env = _config_env(xdg_dir)

    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    with open(_canonical_dst(work_dir), "rb") as fh:
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
    with open(_canonical_dst(work_dir), "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["language"] == expected_language
    assert parsed["gates"]["check"] == expected_check


def test_init_no_manifest_falls_back_to_rust(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["init"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    with open(_canonical_dst(work_dir), "rb") as fh:
        parsed = tomllib.load(fh)
    assert parsed["project"]["language"] == "rust"


def test_init_content_matches_bash_derivation(work_dir: Path, xdg_dir: Path) -> None:
    """Full bash-vs-python parity for ``config init`` under the v6.4.2 contract.

    Both implementations now scaffold to the SAME canonical destination
    (``<workdir>/shepherd.toml`` — precedence tier 2), so this asserts full
    stdout equality AND byte-identical file content, which is strictly
    stronger than the content-only comparison this test ran while
    ``cmd_config.sh``'s port was still in flight. Full-stdout equality is
    what catches the two sides naming different destination paths, which is
    exactly the drift the parity suite exists to prevent.
    """
    _init_git_repo(work_dir, remote_url="https://example.com/org/parity-repo.git")
    env = _config_env(xdg_dir)

    bash_proc = run_bash_config(["init"], work_dir, env)
    assert bash_proc.returncode == 0, bash_proc.stderr
    bash_content = _canonical_dst(work_dir).read_text()
    _canonical_dst(work_dir).unlink()

    python_proc = run_config(["init"], work_dir, env)
    assert python_proc.returncode == 0, python_proc.stderr
    python_content = _canonical_dst(work_dir).read_text()

    assert python_content == bash_content
    assert python_proc.stdout == bash_proc.stdout

    derived_line = "  name=parity-repo  language=rust  namespace=.shepherd"
    assert derived_line in bash_proc.stdout


# --------------------------------------------------------------------------
# migrate (v6.4.2, Python-only — no bash counterpart).
# --------------------------------------------------------------------------
def test_migrate_nothing_to_migrate_when_no_legacy_file(work_dir: Path, xdg_dir: Path) -> None:
    env = _config_env(xdg_dir)
    proc = run_config(["migrate"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "nothing to migrate" in proc.stdout
    assert str(_legacy_dst(work_dir)) in proc.stdout


def test_migrate_moves_legacy_file_to_canonical_location(work_dir: Path, xdg_dir: Path) -> None:
    legacy = _legacy_dst(work_dir)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[project]\nname = \"legacy\"\n")
    env = _config_env(xdg_dir)

    proc = run_config(["migrate"], work_dir, env)

    dst = _canonical_dst(work_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"shctx config migrate: moved {legacy} -> {dst}\n"
    assert not legacy.exists()
    assert dst.is_file()
    assert dst.read_text() == "[project]\nname = \"legacy\"\n"


def test_migrate_is_idempotent(work_dir: Path, xdg_dir: Path) -> None:
    legacy = _legacy_dst(work_dir)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[project]\nname = \"legacy\"\n")
    env = _config_env(xdg_dir)

    first = run_config(["migrate"], work_dir, env)
    assert first.returncode == 0, first.stderr

    second = run_config(["migrate"], work_dir, env)
    assert second.returncode == 0, second.stderr
    assert "nothing to migrate" in second.stdout
    # The first migration's result is untouched by the second, no-op run.
    assert _canonical_dst(work_dir).read_text() == "[project]\nname = \"legacy\"\n"


def test_migrate_never_clobbers_existing_destination(work_dir: Path, xdg_dir: Path) -> None:
    legacy = _legacy_dst(work_dir)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[project]\nname = \"legacy\"\n")
    dst = _canonical_dst(work_dir)
    dst.parent.mkdir(parents=True)
    dst.write_text("[project]\nname = \"already-here\"\n")
    env = _config_env(xdg_dir)

    proc = run_config(["migrate"], work_dir, env)

    assert proc.returncode == 1
    assert "already exists" in proc.stdout
    assert "refusing to overwrite" in proc.stdout
    # Neither file is touched — the conflict is reported, not resolved.
    assert legacy.read_text() == "[project]\nname = \"legacy\"\n"
    assert dst.read_text() == "[project]\nname = \"already-here\"\n"


def test_migrate_dry_run_prints_plan_without_moving(work_dir: Path, xdg_dir: Path) -> None:
    legacy = _legacy_dst(work_dir)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[project]\nname = \"legacy\"\n")
    env = _config_env(xdg_dir)

    proc = run_config(["migrate", "--dry-run"], work_dir, env)

    dst = _canonical_dst(work_dir)
    assert proc.returncode == 0, proc.stderr
    assert "dry run, nothing written" in proc.stdout
    assert str(legacy) in proc.stdout
    assert str(dst) in proc.stdout
    assert legacy.is_file()
    assert not dst.exists()


def test_migrate_dry_run_flag_is_positional_only(work_dir: Path, xdg_dir: Path) -> None:
    """Matches `init`/`claude-md`'s literal-first-token `--force` check (module
    docstring, deviation #3 pattern): a `--dry-run` token anywhere BUT first is
    silently ignored, same as bash's own single-token check."""
    legacy = _legacy_dst(work_dir)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[project]\nname = \"legacy\"\n")
    env = _config_env(xdg_dir)

    proc = run_config(["migrate", "foo", "--dry-run"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert "moved" in proc.stdout
    assert not legacy.exists()


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


# --------------------------------------------------------------------------
# v6.4.2 layering contract (operator directive, 2026-08-03)
# --------------------------------------------------------------------------
# Three layers -- project / legacy / user -- with `local` > `<harness>` > base
# WITHIN each, and project > user ACROSS them. `~/.shepherd` holds defaults; a
# project overrides them simply by setting the key; `<workdir>/
# shepherd.local.toml` is the ultimate override.


def _layered_env(xdg_dir: Path, user_home: Path, *, harness: str = "claude") -> dict[str, str]:
    """A `_config_env` with the user tier and harness pinned explicitly."""
    env = _config_env(xdg_dir)
    env["SHEPHERD_HOME"] = str(user_home)
    env["SHEPHERD_HARNESS"] = harness
    return env


def _write_parallel(path: Path, value: int) -> None:
    """Write a minimal config setting `[spawn].max_parallel` to `value`.

    Distinct from this module's `_write_parallel(path, table, entries)` helper
    above -- same file, different signature, so it must not shadow it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[spawn]\nmax_parallel = {value}\n")


def test_layering_each_tier_overrides_the_one_below(
    work_dir: Path, xdg_dir: Path, tmp_path: Path
) -> None:
    """Adding each higher tier in turn moves the resolved value monotonically.

    This is the whole contract in one test: six writes, six reads, each one
    strictly overriding the last, from the user base default up to the
    project-local ultimate override.
    """
    user_home = tmp_path / "userhome"
    env = _layered_env(xdg_dir, user_home)
    ns = work_dir / ".shepherd"
    ns.mkdir(parents=True, exist_ok=True)

    steps = [
        (user_home / "shepherd.toml", 1),
        (user_home / "shepherd.claude.toml", 2),
        (user_home / "shepherd.local.toml", 3),
        (ns / "shepherd.toml", 4),
        (ns / "shepherd.claude.toml", 5),
        (ns / "shepherd.local.toml", 6),
    ]
    for path, value in steps:
        _write_parallel(path, value)
        proc = run_config(["get", "max_parallel", "0"], work_dir, env)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == str(value), (
            f"after writing {path.name} in {path.parent.name}, expected {value}"
        )


def test_layering_user_tier_is_the_cross_project_default(
    work_dir: Path, xdg_dir: Path, tmp_path: Path
) -> None:
    """A project with NO config of its own inherits `~/.shepherd` defaults."""
    user_home = tmp_path / "userhome"
    env = _layered_env(xdg_dir, user_home)
    _write_parallel(user_home / "shepherd.toml", 11)

    proc = run_config(["get", "max_parallel", "0"], work_dir, env)
    assert proc.stdout.strip() == "11"


def test_layering_legacy_claude_project_outranks_user_tier(
    work_dir: Path, xdg_dir: Path, tmp_path: Path
) -> None:
    """A legacy `.claude/` PROJECT binding beats the whole user layer.

    The deliberate ordering call: `.claude/shepherd.toml` is a project-level
    file, so it outranks `~/.shepherd/*`. Ordering the user layer higher
    would mean that merely creating `~/.shepherd/shepherd.toml` silently
    overrode every existing project still bound through `.claude/` -- a
    regression for every current install. Pinned so it cannot drift.
    """
    user_home = tmp_path / "userhome"
    env = _layered_env(xdg_dir, user_home)
    _write_parallel(user_home / "shepherd.local.toml", 21)  # highest USER tier
    _write_parallel(work_dir / ".claude" / "shepherd.toml", 22)  # lowest PROJECT tier

    proc = run_config(["get", "max_parallel", "0"], work_dir, env)
    assert proc.stdout.strip() == "22"


def test_layering_only_the_active_harness_file_is_read(
    work_dir: Path, xdg_dir: Path, tmp_path: Path
) -> None:
    """A codex knob must not take effect under claude, and vice versa."""
    user_home = tmp_path / "userhome"
    ns = work_dir / ".shepherd"
    _write_parallel(ns / "shepherd.toml", 30)
    _write_parallel(ns / "shepherd.codex.toml", 31)

    under_claude = run_config(
        ["get", "max_parallel", "0"], work_dir, _layered_env(xdg_dir, user_home, harness="claude")
    )
    assert under_claude.stdout.strip() == "30", "codex knob leaked into a claude session"

    under_codex = run_config(
        ["get", "max_parallel", "0"], work_dir, _layered_env(xdg_dir, user_home, harness="codex")
    )
    assert under_codex.stdout.strip() == "31"


def test_layering_no_harness_detected_omits_the_harness_tier(
    work_dir: Path, xdg_dir: Path, tmp_path: Path
) -> None:
    """With no harness, the harness tier is absent -- not guessed at."""
    user_home = tmp_path / "userhome"
    env = _layered_env(xdg_dir, user_home, harness="")
    for marker in ("SHEPHERD_HARNESS", "CLAUDE_PLUGIN_ROOT", "CLAUDECODE", "CODEX_HOME"):
        env.pop(marker, None)
    ns = work_dir / ".shepherd"
    _write_parallel(ns / "shepherd.toml", 40)
    _write_parallel(ns / "shepherd.claude.toml", 41)

    proc = run_config(["get", "max_parallel", "0"], work_dir, env)
    assert proc.stdout.strip() == "40"
