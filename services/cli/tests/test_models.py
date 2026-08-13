"""Tests for `shepherd models` — native port of `cmd_models.sh` (pure config, no DB).

`shepherd models` never opens a database connection — the whole surface is
config-file resolution (`[models]` section of `shepherd.toml`, local ->
project -> XDG precedence) plus built-in defaults. Every test below drives
the real CLI as a subprocess with an ISOLATED `cwd` (a bare `tmp_path`
directory that is never inside a git repository, so
`shepherd_cli.resolution.resolve_repo_root()`'s `git rev-parse
--show-toplevel` fails and falls back to that same `cwd` — exactly mirroring
`_lib.sh`'s `shctx_repo_root() { git rev-parse --show-toplevel 2>/dev/null
|| pwd; }`) and an isolated `XDG_CONFIG_HOME`, so no test ever reads this
real repository's own `.claude/shepherd.toml` (which — being the shepherd
plugin dogfooding itself — DOES have a populated `[models]` block; without
this isolation every "default" assertion below would silently observe
`source=config` instead and the test would prove nothing).

Several tests additionally run the legacy `cmd_models.sh` directly, under
the identical `cwd`/env, asserting byte-for-byte stdout parity — the same
pattern `test_status.py` established for `shepherd status`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, clean_env_dict

CMD_MODELS_SH = REPO_ROOT / "skills" / "context" / "scripts" / "cmd_models.sh"

#: `cmd_models.sh`'s exact `MODELS_ROLES` order — both the `resolve` validity
#: check and the `show` row order iterate this sequence.
MODELS_ROLES = (
    "root",
    "planter",
    "engineer",
    "conductor",
    "critic",
    "discovery",
    "coder",
    "auditor",
    "worker",
)

_OPUS_ROLES = {"root", "planter", "engineer"}


def _default_model(role: str) -> str:
    return "opus[1m]" if role in _OPUS_ROLES else "sonnet"


# --------------------------------------------------------------------------
# Isolation fixtures + subprocess helpers.
# --------------------------------------------------------------------------
@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory to use as the CLI's `cwd`.

    Never inside a git repository (bare `tmp_path` subdirectories under
    pytest's tmp root have no ancestor `.git`), so `resolve_repo_root()`
    (and bash's `shctx_repo_root`) both fall back to this exact directory
    rather than climbing up into this real repository's own root.
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


def _models_env(xdg_dir: Path) -> dict[str, str]:
    """A stripped-then-rebuilt environment, isolated to `xdg_dir`.

    Args:
        xdg_dir: The directory `XDG_CONFIG_HOME` should point at — always
            set explicitly (even when empty) so a populated real
            `~/.config/shepherd.toml` on the host running this test suite
            can never leak into a "no config" assertion.

    Returns:
        An environment dict safe for both the Python CLI and the legacy
        bash script.
    """
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    return env


def run_models(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -m shepherd_cli models <args>` under `cwd`."""
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "models", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def run_bash_models(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the legacy `cmd_models.sh` directly under `cwd` (bash-parity twin)."""
    return subprocess.run(
        ["bash", str(CMD_MODELS_SH), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _write_toml(path: Path, table: dict[str, str]) -> None:
    """Write a minimal `[models]` TOML file at `path` (parents auto-created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[models]"]
    lines.extend(f'{key} = "{value}"' for key, value in table.items())
    path.write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# Defaults only (no config files anywhere) — happy path + ordering.
# --------------------------------------------------------------------------
def test_bare_invocation_all_defaults(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models([], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("shepherd model map (resolved)\n")
    for role in MODELS_ROLES:
        assert f"  {role:<10} {_default_model(role):<10} (default)" in proc.stdout
    assert "root is advisory" in proc.stdout


def test_bare_invocation_matches_show_no_flags(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    bare = run_models([], work_dir, env)
    show = run_models(["show"], work_dir, env)

    assert bare.returncode == show.returncode == 0
    assert bare.stdout == show.stdout


def test_show_row_order_matches_bash_loop_order(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["show"], work_dir, env)
    assert proc.returncode == 0, proc.stderr

    lines = proc.stdout.splitlines()
    role_lines = [line for line in lines if line.startswith("  ") and "(" in line]
    roles_in_output = [line.split()[0] for line in role_lines]
    assert roles_in_output == list(MODELS_ROLES)


def test_show_md_format(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["show", "--md"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("| role | model | source |\n|---|---|---|\n")
    assert "| root | `opus[1m]` | default |" in proc.stdout
    assert "| worker | `sonnet` | default |" in proc.stdout
    assert "_root is advisory" in proc.stdout


def test_show_json_format_shape_and_values(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["show", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert list(payload.keys()) == list(MODELS_ROLES)
    for role in MODELS_ROLES:
        assert payload[role] == {"model": _default_model(role), "source": "default"}


# --------------------------------------------------------------------------
# Config precedence: project -> local -> XDG, and empty-value skip-through.
# --------------------------------------------------------------------------
def test_project_config_overrides_default(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"worker": "haiku"})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "worker"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "haiku\n"

    # Untouched roles still fall to their built-in default.
    proc_root = run_models(["resolve", "root"], work_dir, env)
    assert proc_root.stdout == "opus[1m]\n"


def test_local_config_wins_over_project_config(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"worker": "project-slug"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", {"worker": "local-slug"})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "worker"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "local-slug\n"


def test_xdg_global_config_used_when_no_project_or_local(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(xdg_dir / "shepherd.toml", {"conductor": "opus-xdg"})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "conductor"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "opus-xdg\n"


def test_project_config_wins_over_xdg(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"critic": "project-slug"})
    _write_toml(xdg_dir / "shepherd.toml", {"critic": "xdg-slug"})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "critic"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "project-slug\n"


def test_empty_local_value_falls_through_to_project(work_dir: Path, xdg_dir: Path) -> None:
    """Bash parity: `cfg_section_get`'s `[[ -n "$v" ]] || continue` — an
    empty-string value in a higher-precedence file is treated as unset,
    not as an explicit override."""
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"worker": "project-slug"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", {"worker": ""})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "worker"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "project-slug\n"


def test_show_json_reports_config_source_for_overridden_role(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"auditor": "custom-auditor"})
    env = _models_env(xdg_dir)

    proc = run_models(["show", "--json"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["auditor"] == {"model": "custom-auditor", "source": "config"}
    assert payload["worker"] == {"model": "sonnet", "source": "default"}


def test_malformed_toml_does_not_crash_read(work_dir: Path, xdg_dir: Path) -> None:
    """ROBUSTNESS deviation from bash (documented): bash's `awk` line-scan
    never raises on malformed TOML — it just extracts nothing useful.
    `shepherd models` matches that fail-soft behavior via a caught
    `TOMLDecodeError` rather than crashing a read-only resolve/show call
    over one broken config file."""
    (work_dir / ".claude").mkdir(parents=True)
    (work_dir / ".claude" / "shepherd.toml").write_text("this is not [valid toml")
    env = _models_env(xdg_dir)

    proc = run_models(["show"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert "(default)" in proc.stdout


# --------------------------------------------------------------------------
# resolve — validation branches.
# --------------------------------------------------------------------------
def test_resolve_missing_role_exits_2_with_bash_parity_message(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve"], work_dir, env)

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: usage: shctx models resolve <role>"


def test_resolve_unknown_role_exits_2_with_bash_parity_message(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "bogus"], work_dir, env)

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() == (
        "ERROR: unknown role: bogus (valid: root planter engineer conductor critic "
        "discovery coder auditor worker)"
    )


@pytest.mark.parametrize("role", MODELS_ROLES)
def test_resolve_every_valid_role_defaults(role: str, work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", role], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{_default_model(role)}\n"


def test_resolve_json_additive_flag(work_dir: Path, xdg_dir: Path) -> None:
    """`--json` on `resolve` is an ADDITIVE convenience not present in
    `cmd_models.sh` — asserted separately from the bash-parity tests."""
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "root", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {"role": "root", "model": "opus[1m]", "source": "default"}


# --------------------------------------------------------------------------
# resolve --harness — the engine translates intent slugs, not each
# dispatcher (DF-03). Independent restatement of `models.py`'s
# `_HARNESS_TRANSLATION` (NOT an import) — asserts the implementation
# against a hand-written oracle, never against itself.
# --------------------------------------------------------------------------
_HARNESSES = ("claude", "codex", "pi")

#: Claude's `Agent` tool `model` parameter is a closed enum. Every
#: `--harness=claude` output, for every role and every intent slug, must
#: land inside this set — never `opus[1m]`, never anything else.
_CLAUDE_MODEL_ENUM = {"sonnet", "opus", "haiku", "fable"}

_EXPECTED_HARNESS_TRANSLATION: dict[str, dict[str, str]] = {
    "opus[1m]": {"claude": "opus", "codex": "sol/max", "pi": "opus[1m]"},
    "opus": {"claude": "opus", "codex": "sol/max", "pi": "opus"},
    "sonnet": {"claude": "sonnet", "codex": "terra/high", "pi": "sonnet"},
    "haiku": {"claude": "haiku", "codex": "terra/medium", "pi": "haiku"},
    "fable": {"claude": "fable", "codex": "terra/medium", "pi": "fable"},
}


def _expected_translation(role: str, harness: str) -> str:
    return _EXPECTED_HARNESS_TRANSLATION[_default_model(role)][harness]


@pytest.mark.parametrize("harness", _HARNESSES)
@pytest.mark.parametrize("role", MODELS_ROLES)
def test_resolve_harness_translation_every_role_every_harness(
    role: str, harness: str, work_dir: Path, xdg_dir: Path
) -> None:
    """Table-test all 9 roles x 3 harnesses (27 cases) against a
    hand-written oracle, on the built-in (no config override) intent
    slug each role resolves to by default."""
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", role, f"--harness={harness}"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{_expected_translation(role, harness)}\n"


@pytest.mark.parametrize("role", MODELS_ROLES)
def test_resolve_claude_harness_always_in_closed_enum(role: str, work_dir: Path, xdg_dir: Path) -> None:
    """Hard assertion (brief-mandated): `--harness=claude` output is
    ALWAYS inside `{sonnet, opus, haiku, fable}`, for every one of the 9
    roles — `opus[1m]` must never reach this surface."""
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", role, "--harness=claude"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() in _CLAUDE_MODEL_ENUM


@pytest.mark.parametrize("harness", _HARNESSES)
@pytest.mark.parametrize("intent", ["opus[1m]", "opus", "sonnet", "haiku", "fable"])
def test_resolve_harness_translation_every_known_intent_slug(
    intent: str, harness: str, work_dir: Path, xdg_dir: Path
) -> None:
    """Exercise every row of the translation table, not just the two
    intent slugs the 9 built-in role defaults happen to produce —
    `[models].<role>` can override to any of Claude's four bare names,
    or stay at `opus[1m]`."""
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"worker": intent})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "worker", f"--harness={harness}"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"{_EXPECTED_HARNESS_TRANSLATION[intent][harness]}\n"


def test_resolve_claude_harness_unknown_config_slug_falls_back_to_sonnet(
    work_dir: Path, xdg_dir: Path
) -> None:
    """A `[models].<role>` override outside the built-in intent-slug set
    (e.g. a typo, or someone pasting a harness-specific string into the
    wrong key) must still land inside Claude's closed enum — fall back to
    `sonnet` rather than handing the `Agent` tool a slug it will reject."""
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"worker": "gpt-5-nonsense"})
    env = _models_env(xdg_dir)

    proc = run_models(["resolve", "worker", "--harness=claude"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "sonnet\n"


def test_resolve_codex_and_pi_harness_unknown_config_slug_passes_through(
    work_dir: Path, xdg_dir: Path
) -> None:
    """Codex and Pi have no closed enum — an unrecognized config override
    passes through unchanged; there is nothing safer to guess."""
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"worker": "gpt-5-nonsense"})
    env = _models_env(xdg_dir)

    for harness in ("codex", "pi"):
        proc = run_models(["resolve", "worker", f"--harness={harness}"], work_dir, env)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == "gpt-5-nonsense\n"


def test_resolve_unknown_harness_exits_2(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "root", "--harness=bogus"], work_dir, env)

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert proc.stderr.strip() == "ERROR: unknown harness: bogus (valid: claude codex pi)"


def test_resolve_json_with_harness_adds_harness_key_and_translates_model(
    work_dir: Path, xdg_dir: Path
) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "engineer", "--harness=codex", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {
        "role": "engineer",
        "model": "sol/max",
        "source": "default",
        "harness": "codex",
    }


def test_resolve_json_without_harness_payload_unchanged(work_dir: Path, xdg_dir: Path) -> None:
    """Regression guard: `--json` alone (no `--harness`) must keep
    emitting exactly the pre-existing 3-key payload — no stray `harness`
    key leaking in."""
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "engineer", "--json"], work_dir, env)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload == {"role": "engineer", "model": "opus[1m]", "source": "default"}
    assert "harness" not in payload


# --------------------------------------------------------------------------
# The plan's exact [ACCEPTANCE] lines, restated as tests (direct
# traceability — each of these four is byte-for-byte the same assertion
# `shctx models resolve ... | grep ...` makes).
# --------------------------------------------------------------------------
def test_acceptance_engineer_claude_harness_in_closed_enum(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "engineer", "--harness=claude"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() in _CLAUDE_MODEL_ENUM


def test_acceptance_engineer_codex_harness_is_sol_max(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "engineer", "--harness=codex"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert "sol/max" in proc.stdout


def test_acceptance_discovery_claude_harness_is_sonnet(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "discovery", "--harness=claude"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "sonnet"


def test_acceptance_engineer_no_harness_intent_preserved(work_dir: Path, xdg_dir: Path) -> None:
    """No `--harness` == today's raw intent-slug output, byte-for-byte."""
    env = _models_env(xdg_dir)
    proc = run_models(["resolve", "engineer"], work_dir, env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "opus[1m]"


# --------------------------------------------------------------------------
# help / -h / --help / unknown subcommand.
# --------------------------------------------------------------------------
_USAGE_MARKER = "shctx models <resolve|show> [args]"


@pytest.mark.parametrize("args", [["help"], ["-h"], ["--help"], ["show", "-h"], ["show", "--help"]])
def test_help_variants_print_usage_and_exit_0(args: list[str], work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(args, work_dir, env)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith(_USAGE_MARKER)
    assert "resolve <role>" in proc.stdout
    assert "show [--md|--json]" in proc.stdout


def test_unknown_subcommand_exits_2(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    proc = run_models(["bogus"], work_dir, env)

    assert proc.returncode == 2
    assert proc.stdout == ""


# --------------------------------------------------------------------------
# Bash-parity byte-for-byte comparisons.
# --------------------------------------------------------------------------
def test_bare_invocation_bash_parity_no_config(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    python_proc = run_models([], work_dir, env)
    bash_proc = run_bash_models([], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_show_md_bash_parity_no_config(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    python_proc = run_models(["show", "--md"], work_dir, env)
    bash_proc = run_bash_models(["show", "--md"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout


def test_show_json_bash_parity_with_project_override(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"discovery": "custom-discovery", "worker": "custom-worker"})
    env = _models_env(xdg_dir)

    python_proc = run_models(["show", "--json"], work_dir, env)
    bash_proc = run_bash_models(["show", "--json"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0, (python_proc.stderr, bash_proc.stderr)
    assert python_proc.stdout == bash_proc.stdout


def test_resolve_bash_parity_with_local_override(work_dir: Path, xdg_dir: Path) -> None:
    _write_toml(work_dir / ".claude" / "shepherd.toml", {"engineer": "project-slug"})
    _write_toml(work_dir / ".claude" / "shepherd.local.toml", {"engineer": "local-slug"})
    env = _models_env(xdg_dir)

    python_proc = run_models(["resolve", "engineer"], work_dir, env)
    bash_proc = run_bash_models(["resolve", "engineer"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout == "local-slug\n"


def test_resolve_missing_role_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    python_proc = run_models(["resolve"], work_dir, env)
    bash_proc = run_bash_models(["resolve"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 2
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


def test_resolve_unknown_role_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    python_proc = run_models(["resolve", "bogus"], work_dir, env)
    bash_proc = run_bash_models(["resolve", "bogus"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 2
    assert python_proc.stdout == bash_proc.stdout == ""
    assert python_proc.stderr == bash_proc.stderr


def test_help_bash_parity(work_dir: Path, xdg_dir: Path) -> None:
    env = _models_env(xdg_dir)
    python_proc = run_models(["help"], work_dir, env)
    bash_proc = run_bash_models(["help"], work_dir, env)

    assert python_proc.returncode == bash_proc.returncode == 0
    assert python_proc.stdout == bash_proc.stdout
