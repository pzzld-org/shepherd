"""``shepherd dups`` — field-shape similar-struct detection (bash: ``cmd_dups.sh``, v6.1.8 #157).

Native port of ``skills/context/scripts/cmd_dups.sh``: the third leg of the
mechanical shape-gate set (alongside dep-hygiene and check-impls-defs) that
catches the rename-to-evade-dedup shadow — a second type for an existing
concept under a DIFFERENT name — that name-matching dedup (``index_symbols``
/ ``dedup-check.sql``) cannot see.

Three subcommands, mirrored exactly:

* ``scan``      census the workspace, cluster similar shapes, suggest a canonical.
* ``check``     match a candidate's new defs vs the persisted corpus (authoring gate).
* ``registry``  curate concept→canonical pins + the DO-NOT-MERGE allow-list.

**PURE SUBPROCESS-ORCHESTRATION + FILE, NO ORM.** Exactly like
``cmd_dups.sh`` itself, this module never runs the shape parse / weighted-
Jaccard similarity / union-find clustering logic in Python — that entire
engine already exists, byte-for-byte, in the sibling stdlib script
``skills/context/scripts/dups-core.py`` (pure ``argparse`` + ``re`` + a
hand-rolled Rust brace/generic-aware scanner; no build step). ``cmd_dups.sh``
itself does only four things: config resolution, git-aware ``*.rs`` file
enumeration, argv construction, and JSON-registry curation via ``jq`` — this
port mirrors that division of labor precisely, locating ``dups-core.py`` via
:func:`shepherd_cli.resolution.find_bash_shctx` (same directory as the
``shctx`` dispatcher, exactly like :mod:`shepherd_cli.commands.sync`'s
``_scripts_dir()``) and running it as a real ``python3`` subprocess with the
SAME argv shape bash builds. Reimplementing the parser/clusterer in this
package would risk silent behavioral drift from the one true engine bash
(and the PreToolUse hook, and ``dups check``'s own authoring gate) already
depend on — hard rule #9's "subprocess-orchestration" shape, generalized
from "shells to a sibling ``shctx`` subcommand" to "shells to a sibling
stdlib script", which is what ``cmd_dups.sh`` itself actually does.

**NO ``models_dups.py``.** ``index_struct_shapes`` (migration
``0015_struct_shapes.sql``) is real, and ``scan --update``/``registry
update`` DO end up writing rows into it — but every one of those writes
happens INSIDE the ``dups-core.py`` subprocess's own ``persist_shapes()``
(a raw ``sqlite3`` connection dups-core.py opens itself, with its own
self-healing ``CREATE TABLE IF NOT EXISTS``), never through a Tortoise
connection this module opens. This module therefore imports neither
:mod:`shepherd_cli.db` nor any Tortoise model and opens no
``db.lifespan()`` — the exact same "a subprocess-orchestration command
with no DIRECT DB access needs no lifespan and no mirror-model module"
shape :mod:`shepherd_cli.commands.sync` documents for ``cmd_sync.sh``
(hard rule #7), even though (unlike ``cmd_sync.sh``) a database row can
genuinely end up written by the time this command returns.

WHY ONE VARIADIC CALLBACK, NOT THREE ``@app.command()``s
==========================================================
``cmd_dups.sh`` is one ``case "$sub" in scan|check|registry|""|-h|--help|*)
... esac`` dispatch, and each of ``scan``/``check`` is ITSELF a hand-rolled
``while [[ $# -gt 0 ]]; do case "$arg" in ... esac; shift; done`` token loop
accepting both ``--flag value`` (issue-spec form) and ``--flag=value``
(shctx house style), with its own ``-h|--help`` arm printing the SAME global
usage text from ANY position in the remaining tokens, and its own
"unrecognized flag -> ``ERROR: unknown arg: <token>``, exit 1" catch-all.
None of that matches Typer/Click's own subcommand-dispatch or option-parsing
defaults (Click would raise "No such option" at exit code 2 for an
unrecognized ``--flag``, not run a case arm). Exactly like
:mod:`shepherd_cli.commands.config` (bash parity notes 1-3 in that module's
docstring) and :mod:`shepherd_cli.commands.search`/``sync`` (self-parsed
variadic token loops), this module registers ZERO ``@app.command()``s and
instead defines one ``@app.callback(invoke_without_command=True)`` that
captures every token after ``dups`` as a raw ``list[str]``
(``context_settings={"ignore_unknown_options": True, "help_option_names":
[]}``, so a token like ``--json`` or ``-h`` lands here as a literal string
instead of Click intercepting it) and dispatches on ``argv[0]`` exactly like
bash's ``case`` statement — see :func:`_dispatch`.

Known parity gap (shared with every other multi-subcommand port in this
package, e.g. ``sprint``/``deliverable``/``signal``): Typer/Click's own
argument-count validation never fires here (every subcommand consumes a
raw ``list[str]`` with no Click-level arity checks) — this module owns
100% of its own validation, matching bash's own total absence of any
framework-level arg checking.

Timestamps: N/A at this layer. ``index_struct_shapes.refreshed_at`` (epoch
SECONDS, ``int(time.time())``) is stamped entirely inside ``dups-core.py``'s
own ``persist_shapes()`` — this module never constructs or reads that
column itself.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import typer
from pydantic import BaseModel, ConfigDict, Field

from shepherd_cli.resolution import find_bash_shctx, resolve_db_path, resolve_repo_root, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires full control over -h/--help's own output (the
    # single global usage() heredoc, printed verbatim from any dispatch
    # point) instead of Click's autogenerated help text -- see the module
    # docstring's "WHY ONE VARIADIC CALLBACK" section, mirroring
    # shepherd_cli.commands.config's identical technique.
    context_settings={"ignore_unknown_options": True, "help_option_names": []},
    help="Field-shape similar-struct detection: scan | check | registry (bash: cmd_dups.sh, #157).",
)

#: Verbatim bash-parity usage text -- cmd_dups.sh's usage() heredoc (lines
#: 69-91), printed to STDOUT on a bare invocation / -h / --help (exit 0),
#: and to STDERR (prefixed by an ERROR line) on an unknown subcommand
#: (exit 1) -- mirroring bash's ``usage`` vs ``usage >&2`` call-site
#: redirection (the function itself always writes to its own stdout; only
#: the CALLER decides which fd that lands on).
_USAGE = (
    "shctx dups — field-shape similar-struct detection (#157)\n"
    "\n"
    "  scan  [--threshold F] [--name-weight F] [--min-fields N]\n"
    "        [--fail-on medium|high|foundation-blocking|any] [--update] [--json]\n"
    "            Census every public struct/enum, cluster by field-shape similarity,\n"
    "            and report clusters with a suggested canonical (lowest dep tier).\n"
    "            --update persists the shape corpus to index_struct_shapes (so\n"
    "            `dups check` is fast). --fail-on sets a non-zero exit for gates/CI.\n"
    "\n"
    "  check <file> | --stdin --as <path>  [--threshold F] [--block-threshold F] [--json]\n"
    "            Match a candidate's NEW struct/enum defs against the persisted\n"
    '            corpus; report any same-shape existing type ("reuse it?"). Exits 5\n'
    "            when a match ≥ block-threshold exists. Used by the PreToolUse hook\n"
    "            and as a coder Phase-0 step.\n"
    "\n"
    "  registry show|path|allow A B|unallow A B|pin CONCEPT PKG::TYPE|unpin CONCEPT|update\n"
    "            Curate the concept→canonical pins and the DO-NOT-MERGE allow-list\n"
    "            (intentional distinct-role twins). Feeds scan + check.\n"
    "\n"
    "Config (.claude/shepherd.toml [dups]): dups_threshold, dups_block,\n"
    "dups_name_weight, dups_min_fields, dups_hook (off|warn|block), dups_registry."
)

#: Directories excluded from the git-less ``os.walk`` fallback file-listing
#: branch, matching ``list_rust_files``'s ``find ... -not -path '*/target/*'
#: -not -path '*/.git/*' -not -path '*/node_modules/*'`` predicate: any
#: directory (at any depth) whose basename is one of these is pruned from
#: the walk entirely, so nothing beneath it is ever visited -- the same
#: effect as bash's path-substring exclusion.
_WALK_SKIP_DIRS = frozenset({"target", ".git", "node_modules"})

#: ``_lib.sh``'s ``cfg_get`` value-extraction pipeline, split into its two
#: regex stages (duplicated from :mod:`shepherd_cli.commands.config`'s
#: identically-named module-level constants -- both modules are
#: self-contained per this port's instructions).
_CFG_VALUE_PREFIX_RE = re.compile(r"^[^=]*=\s*")
_CFG_TRAILING_COMMENT_RE = re.compile(r"\s+#.*$")


# --------------------------------------------------------------------------
# Pydantic schema -- the one piece of genuinely STRUCTURED, persisted state
# this module owns end to end: the jq-managed JSON registry file
# (``dups-registry.json``). Everything else here is transient CLI-argument
# state (plain local variables / tuples), matching the parse-loop
# conventions of shepherd_cli.commands.sync/search/config -- this port
# follows that same precedent rather than wrapping ephemeral flag state in
# a model of its own.
# --------------------------------------------------------------------------
class DupsRegistry(BaseModel):
    """The ``dups-registry.json`` document ``shctx dups registry`` curates.

    Mirrors ``cmd_dups.sh``'s ``_read_registry``/``_write_registry`` shape
    exactly: a JSON object with a schema ``version``, a concept→canonical
    pin map, and a DO-NOT-MERGE allow-list of intentional-twin pairs.
    ``dups-core.py``'s own ``_read_registry`` (the corpus-matching side)
    reads the identical shape.

    Attributes:
        version: Schema version tag. Always ``1`` for a freshly-scaffolded
            registry (bash: ``{"version":1,"canonical":{},"allow":[]}``);
            preserved as-is when read back from an existing file (never
            rewritten by any curation action here).
        canonical: Concept name -> ``"package::Type"`` pin, insertion-order
            preserved (JSON object key order == Python dict insertion
            order == jq's own object-key preservation for everything
            except ``allow``'s ``unique``-triggered resort — see
            :func:`_registry_allow`).
        allow: DO-NOT-MERGE pairs, each a two-element ``[A, B]`` list of
            ``package::Type`` strings (order-insensitive when matched by
            ``dups-core.py``'s own ``_allow_listed``, but the ARRAY itself
            preserves whatever order each element was stored/sorted in).
    """

    model_config = ConfigDict(extra="allow")

    version: int = 1
    canonical: dict[str, str] = Field(default_factory=dict)
    allow: list[list[str]] = Field(default_factory=list)


# --------------------------------------------------------------------------
# cfg_get -- section-agnostic line-scan, bash-parity with _lib.sh's cfg_get.
# Duplicated verbatim from shepherd_cli.commands.config's identically-named
# helpers (self-contained module convention -- see hard rule set /
# config.py's own docstring deviation note #2 for why this is a raw regex
# scan, not tomllib).
# --------------------------------------------------------------------------
def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config file paths ``cfg_get`` checks, in precedence order.

    Args:
        repo_root: The resolved repository root.

    Returns:
        ``(local_override, project, xdg_global)`` -- the exact three
        candidate paths ``cfg_get`` tries, in that order.
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

    Args:
        line: The raw matched line, with or without a trailing newline.

    Returns:
        The extracted value (comment-stripped, one leading/trailing
        double-quote stripped), possibly empty.
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
    """Resolve one top-level config key, bash-parity with ``_lib.sh``'s ``cfg_get``.

    Args:
        key: The config key to resolve, e.g. ``"dups_threshold"``.
        repo_root: The resolved repository root.

    Returns:
        The resolved value (local -> project -> XDG precedence, last match
        per file wins), or ``""`` if unset everywhere.
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


def _cfg_default(key: str, default: str, repo_root: str) -> str:
    """``cfg_get`` a key, falling back to ``default`` when unset.

    Mirrors every ``cmd_dups.sh`` config read's own shape:
    ``X="$(cfg_get key)"; [[ -n "$X" ]] || X=default``.

    Args:
        key: The config key.
        default: The value to use when ``key`` resolves to ``""``.
        repo_root: The resolved repository root.

    Returns:
        The resolved (or default) value, as a raw string -- never parsed
        to float/int here; every threshold/weight/count flows straight
        through to ``dups-core.py``'s own ``argparse`` as a CLI arg string,
        exactly as bash passes it.
    """
    value = _cfg_get(key, repo_root)
    return value if value else default


# --------------------------------------------------------------------------
# project_id / registry-path / repo-root resolution.
# --------------------------------------------------------------------------
def _read_project_id() -> str:
    """Read the host project id from ``<workdir>/project.json``.

    Bash parity with ``_lib.sh``'s ``shctx_project_id`` as called
    everywhere in ``cmd_dups.sh``: ``pid="$(shctx_project_id 2>/dev/null
    || true)"`` -- every failure mode (missing file, unreadable, invalid
    JSON, non-object top level) collapses to ``""``. Duplicated from
    :mod:`shepherd_cli.commands.sprint`'s identically-named helper (both
    modules are self-contained per this port's instructions).

    Returns:
        The resolved project id string, the literal string ``"null"`` when
        ``project.json``'s ``"id"`` key is present-but-JSON-null (``jq -r
        '.id'``'s own raw-output rendering of JSON ``null`` -- NOT an
        error), or ``""`` on any other failure.
    """
    path = os.path.join(resolve_workdir(), "project.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    if "id" not in data or data["id"] is None:
        return "null"
    value = data["id"]
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, indent=2)


def _registry_path(repo_root: str) -> str:
    """Resolve the JSON registry file's path, bash-parity with ``registry_path()``.

    Args:
        repo_root: The resolved repository root.

    Returns:
        ``cfg_get('dups_registry')``, absolute as-is or joined onto
        ``repo_root`` when relative; else ``<workdir>/dups-registry.json``
        (bash: ``shctx_artifacts_root()``, i.e.
        :func:`shepherd_cli.resolution.resolve_workdir`).
    """
    configured = _cfg_get("dups_registry", repo_root)
    if configured:
        if configured.startswith("/"):
            return configured
        return f"{repo_root}/{configured}"
    return f"{resolve_workdir()}/dups-registry.json"


def _scripts_dir() -> str:
    """Resolve the directory containing ``dups-core.py`` (and the ``shctx`` dispatcher).

    Bash parity with ``cmd_dups.sh``'s own ``HERE="$(cd "$(dirname "$0")"
    && pwd)"`` -- the directory holding ``cmd_dups.sh`` itself is the same
    directory that holds ``dups-core.py``. Located via
    :func:`shepherd_cli.resolution.find_bash_shctx`, mirroring
    :mod:`shepherd_cli.commands.sync`'s identically-named helper.

    Returns:
        The absolute path to ``skills/context/scripts``.

    Raises:
        typer.Exit: code 1, with a stderr message, if the bash ``shctx``
            tooling cannot be located at all -- ``scan``/``check``/
            ``registry update`` all shell out to ``dups-core.py`` in that
            same directory, so there is nothing useful this command can do
            without it.
    """
    shctx_path = find_bash_shctx()
    if shctx_path is None:
        typer.echo("ERROR: bash shctx tooling not found (skills/context/scripts/)", err=True)
        raise typer.Exit(code=1)
    return os.path.dirname(shctx_path)


def _require_python() -> str | None:
    """Locate ``python3`` on ``PATH``, bash-parity with ``require_python()``.

    Bash: ``PY="$(command -v python3 || true)"`` at module scope, then
    ``require_python() { [[ -n "$PY" ]] || { echo "... skipping
    (fail-open)." >&2; exit 0; } }`` called at the top of every subcommand
    that needs it (``scan``, ``check``, ``registry update`` -- NOT the pure
    JSON-curation registry actions, which never touch ``dups-core.py`` at
    all).

    Returns:
        The resolved ``python3`` executable path, or ``None`` if not found
        on ``PATH`` -- the caller is responsible for printing the
        fail-open stderr message and returning exit code 0, exactly like
        bash's ``require_python`` does inline (this helper itself never
        raises/exits, so it stays a plain, testable lookup).
    """
    return shutil.which("python3")


# --------------------------------------------------------------------------
# Rust file enumeration -- bash parity with ``list_rust_files()``.
# --------------------------------------------------------------------------
def _list_rust_files(repo_root: str) -> list[str]:
    """Newline-list of ``*.rs`` files, repo-root-relative (git-aware).

    Bash parity with ``cmd_dups.sh``'s ``list_rust_files()``: when
    ``repo_root`` is a real git repo (``git -C "$root" rev-parse``
    succeeds), uses ``git ls-files --cached --others --exclude-standard --
    '*.rs'`` (tracked + new-but-not-ignored, git's own sort order).
    Otherwise falls back to a plain filesystem walk excluding any
    ``target``/``.git``/``node_modules`` directory at any depth (bash:
    ``find . -type f -name '*.rs' -not -path '*/target/*' -not -path
    '*/.git/*' -not -path '*/node_modules/*'``), sorted for determinism
    (bash's own ``find`` order is filesystem-dependent and never asserted
    on by this port's tests).

    Args:
        repo_root: The resolved repository root to search from.

    Returns:
        Repo-root-relative ``*.rs`` file paths (forward-slash separated),
        in git's own listing order for the git branch, or sorted order for
        the fallback branch.
    """
    try:
        check = subprocess.run(
            ["git", "-C", repo_root, "rev-parse"],
            capture_output=True,
            text=True,
            check=False,
        )
        is_git = check.returncode == 0
    except OSError:
        is_git = False

    if is_git:
        result = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.rs"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [line for line in result.stdout.splitlines() if line]

    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _WALK_SKIP_DIRS)
        for filename in sorted(filenames):
            if filename.endswith(".rs"):
                rel = os.path.relpath(os.path.join(dirpath, filename), repo_root)
                paths.append(rel.replace(os.sep, "/"))
    return sorted(paths)


def _rust_files_stdin(repo_root: str) -> str:
    """Build the newline-joined ``*.rs`` file list ``dups-core.py --files-stdin`` expects.

    Args:
        repo_root: The resolved repository root.

    Returns:
        Every listed file path, one per line, with a trailing newline
        (empty string if no files matched) -- exactly what
        ``list_rust_files | python3 dups-core.py ...`` pipes to the
        subprocess's stdin.
    """
    files = _list_rust_files(repo_root)
    return "\n".join(files) + ("\n" if files else "")


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------
class _ScanArgs(BaseModel):
    """Parsed ``shctx dups scan`` flags, resolved (config defaults already applied)."""

    model_config = ConfigDict(frozen=True)

    threshold: str
    name_weight: str
    min_fields: str
    fail_on: str = ""
    update: bool = False
    json_out: bool = False
    quiet: bool = False


def _take_value(tokens: list[str], i: int, flag: str) -> tuple[str, int]:
    """Consume the next token as ``flag``'s value, bash-parity with ``${2:?msg}``.

    Bash's ``"${2:?--threshold needs a value}"`` unconditionally treats the
    very next positional token as the flag's value (it does not check
    whether that token itself looks like another flag) and only errors
    when there IS no next token at all. This helper reproduces exactly
    that: any next token (including one starting with ``--``) is accepted
    as the value.

    Args:
        tokens: The full remaining-argument token list.
        i: The index of the flag token itself (``tokens[i] == flag``,
            e.g. ``"--threshold"``).
        flag: The flag's own text, for the error message.

    Returns:
        ``(value, next_index)`` -- ``next_index`` is ``i + 2`` (the flag
        token and its value both consumed).

    Raises:
        typer.Exit: code 1, with a stderr message (a controlled,
            documented stand-in for bash's own unbound-variable abort
            text under ``set -eu``, not byte-identical to it), if there is
            no next token.
    """
    if i + 1 >= len(tokens):
        typer.echo(f"ERROR: {flag} needs a value", err=True)
        raise typer.Exit(code=1)
    return tokens[i + 1], i + 2


def _parse_scan_args(tokens: list[str], repo_root: str) -> _ScanArgs:
    """Parse ``shctx dups scan``'s token stream, bash-parity with its ``while`` loop.

    Both ``--flag value`` (issue-spec form) and ``--flag=value`` (shctx
    house style) are accepted for every value-taking flag, matching
    ``cmd_dups.sh``'s ``scan)`` case block exactly. ``-h``/``--help``
    short-circuits immediately from any position (prints the global usage
    text, exit 0); any other unrecognized token is an immediate hard
    error.

    Args:
        tokens: Every token given after ``dups scan``, in order.
        repo_root: The resolved repository root (for config-default
            resolution).

    Returns:
        The parsed, config-defaulted :class:`_ScanArgs`.

    Raises:
        typer.Exit: code 0 (usage printed) on ``-h``/``--help``; code 1
            (stderr message) on an unrecognized token or a value-taking
            flag given with nothing following it.
    """
    threshold = _cfg_default("dups_threshold", "0.7", repo_root)
    name_weight = _cfg_default("dups_name_weight", "0.5", repo_root)
    min_fields = _cfg_default("dups_min_fields", "2", repo_root)
    fail_on = ""
    update = False
    json_out = False
    quiet = False

    i = 0
    n = len(tokens)
    while i < n:
        arg = tokens[i]
        if arg == "--threshold":
            threshold, i = _take_value(tokens, i, "--threshold")
        elif arg.startswith("--threshold="):
            threshold = arg[len("--threshold=") :]
            i += 1
        elif arg == "--name-weight":
            name_weight, i = _take_value(tokens, i, "--name-weight")
        elif arg.startswith("--name-weight="):
            name_weight = arg[len("--name-weight=") :]
            i += 1
        elif arg == "--min-fields":
            min_fields, i = _take_value(tokens, i, "--min-fields")
        elif arg.startswith("--min-fields="):
            min_fields = arg[len("--min-fields=") :]
            i += 1
        elif arg == "--fail-on":
            fail_on, i = _take_value(tokens, i, "--fail-on")
        elif arg.startswith("--fail-on="):
            fail_on = arg[len("--fail-on=") :]
            i += 1
        elif arg == "--update":
            update = True
            i += 1
        elif arg == "--json":
            json_out = True
            i += 1
        elif arg == "--quiet":
            quiet = True
            i += 1
        elif arg in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            raise typer.Exit(code=1)

    return _ScanArgs(
        threshold=threshold,
        name_weight=name_weight,
        min_fields=min_fields,
        fail_on=fail_on,
        update=update,
        json_out=json_out,
        quiet=quiet,
    )


def _do_scan(rest: list[str]) -> int:
    """Run ``shctx dups scan``: census, cluster, report (and optionally persist).

    Bash parity with ``cmd_dups.sh``'s ``scan)`` case arm: resolves
    ``$db``/``$pid``, builds ``dups-core.py``'s argv, pipes the git-aware
    ``*.rs`` file list to its stdin from a subshell ``cd``'d to the repo
    root, and returns its exit code verbatim (0 normally, 3 on a
    ``--fail-on`` gate failure, or ``dups-core.py``'s own ``argparse``
    error code for a malformed ``--fail-on`` choice).

    Args:
        rest: Every token after ``dups scan``.

    Returns:
        ``dups-core.py``'s subprocess exit code. 0 if ``python3`` is
        unavailable (bash's fail-open contract) -- NOT an error.
    """
    repo_root = resolve_repo_root()
    scan_args = _parse_scan_args(rest, repo_root)

    python_bin = _require_python()
    if python_bin is None:
        typer.echo("shctx dups: python3 not found — skipping (fail-open).", err=True)
        return 0

    scripts_dir = _scripts_dir()
    core = os.path.join(scripts_dir, "dups-core.py")

    db_path = resolve_db_path()
    project_id = _read_project_id()

    argv = [
        python_bin,
        core,
        "scan",
        "--files-stdin",
        "--threshold",
        scan_args.threshold,
        "--name-weight",
        scan_args.name_weight,
        "--min-fields",
        scan_args.min_fields,
        "--registry",
        _registry_path(repo_root),
    ]
    if scan_args.fail_on:
        argv += ["--fail-on", scan_args.fail_on]
    if scan_args.update and project_id:
        argv += ["--update", "--db", db_path, "--project-id", project_id]
    if scan_args.json_out:
        argv.append("--json")

    stdin_text = _rust_files_stdin(repo_root)
    if scan_args.quiet:
        result = subprocess.run(
            argv, cwd=repo_root, input=stdin_text, text=True, stdout=subprocess.DEVNULL, check=False
        )
    else:
        result = subprocess.run(argv, cwd=repo_root, input=stdin_text, text=True, check=False)
    return result.returncode


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------
class _CheckArgs(BaseModel):
    """Parsed ``shctx dups check`` flags, resolved (config defaults already applied)."""

    model_config = ConfigDict(frozen=True)

    threshold: str
    block_threshold: str
    name_weight: str
    min_fields: str
    json_out: bool = False
    use_stdin: bool = False
    as_path: str = ""
    file_arg: str = ""


def _parse_check_args(tokens: list[str], repo_root: str) -> _CheckArgs:
    """Parse ``shctx dups check``'s token stream, bash-parity with its ``while`` loop.

    Args:
        tokens: Every token given after ``dups check``, in order.
        repo_root: The resolved repository root (for config-default
            resolution).

    Returns:
        The parsed, config-defaulted :class:`_CheckArgs`. ``file_arg`` is
        the LAST bare (non-``--``-prefixed) token seen (bash: plain
        variable reassignment inside the loop -- the last positional wins,
        not the first).

    Raises:
        typer.Exit: code 0 (usage printed) on ``-h``/``--help``; code 1
            (stderr message) on an unrecognized ``--`` flag or a
            value-taking flag given with nothing following it.
    """
    threshold = _cfg_default("dups_threshold", "0.7", repo_root)
    block_threshold = _cfg_default("dups_block", "0.85", repo_root)
    name_weight = _cfg_default("dups_name_weight", "0.5", repo_root)
    min_fields = _cfg_default("dups_min_fields", "2", repo_root)
    json_out = False
    use_stdin = False
    as_path = ""
    file_arg = ""

    i = 0
    n = len(tokens)
    while i < n:
        arg = tokens[i]
        if arg == "--threshold":
            threshold, i = _take_value(tokens, i, "--threshold")
        elif arg.startswith("--threshold="):
            threshold = arg[len("--threshold=") :]
            i += 1
        elif arg == "--block-threshold":
            block_threshold, i = _take_value(tokens, i, "--block-threshold")
        elif arg.startswith("--block-threshold="):
            block_threshold = arg[len("--block-threshold=") :]
            i += 1
        elif arg == "--name-weight":
            name_weight, i = _take_value(tokens, i, "--name-weight")
        elif arg.startswith("--name-weight="):
            name_weight = arg[len("--name-weight=") :]
            i += 1
        elif arg == "--min-fields":
            min_fields, i = _take_value(tokens, i, "--min-fields")
        elif arg.startswith("--min-fields="):
            min_fields = arg[len("--min-fields=") :]
            i += 1
        elif arg == "--as":
            as_path, i = _take_value(tokens, i, "--as")
        elif arg.startswith("--as="):
            as_path = arg[len("--as=") :]
            i += 1
        elif arg == "--stdin":
            use_stdin = True
            i += 1
        elif arg == "--json":
            json_out = True
            i += 1
        elif arg in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        elif arg.startswith("--"):
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            raise typer.Exit(code=1)
        else:
            file_arg = arg
            i += 1

    return _CheckArgs(
        threshold=threshold,
        block_threshold=block_threshold,
        name_weight=name_weight,
        min_fields=min_fields,
        json_out=json_out,
        use_stdin=use_stdin,
        as_path=as_path,
        file_arg=file_arg,
    )


def _do_check(rest: list[str]) -> int:
    """Run ``shctx dups check``: match a candidate's new defs against the persisted corpus.

    Bash parity with ``cmd_dups.sh``'s ``check)`` case arm: normalizes
    ``--as`` to repo-relative when it starts with the repo root (so
    self-exclusion matches the corpus), then runs ``dups-core.py`` either
    reading the candidate's content from THIS process's own inherited
    stdin (``--stdin``) or from the given file path positionally.

    Args:
        rest: Every token after ``dups check``.

    Returns:
        ``dups-core.py``'s subprocess exit code (0 normally, 5 when a
        match at or above ``--block-threshold`` exists). 0 if ``python3``
        is unavailable (fail-open). 1, with a stderr usage message, if
        neither ``--stdin`` nor a file argument was given.
    """
    repo_root = resolve_repo_root()
    check_args = _parse_check_args(rest, repo_root)

    python_bin = _require_python()
    if python_bin is None:
        typer.echo("shctx dups: python3 not found — skipping (fail-open).", err=True)
        return 0

    scripts_dir = _scripts_dir()
    core = os.path.join(scripts_dir, "dups-core.py")

    db_path = resolve_db_path()
    project_id = _read_project_id()

    as_path = check_args.as_path
    if as_path:
        prefix = f"{repo_root}/"
        if as_path.startswith(prefix):
            as_path = as_path[len(prefix) :]

    argv = [
        python_bin,
        core,
        "check",
        "--threshold",
        check_args.threshold,
        "--block-threshold",
        check_args.block_threshold,
        "--name-weight",
        check_args.name_weight,
        "--min-fields",
        check_args.min_fields,
        "--registry",
        _registry_path(repo_root),
    ]
    if project_id:
        argv += ["--db", db_path, "--project-id", project_id]
    if as_path:
        argv += ["--as", as_path]
    if check_args.json_out:
        argv.append("--json")

    if check_args.use_stdin:
        argv.append("--stdin")
        result = subprocess.run(argv, check=False)
        return result.returncode

    if not check_args.file_arg:
        typer.echo("ERROR: usage: shctx dups check <file> | --stdin --as <path>", err=True)
        return 1
    if not as_path:
        argv += ["--as", check_args.file_arg]
    argv.append(check_args.file_arg)
    result = subprocess.run(argv, check=False)
    return result.returncode


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
def _read_registry(path: str) -> DupsRegistry:
    """Read the JSON registry file, bash-parity with ``_read_registry()``.

    Args:
        path: The resolved registry file path.

    Returns:
        The parsed :class:`DupsRegistry`, or a fresh
        ``{"version":1,"canonical":{},"allow":[]}`` default when the file
        does not exist (bash: ``_read_registry``'s own missing-file
        fallback).

    Raises:
        typer.Exit: code 1, with a stderr message, if the file exists but
            is not valid JSON -- a controlled, documented stand-in for
            ``jq``'s own parse-error abort (bash: an unguarded
            ``_read_registry | jq ...`` pipeline under ``set -e -o
            pipefail`` would abort the whole script with ``jq``'s own
            nonzero exit code on the same input; this port's exit code and
            message are not byte-identical to ``jq``'s).
    """
    if not os.path.isfile(path):
        return DupsRegistry()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR: {path}: invalid JSON registry", err=True)
        raise typer.Exit(code=1) from exc
    if not isinstance(data, dict):
        typer.echo(f"ERROR: {path}: invalid JSON registry (not an object)", err=True)
        raise typer.Exit(code=1)
    return DupsRegistry.model_validate(data)


def _write_registry(path: str, registry: DupsRegistry) -> None:
    """Write the JSON registry file, bash-parity with ``_write_registry()``.

    Args:
        path: The resolved registry file path.
        registry: The document to persist.

    Bash: ``mkdir -p "$(dirname "$p")"; cat > "$p"`` (writing whatever
    ``jq`` printed, 2-space indented by ``jq``'s own default pretty-print),
    then ``echo "shctx dups registry: wrote $p"``. The trailing
    ``typer.echo`` announcement is the CALLER's job (every curation action
    below prints it right after calling this), matching bash's
    ``_write_registry`` doing the announcement itself as its own last line
    -- functionally identical either way since every call site here has
    exactly one caller.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(registry.model_dump(mode="json"), fh, indent=2)
        fh.write("\n")


def _registry_show(args: list[str], repo_root: str) -> int:
    """``shctx dups registry show [--json]``.

    Args:
        args: Tokens after ``registry show`` (only ``args[0] ==
            "--json"`` is ever inspected, matching bash's ``${1:-}``
            single-token check -- anything else, including extra trailing
            tokens, falls through to the text renderer).
        repo_root: The resolved repository root.

    Returns:
        0, always.
    """
    registry = _read_registry(_registry_path(repo_root))
    if args and args[0] == "--json":
        typer.echo(json.dumps(registry.model_dump(mode="json"), indent=2))
        return 0

    lines = [f"DO-NOT-MERGE allow-list ({len(registry.allow)} pair(s)):"]
    for pair in registry.allow:
        a = pair[0] if len(pair) > 0 else ""
        b = pair[1] if len(pair) > 1 else ""
        lines.append(f"  - {a}  ⟷  {b}")
    lines.append("")
    lines.append(f"Concept → canonical pins ({len(registry.canonical)}):")
    for concept, target in registry.canonical.items():
        lines.append(f"  - {concept}  →  {target}")
    typer.echo("\n".join(lines))
    return 0


def _registry_allow(args: list[str], repo_root: str) -> int:
    """``shctx dups registry allow <A> <B>``.

    Bash: ``.allow = ((.allow // []) + [[$a,$b]] | unique)`` -- ``jq``'s
    ``unique`` both DEDUPLICATES exact-duplicate pairs AND RESORTS the
    entire array (``unique`` is defined as ``group_by(.) | map(.[0])``,
    and ``group_by`` sorts by its key first) -- so the allow-list's order
    after this action is lexicographic-by-pair, not insertion order.
    Mirrored here with Python's own default list/tuple ordering, which
    orders a list of two-string lists identically to ``jq``'s generic
    value ordering for this always-two-strings case.

    Args:
        args: Tokens after ``registry allow`` (``args[0]``/``args[1]`` are
            ``A``/``B``).
        repo_root: The resolved repository root.

    Returns:
        0 on success; 1, with a stderr usage message, if ``A``/``B`` are
        missing.
    """
    a = args[0] if len(args) > 0 else ""
    b = args[1] if len(args) > 1 else ""
    if not a or not b:
        typer.echo("ERROR: usage: shctx dups registry allow <A> <B>", err=True)
        return 1
    path = _registry_path(repo_root)
    registry = _read_registry(path)
    combined = {tuple(pair) for pair in registry.allow if len(pair) == 2}
    combined.add((a, b))
    registry.allow = [list(pair) for pair in sorted(combined)]
    _write_registry(path, registry)
    typer.echo(f"shctx dups registry: wrote {path}")
    return 0


def _registry_unallow(args: list[str], repo_root: str) -> int:
    """``shctx dups registry unallow <A> <B>``.

    Bash: ``.allow = [(.allow // [])[] | select((. == [$a,$b]) or (. ==
    [$b,$a]) | not)]`` -- a plain filter, order-preserving (unlike
    ``allow``, this never calls ``unique``/resorts).

    Args:
        args: Tokens after ``registry unallow`` (``args[0]``/``args[1]``
            are ``A``/``B``).
        repo_root: The resolved repository root.

    Returns:
        0 on success (including when no matching pair existed -- bash's
        filter is a no-op in that case, not an error); 1, with a stderr
        usage message, if ``A``/``B`` are missing.
    """
    a = args[0] if len(args) > 0 else ""
    b = args[1] if len(args) > 1 else ""
    if not a or not b:
        typer.echo("ERROR: usage: shctx dups registry unallow <A> <B>", err=True)
        return 1
    path = _registry_path(repo_root)
    registry = _read_registry(path)
    target = {(a, b), (b, a)}
    registry.allow = [pair for pair in registry.allow if tuple(pair) not in target]
    _write_registry(path, registry)
    typer.echo(f"shctx dups registry: wrote {path}")
    return 0


def _registry_pin(args: list[str], repo_root: str) -> int:
    """``shctx dups registry pin <concept> <pkg::Type>``.

    Bash: ``.canonical[$c] = $t`` -- sets (or overwrites) one key,
    preserving every other key's existing order and appending a genuinely
    new key at the end (plain JSON-object assignment semantics, matching
    Python dict assignment exactly).

    Args:
        args: Tokens after ``registry pin`` (``args[0]``/``args[1]`` are
            ``concept``/``pkg::Type``).
        repo_root: The resolved repository root.

    Returns:
        0 on success; 1, with a stderr usage message, if either argument
        is missing.
    """
    concept = args[0] if len(args) > 0 else ""
    target = args[1] if len(args) > 1 else ""
    if not concept or not target:
        typer.echo("ERROR: usage: shctx dups registry pin <concept> <pkg::Type>", err=True)
        return 1
    path = _registry_path(repo_root)
    registry = _read_registry(path)
    registry.canonical[concept] = target
    _write_registry(path, registry)
    typer.echo(f"shctx dups registry: wrote {path}")
    return 0


def _registry_unpin(args: list[str], repo_root: str) -> int:
    """``shctx dups registry unpin <concept>``.

    Bash: ``del(.canonical[$c])`` -- no error if the key was already
    absent.

    Args:
        args: Tokens after ``registry unpin`` (``args[0]`` is ``concept``).
        repo_root: The resolved repository root.

    Returns:
        0 on success (including when ``concept`` was not pinned); 1, with
        a stderr usage message, if ``concept`` is missing.
    """
    concept = args[0] if len(args) > 0 else ""
    if not concept:
        typer.echo("ERROR: usage: shctx dups registry unpin <concept>", err=True)
        return 1
    path = _registry_path(repo_root)
    registry = _read_registry(path)
    registry.canonical.pop(concept, None)
    _write_registry(path, registry)
    typer.echo(f"shctx dups registry: wrote {path}")
    return 0


def _registry_update(repo_root: str) -> int:
    """``shctx dups registry update``.

    Bash parity with ``cmd_dups.sh``'s ``update)`` arm: runs a JSON
    ``dups-core.py scan`` (no ``--update``/``--db``/``--project-id`` --
    this action never persists to ``index_struct_shapes``, only reads the
    scan's clusters), then merges a canonical pin for every cluster whose
    ``concept`` is not ALREADY pinned (existing pins are never overwritten
    -- non-destructive merge).

    Args:
        repo_root: The resolved repository root.

    Returns:
        0 in every case: python3-unavailable (fail-open), empty scan
        output ("no scan output"), or a successful merge-and-write.
    """
    python_bin = _require_python()
    if python_bin is None:
        typer.echo("shctx dups: python3 not found — skipping (fail-open).", err=True)
        return 0

    scripts_dir = _scripts_dir()
    core = os.path.join(scripts_dir, "dups-core.py")
    threshold = _cfg_default("dups_threshold", "0.7", repo_root)
    name_weight = _cfg_default("dups_name_weight", "0.5", repo_root)
    min_fields = _cfg_default("dups_min_fields", "2", repo_root)
    registry_file = _registry_path(repo_root)

    argv = [
        python_bin,
        core,
        "scan",
        "--files-stdin",
        "--threshold",
        threshold,
        "--name-weight",
        name_weight,
        "--min-fields",
        min_fields,
        "--registry",
        registry_file,
        "--json",
    ]
    stdin_text = _rust_files_stdin(repo_root)
    result = subprocess.run(argv, cwd=repo_root, input=stdin_text, text=True, capture_output=True, check=False)
    scan_json_text = result.stdout

    if not scan_json_text.strip():
        typer.echo("shctx dups registry update: no scan output")
        return 0

    try:
        scan_data = json.loads(scan_json_text)
    except json.JSONDecodeError as exc:
        typer.echo(f"ERROR: shctx dups registry update: invalid scan output: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    clusters = scan_data.get("clusters") or []
    registry = _read_registry(registry_file)
    for cluster in clusters:
        concept = cluster.get("concept")
        if not concept:
            continue
        if registry.canonical.get(concept) is None:
            registry.canonical[concept] = cluster.get("suggested_canonical", "")
    _write_registry(registry_file, registry)

    typer.echo(f"shctx dups registry update: considered {len(clusters)} cluster concept(s).")
    return 0


def _do_registry(rest: list[str]) -> int:
    """Dispatch ``shctx dups registry``'s own sub-action, bash-parity with its ``case``.

    Args:
        rest: Every token after ``dups registry`` -- ``rest[0]`` is the
            action (defaulting to ``"show"`` when absent, bash:
            ``action="${1:-show}"``), ``rest[1:]`` are that action's own
            arguments.

    Returns:
        The dispatched action's exit code; 1, with a stderr usage message,
        for an unrecognized action.
    """
    repo_root = resolve_repo_root()
    action = rest[0] if rest else "show"
    action_args = rest[1:]

    if action == "path":
        typer.echo(_registry_path(repo_root))
        return 0
    if action == "show":
        return _registry_show(action_args, repo_root)
    if action == "allow":
        return _registry_allow(action_args, repo_root)
    if action == "unallow":
        return _registry_unallow(action_args, repo_root)
    if action == "pin":
        return _registry_pin(action_args, repo_root)
    if action == "unpin":
        return _registry_unpin(action_args, repo_root)
    if action == "update":
        return _registry_update(repo_root)

    typer.echo("ERROR: usage: shctx dups registry <show|path|allow|unallow|pin|unpin|update>", err=True)
    return 1


# --------------------------------------------------------------------------
# Top-level dispatcher + Typer wiring.
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Dispatch on ``argv[0]`` exactly like ``cmd_dups.sh``'s top-level ``case`` statement.

    Args:
        argv: The raw remaining command-line tokens after ``dups``, e.g.
            ``["scan", "--json"]`` or ``[]``.

    Returns:
        The bash-parity process exit code for whichever subcommand ran (or
        the bare/``-h``/``--help``/unknown-subcommand arms).
    """
    sub = argv[0] if argv else ""
    rest = argv[1:]

    if sub == "scan":
        return _do_scan(rest)
    if sub == "check":
        return _do_check(rest)
    if sub == "registry":
        return _do_registry(rest)
    if sub in ("", "-h", "--help"):
        typer.echo(_USAGE)
        return 0

    typer.echo(f"ERROR: unknown dups subcommand: {sub}", err=True)
    typer.echo(_USAGE, err=True)
    return 1


@app.callback(invoke_without_command=True)
def dups(
    args: list[str] = typer.Argument(
        None,
        metavar="<scan|check|registry> [args]",
        help=(
            "Subcommand + args: 'scan [--threshold F] [...]' | 'check <file> | --stdin --as <path> [...]' "
            "| 'registry show|path|allow|unallow|pin|unpin|update [...]'. Defaults to usage."
        ),
    ),
) -> None:
    """Field-shape similar-struct detection — native port of ``shctx dups``.

    See the module docstring for why this is ONE variadic callback rather
    than three ``@app.command()``s: bash's own hand-rolled per-subcommand
    token loops (accepting both ``--flag value`` and ``--flag=value``),
    default-to-usage, and exit-1-on-unknown-subcommand contracts don't
    match Typer/Click's own subcommand-dispatch defaults.

    Args:
        args: Every token after ``dups`` on the command line, in order,
            with NOTHING pre-parsed as flags/options by Click (see this
            app's ``context_settings={"ignore_unknown_options": True,
            "help_option_names": []}``, which is what makes a token like
            ``--json`` or ``-h`` land here as a literal string instead of
            Click intercepting it). ``None``/empty means a bare ``shepherd
            dups`` -- dispatched as the usage arm, per bash's
            ``sub="${1:-}"``.
    """
    raise typer.Exit(code=_dispatch(list(args or [])))


__all__ = ["app", "DupsRegistry"]
