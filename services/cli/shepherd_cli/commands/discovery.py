"""``shepherd discovery`` — discovery report registry Typer sub-app.

Native port of ``skills/context/scripts/cmd_discovery.sh`` (subcommands
``list|show|search|clear|insert``). **MIXED FILESYSTEM + DATABASE**, not
uniformly one or the other:

* ``list``/``show``/``search``/``clear`` are PURE FILESYSTEM, exactly like
  :mod:`shepherd_cli.commands.insights` — one JSON record per discovery at
  ``<workdir>/discoveries/<sprint>/<id>.json``, written by ``hooks/scripts/
  discovery_capture.sh`` (the ``## DISCOVERY REPORT`` hook). These four
  subcommands never open the database at all.
* ``insert`` (v5.1.7+) is the ONE subcommand that touches SQLite — it
  writes a structured markdown-ready finding row directly into the
  ``discovery_findings`` TABLE (migration ``0007_canonical_state.sql``),
  a completely separate id space (an autoincrement integer row id) from
  the JSON-file discovery records the other four subcommands manage. Bash
  intercepts ``insert`` BEFORE namespace/sprint resolution (see
  ``cmd_discovery.sh``'s own comment: "works on direct invocation... does
  not need the hooks-lib resolve_namespace/current_sprint helpers"), so
  this module's :func:`_dispatch` does the same — ``insert`` is checked
  first, before any of the other four subcommands' shared ``ns``/
  ``current_sprint`` resolution ever runs.

**IMPORTANT — reading ``discovery_findings`` back is NOT this module's
job.** ``insert`` writes rows into that table, but NONE of ``list``/
``show``/``search``/``clear`` ever read it — those four exclusively read
the JSON-file store. The table's read side already exists, ported
separately: ``shctx report discovery --run=<id>`` (:mod:`shepherd_cli.
commands.report`, reusing the read-scoped :class:`shepherd_cli.
models_report.DiscoveryFinding` model). This module therefore imports
NEITHER that model NOR :mod:`shepherd_cli.models_report` at all — its own
``insert`` write path goes through raw parameterized SQL instead (see the
COLLISION RULE note below), and its four read subcommands never touch
SQL.

**COLLISION RULE / no ``models_discovery.py``.** ``discovery_findings``
already has a model (:class:`shepherd_cli.models_report.DiscoveryFinding`)
declaring a NARROWER column set than ``insert`` needs to write (it omits
``project_id``, which the INSERT statement below requires). Per the port
contract's rule 3, a write that needs MORE columns than an existing
read-scoped model declares must not redeclare the table — it goes through
raw SQL instead, exactly how :mod:`shepherd_cli.commands.lock` handles
``locks_history``. :func:`_insert_async` therefore uses
``Tortoise.get_connection("default").execute_query_dict`` (to read the
active ``project_id``) and ``.execute_insert`` (a plain parameterized
``INSERT ... VALUES (...)`` returning the new row's ``id`` via sqlite's
``lastrowid`` — equivalent to bash's ``INSERT ... RETURNING id;``) rather
than any Tortoise model. No sibling ``models_discovery.py`` is written for
this port: every table/view this module touches already has either full
raw-SQL treatment (``discovery_findings``, for the one write path) or no
SQL involvement at all (the four file-based subcommands).

WHY ONE VARIADIC CALLBACK, NOT FIVE ``@app.command()``s
==========================================================
Exactly the same reasoning as :mod:`shepherd_cli.commands.insights`/
``handoff``/``dups``/``search``/``sync`` (see those modules' own "WHY ONE
VARIADIC CALLBACK" sections): ``cmd_discovery.sh`` is one hand-rolled
``case "$sub" in ... esac`` dispatch (plus the early ``insert``
intercept), and every subcommand's own flag loop is a per-token ``case``
statement with bash-specific defaulting/error contracts that don't match
Typer/Click's own subcommand-dispatch or option-parsing defaults:

* The bare/``-h``/``--help``/``help`` invocations all print the SAME
  ``usage()`` heredoc to STDOUT and exit 0 (bash: ``sub="${1:-help}"``
  defaults an EMPTY argv to ``"help"``, then ``help|-h|--help) usage
  ;;``).
* An unrecognized top-level subcommand prints ``ERROR: unknown shctx
  discovery subcommand: <sub>`` to STDERR, followed by the usage text
  ALSO on stderr, and exits 1 — not Click's own "no such command".
* ``list``'s and ``search``'s per-token ``case`` statements have NO
  default/unknown-flag arm at all — an unrecognized token is silently
  ignored (bash: the ``case`` simply falls through with no matching
  pattern). ``clear``'s loop is identical (no default arm either).
  ``show``'s loop has no default arm either, but treats the FIRST
  non-``--md``/``--json``/``--report`` token as the id positional (see
  :func:`_do_show`'s docstring for the exact quirk this implies, mirroring
  :mod:`shepherd_cli.commands.insights`'s own ``show`` id-is-literally-
  ``argv[0]`` note).
* ``insert``'s loop is the ONE flag loop in this file that DOES reject an
  unrecognized token — but with its own distinct, lowercase message
  (``unknown flag: <token>``, no ``ERROR:``/``ERR:`` prefix) and exit code
  2 (not 1), and its own distinct required-flag validation message (``ERR:
  --run and --title required``, also exit 2).

So this module registers ZERO ``@app.command()``s and instead defines one
``@app.callback(invoke_without_command=True)`` (``context_settings={
"ignore_unknown_options": True, "help_option_names": []}`` at the app
level, so a token like ``-h`` or ``show``'s free-text id argument lands
here as a literal string instead of Click intercepting it) that captures
every token after ``discovery`` as a raw ``list[str]`` and dispatches on
``argv[0]`` exactly like bash's ``case`` statement — see :func:`_dispatch`.

``resolve_namespace()`` PARITY DETAIL (``list``/``show``/``search``/
``clear`` only, NOT ``insert``): ``_lib.sh``'s ``resolve_namespace()`` shim
sets ``SHCTX_QUIET=1`` before delegating to ``shctx_artifacts_root()`` —
suppressing the "both .shepherd/ and .artifacts/ exist" split-brain
warning that a bare ``resolve_workdir()``/``shctx_artifacts_root()`` call
would otherwise print to stderr. ``cmd_discovery.sh``'s four file-based
subcommands all resolve their namespace through this shim (``ns=$(resolve_
namespace)``, computed once, right after the early ``insert`` intercept);
``insert`` itself resolves its DB path via ``shctx_db_path()`` directly
(no shim), so — asymmetrically — an ``insert`` invocation on a
split-brain project WOULD still print that warning while
``list``/``show``/``search``/``clear`` would not. :func:`_resolve_
namespace` reproduces the shim precisely (temporarily setting
``SHCTX_QUIET`` around a plain :func:`shepherd_cli.resolution.
resolve_workdir` call, restoring whatever was there before); ``insert``'s
:func:`shepherd_cli.resolution.resolve_db_path` call is left exactly as
that shared function already behaves (no wrapping), preserving the
asymmetry.

Timestamps: ``discovery_findings.created_at`` (written by ``insert``) is
epoch-MILLISECONDS (bash: ``ts=$(($(date +%s) * 1000))``) — see
:mod:`shepherd_cli.models_report`'s docstring for the cross-table unit
note. The JSON-file discovery records' own ``captured_at`` field (written
by ``hooks/scripts/discovery_capture.sh``, epoch-SECONDS) is never
computed or interpreted by this module — every read subcommand here
treats the loaded JSON as an opaque ``dict``, relaying field values
through unchanged (see :func:`_jq_interp`), exactly like ``cmd_
discovery.sh``'s own jq-based renderers never compute with it either.

jq-INTERPOLATION PARITY: ``list --md``'s row renderer, ``show --md``'s
record renderer, and ``search``'s row renderer are all built from jq
``\\(...)`` STRING INTERPOLATION expressions in bash (``jq -r '"| \\(.id)
| ..."'``). :func:`_jq_interp` reproduces jq's exact interpolation
semantics for the value types these records actually hold: ``null``
(missing key or JSON ``null``) renders as the four-character string
``"null"`` (NOT Python's ``None`` or an empty string — verified against
the real ``jq`` binary: ``echo '{"a":null}' | jq -r '"x=\\(.a)y"'`` prints
``x=nully``), booleans render as ``true``/``false``, strings pass through
raw, and numbers render via their JSON text form. :func:`_jq_slice60`
mirrors jq's ``.field[:60]`` string-slice semantics used on the
``question``/``report_path``-adjacent fields: slicing ``null`` yields
``null`` (which then interpolates as ``"null"``, not empty), slicing a
string truncates it, matching ``jq``'s own (verified) behavior.
``show --md``'s full record renderer additionally reproduces jq -r's
"double trailing newline" quirk for a format string that itself ends in
an embedded ``\\n``: jq -r appends ONE newline after every printed value,
regardless of what the string already ends in, so a value ending in
``"...\\n"`` prints as ``"...\\n\\n"`` (verified: ``jq -r '"abc\\n"'``
prints ``abc`` followed by two newlines). :func:`_render_show_md` builds
its line list with a trailing empty string so ``"\\n".join(...)`` already
ends in one embedded ``\\n``, then the caller's single ``typer.echo``
supplies the second — reproducing the exact byte count.

``list --json``'s exact byte-for-byte reconstruction: bash's ``cmd_list``
never re-serializes the loaded records — it concatenates each file's RAW
BYTES between a literal ``"["``/``"]"`` and a literal ``","`` line
inserted between consecutive files (see :func:`_render_list_json`'s
docstring for the precise byte-sequence derivation, including why no
extra newline appears between one file's content and the following
comma).

``clear``'s bash quirk mirrored deliberately: the COUNT is computed via
an UNRESTRICTED ``find "$dir" -name "*.json" -type f`` (recurses into any
subdirectory under the sprint dir, no ``-maxdepth``), while the actual
REMOVAL uses a shallow, non-recursive shell glob (``rm -f "$dir"/*.json``,
direct children only). In real usage the sprint directory never contains
nested subdirectories (the writer only ever creates flat ``<id>.json``
files directly in it), so this asymmetry is inert in practice, but
:func:`_do_clear` reproduces it literally rather than "fixing" it into a
single consistent glob.

``show``/``search`` glob a non-recursive ``os.path.isfile``/glob two-level
pattern (``<workdir>/discoveries/*/<id>.json`` / ``.../discoveries/*/
*.json``) rather than a literal ``-maxdepth 2`` walk that also matches
files directly under ``discoveries/`` itself (bash's ``find ... -maxdepth
2`` technically covers that too) — the writer never creates a file at that
shallower depth, so this simplification is observationally identical,
exactly the same simplification :mod:`shepherd_cli.commands.insights`'s
own ``_cmd_show``/``_all_files`` make for the identical directory shape.
Both are sorted for determinism (bash's own ``find`` traversal order is
filesystem-dependent/unspecified for these two calls — ``cmd_list`` is the
only one of the four that explicitly ``| sort``s its ``find`` output);
:mod:`shepherd_cli.commands.insights` documents the identical, deliberate
"impose a deterministic order bash itself never guaranteed" choice for its
own unsorted ``find`` calls.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import subprocess
import sys
import time

import typer
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from shepherd_cli import db
from shepherd_cli.resolution import resolve_db_path, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires full control over -h/--help's own output (the
    # single global usage() heredoc, printed verbatim from any dispatch
    # point) instead of Click's autogenerated help text -- see the module
    # docstring's "WHY ONE VARIADIC CALLBACK" section.
    context_settings={"ignore_unknown_options": True, "help_option_names": []},
    help="Discovery report registry: list | show | search | clear | insert (bash: cmd_discovery.sh).",
)

#: Verbatim bash-parity usage text -- cmd_discovery.sh's usage() heredoc,
#: printed to STDOUT on a bare invocation / -h / --help / help (exit 0),
#: and to STDERR (prefixed by an ERROR line) on an unknown subcommand
#: (exit 1) -- mirroring bash's ``usage`` vs ``usage >&2`` call-site
#: redirection.
_USAGE = (
    'shctx discovery — discovery report registry\n'
    "\n"
    "USAGE\n"
    "  shctx discovery list [--sprint=<branch>] [--json|--md]\n"
    "  shctx discovery show <id> [--md|--json|--report]\n"
    '  shctx discovery search --question="<paraphrase>" [--sprint=<branch>] [--max-age-sprints=<N>]\n'
    "  shctx discovery clear --sprint=<branch> [--force]\n"
    "  shctx discovery insert --run=<id> --title=<t> [--section=<s>]\n"
    "                          [--sources=<json>] [--sprint=<branch>]  < body.md\n"
    "\n"
    "EXAMPLES\n"
    "  shctx discovery list                              # current sprint, markdown\n"
    "  shctx discovery show 20260515T141023-a3f9         # structured record\n"
    '  shctx discovery search --question="canonical types freshness"\n'
    "  shctx discovery clear --sprint=v5.1.2-dev.0 --force\n"
    '  echo "Auth probe body" | shctx discovery insert --run=D-AUTH \\\n'
    "      --section=confirmed --title='Auth probe'"
)

#: Markdown table header for ``list`` (default fmt) and ``search`` -- kept
#: as two separate constants since the column sets differ.
_LIST_MD_HEADER = ("| id | question | confidence | sources | reporter |", "|---|---|---|---|---|")
_SEARCH_MD_HEADER = ("| id | sprint | question | confidence | report |", "|---|---|---|---|---|")


# --------------------------------------------------------------------------
# jq-interpolation parity helpers -- see the module docstring's
# "jq-INTERPOLATION PARITY" section for the verified-against-real-jq
# semantics these two functions reproduce.
# --------------------------------------------------------------------------
def _jq_interp(value: object) -> str:
    """Render ``value`` exactly as jq's ``\\(value)`` string interpolation would.

    Args:
        value: A JSON-decoded field value (``None`` for a missing key or an
            explicit JSON ``null`` -- both collapse to the same Python
            ``None`` after ``json.load``, exactly matching jq's own
            "missing key reads as null" semantics for ``.field``).

    Returns:
        ``"null"`` for ``None``; ``"true"``/``"false"`` for a bool; the
        raw string for a ``str`` (no quoting -- jq interpolates a string
        value verbatim); the JSON text form for an ``int``/``float``; a
        compact JSON serialization for a ``list``/``dict`` (jq's
        ``tostring`` applied implicitly during interpolation -- not
        expected for any field this module actually renders, included
        only for completeness/robustness against an unexpected shape).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, separators=(",", ":"))


def _jq_slice60(value: object) -> object:
    """Mirror jq's ``.field[:60]`` slice, as applied to the ``question`` field.

    Args:
        value: The field's decoded value.

    Returns:
        ``None`` unchanged (jq: slicing ``null`` yields ``null``); the
        first 60 characters for a ``str``; any other type passed through
        unsliced (jq would raise on a non-string/non-null/non-array
        operand -- not expected for any real discovery record, so this
        defensively no-ops instead of crashing).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value[:60]
    return value


def _jq_or_empty(value: object) -> str:
    """Mirror jq's ``.field // empty`` -- falsy (``null``/``false``) collapses to ``""``.

    Used for ``show --report``'s ``.report_path // empty`` and ``search``'s
    ``.question // empty`` (the substring-match source text). Per jq's own
    ``//`` operator semantics, ONLY ``null`` and ``false`` are "falsy" here
    -- ``0``, ``""``, and every other value pass through as-is (rendered
    via :func:`_jq_interp` for a non-string, since ``// empty`` still lets
    a non-string, non-falsy value through raw, and this module's only
    callers immediately treat the result as text either way).

    Args:
        value: The field's decoded value.

    Returns:
        ``""`` for ``None``/``False``; the string itself for a ``str``;
        :func:`_jq_interp`'s rendering for anything else.
    """
    if value is None or value is False:
        return ""
    if isinstance(value, str):
        return value
    return _jq_interp(value)


# --------------------------------------------------------------------------
# Namespace / sprint resolution.
# --------------------------------------------------------------------------
def _resolve_namespace() -> str:
    """Mirror ``_lib.sh``'s ``resolve_namespace()`` shim exactly.

    ``resolve_namespace() { SHCTX_QUIET=1 shctx_artifacts_root; }`` --
    delegates to the same workdir resolution as :func:`shepherd_cli.
    resolution.resolve_workdir`, but with the split-brain
    (``.shepherd/`` + ``.artifacts/`` both present) warning suppressed for
    the duration of the call. See the module docstring's
    "``resolve_namespace()`` PARITY DETAIL" section for why this
    suppression applies to ``list``/``show``/``search``/``clear`` but NOT
    to ``insert`` (which calls :func:`shepherd_cli.resolution.
    resolve_db_path` directly, unwrapped).

    Returns:
        The resolved shepherd work directory path (need not exist on disk).
    """
    previous = os.environ.get("SHCTX_QUIET")
    os.environ["SHCTX_QUIET"] = "1"
    try:
        return resolve_workdir()
    finally:
        if previous is None:
            os.environ.pop("SHCTX_QUIET", None)
        else:
            os.environ["SHCTX_QUIET"] = previous


def _current_sprint() -> str:
    """Resolve the current sprint branch, bash parity with ``_lib.sh``'s ``current_sprint()``.

    Bash: ``git rev-parse --abbrev-ref HEAD 2>/dev/null || printf
    'unknown'`` -- used only as ``list``'s default ``--sprint`` value.
    Copied in shape from :mod:`shepherd_cli.commands.handoff`'s
    ``_current_branch`` (kept as a separate copy per this package's
    self-contained-command-module convention).

    Returns:
        The current branch name (stripped), or the literal string
        ``"unknown"`` if ``git`` is unavailable or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
        )
    except OSError:
        return "unknown"
    if result.returncode == 0:
        return result.stdout.strip()
    return "unknown"


def _discovery_dir_for(ns: str, sprint: str) -> str:
    """Bash parity with ``discovery_dir_for() { echo "$ns/discoveries/$1"; }``.

    Args:
        ns: The resolved namespace (see :func:`_resolve_namespace`).
        sprint: The sprint branch subdirectory name.

    Returns:
        ``<ns>/discoveries/<sprint>`` (need not exist on disk).
    """
    return os.path.join(ns, "discoveries", sprint)


# --------------------------------------------------------------------------
# list.
# --------------------------------------------------------------------------
def _render_list_json(files: list[str]) -> str:
    """Reconstruct ``list --json``'s exact byte stream, bash parity with ``cmd_list``.

    Bash::

        echo "["
        first=1
        while IFS= read -r f; do
          [[ $first -eq 0 ]] && echo ","
          first=0
          cat "$f"
        done <<<"$files"
        echo ""
        echo "]"

    Each discovery JSON file (written by ``json.dump(record, f,
    indent=2)`` in ``hooks/scripts/discovery_capture.sh``) has NO trailing
    newline of its own, so the byte sequence is: ``"[\\n"``, then for each
    file (in order) -- a literal ``",\\n"`` immediately before every file
    except the first, followed immediately by that file's raw content
    (ending in ``"}"`` with no newline) -- then a final ``"\\n"`` and
    ``"]\\n"``. Concatenating this way lands the comma directly after the
    previous file's closing ``"}"`` with no intervening blank line (e.g.
    ``"},\\n{"``), exactly reproducing bash's interleaved
    ``echo ","``/``cat`` sequence.

    Args:
        files: The discovery JSON file paths, already in display order (at
            least one -- the caller has already handled the empty-list
            case).

    Returns:
        The complete byte stream, ending in exactly one trailing newline
        (from the final ``echo "]"``) -- intended to be written verbatim
        (``sys.stdout.write``, NOT ``typer.echo``, which would add a
        second trailing newline).
    """
    chunks = ["[\n"]
    for index, path in enumerate(files):
        if index > 0:
            chunks.append(",\n")
        with open(path, encoding="utf-8") as fh:
            chunks.append(fh.read())
    chunks.append("\n")
    chunks.append("]\n")
    return "".join(chunks)


def _list_md_row(record: dict[str, object]) -> str:
    """One ``list`` (default markdown) table row, bash parity with the jq/python3 renderer.

    Bash: ``"| \\(.id) | \\(.question[:60]) | \\(.confidence) | \\(.sources_count) | \\(.reporter) |"``.

    Args:
        record: One loaded discovery JSON record.

    Returns:
        The formatted markdown table row.
    """
    rid = _jq_interp(record.get("id"))
    question = _jq_interp(_jq_slice60(record.get("question")))
    confidence = _jq_interp(record.get("confidence"))
    sources_count = _jq_interp(record.get("sources_count"))
    reporter = _jq_interp(record.get("reporter"))
    return f"| {rid} | {question} | {confidence} | {sources_count} | {reporter} |"


def _do_list(ns: str, rest: list[str]) -> int:
    """Implement ``shctx discovery list``, bash parity with ``cmd_list()``.

    Args:
        ns: The resolved namespace (see :func:`_resolve_namespace`).
        rest: Every token after ``list``, in order. An unrecognized token
            is silently ignored -- bash's per-token ``case`` here has no
            default arm.

    Returns:
        0 always (bash: ``cmd_list`` has no failing path).
    """
    sprint = _current_sprint()
    fmt = "md"
    for arg in rest:
        if arg.startswith("--sprint="):
            sprint = arg[len("--sprint=") :]
        elif arg == "--json":
            fmt = "json"
        elif arg == "--md":
            fmt = "md"

    dir_path = _discovery_dir_for(ns, sprint)
    if not os.path.isdir(dir_path):
        typer.echo(f"[shctx discovery] no discoveries for sprint '{sprint}' (dir: {dir_path})")
        return 0

    files = sorted(glob.glob(os.path.join(dir_path, "*.json")))
    if not files:
        typer.echo(f"[shctx discovery] no discoveries for sprint '{sprint}'")
        return 0

    if fmt == "json":
        sys.stdout.write(_render_list_json(files))
        return 0

    lines = list(_LIST_MD_HEADER)
    for path in files:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        lines.append(_list_md_row(record))
    typer.echo("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# show.
# --------------------------------------------------------------------------
def _render_show_md(record: dict[str, object]) -> str:
    """Render ``show --md``'s full record view, bash parity with the jq renderer.

    See the module docstring's "jq-INTERPOLATION PARITY" section for the
    trailing-newline derivation this function's trailing ``""`` element
    produces when the caller joins with ``"\\n"`` then ``typer.echo``s the
    result.

    Args:
        record: The loaded discovery JSON record.

    Returns:
        The multi-line record view, ending in exactly one embedded
        ``"\\n"`` (via the trailing empty line) -- the caller's
        ``typer.echo`` supplies jq -r's second, matching byte-for-byte.
    """
    lines = [
        f"# Discovery {_jq_interp(record.get('id'))}",
        "",
        f"- Sprint:       {_jq_interp(record.get('sprint'))}",
        f"- Question:     {_jq_interp(record.get('question'))}",
        f"- Confidence:   {_jq_interp(record.get('confidence'))}",
        f"- Sources:      {_jq_interp(record.get('sources_count'))}",
        f"- Tool calls:   {_jq_interp(record.get('tool_calls'))}",
        f"- Time used:    {_jq_interp(record.get('time_used'))}",
        f"- Report:       {_jq_interp(record.get('report_path'))}",
        f"- Status:       {_jq_interp(record.get('status'))}",
        f"- Reporter:     {_jq_interp(record.get('reporter'))}",
        f"- Consumed:     {_jq_interp(record.get('consumed'))}",
        "",
    ]
    return "\n".join(lines)


def _do_show(ns: str, rest: list[str]) -> int:
    """Implement ``shctx discovery show <id> [--md|--json|--report]``.

    Bash parity with ``cmd_show()``: every token is scanned; ``--md``/
    ``--json``/``--report`` set the format (last one wins), and the FIRST
    token that matches none of those three becomes the id -- ONLY if no id
    has been captured yet (bash: ``*) [[ -z "$id" ]] && id="$arg" ;;``, so
    a second non-flag token, or a flag-shaped token appearing before the
    real id, is silently dropped rather than erroring). Exactly like
    :mod:`shepherd_cli.commands.insights`'s ``show``, a token that merely
    LOOKS like a flag but isn't one of the three recognized ones (e.g.
    ``--bogus``) is captured as the id instead of being rejected --
    ``--md``/``--json``/``--report`` themselves are the only tokens this
    loop treats specially, so ``discovery show --json`` (with no other
    token) sets ``fmt="json"`` and leaves the id empty, hitting the
    "usage" branch below.

    Args:
        ns: The resolved namespace.
        rest: Every token after ``show``, in order.

    BASH BUG MIRRORED DELIBERATELY (silent exit 1 when ``discoveries/``
    itself was never created): ``cmd_show()`` resolves its match via
    ``found=$(find "$ns/discoveries" -maxdepth 2 -name "${id}.json" -type f
    2>/dev/null | head -1)`` -- a pipe assigned to a variable via command
    substitution, NOT the process-substitution form :func:`_do_search` and
    ``cmd_list``/``cmd_clear`` use (those either read via
    ``< <(find ...)`` or guard with an explicit ``[[ -d ... ]]`` check
    BEFORE ever calling ``find`` -- see :func:`_do_list`/:func:`_do_clear`,
    which check the SPECIFIC sprint directory they are about to glob, not
    the shared ``discoveries/`` parent). When the top-level ``<ns>/
    discoveries`` directory does not exist at all (a project where no
    discovery has EVER been captured, for any sprint), ``find`` itself
    fails (its argument path does not exist) with a non-zero exit code;
    under ``pipefail``, that failure propagates through the pipe to
    ``head``'s otherwise-successful exit, and since this is a bare
    top-level assignment (not part of an ``&&``/``||`` list), ``set -e``
    aborts the WHOLE script right there -- before the "id not found"
    message is ever reached. The observable result (verified against the
    real bash script) is: exit code 1, and BOTH stdout and stderr
    completely empty. This is reproduced exactly by
    :func:`_do_show` checking ``os.path.isdir(<ns>/discoveries)`` first and
    returning bare ``1`` (no output at all) when it is missing, BEFORE
    the normal "id not found" message path (which only fires once
    ``discoveries/`` exists but simply has no matching file underneath
    it).

    Returns:
        1 (stderr usage message) if no id was resolved. 1 (no output at
        all) if the ``<ns>/discoveries`` directory itself does not exist
        (see the BASH BUG note above). 1 (stderr "id not found" message)
        if ``<ns>/discoveries`` exists but no matching ``*/<id>.json``
        file does. 0 on a successful render (json/md/report).
    """
    disc_id = ""
    fmt = "json"
    for arg in rest:
        if arg == "--md":
            fmt = "md"
        elif arg == "--json":
            fmt = "json"
        elif arg == "--report":
            fmt = "report"
        elif not disc_id:
            disc_id = arg

    if not disc_id:
        typer.echo("ERROR: shctx discovery show <id>", err=True)
        return 1

    discoveries_root = os.path.join(ns, "discoveries")
    if not os.path.isdir(discoveries_root):
        # Bash-bug parity: see the docstring's "BASH BUG MIRRORED
        # DELIBERATELY" section -- silent exit 1, no stdout, no stderr.
        return 1

    matches = sorted(glob.glob(os.path.join(discoveries_root, "*", f"{disc_id}.json")))
    found = matches[0] if matches else None
    if found is None:
        typer.echo(f"[shctx discovery] id not found: {disc_id}", err=True)
        return 1

    if fmt == "json":
        with open(found, encoding="utf-8") as fh:
            content = fh.read()
        sys.stdout.write(content)
        return 0

    with open(found, encoding="utf-8") as fh:
        record = json.load(fh)

    if fmt == "md":
        typer.echo(_render_show_md(record))
        return 0

    # fmt == "report"
    report_path = _jq_or_empty(record.get("report_path"))
    if os.path.isfile(report_path):
        with open(report_path, encoding="utf-8") as fh:
            content = fh.read()
        sys.stdout.write(content)
        return 0
    typer.echo(f"[shctx discovery] report file not found: {report_path}", err=True)
    return 1


# --------------------------------------------------------------------------
# search.
# --------------------------------------------------------------------------
def _search_md_row(record: dict[str, object]) -> str:
    """One ``search`` table row, bash parity with the jq/python3 renderer.

    Bash: ``"| \\(.id) | \\(.sprint) | \\(.question[:60]) | \\(.confidence) | \\(.report_path) |"``.

    Args:
        record: One loaded discovery JSON record.

    Returns:
        The formatted markdown table row.
    """
    rid = _jq_interp(record.get("id"))
    sprint = _jq_interp(record.get("sprint"))
    question = _jq_interp(_jq_slice60(record.get("question")))
    confidence = _jq_interp(record.get("confidence"))
    report_path = _jq_interp(record.get("report_path"))
    return f"| {rid} | {sprint} | {question} | {confidence} | {report_path} |"


def _do_search(ns: str, rest: list[str]) -> int:
    """Implement ``shctx discovery search --question="<text>"``.

    Bash parity with ``cmd_search()``: ``--sprint=``/``--max-age-sprints=``
    are PARSED but never referenced afterward (dead flags -- bash accepts
    and silently ignores their values, matching e.g.
    :mod:`shepherd_cli.commands.report`'s ``teammates --stale-mins``).
    Matching is a case-insensitive SUBSTRING test of ``--question`` against
    each record's ``question`` field (``.question // empty``, so a
    missing/``null``/``false`` question is treated as ``""`` -- matches
    only an empty ``--question``, which is itself rejected below before
    any file is even scanned). File order is bash's own unsorted
    ``find ... -maxdepth 2``, reproduced deterministically via a sorted
    glob -- see the module docstring.

    Args:
        ns: The resolved namespace.
        rest: Every token after ``search``, in order.

    Returns:
        1 (stderr usage message) if ``--question`` is missing/empty. 0
        otherwise (a "no matches" notice, or the matched rows table).
    """
    question = ""
    for arg in rest:
        if arg.startswith("--question="):
            question = arg[len("--question=") :]
        # --sprint=*/--max-age-sprints=* accepted for bash-CLI parity only
        # -- cmd_search() parses but never uses either value. Any other
        # token (including these two, spelled out for clarity) falls
        # through unmatched, exactly like bash's case with no default arm.

    if not question:
        typer.echo('ERROR: shctx discovery search --question="<text>"', err=True)
        return 1

    files = sorted(glob.glob(os.path.join(ns, "discoveries", "*", "*.json")))
    needle = question.lower()
    matched_records: list[dict[str, object]] = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        record_question = _jq_or_empty(record.get("question"))
        if needle in record_question.lower():
            matched_records.append(record)

    if not matched_records:
        typer.echo(f"[shctx discovery] no matches for: {question}")
        return 0

    lines = list(_SEARCH_MD_HEADER)
    lines.extend(_search_md_row(record) for record in matched_records)
    typer.echo("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# clear.
# --------------------------------------------------------------------------
def _do_clear(ns: str, rest: list[str]) -> int:
    """Implement ``shctx discovery clear --sprint=<branch> [--force]``.

    Bash parity with ``cmd_clear()``, including its count-vs-removal glob
    asymmetry -- see the module docstring's "clear's bash quirk mirrored
    deliberately" section.

    Args:
        ns: The resolved namespace.
        rest: Every token after ``clear``, in order.

    Returns:
        1 (stderr usage message) if ``--sprint`` is missing/empty.
        Otherwise 0: a "no records to clear" notice (missing sprint dir),
        a dry-run "would clear N records... pass --force" notice (no
        ``--force``), or a "cleared N records" notice after actually
        removing the files (``--force``).
    """
    sprint = ""
    force = False
    for arg in rest:
        if arg.startswith("--sprint="):
            sprint = arg[len("--sprint=") :]
        elif arg == "--force":
            force = True

    if not sprint:
        typer.echo("ERROR: shctx discovery clear --sprint=<branch>", err=True)
        return 1

    dir_path = _discovery_dir_for(ns, sprint)
    if not os.path.isdir(dir_path):
        typer.echo(f"[shctx discovery] no records to clear for sprint '{sprint}'")
        return 0

    # bash: `find "$dir" -name "*.json" -type f` -- unrestricted (recursive)
    # count, deliberately NOT the same glob the removal step below uses.
    count = len(glob.glob(os.path.join(dir_path, "**", "*.json"), recursive=True))

    if not force:
        typer.echo(f"[shctx discovery] would clear {count} records in {dir_path}; pass --force to execute")
        return 0

    # bash: `rm -f "$dir"/*.json` -- shallow shell glob, direct children only.
    for path in glob.glob(os.path.join(dir_path, "*.json")):
        os.remove(path)

    typer.echo(f"[shctx discovery] cleared {count} records for sprint '{sprint}'")
    return 0


# --------------------------------------------------------------------------
# insert (v5.1.7+) -- the one DB-touching subcommand. See the module
# docstring's COLLISION RULE section for why this is raw SQL, not a model.
# --------------------------------------------------------------------------
async def _insert_async(run: str, section: str, title: str, sources: str, sprint: str, body: str) -> int:
    """Write one ``discovery_findings`` row, bash parity with the ``insert`` intercept block.

    Bash::

        pid="$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")"
        ts=$(($(date +%s) * 1000))
        id=$(sqlite3 "$DB" "INSERT INTO discovery_findings
          (project_id, sprint_branch, discovery_run, section, title, body, sources, created_at)
          VALUES ('$pid', NULLIF('$sprint',''), '$run', NULLIF('$section',''), '$title', '$body',
                  NULLIF('$sources',''), $ts) RETURNING id;")

    This port binds every value as a query parameter (safe against a value
    containing a quote -- bash's own manual ``${x//\\'/''}`` escaping is
    not needed at all here) and folds bash's ``NULLIF(x,'')`` SQL calls
    into a plain Python ``x or None`` before binding, which is equivalent
    for every value these fields can hold (none of ``sprint``/``section``/
    ``sources`` is ever the SQL-NULL-like-but-not-empty-string case
    ``NULLIF`` exists to handle here -- they are always either a real,
    non-empty CLI-supplied string or the empty-string default).

    **IntegrityError -- a disclosed, deliberate platform-level divergence,
    not a bug** (the exact same class of deviation
    :mod:`shepherd_cli.commands.audit`'s own ``insert`` documents and
    handles, for the identical ``discovery_findings``-sibling-table
    reason): bash's raw ``sqlite3 "$DB" "INSERT ..."`` CLI invocation runs
    with ``PRAGMA foreign_keys`` at sqlite's own per-connection OFF
    default, so an ``INSERT`` with ``project_id=''`` (no matching
    ``projects`` row -- i.e. a project whose ``shctx init`` never ran)
    SUCCEEDS in bash, silently writing an orphaned row. Tortoise's sqlite
    backend, by contrast, sets ``PRAGMA foreign_keys = ON`` by default for
    every connection it opens (``tortoise.backends.sqlite.client``'s
    ``self.pragmas.setdefault("foreign_keys", "ON")``) -- a platform
    default shared by every OTHER ported command module's ``db.lifespan()``
    connection, not something this module could selectively disable
    without becoming the one write path with inconsistent referential-
    integrity enforcement. A malformed ``--sources`` value (the column is
    ``CHECK(sources IS NULL OR json_valid(sources))``) raises the SAME
    exception type -- sqlite enforces ``CHECK`` constraints regardless of
    the ``foreign_keys`` pragma, so bash's own uncontrolled ``sqlite3``
    crash there becomes the identical clean error path here too. Both
    cases raise ``tortoise.exceptions.IntegrityError`` out of this
    function; :func:`_do_insert` catches it and converts it to
    ``ERROR: <message>`` on stderr, exit 1, with NO row written -- refusing
    the write is strictly safer than bash's silent orphaned-row success,
    and every healthy project (the only case this subcommand is meant for)
    has exactly one ``projects`` row, written once by ``shctx init``, so
    this divergence never surfaces in practice.

    Args:
        run: The ``--run`` value (validated non-empty by the caller).
        section: The ``--section`` value, or ``""`` (stored as SQL NULL).
        title: The ``--title`` value (validated non-empty by the caller).
        sources: The ``--sources`` value, or ``""`` (stored as SQL NULL).
        sprint: The ``--sprint`` value, or ``""`` (stored as SQL NULL).
        body: The finding's body text, read verbatim from stdin by the
            caller (bash: ``body="$(cat)"``).

    Returns:
        The new row's ``id`` (sqlite's ``lastrowid`` on an ``INTEGER
        PRIMARY KEY`` column -- equivalent to bash's ``RETURNING id``).

    Raises:
        tortoise.exceptions.IntegrityError: If the ``INSERT`` violates the
            ``project_id`` foreign key or the ``sources`` ``json_valid``
            check -- see the note above. Caught by :func:`_do_insert`, not
            here.
    """
    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        project_rows = await connection.execute_query_dict("SELECT id FROM projects LIMIT 1;")
        project_id = project_rows[0]["id"] if project_rows else ""
        created_at = int(time.time()) * 1000
        new_id = await connection.execute_insert(
            "INSERT INTO discovery_findings "
            "(project_id, sprint_branch, discovery_run, section, title, body, sources, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
            [project_id, sprint or None, run, section or None, title, body, sources or None, created_at],
        )
    return new_id


def _do_insert(rest: list[str]) -> int:
    """Implement ``shctx discovery insert``, bash parity with the early-intercept block.

    Args:
        rest: Every token after ``insert``, in order.

    Returns:
        2 (stderr ``unknown flag: <token>``) on the first unrecognized
        flag. 2 (stderr ``ERR: --run and --title required``) if either
        required flag is missing/empty. 1 (stderr ``ERR: registry DB not
        found at <path>``) if the resolved DB file does not exist. 1
        (stderr ``ERROR: <message>``) if the ``INSERT`` violates the
        ``project_id`` foreign key or the ``sources`` JSON-validity check
        -- see :func:`_insert_async`'s docstring. 0 (the new row's integer
        id on stdout) on success.
    """
    run = ""
    section = ""
    title = ""
    sources = ""
    sprint = ""
    for arg in rest:
        if arg.startswith("--run="):
            run = arg[len("--run=") :]
        elif arg.startswith("--section="):
            section = arg[len("--section=") :]
        elif arg.startswith("--title="):
            title = arg[len("--title=") :]
        elif arg.startswith("--sources="):
            sources = arg[len("--sources=") :]
        elif arg.startswith("--sprint="):
            sprint = arg[len("--sprint=") :]
        else:
            typer.echo(f"unknown flag: {arg}", err=True)
            return 2

    if not run or not title:
        typer.echo("ERR: --run and --title required", err=True)
        return 2

    body = sys.stdin.read()

    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(f"ERR: registry DB not found at {db_path}", err=True)
        return 1

    try:
        new_id = asyncio.run(_insert_async(run, section, title, sources, sprint, body))
    except IntegrityError as exc:
        # A dangling project_id FK or a malformed --sources value -- see
        # _insert_async's docstring for why this diverges from bash
        # (which either silently writes an orphaned row or crashes
        # uncontrolled, respectively). Converted to a clean, controlled
        # message rather than a raw traceback.
        typer.echo(f"ERROR: {exc}", err=True)
        return 1
    typer.echo(str(new_id))
    return 0


# --------------------------------------------------------------------------
# Top-level dispatcher + Typer wiring.
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> int:
    """Dispatch on ``argv[0]`` exactly like ``cmd_discovery.sh``'s top-level ``case`` statement.

    ``insert`` is checked FIRST, before any namespace resolution -- bash
    parity with the script's own early-intercept block (see the module
    docstring). Every other subcommand shares one namespace resolution
    (:func:`_resolve_namespace`), matching bash's ``ns=$(resolve_
    namespace)`` computed once, unconditionally, right after the
    ``insert`` intercept (even for ``help``/an unknown subcommand, which
    never use it -- an inconsequential, invisible-from-the-outside detail
    this port does not bother reproducing for those two arms, since
    :func:`_resolve_namespace` has no observable side effect of its own
    when ``SHCTX_QUIET`` is already suppressed).

    Args:
        argv: The raw remaining command-line tokens after ``discovery``,
            e.g. ``["list", "--json"]`` or ``[]``.

    Returns:
        The bash-parity process exit code for whichever subcommand ran
        (or the bare/``-h``/``--help``/``help``/unknown-subcommand arms).
    """
    sub = argv[0] if argv else "help"
    rest = argv[1:]

    if sub == "insert":
        return _do_insert(rest)

    if sub in ("help", "-h", "--help"):
        typer.echo(_USAGE)
        return 0

    if sub in ("list", "show", "search", "clear"):
        ns = _resolve_namespace()
        if sub == "list":
            return _do_list(ns, rest)
        if sub == "show":
            return _do_show(ns, rest)
        if sub == "search":
            return _do_search(ns, rest)
        return _do_clear(ns, rest)

    typer.echo(f"ERROR: unknown shctx discovery subcommand: {sub}", err=True)
    typer.echo(_USAGE, err=True)
    return 1


@app.callback(invoke_without_command=True)
def discovery(
    args: list[str] = typer.Argument(
        None,
        metavar="<list|show|search|clear|insert> [args]",
        help=(
            "Subcommand + args: 'list [--sprint=<branch>] [--json|--md]' | "
            "'show <id> [--md|--json|--report]' | "
            "'search --question=\"<text>\" [--sprint=<branch>] [--max-age-sprints=<N>]' | "
            "'clear --sprint=<branch> [--force]' | "
            "'insert --run=<id> --title=<t> [--section=<s>] [--sources=<json>] "
            "[--sprint=<branch>] < body.md'. Defaults to usage."
        ),
    ),
) -> None:
    """Discovery report registry — native port of ``shctx discovery``.

    See the module docstring for why this is ONE variadic callback rather
    than five ``@app.command()``s: bash's own hand-rolled per-subcommand
    flag loops (each with its own default/error contract), the early
    ``insert`` namespace-resolution bypass, default-to-usage, and exit-1-
    on-unknown-subcommand behaviors don't match Typer/Click's own
    subcommand-dispatch defaults.

    Args:
        args: Every token after ``discovery`` on the command line, in
            order, with NOTHING pre-parsed as flags/options by Click (see
            this app's ``context_settings={"ignore_unknown_options": True,
            "help_option_names": []}``). ``None``/empty means a bare
            ``shepherd discovery`` -- dispatched as the usage arm, per
            bash's ``sub="${1:-help}"``.
    """
    raise typer.Exit(code=_dispatch(list(args or [])))


__all__ = ["app"]
