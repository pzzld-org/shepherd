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

Timestamps: N/A — this module writes no database rows and stamps no
epoch fields; every write here is a plain file write (``.claude/shepherd.toml``
/ ``CLAUDE.md``).
"""

from __future__ import annotations

import os
import re
import subprocess

import typer
from pydantic import BaseModel, ConfigDict

from shepherd_cli.resolution import resolve_repo_root, resolve_workdir

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
    "                                max_parallel, dashboard_cadence, …)."
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


def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config file paths ``cfg_get`` checks, in precedence order.

    Bash parity with ``_lib.sh``'s ``cfg_get`` file loop:
    ``.claude/shepherd.local.toml`` (per-key local override) ->
    ``.claude/shepherd.toml`` (project) -> ``$XDG_CONFIG_HOME/shepherd.toml``
    (user global, falling back to ``$HOME/.config`` when
    ``XDG_CONFIG_HOME`` is unset or empty). Duplicated verbatim from
    :mod:`shepherd_cli.commands.models`'s identically-named helper — small,
    intentional duplication, per this package's self-contained-module
    convention.

    Args:
        repo_root: The resolved repository root.

    Returns:
        The three candidate file paths, in the order ``cfg_get`` tries
        them.
    """
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or ""
    if not xdg_config_home:
        home = os.environ.get("HOME") or os.path.expanduser("~")
        xdg_config_home = os.path.join(home, ".config")
    return (
        os.path.join(repo_root, ".claude", "shepherd.local.toml"),
        os.path.join(repo_root, ".claude", "shepherd.toml"),
        os.path.join(xdg_config_home, "shepherd.toml"),
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
    """Scaffold ``.claude/shepherd.toml`` from the bundled minimal template.

    Bash parity with ``cmd_config.sh``'s ``do_init``.

    Args:
        force: When True, skip both the "destination already exists" and
            "a local-override config is present" idempotency guards and
            overwrite unconditionally.

    Returns:
        0 on success (including every "preserved, nothing written" early
        return); 1 if the bundled template is missing (an installation
        defect, not a user error — bash prints this to stderr too).
    """
    repo = resolve_repo_root()
    dst = os.path.join(repo, ".claude", "shepherd.toml")

    if not force:
        if os.path.isfile(dst):
            typer.echo(f"shctx config: {dst} already exists (preserving)")
            return 0
        local_override_a = os.path.join(repo, ".claude", "shepherd.local.toml")
        local_override_b = os.path.join(repo, ".local.toml")
        if os.path.isfile(local_override_a) or os.path.isfile(local_override_b):
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
    ns = os.path.basename(_resolve_workdir_quiet())
    gates = _detect_gates(repo)

    os.makedirs(os.path.join(repo, ".claude"), exist_ok=True)
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
    """Print the resolved project/local config file(s), raw.

    Bash parity with ``cmd_config.sh``'s ``show`` arm: for each of
    ``.claude/shepherd.local.toml`` and ``.claude/shepherd.toml`` (in
    that order) that exists, prints ``# <path>``, the file's raw
    content verbatim, then a blank line. Prints a "no config" notice
    instead if NEITHER file exists. Note this checks only those two
    files — unlike :func:`_cfg_get`'s three-file precedence chain, the
    XDG global config is never shown here (bash parity: ``show`` never
    reads ``$XDG_CONFIG_HOME``).

    Returns:
        0, always (bash parity: this subcommand never fails).
    """
    repo = resolve_repo_root()
    found = False
    output = ""
    for path in (
        os.path.join(repo, ".claude", "shepherd.local.toml"),
        os.path.join(repo, ".claude", "shepherd.toml"),
    ):
        if os.path.isfile(path):
            found = True
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            output += f"# {path}\n{content}\n"
    if not found:
        output += "(no .claude/shepherd.toml — run 'shctx config init')\n"
    typer.echo(output, nl=False)
    return 0


def _do_path() -> int:
    """Echo the canonical ``shepherd.toml`` write location.

    Bash parity with ``cmd_config.sh``'s ``path`` arm: always echoes
    ``<repo_root>/.claude/shepherd.toml``, whether or not the file
    exists.

    Returns:
        0, always.
    """
    typer.echo(os.path.join(resolve_repo_root(), ".claude", "shepherd.toml"))
    return 0


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
    if sub in ("help", "-h", "--help"):
        return _do_help()

    typer.echo("ERROR: usage: shctx config <init|claude-md|show|path|get>", err=True)
    return 1


@app.callback(invoke_without_command=True, context_settings={"ignore_unknown_options": True, "help_option_names": []})
def config(
    args: list[str] = typer.Argument(
        None,
        help=(
            "Subcommand + args: 'init [--force]' | 'claude-md [--force]' | 'get <key> [default]' "
            "| 'show' | 'path' | 'help'. Defaults to 'help'."
        ),
    ),
) -> None:
    """Scaffold / inspect the project ``shepherd.toml`` binding — native port of ``shctx config``.

    See the module docstring for why this is ONE variadic callback
    rather than five ``@app.command()``s: bash's default-to-``help`` and
    exit-1-on-unknown-subcommand contracts, plus ``init``/``claude-md``'s
    positional-only ``--force`` check, don't match Typer/Click's own
    subcommand-dispatch defaults.

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


__all__ = ["app", "GateToolchain"]
