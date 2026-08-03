"""``shepherd init`` — scaffold the per-project shepherd namespace + registry DB.

Native port of ``skills/context/scripts/cmd_init.sh`` (v6.3.3, #200-era) and
the ``scaffold.sh`` helper it shells out to. A single, flags-only verb (no
subcommands) that:

1. Resolves the target namespace directory (``.shepherd/`` by default,
   ``.artifacts/`` with ``--artifacts``, or whichever already exists —
   see :mod:`shepherd_cli.resolution`'s ``resolve_workdir``) and scaffolds
   its directory tree, ``.gitignore``, and ``CONVENTIONS.md`` (bash:
   ``scaffold.sh``).
2. Seeds ``shepherd.db`` from ``schema/0001_init.sql`` if it does not yet
   exist, then gap-fills every pending migration up to HEAD, NARRATING
   each one to stderr (bash: ``shctx_apply_pending_migrations`` — the
   v6.3.3 #200 self-heal apply loop; see the "DB bootstrap" section
   below for why this module reimplements it locally instead of calling
   the silent :func:`shepherd_cli.db.ensure_migrated`).
3. Registers the host project (a ``projects`` row + ``project.json``) the
   first time ``init`` runs for this namespace — idempotent on every
   later run.
4. Auto-triggers the artifacts refresh — an IN-PROCESS call to
   :func:`shepherd_cli.refresh_impl.refresh_artifacts`, the native port of
   the ``refresh-artifacts.sh`` script bash shelled out to here — when
   pre-existing markdown content is detected under the freshly-scaffolded
   namespace, so a namespace re-pointed at an already-populated repo gets
   indexed without a separate ``refresh --scope=artifacts`` call.
5. (v6.4.2, THE SEAMLESS-BOOTSTRAP ADDITION) Scaffolds the project
   ``shepherd.toml`` if absent, by calling
   :func:`shepherd_cli.commands.config._do_init` IN-PROCESS — imported,
   never reimplemented or copied (lane P1 owns every byte of that
   decision: the destination path, the idempotency guards, the derived
   ``[project]``/``[gates]`` values). Opt out with ``--no-config``.
6. (v6.4.2) Optionally bootstraps ``~/.shepherd`` by calling
   :func:`shepherd_cli.commands.home.init` IN-PROCESS (imported, same
   reasoning as step 5) — the ONE new step that touches ``$HOME``, so
   unlike every other new step here it is opt-IN via ``--user`` (default
   OFF).
7. (v6.4.2) Prints a closing bootstrap summary — created vs. already
   present, for every one of the five things above — then, unless
   ``--no-doctor``, runs :func:`shepherd_cli.commands.doctor.run` (same
   in-process reuse) and prints its findings inline, so one command
   both builds AND verifies the project.

WHY STEPS 5-7 ARE A SEPARATE, LATER PASS — NOT FOLDED INTO STEPS 1-4
=============================================================================
Every new step runs strictly AFTER the existing pipeline (through the
trailing auto-refresh) has already put the DB in a known-good state.
:func:`shepherd_cli.commands.doctor.run` reads that state (schema
version, ``project.json``, refresh timestamps) — running it any earlier
would diagnose a namespace ``init`` hadn't finished building yet. The
config/home scaffolds have no such DB dependency, but keeping ALL THREE
new steps in one late, clearly-labeled block (rather than interleaving
step 5 between the existing steps 1-4) keeps the "existing narrow
behavior, still reachable" contract simple: ``--no-config --no-doctor``
(without ``--user``) reproduces the EXACT pre-v6.4.2 ON-DISK effect
(nothing before this block in :func:`_init_impl` changed at all — no
``shepherd.toml`` is written, no doctor pass runs, ``~/.shepherd`` is
never touched). Stdout gains one new, ALWAYS-printed block regardless of
either flag — the closing "bootstrap summary" (step 7's first half) —
since the task's own flag list opts out of the config scaffold and the
doctor pass specifically, not the summary reporting what each step did;
:func:`_print_bootstrap_summary` still runs unconditionally and simply
reports ``skipped (--no-config)`` / omits the doctor-pass header when
asked to.

COUPLING NOTE — the config-scaffold import name is P1's, not a stable contract
=============================================================================
:func:`_maybe_scaffold_config` imports ``shepherd_cli.commands.config._do_init``
by its CURRENT name. Lane P1 owns ``commands/config.py`` and is concurrently
moving the canonical ``shepherd.toml`` write target to ``<workdir>/
shepherd.toml``; this module deliberately never constructs that destination
path itself (see :func:`_maybe_scaffold_config`'s own docstring) so the move
is inherited automatically the moment P1 lands it. If P1 additionally renames
``_do_init`` to a public name (the natural follow-on to "public scaffold
function"), only this one import line needs updating — nothing else in this
module encodes any assumption about ``config.py``'s destination path or
internal shape.

ARCHITECTURE — flag pre-parsing BEFORE any path resolution
=============================================================================
``cmd_init.sh`` parses ``--artifacts``/``--shepherd``/``-h``/``--help``
in a raw ``for arg in "$@"`` loop and ``export``s ``SHCTX_ROOT_OVERRIDE``
BEFORE ever sourcing ``_lib.sh`` — so the override takes effect on the
VERY FIRST call to ``resolve_workdir()`` (bash: ``shctx_artifacts_root``).
:func:`_apply_flags` mirrors this exactly: it mutates
``os.environ["SHCTX_ROOT_OVERRIDE"]`` directly (not a local variable)
BEFORE :func:`_init_impl` calls
:func:`shepherd_cli.resolution.resolve_workdir` for the first time, so
every downstream resolution call (including the trailing in-process
artifacts refresh, which resolves through this same environment) sees
the same override a real ``export`` would have set.

ARCHITECTURE DEVIATION FROM HARD RULE 7 (fully synchronous, no
``db.lifespan()``/Tortoise/asyncio, and a LOCAL migration-apply loop
instead of :func:`shepherd_cli.db.ensure_migrated`) — same justification
as :mod:`shepherd_cli.commands.doctor` AND :mod:`shepherd_cli.commands.migrate`
=============================================================================
Every other DB-touching command in this package is "a thin sync Typer
wrapper around ``asyncio.run(_impl_async())`` inside ``async with
db.lifespan():``" (hard rule 7). This module deliberately does NOT follow
that shape, for two independent reasons:

1. ``db.lifespan()`` opens a Tortoise connection immediately, and
   aiosqlite/Tortoise will happily create an empty sqlite file the
   instant it connects to a path that does not exist yet — but this
   command's entire job for a FRESH namespace is to create that file
   from ``0001_init.sql`` first, via a plain ``sqlite3.executescript()``
   call, and ``Tortoise.init`` racing (or simply preceding) that raw
   script against the same file is exactly the kind of "two independent
   sqlite handles fighting over one freshly-created file" hazard hard
   rule 1 (never call ``generate_schemas``) exists to avoid in spirit.
2. ``cmd_init.sh``'s own ``shctx_apply_pending_migrations`` call
   NARRATES every migration it applies (``echo "shctx migrate: applying
   $fname" >&2``, from ``_lib.sh``) — real, observable, bash-parity-
   relevant stderr output, verified empirically against the actual bash
   script. :func:`shepherd_cli.db.ensure_migrated` is DELIBERATELY silent
   (see its own docstring: it exists as an internal self-heal for every
   OTHER command's ``db.lifespan()``, which must never narrate). Calling
   it here would silently drop this observable bash behavior. Instead,
   :func:`_apply_pending_migrations` is a local, narrated reimplementation
   of the identical gap-fill algorithm — duplicated from
   :mod:`shepherd_cli.commands.migrate`'s own identically-shaped
   ``_apply_pending_migrations`` (not imported: hard rule 9's "each
   command module stays self-contained", the same reason
   :mod:`shepherd_cli.commands.sync` duplicates rather than imports
   :mod:`shepherd_cli.commands.sprint`'s ``_scripts_dir()``/``_run_stage()``).

There is also nothing here an ORM query buys: every DB touch is either
"run a canned ``.sql`` file" (:func:`_create_base_schema`,
:func:`_apply_pending_migrations`) or one ``INSERT OR IGNORE`` whose
column list (``scope``, ``tags``, ``created_at``, ``updated_at``) extends
past the read-scoped :class:`shepherd_cli.models.Project` model (hard
rule 3's raw-SQL escape hatch) — plain, synchronous ``sqlite3`` is the
correct, simplest tool for both, exactly like
:mod:`shepherd_cli.commands.doctor`'s own justified deviation.

COLLISION-RULE NOTE — no ``models_init.py``
=============================================================================
No Tortoise model is declared for this command: the base-schema apply and
the migration gap-fill are canned ``.sql`` files (hard rule 8's "raw SQL
for a poor ORM fit" — a multi-statement script, not a queryable row
shape), and the one row this module ever writes
(``INSERT OR IGNORE INTO projects (...)``) needs columns
(``scope``/``tags``/``created_at``/``updated_at``) the existing read-scoped
:class:`shepherd_cli.models.Project` deliberately omits — hard rule 3's
"use raw parameterized SQL instead of redeclaring" applies directly, and
since every DB touch in this module already goes through plain
``sqlite3.connect()`` (never Tortoise — see the architecture note above),
there is nothing left for an ORM model to mirror.

BASH-PARITY NOTES (all preserved deliberately)
=============================================================================
* The ``mkdir -p ROOT/{...}`` brace-expansion dir set, the ``.gitkeep``
  placeholder set, the verbatim ``.gitignore`` content, and the
  ``CONVENTIONS.md`` copy are all reproduced byte-for-byte from
  ``scaffold.sh`` (see :data:`_SCAFFOLD_DIRS`, :data:`_GITKEEP_DIRS`,
  :data:`_GITIGNORE_CONTENT`) — every one of these steps is idempotent
  (``exist_ok=True`` / "only write if absent"), matching bash's own
  ``mkdir -p`` / ``[[ ! -f ... ]] &&`` guards.
* The dual-namespace **conflict guard** (refuse to scaffold ``.shepherd/``
  fresh when ``.artifacts/.gitignore`` already marks that namespace as
  initialized, and vice versa) only fires when the TARGET directory does
  not yet exist — :func:`_conflict_guard` is called only when
  ``not os.path.isdir(root)``, exactly like bash's own
  ``if [[ ! -d "$root" ]]; then ...``.
* The **projects INSERT** uses parameterized SQL (``?`` placeholders)
  rather than bash's raw string interpolation
  (``VALUES ('$pid', '$name', '$scope_json', ...)``\\ ) — a deliberate,
  never-observable safety improvement (bash's version would produce
  malformed SQL, not silently-wrong data, for a repo directory name
  containing a literal ``'``; parameter binding avoids that failure mode
  entirely while producing byte-identical stored values for every input
  bash itself handles correctly).
* ``now``/``scaffolded_at`` are two INDEPENDENT calls to the current
  epoch-SECONDS clock, exactly mirroring bash's own two separate
  ``$(shctx_now)`` invocations (one captured into ``now`` before the
  ``INSERT``, one inlined directly into the ``jq -nc --argjson at
  "$(shctx_now)"`` pidfile-write) — they are allowed to differ by a
  fraction of a second under real clock jitter, and this port does not
  paper over that by reusing a single timestamp for both.
* The **auto-refresh trigger**'s pre-existing-markdown scan
  (:func:`_count_preexisting_markdown`) DELIBERATELY double-counts a file
  that lives under BOTH a specific scanned subdir (e.g. ``docs/plans``)
  AND the catch-all ``docs`` scan — bash's own ``for d in plans reports
  docs/plans docs/reports docs`` loop sums every zone independently with
  no de-duplication; this is preserved exactly (it only affects the
  human-readable "detected N pre-existing markdown file(s)" count, not
  which files the artifacts refresh itself indexes).
* The trailing artifacts refresh (bash: ``bash "$HERE/refresh-artifacts.sh"``,
  now :func:`shepherd_cli.refresh_impl.refresh_artifacts` in-process) is
  UNCONDITIONALLY the last statement bash's ``set -e`` script executes
  when it fires at all — a nonzero exit there aborts the whole script
  with that same exit code. :func:`_maybe_auto_refresh` mirrors this by
  propagating the refresh's returned exit code as this command's own
  ``typer.Exit`` code, rather than swallowing it — the exact same
  exit-code contract the former subprocess call had.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass

import typer

from shepherd_cli import refresh_impl
from shepherd_cli.commands.config import _do_init as _scaffold_config
from shepherd_cli.commands.doctor import run as _run_doctor
from shepherd_cli.resolution import (
    find_migrations_dir,
    find_schema_base,
    resolve_db_path,
    resolve_repo_root,
    resolve_user_home,
    resolve_workdir,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach the
    # callback's token loop and print the verbatim bash usage (parity),
    # matching commands/search.py / sync.py / models.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="Scaffold the per-project shepherd namespace tree, create shepherd.db, and register the host project.",
)

#: Verbatim bash-parity usage text — the ``-h|--help`` heredoc in
#: ``cmd_init.sh``. Printed to stdout (bash parity: plain ``cat``, not
#: stderr) on ``-h``/``--help``.
_HELP_TEXT = (
    "shctx init [--artifacts|--shepherd] [--no-config] [--no-doctor] [--user]\n"
    "\n"
    "Scaffold the per-project shepherd namespace tree, create shepherd.db,\n"
    "register the host project, scaffold shepherd.toml, and run a closing\n"
    "doctor pass — one command, a fully configured project.\n"
    "\n"
    "Default: .shepherd/ (v5.0.0+). If either .shepherd/ or .artifacts/ already\n"
    "exists in the repo, that one is used (auto-detect). Use --artifacts to force\n"
    "the legacy .artifacts/ namespace for a NEW init.\n"
    "Legacy projects using root.db are detected automatically and left untouched.\n"
    "\n"
    "  --no-config   Skip scaffolding shepherd.toml.\n"
    "  --no-doctor   Skip the closing doctor pass.\n"
    "  --user        Also bootstrap ~/.shepherd (shepherd home init). Off by\n"
    "                default — the one step here that touches $HOME."
)

#: The ``mkdir -p ROOT/{archive,cache,ctx,docs/{...},logs,scripts,templates,
#: tmp,types,profiles,styles}`` brace-expansion set from ``scaffold.sh``,
#: in the exact order bash's brace expansion produces it. ``docs`` itself
#: is never listed as a bare mkdir target (bash never creates it empty
#: either) — it is created implicitly as the parent of every ``docs/*``
#: entry below.
_SCAFFOLD_DIRS: tuple[str, ...] = (
    "archive",
    "cache",
    "ctx",
    os.path.join("docs", "plans"),
    os.path.join("docs", "reports"),
    os.path.join("docs", "handoffs"),
    os.path.join("docs", "specs"),
    os.path.join("docs", "diagrams"),
    os.path.join("docs", "journal"),
    "logs",
    "scripts",
    "templates",
    "tmp",
    "types",
    "profiles",
    "styles",
)

#: ``scaffold.sh``'s two ``.gitkeep`` loops, concatenated in their own
#: order (new tracked dirs first, then the "retained dirs" second batch) —
#: order has no observable effect (each iteration is an independent
#: idempotent touch), kept for a literal transliteration anyway.
_GITKEEP_DIRS: tuple[str, ...] = (
    "archive",
    "scripts",
    "templates",
    "types",
    os.path.join("docs", "plans"),
    os.path.join("docs", "reports"),
    os.path.join("docs", "journal"),
    os.path.join("docs", "handoffs"),
    os.path.join("docs", "diagrams"),
)

#: Verbatim byte-for-byte content of ``scaffold.sh``'s ``cat > "$gi"
#: <<'EOF' ... EOF`` heredoc (quoted-``EOF`` — no shell variable
#: expansion), written only when ``.gitignore`` does not already exist.
_GITIGNORE_CONTENT = (
    "# shepherd context registry — gitignored by default.\n"
    "# Remove these lines to commit the registry to the repo.\n"
    "#\n"
    "# New standard DB name (v6.1.0+):\n"
    "shepherd.db\n"
    "shepherd.db-journal\n"
    "shepherd.db-wal\n"
    "shepherd.db-shm\n"
    "# Legacy DB name (retained for back-compat — do not remove):\n"
    "root.db\n"
    "root.db-journal\n"
    "root.db-wal\n"
    "root.db-shm\n"
    "shepherd.lock\n"
    "project.json\n"
    "\n"
    "# Transient runtime dirs (never tracked).\n"
    "tmp/\n"
    "logs/\n"
    "cache/\n"
    "runs/\n"
    "dispatch/\n"
    "discoveries/\n"
    "insights/\n"
    "pauses/\n"
    "\n"
    "# Secret hygiene — never commit credentials/keys from the work dir.\n"
    "*.env\n"
    ".env\n"
    "*.key\n"
    "*.pem\n"
    "*.secret\n"
    "secrets/\n"
    "credentials*\n"
    "\n"
    "# Tracked subtrees stay tracked:\n"
    "# docs/ styles/ profiles/ ctx/ archive/ scripts/ templates/ types/\n"
)

#: ``cmd_init.sh``'s trailing auto-refresh scan zones, IN ORDER —
#: ``for d in plans reports docs/plans docs/reports docs``. Deliberately
#: overlapping (see the module docstring's double-count note).
_MD_SCAN_DIRS: tuple[str, ...] = (
    "plans",
    "reports",
    os.path.join("docs", "plans"),
    os.path.join("docs", "reports"),
    "docs",
)

#: Matches a shipped migration filename, capturing its 4-digit version —
#: mirrors :mod:`shepherd_cli.db`'s and
#: :mod:`shepherd_cli.commands.migrate`'s identical pattern (duplicated
#: here, not imported, per this package's self-contained-command-module
#: convention — see e.g. :mod:`shepherd_cli.commands.mem`'s own
#: ``_uuid7``).
_MIGRATION_NAME_RE = re.compile(r"^(\d{4})_.*\.sql$")

#: sqlite error substrings that mean "a sibling process (or an out-of-band
#: apply) already applied this migration" rather than a real failure —
#: mirrors :func:`shepherd_cli.db.ensure_migrated`'s /
#: :mod:`shepherd_cli.commands.migrate`'s identical tolerance list.
_TOLERATED_ERROR_MARKERS = ("duplicate column", "already exists")


@dataclass(frozen=True, slots=True)
class _Flags:
    """Parsed opt-out/opt-in switches for the v6.4.2 seamless-bootstrap steps.

    Only the THREE new tokens live here — ``--artifacts``/``--shepherd``
    stay a direct ``os.environ["SHCTX_ROOT_OVERRIDE"]`` write inside
    :func:`_apply_flags` itself (see that function's own docstring), not a
    field on this dataclass, so the existing pre-path-resolution ordering
    guarantee (module docstring's first ARCHITECTURE note) is untouched.

    Attributes:
        no_config: Skip step 5 (the ``shepherd.toml`` scaffold) entirely
            when True — the existing narrow pre-v6.4.2 behavior stays
            reachable via ``--no-config --no-doctor``.
        no_doctor: Skip step 7's closing doctor pass when True. The
            closing bootstrap summary (also step 7) still prints — only
            the doctor report is opted out of.
        user: Also run step 6 (``shepherd home init``) when True. Default
            OFF, unlike ``no_config``/``no_doctor``: this is the one new
            step that writes outside the project (``~/.shepherd``), so it
            stays opt-IN rather than opt-OUT.
    """

    no_config: bool = False
    no_doctor: bool = False
    user: bool = False


# --------------------------------------------------------------------------
# Flag parsing (bash-parity port of cmd_init.sh's pre-``_lib.sh`` loop).
# --------------------------------------------------------------------------
def _apply_flags(argv: list[str]) -> _Flags:
    """Parse ``shctx init``'s flags, mirroring ``cmd_init.sh``'s ``for arg in "$@"`` loop.

    Every token is visited in order; ``--artifacts``/``--shepherd`` sets
    ``os.environ["SHCTX_ROOT_OVERRIDE"]`` DIRECTLY (bash: ``export
    SHCTX_ROOT_OVERRIDE=...``) so it is visible to every downstream
    ``resolve_workdir()`` call in this same process — plain
    reassignment, last flag wins, exactly like bash's ``export`` inside a
    ``case`` arm. ``--no-config``/``--no-doctor``/``--user`` (v6.4.2, new)
    are plain boolean accumulation into the returned :class:`_Flags` — no
    env var, no path-resolution interaction, so they carry none of the
    ordering sensitivity ``--artifacts``/``--shepherd`` do. ``-h``/
    ``--help`` and an unrecognized token both short-circuit immediately,
    from ANY position in ``argv``.

    Args:
        argv: Every token given to ``shepherd init`` after the command
            name itself, in order.

    Returns:
        The accumulated :class:`_Flags` — last-token-wins for each field,
        exactly like the ``SHCTX_ROOT_OVERRIDE`` reassignment above (a
        flag repeated, or contradicted by nothing, simply stays True once
        set; there is no negating counterpart to any of the three).

    Raises:
        typer.Exit: Code 0, after printing :data:`_HELP_TEXT` to stdout,
            the instant an ``-h``/``--help`` token is reached. Code 1,
            after printing ``"ERROR: unknown init flag: <token>"`` to
            stderr (bash's exact message — note "init flag", not the
            generic "unknown arg" other ports use), the instant a token
            matching none of the recognized shapes is reached.
    """
    no_config = False
    no_doctor = False
    user = False
    for arg in argv:
        if arg == "--artifacts":
            os.environ["SHCTX_ROOT_OVERRIDE"] = ".artifacts"
        elif arg == "--shepherd":
            os.environ["SHCTX_ROOT_OVERRIDE"] = ".shepherd"
        elif arg == "--no-config":
            no_config = True
        elif arg == "--no-doctor":
            no_doctor = True
        elif arg == "--user":
            user = True
        elif arg in ("-h", "--help"):
            typer.echo(_HELP_TEXT)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown init flag: {arg}", err=True)
            raise typer.Exit(code=1)
    return _Flags(no_config=no_config, no_doctor=no_doctor, user=user)


# --------------------------------------------------------------------------
# Scaffold (bash: scaffold.sh).
# --------------------------------------------------------------------------
def _conflict_guard(root: str, repo: str) -> None:
    """Refuse to scaffold a NEW namespace when the OTHER is already initialized.

    Bash parity with ``scaffold.sh``'s conflict guard: only reachable
    when the TARGET directory (``root``) does not yet exist on disk (the
    caller checks this). Fires when the target is ``.shepherd/`` and
    ``<repo>/.artifacts/.gitignore`` already exists (a prior successful
    ``init --artifacts``), or the mirror-image case for a
    ``--artifacts``-targeted ``.artifacts/`` when
    ``<repo>/.shepherd/.gitignore`` already exists.

    Args:
        root: The resolved (not-yet-existing) target namespace directory.
        repo: The resolved repo root (``resolve_repo_root()``).

    Raises:
        typer.Exit: Code 1, after printing bash's exact multi-line stderr
            message for whichever direction the conflict is in, if a
            conflict is detected. No exception otherwise.
    """
    base = os.path.basename(root)
    if base == ".shepherd" and os.path.isfile(os.path.join(repo, ".artifacts", ".gitignore")):
        for line in (
            "ERROR: .artifacts/ is already an initialized shctx namespace.",
            "  Creating .shepherd/ alongside it would cause a split-brain where shctx",
            "  data and shepherd.toml [paths] entries diverge.",
            "",
            "  To keep using .artifacts/ (recommended for existing projects):",
            "    shctx init --artifacts",
            "",
            "  To migrate to .shepherd/ (new default):",
            "    mv .artifacts .shepherd  # move your content first",
            "    shctx init --shepherd",
        ):
            typer.echo(line, err=True)
        raise typer.Exit(code=1)
    if base == ".artifacts" and os.path.isfile(os.path.join(repo, ".shepherd", ".gitignore")):
        for line in (
            "ERROR: .shepherd/ is already an initialized shctx namespace.",
            "  Creating .artifacts/ alongside it would cause a split-brain.",
            "",
            "  To keep using .shepherd/ (recommended):",
            "    shctx init --shepherd",
        ):
            typer.echo(line, err=True)
        raise typer.Exit(code=1)


def _resolve_skill_root() -> str:
    """Resolve the ``skills/context`` skill root, for locating ``CONVENTIONS.md``'s source.

    Mirrors ``_lib.sh``'s ``shctx_skill_root`` three-tier precedence in
    full (``SHCTX_SKILL_ROOT`` env override -> ``CLAUDE_PLUGIN_ROOT``-
    relative -> walk-up-from-the-repo-root), the same shape
    :mod:`shepherd_cli.commands.style`'s own
    ``_resolve_bundled_styles_dir`` uses for its one ``skills/context``-
    relative need — kept local rather than added to
    :mod:`shepherd_cli.resolution`, per that module's disjoint-file-
    ownership contract for this porting wave.

    Returns:
        The resolved ``skills/context`` directory path (need not exist on
        disk — :func:`_copy_conventions` checks the actual source file
        itself before copying).
    """
    skill_root_env = os.environ.get("SHCTX_SKILL_ROOT", "")
    if skill_root_env:
        return skill_root_env

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        return os.path.join(plugin_root, "skills", "context")

    root = resolve_repo_root()
    current = root
    while True:
        candidate = os.path.join(current, "skills", "context")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.join(root, "skills", "context")
        current = parent


def _copy_conventions(root: str) -> None:
    """Seed ``CONVENTIONS.md`` from the bundled naming-conventions reference.

    Bash parity with ``scaffold.sh``'s ``cp "$(shctx_skill_root)/references/
    naming-conventions.md" "$conv"``, idempotent (only writes if absent,
    like every other step of the scaffold).

    Args:
        root: The (already-created) namespace directory.

    Raises:
        typer.Exit: Code 1, with a ``cp``-style stderr message, if the
            source reference file cannot be found — bash's own ``cp``
            would abort the whole script under ``set -e`` in this case
            (the source is genuinely missing from the install), so this
            port aborts too rather than silently skipping
            ``CONVENTIONS.md``.
    """
    conv = os.path.join(root, "CONVENTIONS.md")
    if os.path.isfile(conv):
        return
    skill_root = _resolve_skill_root()
    src = os.path.join(skill_root, "references", "naming-conventions.md")
    if not os.path.isfile(src):
        typer.echo(f"ERROR: cp: cannot stat '{src}': No such file or directory", err=True)
        raise typer.Exit(code=1)
    shutil.copyfile(src, conv)


def _scaffold(root: str, repo: str) -> None:
    """Create the namespace directory tree, ``.gitignore``, and ``CONVENTIONS.md``.

    Bash parity with ``scaffold.sh`` end to end: the conflict guard (only
    when ``root`` does not yet exist), the ``mkdir -p`` dir set, the
    ``.gitkeep`` placeholders, the ``.gitignore`` write, and the
    ``CONVENTIONS.md`` copy — every step idempotent, safe to call on
    every ``init`` invocation (fresh or re-run).

    Args:
        root: The resolved target namespace directory
            (``resolve_workdir()``).
        repo: The resolved repo root (``resolve_repo_root()``).

    Raises:
        typer.Exit: Propagated from :func:`_conflict_guard` (code 1) or
            :func:`_copy_conventions` (code 1).
    """
    if not os.path.isdir(root):
        _conflict_guard(root, repo)

    for rel in _SCAFFOLD_DIRS:
        os.makedirs(os.path.join(root, rel), exist_ok=True)

    for rel in _GITKEEP_DIRS:
        gitkeep = os.path.join(root, rel, ".gitkeep")
        if not os.path.isfile(gitkeep):
            open(gitkeep, "a", encoding="utf-8").close()

    gitignore = os.path.join(root, ".gitignore")
    if not os.path.isfile(gitignore):
        with open(gitignore, "w", encoding="utf-8") as fh:
            fh.write(_GITIGNORE_CONTENT)

    _copy_conventions(root)


# --------------------------------------------------------------------------
# DB bootstrap (bash: the sqlite3 + shctx_apply_pending_migrations block).
# --------------------------------------------------------------------------
def _create_base_schema(db_path: str, schema_sql_path: str) -> None:
    """Seed a brand-new sqlite file from ``0001_init.sql``.

    Bash parity with ``sqlite3 "$db" < "$(shctx_skill_root)/schema/
    0001_init.sql"``, only ever called when ``db_path`` does not already
    exist (the caller checks this). Uses plain stdlib ``sqlite3`` —
    exactly ``tests/conftest.py``'s own ``build_full_schema_db`` helper,
    which applies this same file the same way for every fixture DB in
    this test suite.

    Args:
        db_path: Where to create the sqlite file.
        schema_sql_path: Path to ``0001_init.sql`` (already resolved by
            the caller via ``find_schema_base()``).

    Raises:
        typer.Exit: Code 1, with a controlled stderr message, if the
            schema file cannot be read or the script fails to apply —
            bash's own ``sqlite3 ... < file`` would abort the whole
            script under ``set -e`` on either failure, so this port
            aborts too rather than leaving a half-seeded DB silently in
            place.
    """
    try:
        with open(schema_sql_path, encoding="utf-8") as fh:
            sql_text = fh.read()
    except OSError as exc:
        typer.echo(f"ERROR: failed to read base schema: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        connection = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        connection.executescript(sql_text)
        connection.commit()
    except sqlite3.Error as exc:
        typer.echo(f"ERROR: sqlite3: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        connection.close()


def _shipped_migrations(migrations_dir: str) -> list[tuple[int, str]]:
    """List shipped migration files as ``(version, filename)`` pairs, sorted.

    Duplicated from :mod:`shepherd_cli.commands.migrate`'s identical
    helper (not imported — self-contained-command-module convention).

    Args:
        migrations_dir: Directory to scan for ``NNNN_*.sql`` files.

    Returns:
        Pairs sorted by filename (equivalently by version, since the
        4-digit zero-padded prefix sorts identically either way) —
        matching the order bash's ``nullglob`` loop visits
        ``$migdir/[0-9][0-9][0-9][0-9]_*.sql`` in. Empty if the directory
        cannot be listed.
    """
    try:
        names = os.listdir(migrations_dir)
    except OSError:
        return []
    shipped = [
        (int(match.group(1)), name) for name in names if (match := _MIGRATION_NAME_RE.match(name)) is not None
    ]
    shipped.sort(key=lambda pair: pair[1])
    return shipped


def _apply_pending_migrations(db_path: str, migrations_dir: str) -> tuple[int, str | None]:
    """Apply every migration whose version is ABSENT from ``schema_versions``, narrated.

    Duplicated from :mod:`shepherd_cli.commands.migrate`'s identically-
    shaped ``_apply_pending_migrations`` (not imported — see the module
    docstring's architecture note): the SAME gap-fill algorithm and
    tolerated-error handling as ``_lib.sh``'s
    ``shctx_apply_pending_migrations`` /
    :func:`shepherd_cli.db.ensure_migrated`'s inner loop, but additionally
    narrating each application with ``typer.echo(..., err=True)`` — bash's
    ``echo "shctx migrate: applying $fname" >&2``.

    Args:
        db_path: Path to the sqlite database file. Assumed to already
            exist and contain ``schema_versions`` (the caller only
            invokes this after :func:`_create_base_schema` has run, for a
            fresh DB, or confirmed the file already existed).
        migrations_dir: Directory containing ``NNNN_*.sql`` migration
            files.

    Returns:
        A ``(applied, error)`` pair. ``error`` is ``None`` on full
        success (every pending migration applied or tolerated, or there
        was nothing to apply); otherwise it is the exact bash-parity
        message (``"shctx migrate: ERROR applying <fname>: <detail>"``,
        matching ``_lib.sh``'s own error text) for the FIRST hard failure
        encountered, and ``applied`` is the count of migrations that
        succeeded strictly before that failure — mirroring bash's own
        "stop at the first non-tolerated error" behavior.
    """
    shipped = _shipped_migrations(migrations_dir)
    if not shipped:
        return 0, None

    applied = 0
    try:
        connection = sqlite3.connect(db_path, isolation_level=None)
    except sqlite3.Error as exc:
        return 0, f"shctx migrate: ERROR opening db: {exc}"

    try:
        try:
            connection.execute("PRAGMA busy_timeout=5000;")
        except sqlite3.Error as exc:
            return 0, f"shctx migrate: ERROR opening db: {exc}"

        try:
            known_versions = {row[0] for row in connection.execute("SELECT version FROM schema_versions;")}
        except sqlite3.Error as exc:
            return 0, f"shctx migrate: ERROR reading schema_versions: {exc}"

        for version, fname in shipped:
            if version in known_versions:
                continue

            typer.echo(f"shctx migrate: applying {fname}", err=True)

            sql_path = os.path.join(migrations_dir, fname)
            try:
                with open(sql_path, encoding="utf-8") as fh:
                    sql_text = fh.read()
            except OSError as exc:
                return applied, f"shctx migrate: ERROR applying {fname}: {exc}"

            checksum = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
            try:
                connection.executescript(sql_text)
            except sqlite3.Error as exc:
                message = str(exc).lower()
                if not any(marker in message for marker in _TOLERATED_ERROR_MARKERS):
                    return applied, f"shctx migrate: ERROR applying {fname}: {exc}"
                # tolerated: a sibling process already applied this DDL --
                # fall through and still record the schema_versions row.

            try:
                connection.execute(
                    "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES (?, ?, ?);",
                    (version, int(time.time()), checksum),
                )
            except sqlite3.Error as exc:
                return applied, f"shctx migrate: ERROR applying {fname}: {exc}"

            applied += 1
            known_versions.add(version)
    finally:
        connection.close()

    return applied, None


def _bootstrap_db(db_path: str) -> int:
    """Seed (if absent) and gap-fill-migrate the project DB to HEAD, narrated.

    Bash parity with ``cmd_init.sh``'s::

        if [[ ! -f "$db" ]]; then
          sqlite3 "$db" < "$(shctx_skill_root)/schema/0001_init.sql" >/dev/null
        fi
        shctx_apply_pending_migrations >/dev/null \\
          || echo "shctx init: WARNING — schema migration incomplete; run 'shctx migrate'" >&2

    Runs UNCONDITIONALLY on every ``init`` invocation, not only for a
    fresh namespace — this is the source-side fix for #200: re-running
    ``init`` on an existing (possibly behind-HEAD) DB heals any drift,
    exactly like bash's own comment on this block explains. Every
    successfully-applied migration is narrated to stderr as it happens
    (see :func:`_apply_pending_migrations`); a missing migrations
    directory is silently treated as "nothing to apply" (bash:
    ``shctx_apply_pending_migrations``'s own ``[[ ! -d "$migdir" ... ]] &&
    echo 0 && return 0`` early-success return).

    Args:
        db_path: The resolved project database path
            (``resolve_db_path()``).

    Returns:
        The number of migrations actually applied by THIS call (0 when
        the DB was already at HEAD, or the migrations directory could not
        be located) — v6.4.2 addition, consumed by :func:`_init_impl`'s
        closing bootstrap summary so it can report "created" vs.
        "already present, at HEAD" vs. "already present, self-healed N"
        without re-deriving the gap-fill count independently (the exact
        "IMPORT IT, do not reimplement" discipline this module's docstring
        asks of the config/home reuse, applied here to its own internal
        helper instead of a sibling module's).

    Raises:
        typer.Exit: Code 1, propagated from :func:`_create_base_schema`,
            if a fresh DB's base-schema apply fails outright. No
            exception for an incomplete migration gap-fill — bash parity
            is a WARNING (plus the underlying ERROR line) to stderr, not
            a hard failure of the ``init`` command itself.
    """
    if not os.path.isfile(db_path):
        schema_base = find_schema_base()
        if schema_base is None:
            typer.echo("ERROR: base schema (0001_init.sql) not found", err=True)
            raise typer.Exit(code=1)
        _create_base_schema(db_path, schema_base)

    migrations_dir = find_migrations_dir()
    if migrations_dir is None:
        return 0

    applied, error = _apply_pending_migrations(db_path, migrations_dir)
    if error is not None:
        typer.echo(error, err=True)
        typer.echo("shctx init: WARNING — schema migration incomplete; run 'shctx migrate'", err=True)
    return applied


# --------------------------------------------------------------------------
# Project registration (bash: the pidfile branch).
# --------------------------------------------------------------------------
def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for the new ``projects`` row.

    Independent, equally-valid UUIDv7 generator over stdlib
    ``time``/``os.urandom`` — duplicated from
    :mod:`shepherd_cli.commands.mem`'s identical helper (not imported,
    per this package's self-contained-command-module convention). NOT
    byte-for-byte identical to bash's ``shctx_uuid7`` construction
    (different random source, different bit-packing helper); every id it
    produces is a spec-compliant, time-sortable UUIDv7, the only property
    either tool's rows actually depend on.

    Returns:
        A lowercase, hyphenated UUIDv7 string.
    """
    ts_ms = int(time.time() * 1000)
    raw = bytearray(16)
    raw[0:6] = ts_ms.to_bytes(6, "big")
    rand = os.urandom(10)
    raw[6] = 0x70 | (rand[0] & 0x0F)  # version nibble (0111) + 4 random bits
    raw[7] = rand[1]
    raw[8] = 0x80 | (rand[2] & 0x3F)  # variant bits (10) + 6 random bits
    raw[9:16] = rand[3:10]
    hex_str = raw.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


def _read_pidfile_id(pidfile: str) -> str:
    """Read ``.id`` back out of an existing ``project.json``.

    Bash parity with ``pid=$(jq -r '.id' "$pidfile")`` — a malformed
    ``project.json`` is a HARD failure in bash (the command substitution
    fails, and ``set -e`` aborts the whole script with ``jq``'s own error
    text); this port raises the same class of failure (controlled stderr
    message, exit 1) rather than silently defaulting.

    Args:
        pidfile: Path to the existing ``project.json``.

    Returns:
        The ``.id`` value as a string, or the literal three-character
        string ``"null"`` if the key is absent or JSON ``null`` (``jq
        -r``'s raw-output rendering of JSON ``null``).

    Raises:
        typer.Exit: Code 1, with a controlled stderr message, if the file
            cannot be read or is not valid JSON.
    """
    try:
        with open(pidfile, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR: failed to parse {pidfile} as JSON", err=True)
        raise typer.Exit(code=1) from exc
    raw_id = data.get("id") if isinstance(data, dict) else None
    return "null" if raw_id is None else str(raw_id)


def _insert_project(db_path: str, project_id: str, name: str, scope_json: str, now: int) -> None:
    """Insert the host project row, bash parity with ``INSERT OR IGNORE INTO projects``.

    Uses parameterized SQL rather than bash's raw string interpolation —
    see the module docstring's "projects INSERT" bash-parity note.
    ``tags`` is always the literal ``'[]'``, matching bash's own
    hardcoded value (this row is written exactly once, at scaffold time —
    nothing here ever sets a non-empty tag).

    Args:
        db_path: The resolved project database path.
        project_id: The freshly-generated UUIDv7 (:func:`_uuid7`).
        name: ``os.path.basename(repo)`` — the host repo's directory name.
        scope_json: A compact JSON array containing the repo root path,
            e.g. ``'["/repo/root"]'``.
        now: The current epoch-SECONDS timestamp, shared by
            ``created_at`` and ``updated_at`` (bash: one ``$(shctx_now)``
            call reused for both columns in the same INSERT).
    """
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT OR IGNORE INTO projects (id, name, scope, tags, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, scope_json, "[]", now, now),
        )
        connection.commit()
    finally:
        connection.close()


def _write_pidfile(pidfile: str, project_id: str, scaffolded_at: int) -> None:
    """Write ``project.json``, bash parity with the ``jq -nc`` pidfile write.

    Args:
        pidfile: Path to write (``<root>/project.json``).
        project_id: The freshly-generated UUIDv7.
        scaffolded_at: A FRESH epoch-SECONDS timestamp (bash: a second,
            independent ``$(shctx_now)`` call — see the module docstring's
            timestamp note; deliberately NOT the same ``now`` value used
            for the ``projects`` row's ``created_at``/``updated_at``).
    """
    payload = {"id": project_id, "scaffolded_at": scaffolded_at}
    with open(pidfile, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _register_project(root: str, repo: str, db_path: str) -> str:
    """Register the host project exactly once, bash parity with the pidfile branch.

    Bash::

        if [[ -f "$pidfile" ]]; then
          pid=$(jq -r '.id' "$pidfile")
        else
          pid=$(shctx_uuid7)
          name=$(basename "$(shctx_repo_root)")
          scope_json=$(jq -nc --arg p "$(shctx_repo_root)" '[$p]')
          now=$(shctx_now)
          shctx_sql "INSERT OR IGNORE INTO projects (...) VALUES (...);"
          jq -nc --arg id "$pid" --argjson at "$(shctx_now)" '{id:$id, scaffolded_at:$at}' > "$pidfile"
        fi

    Args:
        root: The resolved namespace directory (``project.json`` lives at
            its top level).
        repo: The resolved repo root — supplies both ``name`` (its
            basename) and the sole ``scope`` array entry.
        db_path: The resolved, already-bootstrapped project database path.

    Returns:
        The active project id — either read back from an existing
        ``project.json`` (:func:`_read_pidfile_id`) or the freshly
        generated one this call just registered.
    """
    pidfile = os.path.join(root, "project.json")
    if os.path.isfile(pidfile):
        return _read_pidfile_id(pidfile)

    project_id = _uuid7()
    name = os.path.basename(repo)
    scope_json = json.dumps([repo], separators=(",", ":"))
    now = int(time.time())
    _insert_project(db_path, project_id, name, scope_json, now)
    scaffolded_at = int(time.time())
    _write_pidfile(pidfile, project_id, scaffolded_at)
    return project_id


# --------------------------------------------------------------------------
# Auto-refresh trigger (bash: the trailing preexisting-markdown block).
# --------------------------------------------------------------------------
def _count_preexisting_markdown(root: str) -> int:
    """Count ``*.md`` files under every auto-refresh scan zone, bash parity.

    Bash::

        for d in plans reports docs/plans docs/reports docs; do
          if [[ -d "$root/$d" ]]; then
            n=$(find "$root/$d" -type f -name '*.md' | wc -l)
            preexisting_count=$((preexisting_count + n))
          fi
        done

    See the module docstring's double-count note: a file under both
    ``docs/plans`` and the catch-all ``docs`` zone is counted twice,
    deliberately, matching bash's own unconditional per-zone summation.

    Args:
        root: The resolved (already-scaffolded) namespace directory.

    Returns:
        The total ``*.md`` file count across every zone in
        :data:`_MD_SCAN_DIRS` that exists as a directory, doubled-counted
        overlaps included.
    """
    total = 0
    for rel in _MD_SCAN_DIRS:
        target = os.path.join(root, rel)
        if not os.path.isdir(target):
            continue
        for _dirpath, _dirnames, filenames in os.walk(target):
            total += sum(1 for name in filenames if name.endswith(".md"))
    return total


def _maybe_auto_refresh(root: str) -> None:
    """Trigger the artifacts refresh when pre-existing markdown content is found.

    Bash parity with ``cmd_init.sh``'s trailing block, which shelled out
    to the sibling ``refresh-artifacts.sh``. That script is now ported
    natively as :func:`shepherd_cli.refresh_impl.refresh_artifacts` — the
    SAME function ``shepherd refresh --scope=artifacts`` runs — so this
    step is an IN-PROCESS call, no ``bash`` subprocess. The function
    prints exactly what the script printed (unredirected, matching bash's
    own unredirected call) and returns a process-style exit code; it
    resolves the namespace/DB through the same environment
    (``SHCTX_ROOT_OVERRIDE`` et al.) the subprocess used to inherit,
    since :func:`_apply_flags` exports the override into ``os.environ``
    before this runs.

    Args:
        root: The resolved (already-scaffolded) namespace directory.

    Raises:
        typer.Exit: The refresh's own exit code, if nonzero — bash parity
            with ``set -e`` aborting the whole script on this
            (unconditionally last) statement's failure. No exception
            (implicit success) if no pre-existing markdown was found, or
            the refresh succeeded.
    """
    count = _count_preexisting_markdown(root)
    if count <= 0:
        return

    typer.echo(f"shctx: detected {count} pre-existing markdown file(s); auto-indexing")

    rc = refresh_impl.refresh_artifacts()
    if rc != 0:
        raise typer.Exit(code=rc)


# --------------------------------------------------------------------------
# Seamless-bootstrap additions (v6.4.2) — config scaffold, optional user-tier
# bootstrap, and the closing summary + doctor pass. See the module
# docstring's "WHY STEPS 5-7 ARE A SEPARATE, LATER PASS" note for why these
# run strictly after the pre-existing pipeline rather than being interleaved
# into it, and its "COUPLING NOTE" for why :func:`_maybe_scaffold_config`
# never constructs a ``shepherd.toml`` destination path of its own.
# --------------------------------------------------------------------------
def _maybe_scaffold_config(*, no_config: bool) -> str:
    """Step 5: scaffold the project ``shepherd.toml`` via lane P1's own scaffold.

    Calls :func:`shepherd_cli.commands.config._do_init` (imported as
    :data:`_scaffold_config` — never reimplemented or copied) IN-PROCESS,
    with its own stdout captured and re-emitted verbatim so its exact
    "scaffolded ..." / "already exists (preserving)" / local-override
    messages still reach the operator. This function never builds a
    ``.claude/shepherd.toml``-shaped (or any other) path itself — lane P1
    owns the destination entirely, including its concurrent move to
    ``<workdir>/shepherd.toml``; classification below reads only the
    MESSAGE ``_do_init`` chose to print, never a path this module derived.

    Args:
        no_config: When True (``--no-config``), skip the call entirely.

    Returns:
        One closing-summary line (see :func:`_print_bootstrap_summary`),
        already formatted, for: ``"skipped (--no-config)"`` when opted
        out; ``"already present"`` when ``_do_init`` preserved an existing
        file (project config or a local override); ``"created"`` when it
        wrote a fresh one; ``"scaffold failed (see stderr above)"`` when
        ``_do_init`` reported an installation defect (bundled template
        missing) — a soft failure, bash-parity with this module's own
        migration-gap-fill WARNING: it never aborts ``shepherd init``
        itself (namespace/db/project already succeeded by this point).
    """
    if no_config:
        return "shepherd.toml : skipped (--no-config)"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _scaffold_config(force=False)
    text = buffer.getvalue()
    typer.echo(text, nl=False)

    if "already exists (preserving)" in text or "local-override config is present" in text:
        return "shepherd.toml : already present"
    if "scaffolded " in text:
        return "shepherd.toml : created"
    return "shepherd.toml : scaffold failed (see stderr above)"


def _maybe_bootstrap_user(*, user: bool) -> str:
    """Step 6: optionally bootstrap ``~/.shepherd`` via ``shepherd home init``.

    Calls :func:`shepherd_cli.commands.home.init` (imported LOCALLY, only
    when ``user`` is True — see the inline comment below) IN-PROCESS, with
    its own stdout captured and re-emitted verbatim, same reuse contract
    as :func:`_maybe_scaffold_config`. Default OFF: this is the one new
    step in the whole seamless-bootstrap pipeline that writes outside the
    project directory, so unlike ``--no-config``/``--no-doctor`` it is
    opt-IN.

    Args:
        user: Whether ``--user`` was passed.

    Returns:
        One closing-summary line: ``"skipped ..."`` when not requested;
        otherwise ``"created (<home>)"`` if this call actually created
        either ``~/.shepherd/profiles`` or ``~/.shepherd/templates``, else
        ``"already present (<home>)"``.
    """
    if not user:
        return "user tier     : skipped (pass --user to also bootstrap ~/.shepherd)"

    # Deferred import: shepherd_cli.commands.home pulls in
    # shepherd_cli.render (and therefore jinja2) at module scope. --user
    # defaults OFF, so every OTHER `shepherd init` invocation should never
    # pay that import cost — see shepherd_cli.app's own module docstring
    # on why this package takes CLI-startup latency seriously.
    from shepherd_cli.commands.home import init as _home_init

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _home_init(profile=[])
    text = buffer.getvalue()
    typer.echo(text, nl=False)

    status = "created" if "created " in text else "already present"
    return f"user tier     : {status} ({resolve_user_home()})"


def _print_bootstrap_summary(
    *,
    namespace_existed: bool,
    root: str,
    db_existed: bool,
    migrations_applied: int,
    project_existed: bool,
    project_id: str,
    config_line: str,
    user_line: str,
) -> None:
    """Step 7 (part 1): print the closing "created vs. already present" summary.

    One line per bootstrap concern, in the SAME order :func:`_init_impl`
    performs them (namespace, db, project, shepherd.toml, user tier) — the
    idempotency contract this sprint requires ("running ``shepherd init``
    twice must ... report that clearly") is satisfied by construction: a
    second run's ``namespace_existed``/``db_existed``/``project_existed``
    are all True and ``migrations_applied`` is 0, so every line below
    reads "already present"/"already registered" verbatim, with nothing
    further to derive.

    Args:
        namespace_existed: Whether ``root`` already existed BEFORE
            :func:`_scaffold` ran this invocation.
        root: The resolved namespace directory.
        db_existed: Whether the DB file already existed BEFORE
            :func:`_bootstrap_db` ran this invocation.
        migrations_applied: :func:`_bootstrap_db`'s own return value —
            migrations applied THIS run (0 on an already-HEAD DB).
        project_existed: Whether ``project.json`` already existed BEFORE
            :func:`_register_project` ran this invocation.
        project_id: The active project id (fresh or read back).
        config_line: :func:`_maybe_scaffold_config`'s pre-formatted line.
        user_line: :func:`_maybe_bootstrap_user`'s pre-formatted line.
    """
    namespace_status = "already present" if namespace_existed else "created"
    if not db_existed:
        db_status = f"created ({migrations_applied} migration(s) applied)"
    elif migrations_applied > 0:
        db_status = f"already present ({migrations_applied} migration(s) self-healed)"
    else:
        db_status = "already present, at HEAD"
    project_status = "already registered" if project_existed else "registered"

    typer.echo("shctx init: bootstrap summary")
    typer.echo(f"  namespace     : {namespace_status} ({root})")
    typer.echo(f"  db            : {db_status}")
    typer.echo(f"  project       : {project_status} (id={project_id})")
    typer.echo(f"  {config_line}")
    typer.echo(f"  {user_line}")


def _maybe_run_doctor(*, no_doctor: bool) -> None:
    """Step 7 (part 2): run the closing doctor pass and surface it inline.

    Calls :func:`shepherd_cli.commands.doctor.run` (imported as
    :data:`_run_doctor` — never reimplemented) IN-PROCESS, in the SAME
    environment ``shepherd init``'s own DB/namespace resolution just ran
    in, so the report reflects exactly what this invocation built.
    Deliberately never inspects (let alone propagates) the returned exit
    code: a fresh project's ``refresh``-zone WARNs are entirely normal
    (nothing has been refreshed yet — see
    :mod:`shepherd_cli.commands.doctor`'s own module docstring on the
    ``artifacts`` zone's structural "always never refreshed" quirk), and
    ``shepherd ready`` runs this stage as a strict, unguarded
    ``set -e``-equivalent child (see :mod:`shepherd_cli.commands.ready`'s
    own ``_run_init_stage`` docstring) — a doctor WARN turning into a
    nonzero ``init`` exit would break ``shepherd ready`` on every fresh
    project, not just report a diagnostic.

    Args:
        no_doctor: When True (``--no-doctor``), skip entirely.
    """
    if no_doctor:
        return
    typer.echo("shctx init: doctor pass")
    report_text, _doctor_exit_code = _run_doctor("md")
    typer.echo(report_text)


# --------------------------------------------------------------------------
# Driver.
# --------------------------------------------------------------------------
def _init_impl(flags: _Flags) -> None:
    """Run the full seamless-bootstrap pipeline: scaffold -> db -> project ->
    auto-refresh -> config scaffold -> optional user tier -> summary + doctor.

    Bash parity with ``cmd_init.sh``'s body (post flag-parsing) through the
    auto-refresh trigger — every one of those steps runs unconditionally
    EXCEPT the project registration (only the first time, per
    :func:`_register_project`) and the auto-refresh itself (only when
    pre-existing markdown is found, per :func:`_maybe_auto_refresh`).
    Everything from the config scaffold onward is the v6.4.2 addition (see
    the module docstring's numbered list and "WHY STEPS 5-7" note).

    Args:
        flags: The parsed opt-out/opt-in switches (:func:`_apply_flags`).

    Raises:
        typer.Exit: Propagated from any pre-existing pipeline step (code 1
            on a hard scaffold/db failure, or the auto-refresh's own exit
            code). The v6.4.2 steps never raise: a config-scaffold or
            doctor-pass problem is reported inline, never escalated to
            this command's own exit code (see :func:`_maybe_scaffold_config`
            and :func:`_maybe_run_doctor`'s docstrings).
    """
    root = resolve_workdir()
    repo = resolve_repo_root()
    namespace_existed = os.path.isdir(root)
    _scaffold(root, repo)

    db_path = resolve_db_path()
    db_existed = os.path.isfile(db_path)
    migrations_applied = _bootstrap_db(db_path)

    pidfile = os.path.join(root, "project.json")
    project_existed = os.path.isfile(pidfile)
    project_id = _register_project(root, repo, db_path)

    typer.echo(f"shctx: initialized {os.path.basename(root)}/ at {root}")
    typer.echo(f"shctx: project_id = {project_id}")

    _maybe_auto_refresh(root)

    config_line = _maybe_scaffold_config(no_config=flags.no_config)
    user_line = _maybe_bootstrap_user(user=flags.user)
    _print_bootstrap_summary(
        namespace_existed=namespace_existed,
        root=root,
        db_existed=db_existed,
        migrations_applied=migrations_applied,
        project_existed=project_existed,
        project_id=project_id,
        config_line=config_line,
        user_line=user_line,
    )

    _maybe_run_doctor(no_doctor=flags.no_doctor)


@app.callback(invoke_without_command=True)
def init(
    args: list[str] = typer.Argument(
        None,
        metavar="[--artifacts|--shepherd] [--no-config] [--no-doctor] [--user] [-h|--help]",
        hidden=True,
        help="Flags only, no positional arguments — see cmd_init.sh's usage text (-h/--help).",
    ),
) -> None:
    """The seamless bootstrap: namespace + db + project + shepherd.toml + doctor, one command.

    Native port of ``shctx init`` (``cmd_init.sh`` + ``scaffold.sh``),
    extended in v6.4.2 into the ONE command that takes a bare repo to
    fully configured (see the module docstring's numbered step list).
    Takes no subcommands — only the flags documented in
    :data:`_HELP_TEXT` — captured together as one variadic argument
    (mirroring :mod:`shepherd_cli.commands.sync`'s identical
    ``context_settings`` pattern).

    Args:
        args: Every token given after ``init`` on the command line, or
            None/empty for a bare ``shepherd init`` (bash parity: runs
            the full bootstrap pipeline with no namespace override, NOT a
            usage screen).

    Raises:
        typer.Exit: Propagated from :func:`_apply_flags` (help/unknown
            flag) or :func:`_init_impl` (every pre-existing pipeline
            failure mode — the v6.4.2 additions never raise). Implicit
            code 0 on success.
    """
    argv = list(args) if args else []
    flags = _apply_flags(argv)
    _init_impl(flags)


__all__ = ["app"]
