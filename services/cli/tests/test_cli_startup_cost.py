"""T3-startup-cost: gate the two per-invocation perf defects `guard eval`
timing surfaced (measuring where "just start the CLI" time went, unrelated
to guard logic itself).

DEFECT 1 -- `bin/shepherd` re-resolved the venv interpreter via `poetry -C
services/cli env info --executable` on EVERY invocation: ~250-360ms of pure
poetry-process startup, paid before a single line of the CLI itself ran.
Fixed by caching the resolved path in a plain-text file inside the venv
directory (`.venv/.shepherd-venv-python` -- gitignored, lives and dies with
the venv) and trusting it once it passes the exact same `venv_provisioned`
check the uncached path already ran before every exec. See `bin/shepherd`'s
own "T3-startup-cost" comment block for the full invalidation contract.

DEFECT 2 -- `shepherd_cli/commands/__init__.py` eagerly did `from
shepherd_cli.commands import teammate`. Python always executes a package's
`__init__` before any of its submodules, so this ran -- and dragged the
full Tortoise ORM + Pydantic stack in behind it -- on EVERY invocation of
EVERY lazily-dispatched command (`shepherd_cli/app.py`'s `_LazyGroup`
imports `shepherd_cli.commands.<name>` directly via `importlib`, which
means the *package* import always runs first), not just `teammate`
invocations. ~116ms measured via `python -X importtime`.

Why this suite does NOT test bare `shepherd --help`'s import graph, even
though that is the literal invocation named when this defect was reported:
root `--help` legitimately imports EVERY command module (Click's
`format_commands`/Typer's rich help renderer must resolve each one via
`get_command()` to read its own short-help text) -- `shepherd_cli/app.py`'s
own "LAZY SUBCOMMAND DISPATCH" docstring documents this as "the one
accepted cost". That includes `teammate` itself, so root `--help` imports
Tortoise both before AND after this fix; asserting otherwise would be a
test that can never pass without breaking that documented, out-of-scope-
for-this-lane design. `guard --help` (any ONE subcommand's own help,
resolving only itself) is the invocation defect 2 actually taxed, and is
what every test below that needs an import-graph assertion uses instead.

Every test drives the real CLI as a fresh subprocess -- this package's
universal convention (see conftest.py's module docstring): never import
`shepherd_cli` into the pytest process.
"""

from __future__ import annotations

import os
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, REPO_ROOT, clean_env_dict

BIN_SHEPHERD = REPO_ROOT / "bin" / "shepherd"
VENV_PY_CACHE = CLI_ROOT / ".venv" / ".shepherd-venv-python"

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")

# Baselines measured for this fix (same machine, `perl -MTime::HiRes=time`,
# `bin/shepherd --version`, 5 runs each):
#   BEFORE (uncached `poetry env info --executable` every call):
#     313.4, 312.1, 358.0, 329.3, 312.8 ms
#   AFTER (warm cache -- the steady-state hot path this fix targets):
#     71.8, 73.5, 70.8, 74.8, 69.6 ms
# Threshold is 4x the AFTER median (huge headroom for a loaded CI box or a
# machine running a concurrent shepherd wave -- this repo's own sprints
# fan out several agents on one machine, see CLAUDE.md's #256 resource-
# discipline note) while staying at/under the lowest BEFORE sample, so a
# regression back to "always re-resolve via poetry" still fails reliably:
# under the SAME load that inflates the AFTER median toward this
# threshold, the BEFORE path (one full extra `poetry` process spawn) is
# inflated at least as much, never less.
VERSION_THRESHOLD_MS = 300.0


def _importtime_names(args: list[str], env: dict[str, str], cwd: Path) -> tuple[subprocess.CompletedProcess[str], set[str]]:
    """Run `${PY} -X importtime <args>` and return (proc, {imported module names}).

    `-X importtime` writes exclusively to stderr, one `import time: <self>
    | <cumulative> | <name>` line per module actually imported (indentation
    shows nesting, stripped here since only membership is asserted).
    """
    proc = subprocess.run(
        [PY, "-X", "importtime", *args],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )
    names: set[str] = set()
    for line in proc.stderr.splitlines():
        if not line.startswith("import time:"):
            continue
        _, _, name = line.rpartition("|")
        names.add(name.strip())
    return proc, names


@pytest.fixture
def preserved_venv_cache():
    """Snapshot + restore `.venv/.shepherd-venv-python` around a test.

    Several tests below deliberately poison this file to prove #266's
    guarantee survives the DEFECT 1 cache. Restoring it afterward keeps
    both the developer's real environment and every other test in this
    file unaffected by what ran here, win or lose.
    """
    existed = VENV_PY_CACHE.exists()
    original = VENV_PY_CACHE.read_text() if existed else None
    try:
        yield
    finally:
        if existed:
            VENV_PY_CACHE.write_text(original)
        elif VENV_PY_CACHE.exists():
            VENV_PY_CACHE.unlink()


# ---------------------------------------------------------------------------
# DEFECT 2 -- import-graph assertions (deterministic; see module docstring
# for why `guard --help`, not root `--help`).
# ---------------------------------------------------------------------------
def test_unrelated_subcommand_import_graph_excludes_tortoise_and_teammate() -> None:
    """`guard --help` no longer imports Tortoise or `commands.teammate`.

    Before the fix, resolving ANY `shepherd_cli.commands.<x>` module first
    ran `commands/__init__.py` (Python always executes a package's
    `__init__` before its submodules), which eagerly imported `teammate`
    and, through it, Tortoise -- regardless of which command was actually
    requested. `guard` was picked as the unrelated command because it is
    cheap, real, and shares nothing with `teammate` (confirmed via `rg`
    during this lane's dedup pass: no `teammate` import anywhere in
    `guard.py`'s own dependency chain).
    """
    env = clean_env_dict()
    proc, names = _importtime_names(["-m", "shepherd_cli", "guard", "--help"], env, CLI_ROOT)

    assert proc.returncode == 0, f"`shepherd guard --help` failed: {proc.stderr}"
    assert "tortoise" not in names, (
        f"'tortoise' present in `guard --help`'s import graph: {sorted(names)} -- "
        "commands/__init__.py is dragging it in again"
    )
    assert "shepherd_cli.commands.teammate" not in names, (
        f"'shepherd_cli.commands.teammate' present in `guard --help`'s import graph: "
        f"{sorted(names)} -- commands/__init__.py is eagerly importing it again"
    )


def test_direct_submodule_import_excludes_tortoise_and_teammate() -> None:
    """The single most precise regression target: `import shepherd_cli.commands.guard` alone.

    Decoupled from Click/Typer help rendering entirely -- this is exactly
    the mechanism defect 2 exploited (a package `__init__` running before
    any of its submodules), isolated from every other moving part.
    """
    env = clean_env_dict()
    proc, names = _importtime_names(["-c", "import shepherd_cli.commands.guard"], env, CLI_ROOT)

    assert proc.returncode == 0, f"import snippet failed: {proc.stderr}"
    assert "tortoise" not in names, sorted(names)
    assert "shepherd_cli.commands.teammate" not in names, sorted(names)


def test_negative_control_reintroducing_eager_import_fails_the_graph_assertion(tmp_path: Path) -> None:
    """A perf gate never watched fail is not a gate.

    Copies the real `shepherd_cli` package into a scratch tree, restores
    ONLY `commands/__init__.py` to its pre-fix content (the eager `from
    shepherd_cli.commands import teammate`), and re-runs the exact
    mechanism `test_direct_submodule_import_excludes_tortoise_and_teammate`
    relies on against the broken copy. Proves the graph assertion actually
    discriminates fixed-from-broken rather than being vacuously true.
    """
    scratch_root = tmp_path / "scratch_cli"
    shutil.copytree(
        CLI_ROOT / "shepherd_cli",
        scratch_root / "shepherd_cli",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    broken_init = scratch_root / "shepherd_cli" / "commands" / "__init__.py"
    broken_init.write_text(
        '"""Command sub-apps for the shepherd CLI (T3 negative-control copy).\n\n'
        "Re-exports the ``teammate`` Typer sub-app; deliberately restores the\n"
        "pre-T3-startup-cost eager import this file used to carry, so this\n"
        "scratch copy reproduces defect 2 on purpose.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "from shepherd_cli.commands import teammate\n\n"
        '__all__ = ["teammate"]\n'
    )

    env = clean_env_dict()
    env["PYTHONPATH"] = str(scratch_root)
    proc, names = _importtime_names(["-c", "import shepherd_cli.commands.guard"], env, scratch_root)

    assert proc.returncode == 0, f"scratch import failed: {proc.stderr}"
    assert "tortoise" in names, (
        "negative control did not reproduce the defect -- expected 'tortoise' in the "
        f"import graph of the pre-fix commands/__init__.py copy, got: {sorted(names)}. "
        "If this assertion fails, the graph checks above may be passing for the wrong "
        "reason and are not actually gating defect 2."
    )
    assert "shepherd_cli.commands.teammate" in names, sorted(names)


# ---------------------------------------------------------------------------
# DEFECT 1 -- `bin/shepherd` timing + #266 guarantee under the new cache.
# ---------------------------------------------------------------------------
@pytest.mark.xdist_group(name="shepherd_venv_cache")
def test_bin_shepherd_version_completes_under_measured_threshold(preserved_venv_cache) -> None:
    """`bin/shepherd --version` stays well under the pre-fix cold-poetry floor.

    See the module-level baseline comment for the measurements this
    threshold is set from. Two unmeasured warmup calls settle the cache
    (a fresh clone pays a one-time resolution on the very first call) and
    OS-level page-cache effects before the 5 measured runs; the assertion
    is on the MEDIAN of those 5, not the max, per this module's own
    docstring on why the timing test is expected to be noisier than the
    import-graph tests (a single scheduler hiccup on a loaded box
    shouldn't fail a deterministic-in-substance perf gate).
    """
    for _ in range(2):
        warmup = subprocess.run([str(BIN_SHEPHERD), "--version"], capture_output=True, text=True, timeout=15)
        assert warmup.returncode == 0, warmup.stderr

    samples_ms: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        proc = subprocess.run([str(BIN_SHEPHERD), "--version"], capture_output=True, text=True, timeout=15)
        samples_ms.append((time.perf_counter() - t0) * 1000)
        assert proc.returncode == 0, proc.stderr
        assert _VERSION_RE.fullmatch(proc.stdout.strip()), proc.stdout

    median_ms = statistics.median(samples_ms)
    assert median_ms < VERSION_THRESHOLD_MS, (
        f"bin/shepherd --version had a {median_ms:.1f}ms median over 5 warm-cache runs "
        f"({[round(s, 1) for s in samples_ms]}), over the {VERSION_THRESHOLD_MS}ms threshold. "
        "Baseline measured for this fix (bin/shepherd --version, 5 runs, same method, quiet "
        "machine): BEFORE (uncached poetry resolution) 313.4/312.1/358.0/329.3/312.8ms; AFTER "
        "(warm cache) 71.8/73.5/70.8/74.8/69.6ms. A regression toward the BEFORE numbers means "
        "the venv-python cache stopped being trusted -- check venv_provisioned() and the "
        "VENV_PY_CACHE read path in bin/shepherd."
    )


@pytest.mark.xdist_group(name="shepherd_venv_cache")
def test_bin_shepherd_guard_test_still_passes_all_examples(preserved_venv_cache) -> None:
    """`bin/shepherd guard test` still prints `17/17 examples passed`.

    This command exercises the whole startup path this lane changed --
    the cached venv resolution AND the lazy-import-safe `commands`
    package -- end to end, through the real entrypoint script.
    """
    proc = subprocess.run([str(BIN_SHEPHERD), "guard", "test"], capture_output=True, text=True, timeout=30)

    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "17/17 examples passed" in proc.stdout, proc.stdout


@pytest.mark.xdist_group(name="shepherd_venv_cache")
def test_stale_cache_missing_interpreter_falls_through_and_self_heals(preserved_venv_cache) -> None:
    """#266 guarantee: a cache naming a dead interpreter is never exec'd into.

    Simulates "venv deleted/moved, cache file left behind" -- exactly the
    shape this lane's brief warned a naive cache could get wrong ("a cache
    that survives a poetry install or a Python upgrade and then execs a
    dead interpreter is worse than the 300ms"). `bin/shepherd`'s fast path
    checks `[ -x "$CACHED_PY" ]` before trusting the cache; a nonexistent
    path fails that check, falls through to the real (slow) resolution,
    which succeeds normally and rewrites the cache to a real path.
    """
    VENV_PY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VENV_PY_CACHE.write_text("/nonexistent/dead-interpreter/python\n")

    proc = subprocess.run([str(BIN_SHEPHERD), "--version"], capture_output=True, text=True, timeout=30)

    assert proc.returncode == 0, f"a stale cache must self-heal, not fail: {proc.stderr}"
    assert _VERSION_RE.fullmatch(proc.stdout.strip()), proc.stdout

    assert VENV_PY_CACHE.is_file(), "cache file should have been rewritten after falling through"
    healed_path = VENV_PY_CACHE.read_text().strip()
    assert Path(healed_path).is_file() and os.access(healed_path, os.X_OK), (
        f"cache after self-heal points at a non-executable path: {healed_path!r}"
    )


@pytest.mark.xdist_group(name="shepherd_venv_cache")
def test_stale_cache_unprovisioned_interpreter_is_not_trusted(preserved_venv_cache, tmp_path: Path) -> None:
    """#266 guarantee: a cached path that exists but is not provisioned is rejected.

    Sharper than the dead-interpreter case: the cached path here is real
    and executable (a bare `[ -x ]` check alone would wrongly trust it),
    but the "venv" it names has no `shepherd` console script and no
    `typer` package -- `venv_provisioned()` (the SAME function the
    uncached path already trusts before every exec) must reject it too,
    or a corrupted/half-installed venv would get silently exec'd into on
    every subsequent call, permanently masking `poetry install` never
    having run -- the exact #266 incident this cache must not reintroduce.
    """
    fake_python = tmp_path / "fake-venv" / "bin" / "python3"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_python.chmod(0o755)

    VENV_PY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    VENV_PY_CACHE.write_text(f"{fake_python}\n")

    proc = subprocess.run([str(BIN_SHEPHERD), "--version"], capture_output=True, text=True, timeout=30)

    # A wrongly-trusted fake_python would exec silently and print nothing
    # (its body is `exit 0`, ignoring all argv) -- real --version output is
    # always a version string, so this also proves it fell through rather
    # than execing into the unprovisioned interpreter.
    assert proc.returncode == 0, proc.stderr
    assert _VERSION_RE.fullmatch(proc.stdout.strip()), (
        f"stdout {proc.stdout!r} does not look like a real `shepherd --version` print -- "
        "bin/shepherd may have trusted the unprovisioned cached interpreter"
    )
