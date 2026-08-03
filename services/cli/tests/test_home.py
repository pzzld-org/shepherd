"""Tests for ``shepherd home`` — bootstrap/inspect the user-level tier (issue #254).

Bash parity target: NONE — ``home`` is a brand-new command group with no
bash predecessor (see ``shepherd_cli/commands/home.py``'s module docstring),
so there is no ``cmd_home.sh`` to diff against and no bash-parity usage text
to reproduce; it uses Typer/Click's own ``--help`` machinery.

INVOCATION NOTE (same shape as ``test_adapt.py``/``test_inject.py``):
``home`` is registered in ``shepherd_cli.app`` but ``shepherd_cli.
__main__``'s ``PORTED`` set (the ``${PY} -m shepherd_cli home ...`` gate)
is out of this lane's file list — adding a subcommand name there is the
orchestrator's cross-lane integration step, done once for every lane's new
command group at the same time. Every test here therefore drives the
module's own Typer app directly in a fresh subprocess (``${PY} -c
"...commands.home import app; app(...)"``), exactly like
``test_adapt.py``'s ``_ADAPT_SNIPPET`` — an invocation that works both
before AND after ``__main__.PORTED`` is updated, so these tests need no
edits when the integrator flips the sub-app on.

No database is involved anywhere in this module: ``shepherd home`` is
filesystem-only (``~/.shepherd/profiles/``, ``~/.shepherd/templates/``),
so tests need no fixture DB, only isolated ``SHEPHERD_HOME``/
``SHEPHERD_WORKDIR``/``CLAUDE_PLUGIN_ROOT`` env vars — mirroring
``test_render.py``'s isolation pattern (``_env`` there, ``_home_env``
here), NOT ``test_style.py``'s DB-backed fixtures.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

import pytest
from conftest import CLI_ROOT, PY, REPO_ROOT, clean_env_dict

# --------------------------------------------------------------------------
# Module-app invocation (see module docstring's INVOCATION NOTE).
# --------------------------------------------------------------------------
_HOME_SNIPPET = (
    "import sys\n"
    "from shepherd_cli.commands.home import app\n"
    "app(args=sys.argv[1:], prog_name='shepherd home')\n"
)

#: A style resolver snippet, run under the SAME env as `home which`, so
#: `test_which_resolved_tier_matches_real_resolver` can assert the two
#: never disagree — the regression test that keeps the chain from forking
#: (see `shepherd_cli/profiles.py`'s `style_chain`/`resolve_style_path`).
_RESOLVE_STYLE_SNIPPET = (
    "import sys\n"
    "from shepherd_cli import profiles\n"
    "hit = profiles.resolve_style_path(sys.argv[1], bundled_dir=profiles.bundled_styles_dir())\n"
    "print(hit[1] if hit else 'NONE')\n"
)


def run_home(args: Sequence[str], env: dict[str, str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run the ``home`` module app as a real subprocess (see module docstring)."""
    return subprocess.run(
        [PY, "-c", _HOME_SNIPPET, *args],
        env=env,
        cwd=str(cwd or CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


def resolve_style_source(profile: str, env: dict[str, str], *, cwd: Path | None = None) -> str:
    """The tier label `profiles.resolve_style_path` itself picks for `profile`, under `env`."""
    proc = subprocess.run(
        [PY, "-c", _RESOLVE_STYLE_SNIPPET, profile],
        env=env,
        cwd=str(cwd or CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _home_env(tmp_path: Path, *, home_dir: Path | None = None, workdir: Path | None = None) -> dict[str, str]:
    """A stripped env isolating `SHEPHERD_HOME`/`SHEPHERD_WORKDIR` into `tmp_path`.

    `CLAUDE_PLUGIN_ROOT` points at the real repo so `bundled_styles_dir()`/
    `BUNDLED_TEMPLATES_DIR` resolve against the real, checked-in bundled
    styles/templates — never written to, only read.
    """
    env = clean_env_dict()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["SHEPHERD_HOME"] = str(home_dir if home_dir is not None else tmp_path / "user-home")
    env["SHEPHERD_WORKDIR"] = str(workdir if workdir is not None else tmp_path / "project" / ".shepherd")
    return env


# --------------------------------------------------------------------------
# --help
# --------------------------------------------------------------------------
def test_help_exits_0_and_writes_nothing_to_stderr(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    proc = run_home(["--help"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "shepherd home" in proc.stdout
    assert "init" in proc.stdout
    assert "show" in proc.stdout
    assert "which" in proc.stdout


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------
def test_init_creates_both_dirs_under_tmp_home(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])
    assert not home.exists()

    proc = run_home(["init"], env)

    assert proc.returncode == 0, proc.stderr
    assert (home / "profiles").is_dir()
    assert (home / "templates").is_dir()
    assert str(home / "profiles") in proc.stdout
    assert str(home / "templates") in proc.stdout
    assert "created" in proc.stdout
    assert str(home) in proc.stdout  # the resolved home itself is always printed


def test_init_is_idempotent_second_run_creates_nothing(tmp_path: Path) -> None:
    env = _home_env(tmp_path)

    first = run_home(["init"], env)
    assert first.returncode == 0, first.stderr

    second = run_home(["init"], env)
    assert second.returncode == 0, second.stderr
    assert "already present" in second.stdout
    assert "created" not in second.stdout


def test_init_profile_seeds_from_bundled(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])

    proc = run_home(["init", "--profile", "rust"], env)

    assert proc.returncode == 0, proc.stderr
    seeded = home / "profiles" / "rust" / "style.md"
    assert seeded.is_file()
    assert seeded.read_text() == (REPO_ROOT / "skills" / "context" / "styles" / "rust.md").read_text()
    assert f"wrote {seeded}" in proc.stdout


def test_init_profile_never_overwrites_existing_user_style(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])
    seeded = home / "profiles" / "rust" / "style.md"
    seeded.parent.mkdir(parents=True)
    seeded.write_text("CUSTOM USER RUST STYLE — do not clobber\n")

    proc = run_home(["init", "--profile", "rust"], env)

    assert proc.returncode == 0, proc.stderr
    assert seeded.read_text() == "CUSTOM USER RUST STYLE — do not clobber\n"
    assert "already exists (preserving)" in proc.stdout
    assert "wrote" not in proc.stdout


def test_init_profile_with_no_bundled_default_reports_and_continues(tmp_path: Path) -> None:
    """A profile with no bundled source is reported (stderr) and skipped —
    non-fatal, so the other roots this invocation asked for still get made."""
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])

    proc = run_home(["init", "--profile", "no-such-language"], env)

    assert proc.returncode == 0, proc.stderr
    assert "no bundled style for no-such-language" in proc.stderr
    assert (home / "profiles").is_dir()
    assert (home / "templates").is_dir()
    assert not (home / "profiles" / "no-such-language").exists()


def test_init_multiple_profiles_repeatable_flag(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])

    proc = run_home(["init", "--profile", "rust", "--profile", "python"], env)

    assert proc.returncode == 0, proc.stderr
    assert (home / "profiles" / "rust" / "style.md").is_file()
    assert (home / "profiles" / "python" / "style.md").is_file()


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------
def test_show_on_nonexistent_home_exits_0_and_says_so(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])
    assert not home.exists()

    proc = run_home(["show"], env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert "not created" in proc.stdout
    assert str(home) in proc.stdout


def test_show_lists_profiles_and_templates_present(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    home = Path(env["SHEPHERD_HOME"])

    init_proc = run_home(["init", "--profile", "rust"], env)
    assert init_proc.returncode == 0, init_proc.stderr
    (home / "templates").mkdir(parents=True, exist_ok=True)
    (home / "templates" / "custom.md.j2").write_text("hi\n")

    proc = run_home(["show"], env)

    assert proc.returncode == 0, proc.stderr
    assert "status: present" in proc.stdout
    assert "profiles (1): rust" in proc.stdout
    assert "templates (1): custom.md.j2" in proc.stdout


def test_show_reports_none_when_home_present_but_empty(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    run_home(["init"], env)

    proc = run_home(["show"], env)

    assert proc.returncode == 0, proc.stderr
    assert "profiles: (none)" in proc.stdout
    assert "templates: (none)" in proc.stdout


# --------------------------------------------------------------------------
# which — style profile chain
# --------------------------------------------------------------------------
def test_which_prints_all_four_tiers_in_precedence_order(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    proc = run_home(["which", "rust"], env)

    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    labels = [line.split()[0] for line in lines]
    assert labels == ["project", "legacy", "user", "bundled"]


def test_which_marks_exactly_one_resolved_tier(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    proc = run_home(["which", "rust"], env)

    assert proc.returncode == 0, proc.stderr
    resolved_lines = [line for line in proc.stdout.splitlines() if "<- resolved" in line]
    assert len(resolved_lines) == 1
    # No project/legacy/user file exists in this isolated env -> bundled wins.
    assert resolved_lines[0].split()[0] == "bundled"


def test_which_resolved_tier_matches_real_resolver_bundled_case(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    proc = run_home(["which", "rust"], env)
    assert proc.returncode == 0, proc.stderr
    resolved_label = next(line.split()[0] for line in proc.stdout.splitlines() if "<- resolved" in line)

    assert resolve_style_source("rust", env) == resolved_label


def test_which_resolved_tier_matches_real_resolver_legacy_case(tmp_path: Path) -> None:
    """Same cross-check, but with the legacy tier populated so the winner
    is NOT the trivial bundled-default case."""
    env = _home_env(tmp_path)
    legacy = Path(env["SHEPHERD_WORKDIR"]) / "styles" / "rust.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("LEGACY RUST STYLE\n")

    proc = run_home(["which", "rust"], env)
    assert proc.returncode == 0, proc.stderr
    resolved_label = next(line.split()[0] for line in proc.stdout.splitlines() if "<- resolved" in line)

    assert resolved_label == "legacy"
    assert resolve_style_source("rust", env) == resolved_label


def test_which_resolved_tier_matches_real_resolver_user_case(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    user_style = Path(env["SHEPHERD_HOME"]) / "profiles" / "rust" / "style.md"
    user_style.parent.mkdir(parents=True)
    user_style.write_text("USER RUST STYLE\n")

    proc = run_home(["which", "rust"], env)
    assert proc.returncode == 0, proc.stderr
    resolved_label = next(line.split()[0] for line in proc.stdout.splitlines() if "<- resolved" in line)

    assert resolved_label == "user"
    assert resolve_style_source("rust", env) == resolved_label


def test_which_unknown_profile_still_shows_bundled_missing(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    proc = run_home(["which", "no-such-profile-at-all"], env)

    assert proc.returncode == 0, proc.stderr
    assert "<- resolved" not in proc.stdout
    assert proc.stdout.count("(missing)") == 4


# --------------------------------------------------------------------------
# which --template
# --------------------------------------------------------------------------
def test_which_template_prints_three_tiers_bundled_resolves_by_default(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    proc = run_home(["which", "handoff.md.j2", "--template"], env)

    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    labels = [line.split()[0] for line in lines]
    assert labels == ["project", "user", "bundled"]
    resolved_lines = [line for line in lines if "<- resolved" in line]
    assert len(resolved_lines) == 1
    assert resolved_lines[0].split()[0] == "bundled"


def test_which_template_user_override_wins_over_bundled(tmp_path: Path) -> None:
    env = _home_env(tmp_path)
    user_template = Path(env["SHEPHERD_HOME"]) / "templates" / "handoff.md.j2"
    user_template.parent.mkdir(parents=True)
    user_template.write_text("USER OVERRIDE\n")

    proc = run_home(["which", "handoff.md.j2", "--template"], env)

    assert proc.returncode == 0, proc.stderr
    resolved_lines = [line for line in proc.stdout.splitlines() if "<- resolved" in line]
    assert len(resolved_lines) == 1
    assert resolved_lines[0].split()[0] == "user"


@pytest.mark.parametrize("bare_name", ["handoff.md"])
def test_which_template_bare_stem_resolves_j2_suffix(bare_name: str, tmp_path: Path) -> None:
    """`home which <name> --template` mirrors `render_template`'s own bare-stem `.j2` fallback."""
    env = _home_env(tmp_path)
    proc = run_home(["which", bare_name, "--template"], env)

    assert proc.returncode == 0, proc.stderr
    resolved_lines = [line for line in proc.stdout.splitlines() if "<- resolved" in line]
    assert len(resolved_lines) == 1
    assert resolved_lines[0].endswith("handoff.md.j2  <- resolved") or "handoff.md.j2" in resolved_lines[0]
