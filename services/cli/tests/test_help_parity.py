"""Cross-module ``-h``/``--help`` parity gate (GH #249's class of bug).

GH #249: ``shepherd dash --help`` and ``shepherd migrate --help`` did not
print help at all -- they silently executed the full command instead
(dashboard render, schema-migration apply). Fixed in
:mod:`shepherd_cli.commands.dash` / :mod:`shepherd_cli.commands.migrate`
(see their module docstrings' GH #249 notes). This module is the
mechanical regression gate for that ENTIRE class of bug, not just those
two modules: it walks EVERY command registered in
:mod:`shepherd_cli.app` (introspected dynamically -- never a hardcoded
list, so a new command added later is covered automatically), invokes
both ``<cmd> --help`` and ``<cmd> -h`` as real subprocesses (this
package's universal test-suite convention -- see ``conftest.py``'s module
docstring; never by importing ``shepherd_cli`` into the pytest process),
and asserts three things per invocation:

1. Exit code 0.
2. Non-empty stdout that mentions the command's own name (a real usage
   block, not silence).
3. ZERO filesystem mutation: every file under the isolated ``SHCTX_DB``/
   ``SHEPHERD_WORKDIR`` tree is byte-identical (path, mtime, size,
   sha256) before and after the call -- see :func:`_snapshot`.

Assertion 3 is airtight by construction (a whole-tree walk hashing every
file, not a spot-check of one or two paths), and it is checked for EVERY
command regardless of whether assertions 1/2 pass -- a command that
mutates state while ALSO failing to print help would be a strictly worse
finding than either failure alone, and this suite must not let that hide
behind an early assertion failure.

**This suite is allowed to be red for commands other than ``dash``/
``migrate``.** Per the lane instructions that produced it: any other
command that fails is a genuine, separate finding (most of this
package's ~40 command modules never claimed ``-h`` parity with
``--help`` in the first place -- see ``CATALOGUED FAILURES`` below), not
a reason to weaken this test with an xfail/skip list. Every currently-
known failure is catalogued in the module-level ``CATALOGUED FAILURES``
comment below with its root cause, verified empirically while building
this suite (a full audit run: every command x both flags, snapshotted
for mutation -- ZERO of the 84 combinations mutated anything, so every
failure below is an exit-code/stdout-content gap, never data loss).

CATALOGUED FAILURES (as of this suite's authorship -- re-verify against
current `pytest -q tests/test_help_parity.py -k "not dash and not
migrate"` output before treating this list as current):

* Twelve Typer sub-app GROUPS never override Click's default
  ``help_option_names`` (only ``--help`` is recognized) and have no
  eager ``-h`` option of their own: ``adapt``, ``deliverable``, ``lock``,
  ``loop``, ``mem``, ``render``, ``report``, ``run``, ``signal``,
  ``sprint``, ``status``, ``teammate``. Their ``-h`` invocation fails
  fast inside Click's own option parser (``No such option: -h``, exit 2,
  message on stderr) BEFORE any subcommand dispatch -- safe (assertion 3
  always passes) but assertions 1/2 fail.
* Four single-verb, catch-all-argv modules (the same shape as
  ``dash``/``migrate`` pre-#249) do not special-case ``-h`` at all, so
  it is consumed as if it were real positional data and the command
  actually attempts to run, then fails ITS OWN validation on the
  literal string ``"-h"``: ``export`` (``ERROR: unknown export kind:
  -h``), ``inject`` (``ERROR: unknown role: -h``), ``query`` (``ERROR:
  query not found: -h``), ``style`` (``ERROR: no project registered``).
  Exit 1, message on stderr, no help text -- same root cause as #249,
  scoped to modules outside this lane's file list.
* ``lint`` is the sharpest instance of the #249 bug class found outside
  ``dash``/``migrate``: ``shepherd lint -h`` does not error at all -- it
  silently runs the real lint check to completion (``lint: ok``, exit
  0). Confirmed side-effect-free only because ``lint`` itself happens to
  be read-only in this fixture's empty-workdir shape; a lint command
  with a real write path would make this a DATA-mutating instance of
  #249, not just a UX one.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, REPO_ROOT, build_full_schema_db, clean_env_dict


def _registered_commands() -> list[str]:
    """Every top-level command name ``shepherd_cli/app.py`` registers.

    Introspected via a subprocess (never imported into the pytest
    process itself -- matching ``conftest.py``'s module-wide contract)
    against the REAL ``typer.Typer`` app object, so this list can never
    drift out of sync with ``app.py``'s actual ``add_typer``/``command``
    registrations the way a hand-maintained tuple could.

    Returns:
        Every registered top-level command name, sorted (e.g.
        ``"close-lane"``, ``"dash"``, ``"migrate"``, ...).
    """
    code = (
        "import json\n"
        "import typer.main\n"
        "from shepherd_cli.app import app\n"
        "click_app = typer.main.get_command(app)\n"
        "print(json.dumps(sorted(click_app.commands.keys())))\n"
    )
    proc = subprocess.run(
        [PY, "-c", code],
        env=clean_env_dict(),
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"failed to introspect shepherd_cli.app's registered commands: {proc.stderr}"
    return json.loads(proc.stdout)


#: Computed once at import time, exactly like ``test_migrate.py``'s
#: ``_SHIPPED_MIGRATIONS`` -- every node below automatically tracks
#: whatever ``shepherd_cli/app.py`` registers today, no manual upkeep.
_COMMANDS: list[str] = _registered_commands()

assert len(_COMMANDS) >= 30, f"expected ~40 registered commands, found only {len(_COMMANDS)}: {_COMMANDS}"
assert "dash" in _COMMANDS and "migrate" in _COMMANDS, _COMMANDS


def _sha256(path: Path) -> str:
    """The sha256 hex digest of one file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    """``{relative_path: (mtime_ns, size, sha256)}`` for every file under ``root``.

    The airtight mutation check this whole suite exists to run: a
    directory-wide walk hashing every file's full CONTENT (not just size
    or mtime, either of which a pathological write could preserve by
    accident -- e.g. an in-place rewrite of identical length at the same
    second) plus its exact byte size and nanosecond mtime, keyed by path
    relative to ``root`` so the comparison is stable across the two
    ``tmp_path``-derived absolute paths a before/after pair would
    otherwise differ on for no real reason.

    Args:
        root: The directory tree to snapshot (need not exist yet -- an
            absent root is a valid, empty snapshot, matching the "SHCTX_DB
            file itself does not exist yet" shape some commands' help
            paths are exercised under).

    Returns:
        The snapshot dict, empty if ``root`` does not exist or contains
        no files.
    """
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size, _sha256(p)) for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def help_root(tmp_path: Path) -> Path:
    """A full-schema DB + empty workdir, both inside one isolated tree.

    Several commands' ``-h``/``--help`` handling deliberately gates on
    the registry DB existing FIRST -- bash parity, see e.g.
    :func:`shepherd_cli.commands.panes._require_db`'s and
    :mod:`shepherd_cli.commands.models`'s own docstrings ("the script-top
    DB gate runs BEFORE the case arm that prints usage, so a missing
    registry DB beats a help request"). A nonexistent DB would make even
    a CORRECT help handler exit 1 there, which is not what this suite is
    testing for -- building a real, up-to-date DB lets every command's
    help path reach its own normal exit-0 branch, while
    :func:`_snapshot` below still catches any mutation to it (or to the
    workdir) that a help invocation must never cause.

    Returns:
        The isolated root directory (``tmp_path`` itself); ``shepherd.db``
        and ``work/`` live directly under it.
    """
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    (tmp_path / "work").mkdir()
    return tmp_path


def _help_env(root: Path) -> dict[str, str]:
    """The subprocess environment for one ``help_root``-scoped CLI invocation."""
    env = clean_env_dict()
    env["SHCTX_DB"] = str(root / "shepherd.db")
    env["SHEPHERD_WORKDIR"] = str(root / "work")
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env


@pytest.mark.parametrize("flag", ["--help", "-h"])
@pytest.mark.parametrize("cmd", _COMMANDS)
def test_help_flag_prints_usage_and_mutates_nothing(help_root: Path, cmd: str, flag: str) -> None:
    """``<cmd> <flag>`` must exit 0, print real usage, and touch nothing.

    See the module docstring's ``CATALOGUED FAILURES`` list: this node
    is expected to be RED for every command listed there (a real,
    separate finding each, not something this test hides) and GREEN for
    ``dash``/``migrate`` (this lane's GH #249 fix) and every other
    already-correct command.
    """
    env = _help_env(help_root)
    before = _snapshot(help_root)

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", cmd, flag],
        env=env,
        cwd=str(help_root),
        capture_output=True,
        text=True,
        timeout=15,
    )

    after = _snapshot(help_root)
    assert after == before, (
        f"{cmd!r} {flag} mutated the filesystem under {help_root} "
        f"(exit={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}):\n"
        f"before={before}\nafter={after}"
    )
    assert proc.returncode == 0, (
        f"{cmd!r} {flag} exited {proc.returncode} instead of 0 "
        f"(stdout={proc.stdout!r}, stderr={proc.stderr!r})"
    )
    assert proc.stdout.strip() != "", f"{cmd!r} {flag} produced no stdout (stderr={proc.stderr!r})"
    assert cmd in proc.stdout, f"{cmd!r} {flag} stdout does not mention the command's own name: {proc.stdout!r}"


# --------------------------------------------------------------------------
# dash/migrate-specific pin: this lane's GH #249 fix, isolated from the
# whole-suite sweep above so a regression in EITHER of these two modules
# fails loudly and specifically, independent of any other command's
# (expected, catalogued) failures.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cmd", ["dash", "migrate"])
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_dash_and_migrate_help_never_execute_the_command(help_root: Path, cmd: str, flag: str) -> None:
    """GH #249's own regression pin: no DB open, no graph walk, no migration apply."""
    env = _help_env(help_root)
    before = _snapshot(help_root)

    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", cmd, flag],
        env=env,
        cwd=str(help_root),
        capture_output=True,
        text=True,
        timeout=15,
    )

    after = _snapshot(help_root)
    assert after == before, f"{cmd!r} {flag} mutated the filesystem: before={before} after={after}"
    assert proc.returncode == 0, proc.stderr
    assert cmd in proc.stdout
    assert proc.stderr == ""
    # The command's own real-run markers must never appear in help output.
    if cmd == "dash":
        assert "═══ SHEPHERD DASH ═══" not in proc.stdout
        assert "SPRINT      schema=" not in proc.stdout
    else:
        assert "no migrations pending" not in proc.stdout
        assert "applied" not in proc.stdout
