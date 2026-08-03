"""``shepherd config`` — scaffold / inspect the project ``shepherd.toml`` binding.

Bash source of truth: ``skills/context/scripts/cmd_config.sh`` (subcommands
``init|claude-md|get|show|path``), built on ``skills/context/scripts/_lib.sh``'s
``shctx_repo_root``/``resolve_workdir``/``cfg_get`` helpers. PURE FILESYSTEM +
CONFIG, NO DATABASE — this module never imports :mod:`shepherd_cli.db` or
opens a Tortoise connection, matching ``cmd_config.sh``'s own total absence
of any ``shctx_sql``/``shctx_db_path`` call (the same "no DB access needs no
lifespan" shape as :mod:`shepherd_cli.commands.models`).

WHY A SINGLE VARIADIC COMMAND, NOT FIVE ``@app.command()``s
=============================================================
``cmd_config.sh`` is one ``case "$sub" in ... esac`` block with parity
requirements that don't match Typer/Click's own subcommand-dispatch
defaults, in the same way :mod:`shepherd_cli.commands.style` documents at
length:

- **Default subcommand is ``help``, not Click's auto-help.**
  ``sub="${1:-help}"`` — a bare ``shctx config`` runs the ``help`` arm
  (prints the usage blurb to STDOUT and exits 0), not a Click-generated
  help screen.
- **Unknown subcommand exits 1 with a bash-specific message, not Click's
  default 2.** The ``*)`` branch prints ``"ERROR: usage: shctx config
  <init|claude-md|show|path|get>"`` to stderr and exits 1.
- **``--force`` is checked POSITIONALLY, not as a flag search.**
  ``init) do_init "${1:-}" ;;`` passes ONLY the single next token after
  ``init`` to ``do_init`` — ``do_init``'s own guard is
  ``[[ "${1:-}" == "--force" ]]``, i.e. it only ever looks at that ONE
  token. ``shctx config init foo --force`` passes ``do_init`` the single
  argument ``"foo"``; the trailing ``--force`` is silently discarded and
  force stays 0. This module reproduces that literal-first-token check
  (see :func:`_dispatch`) rather than a more forgiving "look for
  ``--force`` anywhere in the remaining args" scan.

So this module registers ZERO ``@app.command()``s and instead defines one
``@app.callback(invoke_without_command=True)`` that captures every
remaining token as a raw ``list[str]`` (Click's ``nargs=-1`` via
``context_settings={"ignore_unknown_options": True}``, so a token like
``--force`` lands here as a literal string instead of raising "no such
option") and dispatches on ``argv[0]`` exactly like bash's ``case``
statement, including running ``help`` when ``argv`` is empty.

THREE DELIBERATE, DOCUMENTED DEVIATIONS FROM A BYTE-FOR-BYTE BASH PORT
=========================================================================
1. **``plugin_root()`` resolution.** ``cmd_config.sh``'s own
   ``plugin_root()`` prefers ``CLAUDE_PLUGIN_ROOT`` (when it carries an
   ``examples/`` dir), else ``cd "$HERE/../../.." && pwd`` — a FIXED
   three-level climb from the script's own on-disk location
   (``skills/context/scripts``) up to the repo root, which always
   succeeds regardless of ``cwd``. This module has no
   ``skills/context/scripts`` sibling of its own to climb from (it lives
   under ``services/cli/shepherd_cli/commands/``), so :func:`_plugin_root`
   instead walks UP from :func:`shepherd_cli.resolution.resolve_repo_root`
   looking for an ``examples/minimal`` directory — the same
   walk-up-from-repo-root fallback pattern
   :func:`shepherd_cli.resolution._find_via_plugin_root_then_walk_up` and
   :mod:`shepherd_cli.commands.style`'s ``_resolve_bundled_styles_dir``
   already establish for this port. In every real deployment (and every
   test in this suite, which sets ``CLAUDE_PLUGIN_ROOT``) the
   ``CLAUDE_PLUGIN_ROOT`` branch is taken directly and this fallback never
   triggers; it exists only so a git-toplevel-rooted checkout with no
   ``CLAUDE_PLUGIN_ROOT`` set still resolves correctly, exactly as bash's
   fallback does for THIS repo's own layout (``examples/`` sits directly
   at the repo root, one level above ``skills/``).
2. **``get``'s ``cfg_get`` is a raw regex line-scan, NOT ``tomllib``.**
   Unlike :mod:`shepherd_cli.commands.models`'s ``cfg_section_get`` (which
   is explicitly SECTION-AWARE and uses ``tomllib`` because ``[models]``
   role keys would otherwise collide across sections), ``_lib.sh``'s
   ``cfg_get`` is explicitly documented as SECTION-AGNOSTIC: it ``grep
   -E``s every line of each candidate file for ``^[[:space:]]*<key>[[:space:]]*=``
   regardless of which (if any) ``[section]`` the line sits under, takes
   the LAST match per file (``tail -1``), and is the ONE uniform read
   path the top-level toggles (``on_grade_floor``, ``max_parallel``, ...)
   use. Reimplementing this via ``tomllib`` would require recursively
   walking every table in the parsed document to reproduce "any key,
   anywhere, last physical match wins" — more complex than the contract
   calls for, and subtly wrong for a file that doesn't even parse as
   valid TOML (bash's line-oriented ``grep``/``sed`` never validates TOML
   syntax at all; a strict ``tomllib.load`` would raise on the same input
   bash tolerates). :func:`_cfg_get` instead reproduces ``cfg_get`` line
   for line: :func:`_extract_cfg_value` mirrors its ``sed -E`` pipeline
   exactly (strip up to the first ``=`` and following whitespace, strip a
   trailing `` #comment``, strip one leading and one trailing ``"``).
3. **``derive_name``'s git-remote lookup never raises.** Bash's
   ``git -C "$root" remote get-url origin 2>/dev/null || true`` silently
   swallows a missing-remote/non-git-repo failure. :func:`_derive_name`
   does the same via ``subprocess.run(..., check=False)`` plus a broad
   ``except (OSError, subprocess.SubprocessError)`` around the call
   itself, falling back to ``os.path.basename(repo_root)`` on any
   failure — never a fresh ``os.getcwd()``, matching bash's ``basename
   "$root"`` (the ALREADY-RESOLVED repo root, not a fresh ``pwd``).

THE v6.4.2 HARNESS-NEUTRAL PRECEDENCE CONTRACT
=================================================
``.claude/`` is owned by ONE harness (Claude Code). shepherd's own bridge
contract (``skills/bridge/SKILL.md``) says implementations coordinate
"exclusively through the project-visible artifact schema... never harness
internals" — yet, before this change, a project's shepherd binding lived
INSIDE a competing harness's config directory, so ``codex-shepherd`` or any
future harness had to reach into ``.claude/`` just to discover that a repo
uses shepherd at all. ``.shepherd/`` (or whatever the project's namespace
resolver returns — see below) is the namespace shepherd already owns and
every harness can read, so it now leads the chain:

    1. ``<workdir>/shepherd.local.toml``    NEW
    2. ``<workdir>/shepherd.toml``          NEW canonical (write target)
    3. ``<repo>/.claude/shepherd.local.toml``   unchanged
    4. ``<repo>/.claude/shepherd.toml``         unchanged
    5. ``$XDG_CONFIG_HOME/shepherd.toml``       unchanged

First match wins, highest precedence first — see :func:`_config_search_paths`,
the ONE list-returning function every reader (:func:`_cfg_get`, :func:`_do_show`,
:func:`_do_validate`) and every writer (:func:`_do_path`, :func:`_do_init`,
:func:`_do_migrate`) now consumes, so the chain is spelled out exactly once.

Backward compatibility is the whole point: tiers 3-5 keep working forever,
and a project that never adds a ``<workdir>/`` config sees ZERO behavior
change — this is purely additive. ``<workdir>`` is NOT hardcoded to
``.shepherd/`` — legacy projects use ``.artifacts/`` — so tiers 1-2 resolve
through the SAME namespace resolver every other command already uses,
:func:`shepherd_cli.resolution.resolve_workdir` (bash twin:
``shctx_artifacts_root`` in ``_lib.sh``), never a literal ``".shepherd"``.
:func:`is_shepherd_project` reflects the OR across both canonical locations
(new tier 2 or legacy tier 4) so callers elsewhere in the CLI can detect a
shepherd binding regardless of which one a project happens to use.
:func:`_do_init` now scaffolds tier 2, :func:`_do_path` now echoes it, and
:func:`_do_migrate` (new) moves an existing tier-4 file onto it.

Timestamps: N/A — this module writes no database rows and stamps no
epoch fields; every write here is a plain file write (``.claude/shepherd.toml``
/ ``<workdir>/shepherd.toml`` / ``CLAUDE.md``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import typer
from typing import NamedTuple
from pydantic import BaseModel, ConfigDict

from shepherd_cli.config_schema import format_report, report_to_dict, validate_config_file
from shepherd_cli.resolution import resolve_repo_root, resolve_user_home, resolve_workdir

app = typer.Typer(
    add_completion=False,
    help="Scaffold / inspect the project shepherd.toml binding (bash: cmd_config.sh).",
)

#: Verbatim bash-parity usage text — ``cmd_config.sh``'s ``help|-h|--help)``
#: heredoc, captured byte-for-byte via ``bash cmd_config.sh help`` (including
#: its em dash, right-arrows, and ellipsis). No trailing newline: the sole
#: caller (:func:`_do_help`) prints it via ``typer.echo``, which appends
#: exactly one — matching bash's ``cat <<'EOF' ... EOF``, whose own output
#: already ends with exactly one trailing newline.
_USAGE = (
    "shctx config — scaffold / inspect the project shepherd.toml binding\n"
    "\n"
    "Usage:\n"
    "  shctx config init [--force]   Scaffold .claude/shepherd.toml from the bundled\n"
    "                                minimal template (idempotent). Derives [project].name\n"
    "                                (git remote → cwd) + [gates] (Cargo.toml→cargo,\n"
    "                                go.mod→go, pyproject→pytest, package.json→npm), and\n"
    "                                realigns [paths] to the active shctx namespace.\n"
    "  shctx config claude-md [--force]\n"
    "                                Materialize the portable operating doctrine into the\n"
    "                                repo's CLAUDE.md as a fenced managed block. Append-only\n"
    "                                and never-clobber (operator content outside the markers\n"
    "                                is preserved); --force re-syncs only the managed block.\n"
    "  shctx config show             Print the resolved project/local config.\n"
    "  shctx config path             Echo the canonical write location.\n"
    "  shctx config get <key> [def]  Resolve one key via cfg_get (local→project→XDG),\n"
    "                                echoing [def] when unset. The uniform read path for\n"
    "                                the v6.1.5 toggles (on_grade_floor, inter_sprint_pause,\n"
    "                                max_parallel, dashboard_cadence, …).\n"
    "\n"
    "Python-only additions (v6.4.2, harness-neutral config path):\n"
    "  shctx config migrate [--dry-run]\n"
    "                                Move .claude/shepherd.toml to the canonical\n"
    "                                <workdir>/shepherd.toml location. Idempotent; never\n"
    "                                overwrites an existing destination (reports and stops);\n"
    "                                --dry-run prints the plan without moving anything.\n"
    "  shctx config validate [--json]\n"
    "                                Validate every existing precedence-tier config file\n"
    "                                against the shepherd.toml schema (unknown keys/sections\n"
    "                                get a did-you-mean, wrong types name the allowed set).\n"
    "                                Exit 0 clean, nonzero otherwise."
)

#: The ``CLAUDE.md`` managed-block markers ``do_claude_md`` scans for.
#: ``_BEGIN`` is a PREFIX substring (the real marker line also carries a
#: trailing ``(managed block — re-sync with ...)  -->`` comment bash's
#: ``grep -qF``/``index()`` substring checks don't care about); ``_END`` is
#: the complete, exact closing line.
_CLAUDEMD_BEGIN = "<!-- BEGIN shepherd:operating-doctrine"
_CLAUDEMD_END = "<!-- END shepherd:operating-doctrine -->"

#: Regexes for the five ``[project]``/``[gates]``/``[paths]`` template keys
#: ``do_init``'s ``awk`` patches, anchored to the start of the line exactly
#: like bash's ``/^key[[:space:]]*=/``.
_TEMPLATE_NAME_RE = re.compile(r"^name\s*=")
_TEMPLATE_LANGUAGE_RE = re.compile(r"^language\s*=")
_TEMPLATE_CHECK_RE = re.compile(r"^check\s*=")
_TEMPLATE_LINT_RE = re.compile(r"^lint\s*=")
_TEMPLATE_FORMAT_RE = re.compile(r"^format\s*=")
_TEMPLATE_PATHS_RE = re.compile(r"^(plans|reports|docs|ctx)\s*=")

#: ``cfg_get``'s value-extraction pipeline, split into its two regex
#: stages (quote-stripping is a plain ``str`` slice, not a regex, matching
#: ``sed``'s single-character anchor strips).
_CFG_VALUE_PREFIX_RE = re.compile(r"^[^=]*=\s*")
_CFG_TRAILING_COMMENT_RE = re.compile(r"\s+#.*$")


# --------------------------------------------------------------------------
# Pydantic schema.
# --------------------------------------------------------------------------
class GateToolchain(BaseModel):
    """The detected build-gate toolchain for ``shepherd config init``.

    Mirrors ``cmd_config.sh``'s ``detect_gates`` pipe-delimited tuple
    (``"<language>|<check>|<lint>|<format>"``) as a typed structure
    instead of hand-parsed ``${gates%%|*}``/``${gates#*|}`` shell
    substring surgery.

    Attributes:
        language: The detected project language
            (``rust``/``go``/``python``/``typescript``), or bash's
            ``rust`` fallback when no build manifest is found at the
            repo root.
        check: The gate's build/typecheck command.
        lint: The gate's lint command.
        format: The gate's format command.
    """

    model_config = ConfigDict(from_attributes=True)

    language: str
    check: str
    lint: str
    format: str


# --------------------------------------------------------------------------
# Small stdlib helpers.
# --------------------------------------------------------------------------
def _plugin_root() -> str:
    """Resolve the plugin install root (where ``examples/`` lives).

    See the module docstring's deviation note #1. Prefers
    ``CLAUDE_PLUGIN_ROOT`` when it carries an ``examples/`` directory;
    otherwise walks up from :func:`shepherd_cli.resolution.resolve_repo_root`
    looking for an ``examples/minimal`` directory, returning the first
    ancestor that has one (or the repo root itself if none is found,
    matching bash's own always-succeeds fallback shape for this repo's
    layout).

    Returns:
        The resolved plugin/repo root path.
    """
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root_env and os.path.isdir(os.path.join(plugin_root_env, "examples")):
        return plugin_root_env

    root = resolve_repo_root()
    current = root
    while True:
        candidate = os.path.join(current, "examples", "minimal")
        if os.path.isdir(candidate):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return root
        current = parent


def _derive_name(repo_root: str) -> str:
    """Derive a project name: git remote ``origin`` basename -> repo-root basename.

    Bash parity with ``cmd_config.sh``'s ``derive_name``:
    ``git -C "$root" remote get-url origin`` (silently tolerating a
    missing remote or non-git repo), stripping a trailing ``.git`` and
    everything up to and including the last ``/``; falls back to
    ``basename "$root"`` when no remote URL is available.

    Args:
        repo_root: The resolved repository root.

    Returns:
        The derived project name.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        url = result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        url = ""

    if url:
        name = url.rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[: -len(".git")]
        return name
    return os.path.basename(repo_root)


def _detect_gates(repo_root: str) -> GateToolchain:
    """Detect the gate toolchain from build-manifest presence at the repo root.

    Bash parity with ``cmd_config.sh``'s ``detect_gates``: checks, in
    order, ``Cargo.toml`` -> rust, ``go.mod`` -> go, ``pyproject.toml`` OR
    ``setup.py`` -> python, ``package.json`` -> typescript, else falls
    back to the same rust defaults the bundled template already ships
    with (so an unrecognized project ends up with a no-op patch on those
    four fields).

    Args:
        repo_root: The resolved repository root.

    Returns:
        The detected :class:`GateToolchain`.
    """
    if os.path.isfile(os.path.join(repo_root, "Cargo.toml")):
        return GateToolchain(
            language="rust",
            check="cargo check --workspace",
            lint="cargo clippy --workspace -- -D warnings",
            format="cargo fmt --all",
        )
    if os.path.isfile(os.path.join(repo_root, "go.mod")):
        return GateToolchain(
            language="go",
            check="go build ./...",
            lint="go vet ./...",
            format="gofmt -l .",
        )
    if os.path.isfile(os.path.join(repo_root, "pyproject.toml")) or os.path.isfile(
        os.path.join(repo_root, "setup.py")
    ):
        return GateToolchain(
            language="python",
            check="pytest -q",
            lint="ruff check .",
            format="ruff format .",
        )
    if os.path.isfile(os.path.join(repo_root, "package.json")):
        return GateToolchain(
            language="typescript",
            check="npm run build --if-present",
            lint="npm run lint --if-present",
            format="npm run format --if-present",
        )
    return GateToolchain(
        language="rust",
        check="cargo check --workspace",
        lint="cargo clippy --workspace -- -D warnings",
        format="cargo fmt --all",
    )


def _resolve_workdir_quiet() -> str:
    """Resolve the shepherd work directory with the split-brain warning suppressed.

    Bash parity: ``do_init`` computes its namespace via
    ``ns="$(basename "$(SHCTX_QUIET=1 resolve_workdir)")"`` — a
    ``SHCTX_QUIET=1``-scoped subshell call, so the "both .shepherd/ and
    .artifacts/ exist" warning :func:`shepherd_cli.resolution.resolve_workdir`
    can print to stderr is suppressed for THIS one call only. Since
    Python has no subshell-scoped environment, this temporarily sets
    ``SHCTX_QUIET`` in the current process's environment for the
    duration of the call and restores its prior value (present, absent,
    or a different value) afterward — safe for a single-shot CLI
    invocation, which is the only context this module ever runs in.

    Returns:
        The resolved work directory path (need not exist on disk).
    """
    had_prev = "SHCTX_QUIET" in os.environ
    prev = os.environ.get("SHCTX_QUIET")
    os.environ["SHCTX_QUIET"] = "1"
    try:
        return resolve_workdir()
    finally:
        if had_prev:
            os.environ["SHCTX_QUIET"] = prev  # type: ignore[assignment]
        else:
            os.environ.pop("SHCTX_QUIET", None)


def _patch_init_template(src_text: str, *, name: str, gates: GateToolchain, ns: str) -> str:
    """Patch the bundled minimal template's derived-value lines.

    Bash parity with ``do_init``'s ``awk`` script: rewrites exactly the
    ``name``/``language``/``check``/``lint``/``format`` key lines
    wholesale (dropping any trailing inline comment those lines carried
    in the bundled template — bash's ``print`` replaces the entire
    matched line, comment included), and rewrites the ``plans``/
    ``reports``/``docs``/``ctx`` lines by substituting every literal
    ``.shepherd`` occurrence with ``ns`` IN PLACE (preserving the rest of
    the line, including any trailing comment — bash's ``gsub`` mutates
    ``$0`` before printing the whole line, it does not replace it).
    Every other line passes through completely unchanged.

    Args:
        src_text: The bundled template's raw text
            (``examples/minimal/shepherd.toml``).
        name: The derived project name (see :func:`_derive_name`).
        gates: The detected gate toolchain (see :func:`_detect_gates`).
        ns: The active shctx namespace basename (``.shepherd`` or
            ``.artifacts``).

    Returns:
        The patched template text, terminated by exactly one trailing
        newline (matching ``awk``'s per-record ``ORS`` behavior
        regardless of whether the source file's own final line already
        had one).
    """
    out_lines: list[str] = []
    for line in src_text.splitlines():
        if _TEMPLATE_NAME_RE.match(line):
            out_lines.append(f'name     = "{name}"')
        elif _TEMPLATE_LANGUAGE_RE.match(line):
            out_lines.append(f'language = "{gates.language}"')
        elif _TEMPLATE_CHECK_RE.match(line):
            out_lines.append(f'check  = "{gates.check}"')
        elif _TEMPLATE_LINT_RE.match(line):
            out_lines.append(f'lint   = "{gates.lint}"')
        elif _TEMPLATE_FORMAT_RE.match(line):
            out_lines.append(f'format = "{gates.format}"')
        elif _TEMPLATE_PATHS_RE.match(line):
            out_lines.append(line.replace(".shepherd", ns))
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"


def _resync_managed_block(dst_text: str, src_text: str) -> str:
    """Replace ONLY the ``BEGIN..END`` managed block in ``dst_text`` with ``src_text``.

    Bash parity with ``do_claude_md``'s re-sync ``awk`` script: the line
    containing :data:`_CLAUDEMD_BEGIN` is replaced (not merely prefixed)
    by every line of ``src_text`` verbatim (``src_text`` already carries
    its own BEGIN/END markers); every line from there up to and
    including the line containing :data:`_CLAUDEMD_END` is dropped;
    every other line of ``dst_text`` — everything outside the block — is
    preserved exactly, in order.

    Args:
        dst_text: The existing ``CLAUDE.md``'s full text (already
            confirmed by the caller to contain both markers).
        src_text: The bundled template's current managed-block text
            (``examples/minimal/CLAUDE.md``).

    Returns:
        The re-synced text, terminated by exactly one trailing newline
        (``awk``'s per-record ``ORS`` behavior, same as
        :func:`_patch_init_template`).
    """
    out_lines: list[str] = []
    in_block = False
    src_lines = src_text.splitlines()
    for line in dst_text.splitlines():
        if not in_block and _CLAUDEMD_BEGIN in line:
            out_lines.extend(src_lines)
            in_block = True
            continue
        if in_block and _CLAUDEMD_END in line:
            in_block = False
            continue
        if in_block:
            continue
        out_lines.append(line)
    return "\n".join(out_lines) + "\n"


#: Harness ids that may carry a per-harness config layer. A harness file is
#: TRACKED in git (unlike ``*.local.toml``) because a harness knob is a
#: property of the project, not of one developer's machine.
KNOWN_HARNESSES: tuple[str, ...] = ("claude", "codex")


def resolve_harness() -> str:
    """The active harness id, or ``""`` when none can be determined.

    Order: ``SHEPHERD_HARNESS`` (explicit, always wins) -> Claude Code's own
    markers (``CLAUDECODE`` / ``CLAUDE_PLUGIN_ROOT``) -> ``CODEX_HOME`` ->
    ``""``. An unrecognized explicit value is returned as-is: an unknown
    harness simply has no file on disk, which is indistinguishable from
    having none, so there is nothing to fail about.

    Only the ACTIVE harness's file is read. Reading every harness file would
    let a codex knob take effect under Claude Code, which is the opposite of
    what a per-harness layer is for.

    Returns:
        The harness id (e.g. ``"claude"``), or ``""`` when unknown.
    """
    explicit = os.environ.get("SHEPHERD_HARNESS", "").strip()
    if explicit:
        return explicit
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "claude"
    if os.environ.get("CODEX_HOME"):
        return "codex"
    return ""


def _layer(root: str, harness: str) -> list[str]:
    """One layer's files, highest precedence first.

    Within any layer: ``shepherd.local.toml`` (this machine) beats
    ``shepherd.<harness>.toml`` (this harness) beats ``shepherd.toml``
    (everyone).

    Args:
        root: The directory holding the layer's files.
        harness: The active harness id, or ``""`` to omit that tier.

    Returns:
        Two or three absolute paths, highest precedence first.
    """
    files = [os.path.join(root, "shepherd.local.toml")]
    if harness:
        files.append(os.path.join(root, f"shepherd.{harness}.toml"))
    files.append(os.path.join(root, "shepherd.toml"))
    return files


class ConfigTier(NamedTuple):
    """One entry in the config precedence chain.

    Attributes:
        label: Stable machine-ish name for the tier (``"workdir"``,
            ``"user-harness"``, ...). Used by ``doctor`` to name where a
            binding resolved from, and by ``config validate`` to report
            per-file. Stable across chain growth — callers key on the LABEL,
            never on a positional index.
        path: The absolute candidate file path.
        scope: ``"project"`` or ``"user"``. ``config show`` displays only
            project-scope files (bash parity: ``show`` never printed the
            user global).
    """

    label: str
    path: str
    scope: str


def _config_tiers(repo_root: str) -> tuple[ConfigTier, ...]:
    """The full precedence chain as labelled tiers, highest first.

    THE single source of truth for config resolution. Everything else --
    :func:`_config_search_paths`, :func:`_cfg_get`, :func:`_do_show`,
    :func:`_do_validate`, :func:`is_shepherd_project`, and ``doctor``'s
    tier labelling -- derives from this, so growing the chain cannot leave
    a caller behind. It already did once: ``_do_show`` sliced ``[:4]`` and
    ``doctor`` mapped tier-to-label by position, and both silently
    mislabelled the moment the chain grew past five entries. Labels and
    scopes exist so no caller ever indexes positionally again.

    See :func:`_config_search_paths` for the layering contract itself.

    Args:
        repo_root: The resolved repository root.

    Returns:
        Labelled tiers, highest precedence first.
    """
    harness = resolve_harness()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or ""
    if not xdg_config_home:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        xdg_config_home = os.path.join(home, ".config")

    workdir = resolve_workdir()
    userhome = resolve_user_home()
    tiers: list[ConfigTier] = [
        ConfigTier("workdir-local", os.path.join(workdir, "shepherd.local.toml"), "project"),
    ]
    if harness:
        tiers.append(
            ConfigTier("workdir-harness", os.path.join(workdir, f"shepherd.{harness}.toml"), "project")
        )
    tiers += [
        ConfigTier("workdir", os.path.join(workdir, "shepherd.toml"), "project"),
        ConfigTier("legacy-local", os.path.join(repo_root, ".claude", "shepherd.local.toml"), "project"),
        ConfigTier("legacy", os.path.join(repo_root, ".claude", "shepherd.toml"), "project"),
        ConfigTier("user-local", os.path.join(userhome, "shepherd.local.toml"), "user"),
    ]
    if harness:
        tiers.append(
            ConfigTier("user-harness", os.path.join(userhome, f"shepherd.{harness}.toml"), "user")
        )
    tiers += [
        ConfigTier("user", os.path.join(userhome, "shepherd.toml"), "user"),
        ConfigTier("xdg", os.path.join(xdg_config_home, "shepherd.toml"), "user"),
    ]
    return tuple(tiers)


def _config_search_paths(repo_root: str) -> tuple[str, ...]:
    """Every config file a reader checks, highest precedence first.

    THE LAYERING CONTRACT (v6.4.2, operator directive 2026-08-03)
    -------------------------------------------------------------------
    Three layers. Within each, ``local`` beats ``<harness>`` beats base;
    across them, PROJECT always beats USER::

        project   <workdir>/shepherd.local.toml        <- ultimate override
                  <workdir>/shepherd.<harness>.toml
                  <workdir>/shepherd.toml              <- the project binding
        legacy    <repo>/.claude/shepherd.local.toml   <- pre-v6.4.2, honored
                  <repo>/.claude/shepherd.toml            indefinitely
        user      ~/.shepherd/shepherd.local.toml      <- cross-project
                  ~/.shepherd/shepherd.<harness>.toml     DEFAULTS
                  ~/.shepherd/shepherd.toml
                  $XDG_CONFIG_HOME/shepherd.toml       <- pre-v6.4.2 global

    ``~/.shepherd`` holds DEFAULT behavior; a project overrides it simply by
    setting the key.

    The deliberate call: the legacy ``.claude/`` tiers are PROJECT-level
    files, so they rank above the whole user layer. Putting the user layer
    higher would mean creating ``~/.shepherd/shepherd.toml`` silently
    overrode every existing project still bound through ``.claude/`` — a
    regression for every current install, which is not an acceptable price
    for tidier ordering.

    ``*.local.toml`` is gitignored (one machine); ``shepherd.<harness>.toml``
    is TRACKED, since a harness knob is a property of the project.

    Namespace tiers resolve through
    :func:`shepherd_cli.resolution.resolve_workdir` rather than a literal
    ``".shepherd"``, so an ``--artifacts`` project is found too.

    Args:
        repo_root: The resolved repository root.

    Returns:
        The candidate paths, highest precedence first. Length varies with
        whether a harness is detected (:func:`resolve_harness`).
    """
    return tuple(tier.path for tier in _config_tiers(repo_root))


def _canonical_write_target(workdir: str | None = None) -> str:
    """The canonical ``shepherd.toml`` WRITE location — precedence tier 2.

    What ``shctx config path`` echoes and ``shctx config init`` scaffolds
    (v6.4.2). Accepts an already-resolved ``workdir`` so a caller that
    already paid for one ``resolve_workdir()`` call (e.g. :func:`_do_init`,
    which also needs it for the namespace basename) doesn't pay for a
    second — the same ``workdir if workdir is not None else
    resolve_workdir()`` shape :mod:`shepherd_cli.profiles` and
    :mod:`shepherd_cli.models_run` already use.

    Args:
        workdir: A pre-resolved work directory, or None to resolve one
            here.

    Returns:
        ``<workdir>/shepherd.toml``.
    """
    return os.path.join(workdir if workdir is not None else resolve_workdir(), "shepherd.toml")


def is_shepherd_project(repo_root: str | None = None) -> bool:
    """True iff this repo has ANY shepherd.toml binding, canonical or legacy.

    True when EITHER ``<workdir>/shepherd.toml`` (the v6.4.2 canonical
    tier-2 location) OR ``<repo>/.claude/shepherd.toml`` (the legacy
    tier-4 location this repo may still be using, pre-:func:`_do_migrate`)
    exists — callers elsewhere in the CLI that just need "does this repo
    use shepherd at all" should not have to know which of the two
    locations a given project happens to bind through.

    Args:
        repo_root: A pre-resolved repository root, or None to resolve one
            here.

    Returns:
        True iff either canonical location exists on disk.
    """
    root = repo_root if repo_root is not None else resolve_repo_root()
    workdir = resolve_workdir()
    return os.path.isfile(os.path.join(workdir, "shepherd.toml")) or os.path.isfile(
        os.path.join(root, ".claude", "shepherd.toml")
    )


def _extract_cfg_value(line: str) -> str:
    """Extract ``cfg_get``'s value from one matched ``key = value`` line.

    Bash parity with ``_lib.sh``'s ``sed -E`` pipeline, applied in the
    same order:

    1. ``s/^[^=]*=[[:space:]]*//`` — strip everything up to and
       including the first ``=`` plus any following whitespace.
    2. ``s/[[:space:]]+#.*$//`` — strip a trailing `` #comment`` (only
       when preceded by at least one whitespace character; a bare ``#``
       glued to the preceding character, e.g. inside a value, is left
       alone).
    3. ``s/^"//`` — strip exactly one leading double-quote, if present.
    4. ``s/"$//`` — strip exactly one trailing double-quote, if present.

    Args:
        line: The raw matched line, with or without a trailing newline.

    Returns:
        The extracted value, possibly empty.
    """
    text = line.rstrip("\r\n")
    text = _CFG_VALUE_PREFIX_RE.sub("", text, count=1)
    text = _CFG_TRAILING_COMMENT_RE.sub("", text, count=1)
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    return text


def _cfg_get(key: str, repo_root: str) -> str:
    """Resolve one config key via bash-parity ``cfg_get`` semantics.

    See the module docstring's deviation note #2: this is a raw,
    section-agnostic line scan — NOT a ``tomllib`` parse. For each
    candidate file (in :func:`_config_search_paths` order), every line
    matching ``^[[:space:]]*<key>[[:space:]]*=`` is a candidate; the
    LAST such line in the file wins (``tail -1``); if that line's
    extracted value (:func:`_extract_cfg_value`) is non-empty, it is
    returned immediately. An empty value (or a file with no matching
    line, or a file that can't be read/decoded at all) falls through to
    the next file in precedence order, exactly like bash's
    ``[[ -n "$v" ]] || continue`` — a file existing with the key set to
    ``""`` is treated as unset, not as an explicit empty override.

    Args:
        key: The config key to resolve, e.g. ``"max_parallel"``.
        repo_root: The resolved repository root.

    Returns:
        The resolved value, or the empty string if no candidate file has
        a non-empty value for this key.
    """
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for path in _config_search_paths(repo_root):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        matched_line: str | None = None
        for candidate_line in lines:
            if pattern.match(candidate_line):
                matched_line = candidate_line
        if matched_line is None:
            continue
        value = _extract_cfg_value(matched_line)
        if value:
            return value
    return ""


# --------------------------------------------------------------------------
# Subcommand handlers — each returns the bash-parity process exit code.
# --------------------------------------------------------------------------
def _do_init(force: bool) -> int:
    """Scaffold ``<workdir>/shepherd.toml`` from the bundled minimal template.

    Bash-derived from ``cmd_config.sh``'s ``do_init``, with the v6.4.2
    write target moved from ``.claude/shepherd.toml`` (tier 4) to
    ``<workdir>/shepherd.toml`` (tier 2, the new canonical location — see
    the module docstring). Two idempotency guards beyond the original:

    - A pre-existing tier-4 ``.claude/shepherd.toml`` now ALSO preserves
      (pointing the operator at :func:`_do_migrate`) rather than silently
      scaffolding a second, tier-2 binding beside it — an un-migrated
      legacy project would otherwise end up with two config files, the
      new one silently shadowing any key the legacy one set that the
      bundled template's derived values don't happen to match.
    - The local-override check now ALSO covers ``<workdir>/
      shepherd.local.toml`` (tier 1), not just the two ``.claude``-rooted
      locations bash already checked.

    Args:
        force: When True, skip every idempotency guard above and
            overwrite unconditionally.

    Returns:
        0 on success (including every "preserved, nothing written" early
        return); 1 if the bundled template is missing (an installation
        defect, not a user error — bash prints this to stderr too).
    """
    repo = resolve_repo_root()
    workdir = _resolve_workdir_quiet()
    dst = _canonical_write_target(workdir)
    legacy_dst = os.path.join(repo, ".claude", "shepherd.toml")

    if not force:
        if os.path.isfile(dst):
            typer.echo(f"shctx config: {dst} already exists (preserving)")
            return 0
        if os.path.isfile(legacy_dst):
            typer.echo(
                f"shctx config: {legacy_dst} already exists (preserving; run "
                f"'shctx config migrate' to move it to the canonical {dst})"
            )
            return 0
        local_override_a = os.path.join(workdir, "shepherd.local.toml")
        local_override_b = os.path.join(repo, ".claude", "shepherd.local.toml")
        local_override_c = os.path.join(repo, ".local.toml")
        if any(os.path.isfile(p) for p in (local_override_a, local_override_b, local_override_c)):
            typer.echo(
                "shctx config: a local-override config is present "
                "(preserving; no project binding written)"
            )
            return 0

    src = os.path.join(_plugin_root(), "examples", "minimal", "shepherd.toml")
    if not os.path.isfile(src):
        typer.echo(f"ERROR: bundled template missing: {src}", err=True)
        return 1

    name = _derive_name(repo)
    ns = os.path.basename(workdir)
    gates = _detect_gates(repo)

    os.makedirs(workdir, exist_ok=True)
    with open(src, encoding="utf-8") as fh:
        src_text = fh.read()
    patched = _patch_init_template(src_text, name=name, gates=gates, ns=ns)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(patched)

    typer.echo(f"shctx config: scaffolded {dst}")
    typer.echo(f"  name={name}  language={gates.language}  namespace={ns}")
    typer.echo(f'  gates: check="{gates.check}" lint="{gates.lint}" format="{gates.format}"')
    typer.echo("  Review [branching] + [gates] before your first sprint.")
    return 0


def _do_claude_md(force: bool) -> int:
    """Materialize the operating doctrine into the repo's ``CLAUDE.md``.

    Bash parity with ``cmd_config.sh``'s ``do_claude_md``: append-only
    and never-clobber by default (operator content outside the
    ``BEGIN``/``END`` markers is always preserved); ``force`` re-syncs
    ONLY the managed block when one is already present.

    Args:
        force: When True and a managed block is already present,
            re-sync it to the bundled template's current content instead
            of leaving it untouched.

    Returns:
        0 on success; 1 if the bundled template is missing, or if the
        destination has a ``BEGIN`` marker but no matching ``END``
        marker (a hand-damaged block this function refuses to touch
        rather than risk silently dropping trailing content).
    """
    repo = resolve_repo_root()
    dst = os.path.join(repo, "CLAUDE.md")
    src = os.path.join(_plugin_root(), "examples", "minimal", "CLAUDE.md")
    if not os.path.isfile(src):
        typer.echo(f"ERROR: bundled template missing: {src}", err=True)
        return 1

    if not os.path.isfile(dst):
        with open(src, encoding="utf-8") as fh:
            content = fh.read()
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(content)
        typer.echo(f"shctx config: wrote {dst} (shepherd operating doctrine)")
        return 0

    with open(dst, encoding="utf-8") as fh:
        dst_text = fh.read()

    if _CLAUDEMD_BEGIN in dst_text:
        if not force:
            typer.echo(
                f"shctx config: {dst} already carries the shepherd doctrine block "
                "(preserving; --force to re-sync)"
            )
            return 0
        if _CLAUDEMD_END not in dst_text:
            typer.echo(
                f"ERROR: {dst} has a BEGIN marker but no '{_CLAUDEMD_END}' — refusing "
                "to re-sync (would drop trailing content). Repair the markers manually.",
                err=True,
            )
            return 1
        with open(src, encoding="utf-8") as fh:
            src_text = fh.read()
        new_text = _resync_managed_block(dst_text, src_text)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        typer.echo(f"shctx config: re-synced the shepherd doctrine block in {dst}")
        return 0

    with open(src, encoding="utf-8") as fh:
        src_text = fh.read()
    with open(dst, "a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write(src_text)
    typer.echo(
        f"shctx config: appended the shepherd operating doctrine block to {dst} "
        "(operator content preserved)"
    )
    return 0


def _do_get(key: str, default: str) -> int:
    """Resolve one config key, or echo ``default`` when unset everywhere.

    Bash parity with ``cmd_config.sh``'s ``get`` arm.

    Args:
        key: The config key to resolve; empty means the argument was
            omitted entirely.
        default: The fallback value to print when ``key`` resolves to
            nothing (bash's ``def="${2:-}"`` — empty string when
            omitted).

    Returns:
        0 on success; 1 (with a stderr usage message) if ``key`` is
        empty.
    """
    if not key:
        typer.echo("ERROR: usage: shctx config get <key> [default]", err=True)
        return 1
    value = _cfg_get(key, resolve_repo_root())
    typer.echo(value if value else default)
    return 0


def _do_show() -> int:
    """Print every existing precedence-tier config file, raw.

    v6.4.2: extended from bash's original two files
    (``.claude/shepherd.local.toml`` / ``.claude/shepherd.toml``) to all
    FOUR non-XDG tiers of :func:`_config_search_paths` — ``<workdir>/
    shepherd.local.toml``, ``<workdir>/shepherd.toml``,
    ``.claude/shepherd.local.toml``, ``.claude/shepherd.toml`` — in that
    (highest-precedence-first) order, since a project may now bind
    through either the new or the legacy canonical location. For each
    that exists, prints ``# <path>``, the file's raw content verbatim,
    then a blank line. Prints a "no config" notice instead if NONE
    exist. The XDG global config (tier 5) is still never shown here
    (bash parity: ``show`` never read ``$XDG_CONFIG_HOME`` either).

    Returns:
        0, always (bash parity: this subcommand never fails).
    """
    repo = resolve_repo_root()
    found = False
    output = ""
    # Project-scope tiers only -- bash parity: `show` never printed the user
    # global. Filtered by SCOPE, not by a positional slice: the old `[:4]`
    # silently became wrong the moment the chain grew past five entries.
    for path in (t.path for t in _config_tiers(repo) if t.scope == "project"):
        if os.path.isfile(path):
            found = True
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            output += f"# {path}\n{content}\n"
    if not found:
        output += f"(no {_canonical_write_target()} — run 'shctx config init')\n"
    typer.echo(output, nl=False)
    return 0


def _do_path() -> int:
    """Echo the canonical ``shepherd.toml`` write location.

    v6.4.2: now echoes ``<workdir>/shepherd.toml`` (tier 2 — see the
    module docstring), not the pre-v6.4.2 ``<repo_root>/.claude/
    shepherd.toml``, whether or not the file exists.

    Returns:
        0, always.
    """
    typer.echo(_canonical_write_target())
    return 0


def _do_migrate(dry_run: bool) -> int:
    """Move ``.claude/shepherd.toml`` (tier 4) onto the canonical ``<workdir>/shepherd.toml`` (tier 2).

    New in v6.4.2 — no bash counterpart (this module's ``YOUR FILES``
    lane is Python-side only; see the module docstring). A plain
    ``shutil.move`` (git-mv semantics), never a copy-plus-pointer-comment
    — the source location simply stops existing, exactly like a
    ``git mv``, which is the safest and most legible thing to leave
    behind: no stale duplicate content, no partially-trustworthy tier-4
    file an operator could mistake for still-authoritative.

    Idempotent: a second run finds no ``.claude/shepherd.toml`` (already
    moved) and reports "nothing to migrate" rather than erroring. Never
    clobbers an existing destination — if BOTH the legacy source and a
    tier-2 destination already exist (a genuine conflict, not a
    re-run), this reports the conflict and stops rather than guessing
    which one the operator wants to keep.

    Args:
        dry_run: When True, print the plan and change nothing on disk.

    Returns:
        0 on success (including "nothing to migrate" and the dry-run
        report); 1 when the destination already exists (a conflict the
        operator must resolve by hand).
    """
    repo = resolve_repo_root()
    workdir = resolve_workdir()
    src = os.path.join(repo, ".claude", "shepherd.toml")
    dst = _canonical_write_target(workdir)

    if not os.path.isfile(src):
        typer.echo(f"shctx config migrate: nothing to migrate ({src} does not exist)")
        return 0

    if os.path.isfile(dst):
        typer.echo(
            f"shctx config migrate: {dst} already exists — refusing to overwrite "
            f"it (leaving {src} in place). Resolve the conflict by hand, then re-run."
        )
        return 1

    if dry_run:
        typer.echo(f"shctx config migrate: would move {src} -> {dst} (dry run, nothing written)")
        return 0

    os.makedirs(workdir, exist_ok=True)
    shutil.move(src, dst)
    typer.echo(f"shctx config migrate: moved {src} -> {dst}")
    return 0


def _do_validate(as_json: bool) -> int:
    """Validate every existing precedence-tier config file against the shepherd.toml schema.

    New in v6.4.2. Validates each of the (up to 5) tier files from
    :func:`_config_search_paths` that actually exists, SEPARATELY — never
    the merged/resolved config — so a bad key in
    ``.claude/shepherd.local.toml`` is reported against that file, not
    misattributed to ``.claude/shepherd.toml`` sitting one tier lower,
    per :mod:`shepherd_cli.config_schema`'s "every message must name the
    FILE and the ``[section].key``" contract.

    Args:
        as_json: When True, emit a single JSON object
            (``{"ok": bool, "files": [...]}``, one entry per validated
            file, each shaped by
            :func:`shepherd_cli.config_schema.report_to_dict`) instead of
            the human-readable text report.

    Returns:
        0 when every existing tier file validates clean (including when
        NONE exist — nothing to validate is not a failure); nonzero when
        any existing tier file has at least one issue.
    """
    repo = resolve_repo_root()
    candidates = [p for p in _config_search_paths(repo) if os.path.isfile(p)]

    if not candidates:
        if as_json:
            typer.echo(json.dumps({"ok": True, "files": []}))
        else:
            typer.echo("shctx config validate: no config files found across any precedence tier")
        return 0

    reports = [validate_config_file(p) for p in candidates]
    ok = all(r.ok for r in reports)

    if as_json:
        typer.echo(json.dumps({"ok": ok, "files": [report_to_dict(r) for r in reports]}, indent=2))
    else:
        for report in reports:
            typer.echo(format_report(report), nl=False)

    return 0 if ok else 1


def _do_help() -> int:
    """Print the verbatim bash-parity usage blurb.

    Returns:
        0, always.
    """
    typer.echo(_USAGE)
    return 0


# --------------------------------------------------------------------------
# Dispatcher + Typer wiring.
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Dispatch on ``argv[0]`` exactly like ``cmd_config.sh``'s ``case`` statement.

    Args:
        argv: The raw remaining command-line tokens after ``config``,
            e.g. ``["init", "--force"]`` or ``[]``.

    Returns:
        The bash-parity process exit code for whichever subcommand ran
        (or the unknown-subcommand/default-``help`` arms).
    """
    sub = argv[0] if argv else "help"
    rest = argv[1:]

    if sub == "init":
        force = bool(rest) and rest[0] == "--force"
        return _do_init(force)
    if sub == "claude-md":
        force = bool(rest) and rest[0] == "--force"
        return _do_claude_md(force)
    if sub == "get":
        key = rest[0] if len(rest) >= 1 else ""
        default = rest[1] if len(rest) >= 2 else ""
        return _do_get(key, default)
    if sub == "show":
        return _do_show()
    if sub == "path":
        return _do_path()
    if sub == "migrate":
        # v6.4.2, Python-only (see the module docstring) — same
        # literal-first-token ``--force``-style check as init/claude-md
        # above, not a general "look for the flag anywhere" scan.
        dry_run = bool(rest) and rest[0] == "--dry-run"
        return _do_migrate(dry_run)
    if sub == "validate":
        # v6.4.2, Python-only.
        as_json = bool(rest) and rest[0] == "--json"
        return _do_validate(as_json)
    if sub in ("help", "-h", "--help"):
        return _do_help()

    # Bash-parity usage message, deliberately UNCHANGED (still names only
    # the five subcommands bash's own cmd_config.sh implements) — migrate/
    # validate are Python-only additions with no bash counterpart to stay
    # in parity with; the full subcommand list lives in `help` (_USAGE)
    # instead of this terse fallback line.
    typer.echo("ERROR: usage: shctx config <init|claude-md|show|path|get>", err=True)
    return 1


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True, "help_option_names": []})
def config(
    args: list[str] = typer.Argument(
        None,
        help=(
            "Subcommand + args: 'init [--force]' | 'claude-md [--force]' | 'get <key> [default]' "
            "| 'show' | 'path' | 'migrate [--dry-run]' | 'validate [--json]' | 'help'. "
            "Defaults to 'help'."
        ),
    ),
) -> None:
    """Scaffold / inspect the project ``shepherd.toml`` binding — native port of ``shctx config``.

    See the module docstring for why this is ONE variadic callback
    rather than N ``@app.command()``s: bash's default-to-``help`` and
    exit-1-on-unknown-subcommand contracts, plus ``init``/``claude-md``'s
    positional-only ``--force`` check, don't match Typer/Click's own
    subcommand-dispatch defaults. ``migrate``/``validate`` (v6.4.2) are
    Python-only additions dispatched the same way for consistency, even
    though they have no bash ``--force``-style positional flag to mimic.

    Args:
        args: Every token after ``config`` on the command line, in
            order, with NOTHING pre-parsed as flags/options by Click
            (see ``context_settings={"ignore_unknown_options": True}``
            on this callback, which is what makes a token like
            ``--force`` land here as a literal string instead of
            raising "no such option"). ``None``/empty means a bare
            ``shepherd config`` — dispatched as ``help``, per bash's
            ``sub="${1:-help}"``.
    """
    raise typer.Exit(code=_dispatch(list(args or [])))


__all__ = ["app", "GateToolchain", "is_shepherd_project"]
