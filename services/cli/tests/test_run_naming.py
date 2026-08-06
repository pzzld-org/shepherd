"""Tests for #P4 — canonical run ids (``shepherd_cli.models_run``'s "CANONICAL
RUN IDS" section) and the ``shepherd run`` / ``shepherd lint`` surfaces that
enforce it.

Two kinds of test live here:

- **Pure-function tests** (:func:`derive_run_id`, :func:`is_canonical_run_id`,
  :func:`suggest_canonical_id`) drive a ``${PY} -c "..."`` subprocess snippet
  rather than importing ``shepherd_cli`` into the pytest process — the same
  "never import shepherd_cli into the pytest process itself" convention
  ``conftest.resolve_fields``/``test_config_schema.py`` already establish.
  These snippets run under an ISOLATED, non-git ``cwd`` with an isolated
  ``XDG_CONFIG_HOME`` (mirroring ``test_config.py``'s ``work_dir``/``xdg_dir``
  fixtures) so a "default pattern" assertion can never accidentally read
  this real repository's own ``.claude/shepherd.toml`` (which happens to set
  the *same* values as the hardcoded defaults today, but that's a coincidence
  a test must not depend on).
- **CLI-level tests** (``run init``/``run rename``/``run canonicalize``) drive
  the real CLI as a subprocess exactly like ``test_run.py``, reusing that
  file's ``SHEPHERD_WORKDIR``-isolation idiom.

``shepherd lint``'s WARN-on-non-canonical-run behavior lives in
``test_lint.py`` alongside every other lint check, not here.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, clean_env_dict, run_cli


# --------------------------------------------------------------------------
# Isolation fixtures + snippet runner (pure-function half).
# --------------------------------------------------------------------------
@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """A fresh, non-git directory — `resolve_repo_root()` falls back to this
    exact directory rather than climbing into this real repo's own root."""
    d = tmp_path / "work"
    d.mkdir()
    return d


@pytest.fixture
def xdg_dir(tmp_path: Path) -> Path:
    """An isolated, initially-empty `XDG_CONFIG_HOME` directory."""
    d = tmp_path / "xdg-config"
    d.mkdir()
    return d


def _isolated_env(xdg_dir: Path) -> dict[str, str]:
    env = clean_env_dict()
    env["XDG_CONFIG_HOME"] = str(xdg_dir)
    return env


def _snippet(code: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `${PY} -c code` under `cwd`/`env`, exactly like `test_config_schema.py`'s snippets."""
    return subprocess.run([PY, "-c", code], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=10)


def _derive(
    version: str, *, kind: str = "sprint", work_dir: Path, xdg_dir: Path, workdir: str | None = None
) -> tuple[str | None, str]:
    """Call `derive_run_id(version, kind=kind, workdir=workdir)` in a fresh subprocess.

    Returns:
        `(result, stderr)` — `result` is None on a `RunIdDerivationError`
        (the exception's message is embedded in the printed JSON instead).
    """
    code = (
        "import json\n"
        "from shepherd_cli.models_run import derive_run_id, RunIdDerivationError\n"
        "try:\n"
        f"    print(json.dumps({{'ok': derive_run_id({version!r}, kind={kind!r}, workdir={workdir!r})}}))\n"
        "except RunIdDerivationError as exc:\n"
        "    print(json.dumps({'err': str(exc)}))\n"
    )
    proc = _snippet(code, work_dir, _isolated_env(xdg_dir))
    assert proc.returncode == 0, f"snippet crashed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = json.loads(proc.stdout)
    return payload.get("ok"), payload.get("err", "")


def _is_canonical(run_id: str, *, work_dir: Path, xdg_dir: Path, workdir: str | None = None) -> bool:
    code = (
        "import json\n"
        "from shepherd_cli.models_run import is_canonical_run_id\n"
        f"print(json.dumps(is_canonical_run_id({run_id!r}, workdir={workdir!r})))\n"
    )
    proc = _snippet(code, work_dir, _isolated_env(xdg_dir))
    assert proc.returncode == 0, f"snippet crashed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def _suggest(run_id: str, *, work_dir: Path, xdg_dir: Path, workdir: str | None = None) -> str | None:
    code = (
        "import json\n"
        "from shepherd_cli.models_run import suggest_canonical_id\n"
        f"print(json.dumps(suggest_canonical_id({run_id!r}, workdir={workdir!r})))\n"
    )
    proc = _snippet(code, work_dir, _isolated_env(xdg_dir))
    assert proc.returncode == 0, f"snippet crashed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    return json.loads(proc.stdout)


def _write_custom_patterns(work_dir: Path, **patterns: str) -> None:
    """Write `<work_dir>/shepherd.toml` with a `[branching]` table of `patterns`."""
    lines = ["[branching]"]
    lines.extend(f'{key} = "{value}"' for key, value in patterns.items())
    (work_dir / "shepherd.toml").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# derive_run_id — default patterns.
# --------------------------------------------------------------------------
def test_derive_run_id_sprint_default_pattern(work_dir: Path, xdg_dir: Path) -> None:
    result, _err = _derive("v0.3.9-dev.0", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result == "v039-dev0"


def test_derive_run_id_patch_arc_default_pattern(work_dir: Path, xdg_dir: Path) -> None:
    result, _err = _derive("v0.3.9", kind="patch-arc", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result == "v039"


def test_derive_run_id_accepts_bare_version_no_v_prefix(work_dir: Path, xdg_dir: Path) -> None:
    result, _err = _derive("0.3.9-dev.0", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result == "v039-dev0"


def test_derive_run_id_accepts_branch_name_shape(work_dir: Path, xdg_dir: Path) -> None:
    """A branch name (`v6.4.1-dev.0`) parses exactly like a version string."""
    result, _err = _derive("v6.4.1-dev.0", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result == "v641-dev0"


def test_derive_run_id_double_digit_component_documented_behavior(work_dir: Path, xdg_dir: Path) -> None:
    """DOCUMENTED (see `derive_run_id`'s docstring): components are substituted
    un-padded, so a two-digit `Z` produces a longer, non-fixed-width slug —
    `v0.3.10-dev.2` -> `v0310-dev2`, not any zero-padded alternative."""
    result, _err = _derive("v0.3.10-dev.2", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result == "v0310-dev2"


def test_derive_run_id_deterministic_across_repeated_calls(work_dir: Path, xdg_dir: Path) -> None:
    first, _ = _derive("v0.3.9-dev.0", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    second, _ = _derive("v0.3.9-dev.0", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert first == second == "v039-dev0"


def test_derive_run_id_sprint_requires_dev_component(work_dir: Path, xdg_dir: Path) -> None:
    result, err = _derive("v0.3.9", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result is None
    assert "{N}" in err


def test_derive_run_id_rejects_unparseable_version(work_dir: Path, xdg_dir: Path) -> None:
    result, err = _derive("not-a-version", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result is None
    assert "cannot derive a run id" in err


def test_derive_run_id_rejects_invalid_kind(work_dir: Path, xdg_dir: Path) -> None:
    result, err = _derive("v0.3.9-dev.0", kind="bogus", work_dir=work_dir, xdg_dir=xdg_dir)
    assert result is None
    assert "invalid kind" in err


# --------------------------------------------------------------------------
# derive_run_id — custom `[branching]` patterns from shepherd.toml.
# --------------------------------------------------------------------------
def test_derive_run_id_honors_custom_sprint_pattern(work_dir: Path, xdg_dir: Path) -> None:
    _write_custom_patterns(work_dir, sprint_slug_pattern="sprint-{X}.{Y}.{Z}-w{N}")
    result, _err = _derive(
        "v1.2.3-dev.4", kind="sprint", work_dir=work_dir, xdg_dir=xdg_dir, workdir=str(work_dir)
    )
    assert result == "sprint-1.2.3-w4"


def test_derive_run_id_honors_custom_patch_pattern(work_dir: Path, xdg_dir: Path) -> None:
    _write_custom_patterns(work_dir, patch_slug_pattern="patch-{X}-{Y}-{Z}")
    result, _err = _derive(
        "v1.2.3", kind="patch-arc", work_dir=work_dir, xdg_dir=xdg_dir, workdir=str(work_dir)
    )
    assert result == "patch-1-2-3"


# --------------------------------------------------------------------------
# is_canonical_run_id.
# --------------------------------------------------------------------------
def test_is_canonical_accepts_derived_sprint_form(work_dir: Path, xdg_dir: Path) -> None:
    assert _is_canonical("v039-dev0", work_dir=work_dir, xdg_dir=xdg_dir) is True


def test_is_canonical_accepts_derived_patch_form(work_dir: Path, xdg_dir: Path) -> None:
    assert _is_canonical("v039", work_dir=work_dir, xdg_dir=xdg_dir) is True


def test_is_canonical_rejects_harness_suffixed_id(work_dir: Path, xdg_dir: Path) -> None:
    """The exact axiom live-run shape named in the operator directive."""
    assert _is_canonical("v039-dev0-codex-01", work_dir=work_dir, xdg_dir=xdg_dir) is False


def test_is_canonical_rejects_invented_id(work_dir: Path, xdg_dir: Path) -> None:
    assert _is_canonical("my-favorite-run", work_dir=work_dir, xdg_dir=xdg_dir) is False


def test_is_canonical_independent_of_validate_id_grammar(work_dir: Path, xdg_dir: Path) -> None:
    """Grammar-invalid strings (uppercase, path separators) never raise here —
    `is_canonical_run_id` is a pure shape check, a SEPARATE concern from
    `validate_id`'s `[a-z0-9][a-z0-9-]*` path-safety grammar."""
    assert _is_canonical("V039-DEV0", work_dir=work_dir, xdg_dir=xdg_dir) is False
    assert _is_canonical("a/b", work_dir=work_dir, xdg_dir=xdg_dir) is False
    assert _is_canonical("", work_dir=work_dir, xdg_dir=xdg_dir) is False


def test_is_canonical_honors_custom_pattern(work_dir: Path, xdg_dir: Path) -> None:
    _write_custom_patterns(work_dir, sprint_slug_pattern="sprint-{X}.{Y}.{Z}-w{N}")
    assert _is_canonical("v039-dev0", work_dir=work_dir, xdg_dir=xdg_dir, workdir=str(work_dir)) is False
    assert _is_canonical("sprint-1.2.3-w4", work_dir=work_dir, xdg_dir=xdg_dir, workdir=str(work_dir)) is True


# --------------------------------------------------------------------------
# suggest_canonical_id.
# --------------------------------------------------------------------------
def test_suggest_canonical_id_strips_harness_suffix(work_dir: Path, xdg_dir: Path) -> None:
    assert _suggest("v039-dev0-codex-01", work_dir=work_dir, xdg_dir=xdg_dir) == "v039-dev0"


def test_suggest_canonical_id_strips_ordinal_only_suffix(work_dir: Path, xdg_dir: Path) -> None:
    assert _suggest("v039-codex-01", work_dir=work_dir, xdg_dir=xdg_dir) == "v039"


def test_suggest_canonical_id_identity_when_already_canonical(work_dir: Path, xdg_dir: Path) -> None:
    assert _suggest("v039-dev0", work_dir=work_dir, xdg_dir=xdg_dir) == "v039-dev0"


def test_suggest_canonical_id_none_for_unrecognizable_id(work_dir: Path, xdg_dir: Path) -> None:
    assert _suggest("totally-invented", work_dir=work_dir, xdg_dir=xdg_dir) is None


# --------------------------------------------------------------------------
# CLI: `shepherd run init` — #P4 refusal/derivation/--force.
# --------------------------------------------------------------------------
def _env(tmp_path: Path) -> dict[str, str]:
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(tmp_path / ".shepherd")
    return env


def naming_env(workdir: Path) -> dict[str, str]:
    """Env pinning SHEPHERD_WORKDIR at an explicit artifacts root."""
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(workdir)
    return env


def _run_json(tmp_path: Path, run: str) -> dict:
    return json.loads((tmp_path / ".shepherd" / "runs" / run / "run.json").read_text())


def test_init_refuses_noncanonical_explicit_id(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "v039-dev0-codex-01"], env)
    assert proc.returncode == 2
    assert "non-canonical run id" in proc.stderr
    assert "v039-dev0" in proc.stderr  # names the canonical form
    assert not (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").exists()


def test_init_force_allows_noncanonical_id_and_warns(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    assert proc.returncode == 0, proc.stderr
    assert "WARNING" in proc.stderr
    assert "bridge" in proc.stderr.lower()
    doc = _run_json(tmp_path, "v039-dev0-codex-01")
    assert doc["run"] == "v039-dev0-codex-01"


def test_init_accepts_canonical_explicit_id_with_no_warning(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "v641-dev0"], env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


def test_init_derives_id_from_version(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "--version", "v0.3.9-dev.0"], env)
    assert proc.returncode == 0, proc.stderr
    doc = _run_json(tmp_path, "v039-dev0")
    assert doc["run"] == "v039-dev0"


def test_init_derives_id_from_branch(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "--branch", "v6.4.1-dev.0", "--kind", "sprint"], env)
    assert proc.returncode == 0, proc.stderr
    doc = _run_json(tmp_path, "v641-dev0")
    assert doc["run"] == "v641-dev0"
    assert doc["branch"] == "v6.4.1-dev.0"


def test_init_derives_patch_arc_id(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "--version", "v0.3.9", "--kind", "patch-arc"], env)
    assert proc.returncode == 0, proc.stderr
    assert _run_json(tmp_path, "v039")["kind"] == "patch-arc"


def test_init_requires_run_or_version_when_both_omitted(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init"], env)
    assert proc.returncode == 2
    assert "pass <run>" in proc.stderr


def test_init_still_rejects_bad_grammar_ids_even_with_force(tmp_path: Path) -> None:
    """--force overrides canonicality, NEVER the [a-z0-9][a-z0-9-]* path-safety grammar."""
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "V650", "--force"], env)
    assert proc.returncode == 2
    assert "invalid run id" in proc.stderr


# --------------------------------------------------------------------------
# CLI: `shepherd run rename`.
# --------------------------------------------------------------------------
def test_rename_moves_dir_and_rewrites_run_field(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    proc = run_cli(["run", "rename", "v039-dev0-codex-01", "v039-dev0"], env)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").exists()
    doc = _run_json(tmp_path, "v039-dev0")
    assert doc["run"] == "v039-dev0"


def test_rename_rewrites_self_referential_seed_and_plan_paths(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    run_cli(
        [
            "run",
            "set",
            "v039-dev0-codex-01",
            "--seed",
            "runs/v039-dev0-codex-01/seed.md",
            "--plan",
            "runs/v039-dev0-codex-01/plan.md",
        ],
        env,
    )
    run_cli(["run", "rename", "v039-dev0-codex-01", "v039-dev0"], env)
    doc = _run_json(tmp_path, "v039-dev0")
    assert doc["seed"] == "runs/v039-dev0/seed.md"
    assert doc["plan"] == "runs/v039-dev0/plan.md"


def test_rename_preserves_lanes_and_other_fields(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force", "--branch", "v0.3.9-dev.0"], env)
    run_cli(["run", "lane", "add", "v039-dev0-codex-01", "lane-cli"], env)
    run_cli(["run", "rename", "v039-dev0-codex-01", "v039-dev0"], env)
    doc = _run_json(tmp_path, "v039-dev0")
    assert doc["branch"] == "v0.3.9-dev.0"
    assert [lane["id"] for lane in doc["lanes"]] == ["lane-cli"]
    assert (tmp_path / ".shepherd" / "runs" / "v039-dev0" / "lanes" / "lane-cli").is_dir()


def test_rename_refuses_existing_destination(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    run_cli(["run", "init", "v039-dev0"], env)
    proc = run_cli(["run", "rename", "v039-dev0-codex-01", "v039-dev0"], env)
    assert proc.returncode == 5
    assert "already exists" in proc.stderr
    # Neither run was touched.
    assert (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").is_dir()
    assert (tmp_path / ".shepherd" / "runs" / "v039-dev0").is_dir()


def test_rename_refuses_missing_source(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "rename", "ghost", "somewhere"], env)
    assert proc.returncode == 5
    # v6.4.4: the gate is the DIRECTORY, not run.json — an unregistered
    # directory is renameable, so the message names what is actually missing.
    assert "no such run directory: ghost" in proc.stderr


def test_rename_source_with_corrupt_run_json_fails_cleanly(tmp_path: Path) -> None:
    """A source run whose run.json is unreadable fails clean (exit 2, no
    traceback) rather than crashing -- `_rename_run` loads via the same
    `_load_or_fail` every other mutator uses."""
    env = _env(tmp_path)
    run_dir = tmp_path / ".shepherd" / "runs" / "v641-dev0"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{not json at all")

    proc = run_cli(["run", "rename", "v641-dev0", "v641-dev1"], env)
    assert proc.returncode == 2
    assert "could not be read" in proc.stderr
    # Nothing moved.
    assert run_dir.is_dir()


def test_rename_refuses_identical_ids(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    proc = run_cli(["run", "rename", "v641-dev0", "v641-dev0"], env)
    assert proc.returncode == 2
    assert "identical" in proc.stderr


def test_rename_rejects_bad_grammar_ids(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    proc = run_cli(["run", "rename", "v641-dev0", "Bad/Id"], env)
    assert proc.returncode == 2


def test_rename_reports_dangling_references_without_touching_them(tmp_path: Path) -> None:
    """A mention of the old id in ANOTHER run's run.json is reported (stderr)
    but never rewritten -- that file lives outside the run directory."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    run_cli(["run", "init", "v641-dev0"], env)
    other = tmp_path / ".shepherd" / "runs" / "v641-dev0" / "run.json"
    doc = json.loads(other.read_text())
    doc["notes"] = "depends on v039-dev0-codex-01 finishing first"
    other.write_text(json.dumps(doc))

    proc = run_cli(["run", "rename", "v039-dev0-codex-01", "v039-dev0"], env)
    assert proc.returncode == 0, proc.stderr
    assert "still referenced" in proc.stderr
    assert str(other) in proc.stderr
    # NOT rewritten.
    assert "v039-dev0-codex-01" in other.read_text()


# --------------------------------------------------------------------------
# CLI: `shepherd run canonicalize`.
# --------------------------------------------------------------------------
def test_canonicalize_dry_run_changes_nothing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    proc = run_cli(["run", "canonicalize", "v039-dev0-codex-01", "--dry-run"], env)
    assert proc.returncode == 0, proc.stderr
    assert "v039-dev0-codex-01 -> v039-dev0" in proc.stdout
    assert (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").is_dir()
    assert not (tmp_path / ".shepherd" / "runs" / "v039-dev0").exists()


def test_canonicalize_real_run_renames(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    proc = run_cli(["run", "canonicalize", "v039-dev0-codex-01"], env)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").exists()
    assert _run_json(tmp_path, "v039-dev0")["run"] == "v039-dev0"


def test_canonicalize_idempotent_on_already_canonical_run(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    proc = run_cli(["run", "canonicalize", "v641-dev0"], env)
    assert proc.returncode == 0, proc.stderr
    assert "already canonical" in proc.stdout
    assert (tmp_path / ".shepherd" / "runs" / "v641-dev0").is_dir()


def test_canonicalize_all_handles_several(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    run_cli(["run", "init", "v100-dev2-codex-05", "--force"], env)
    run_cli(["run", "init", "v641-dev0"], env)

    proc = run_cli(["run", "canonicalize", "--all"], env)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").exists()
    assert not (tmp_path / ".shepherd" / "runs" / "v100-dev2-codex-05").exists()
    assert _run_json(tmp_path, "v039-dev0")["run"] == "v039-dev0"
    assert _run_json(tmp_path, "v100-dev2")["run"] == "v100-dev2"
    assert _run_json(tmp_path, "v641-dev0")["run"] == "v641-dev0"  # untouched, already canonical


def test_canonicalize_requires_exactly_one_of_run_or_all(tmp_path: Path) -> None:
    env = _env(tmp_path)
    neither = run_cli(["run", "canonicalize"], env)
    assert neither.returncode == 2
    assert "exactly one" in neither.stderr

    run_cli(["run", "init", "v641-dev0"], env)
    both = run_cli(["run", "canonicalize", "v641-dev0", "--all"], env)
    assert both.returncode == 2
    assert "exactly one" in both.stderr


def test_canonicalize_reports_unfixable_run_without_crashing(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "totally-invented", "--force"], env)
    proc = run_cli(["run", "canonicalize", "totally-invented"], env)
    assert proc.returncode == 0, proc.stderr
    assert "no recognizable canonical form" in proc.stdout
    assert (tmp_path / ".shepherd" / "runs" / "totally-invented").is_dir()


def test_canonicalize_refuses_to_overwrite_existing_destination(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v039-dev0-codex-01", "--force"], env)
    run_cli(["run", "init", "v039-dev0"], env)
    proc = run_cli(["run", "canonicalize", "v039-dev0-codex-01"], env)
    assert proc.returncode == 0, proc.stderr
    assert "already exists" in proc.stdout
    # Neither the source nor the pre-existing destination were touched.
    assert (tmp_path / ".shepherd" / "runs" / "v039-dev0-codex-01").is_dir()
    assert (tmp_path / ".shepherd" / "runs" / "v039-dev0").is_dir()


def test_canonicalize_missing_run_exits_5(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "canonicalize", "ghost"], env)
    assert proc.returncode == 5


def test_canonicalize_all_with_no_runs_is_a_noop(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "canonicalize", "--all"], env)
    assert proc.returncode == 0
    assert "no runs to canonicalize" in proc.stdout


# --------------------------------------------------------------------------
# v6.4.4 — rename/canonicalize reach UNREGISTERED directories.
# --------------------------------------------------------------------------
def test_rename_works_on_a_directory_without_run_json(tmp_path: Path) -> None:
    """An unregistered directory is renameable — it is the population that needs it.

    `run init` REFUSES a non-canonical id and `run rename` used to require
    `run.json`, so a misnamed directory nothing had registered could be neither
    registered nor renamed. `shepherd lint` points operators here; it must not
    point at a dead end.
    """
    workdir = tmp_path / "ws" / ".shepherd"
    stray = workdir / "runs" / "2026-05-04-shepherd-context"
    stray.mkdir(parents=True)
    (stray / "plan.md").write_text("plan body")
    env = naming_env(workdir)

    proc = run_cli(["run", "rename", "2026-05-04-shepherd-context", "v500"], env)

    assert proc.returncode == 0, proc.stderr
    assert (workdir / "runs" / "v500" / "plan.md").read_text() == "plan body"
    assert not stray.exists()
    # And it says the run is still unregistered rather than implying otherwise.
    assert "has no run.json" in proc.stderr
    assert "shepherd run init v500" in proc.stderr


def test_canonicalize_works_on_a_directory_without_run_json(tmp_path: Path) -> None:
    """`canonicalize` enumerates directories too, and derives the canonical id."""
    workdir = tmp_path / "ws" / ".shepherd"
    stray = workdir / "runs" / "v514-teammate-parallel"
    stray.mkdir(parents=True)
    (stray / "seed.md").write_text("seed body")
    env = naming_env(workdir)

    proc = run_cli(["run", "canonicalize", "v514-teammate-parallel"], env)

    assert proc.returncode == 0, proc.stderr
    assert (workdir / "runs" / "v514" / "seed.md").read_text() == "seed body"
    assert not stray.exists()


def test_canonicalize_all_sees_unregistered_directories(tmp_path: Path) -> None:
    """`--all` must not silently skip the directories it exists to fix."""
    workdir = tmp_path / "ws" / ".shepherd"
    (workdir / "runs" / "v514-teammate-parallel").mkdir(parents=True)
    (workdir / "runs" / "v641-dev0").mkdir(parents=True)
    env = naming_env(workdir)

    proc = run_cli(["run", "canonicalize", "--all"], env)

    assert proc.returncode == 0, proc.stderr
    assert (workdir / "runs" / "v514").is_dir()
    assert (workdir / "runs" / "v641-dev0").is_dir()  # already canonical, untouched
    assert "already canonical" in proc.stdout


def test_rename_refuses_a_missing_directory(tmp_path: Path) -> None:
    """Loosening the run.json gate must not loosen the existence gate."""
    workdir = tmp_path / "ws" / ".shepherd"
    (workdir / "runs").mkdir(parents=True)
    env = naming_env(workdir)

    proc = run_cli(["run", "rename", "nope", "v500"], env)

    assert proc.returncode == 5
    assert "no such run directory: nope" in proc.stderr


def test_rename_refuses_an_existing_destination_directory(tmp_path: Path) -> None:
    """Collision check covers a bare DIRECTORY, not just a registered run."""
    workdir = tmp_path / "ws" / ".shepherd"
    (workdir / "runs" / "old-name").mkdir(parents=True)
    (workdir / "runs" / "v500").mkdir(parents=True)
    env = naming_env(workdir)

    proc = run_cli(["run", "rename", "old-name", "v500"], env)

    assert proc.returncode == 5
    assert "destination already exists" in proc.stderr
    assert (workdir / "runs" / "old-name").is_dir()  # nothing moved
