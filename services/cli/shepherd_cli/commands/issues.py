"""``shepherd issues`` — read-only issue triage over the ``index_issues`` cache.

Native port of ``skills/context/scripts/cmd_issues.sh``: two subcommands,
``classify`` (deterministic label/milestone bucketing of open issues) and
``list`` (plain listing from cache, no classification). Both are pure
reads over the ``index_issues`` table — no LLM/``gh`` calls anywhere in the
bash source (verified: the only external process ``cmd_issues.sh`` shells
out to is ``git rev-parse --abbrev-ref HEAD``, to default ``--sprint`` when
not given). Per the port instructions' group-specific note ("classify:
EXAMINE the bash carefully — if it calls gh/github or an LLM/latent step,
DO NOT reimplement... otherwise port list natively and drive classify by
shelling to bash"): ``classify``'s bucketing (``_classify_row`` in the bash
source) is deterministic label/milestone string matching, not an LLM call,
so BOTH subcommands are ported natively here. No subprocess shim to bash
``cmd_issues.sh`` is used for either.

**Raw SQL, no ``models_issues.py`` (COLLISION RULE).** ``index_issues``
already has a Tortoise mirror — :class:`shepherd_cli.models_status.IndexIssue`
— but it declares ONLY ``id`` and ``refreshed_at`` (the two columns
``shepherd status`` needs). This command needs ``number``, ``title``,
``state``, ``labels``, ``milestone``, ``updated_at``, and ``url``, none of
which are on that model. Per the collision rule, redeclaring a second model
over the same table is not allowed; the fix is raw parameterized SQL via
``Tortoise.get_connection("default").execute_query_dict()`` — exactly the
pattern :mod:`shepherd_cli.commands.search` and
:mod:`shepherd_cli.commands.query` use for the identical reason. No
``models_issues.py`` is written for this port.

**Dispatch shape.** Like :mod:`shepherd_cli.commands.search`, this module
does NOT use Click subcommand routing (``@app.command()`` per verb) —
``cmd_issues.sh``'s own dispatch is a single hand-rolled ``case "$sub"``
covering FOUR outcomes no Click ``Group`` reproduces without a fight: no
subcommand at all (``usage``, exit 0), ``-h``/``--help`` as the sub-verb
itself (same, exit 0), a recognized sub-verb (``classify``/``list``,
dispatched with the REST of the tokens), and an unrecognized sub-verb
(``ERROR: unknown subcommand: <sub>`` + usage on stderr, exit **2**). A
single ``@app.callback(invoke_without_command=True)`` with one variadic
``raw: list[str]`` argument (``context_settings={"help_option_names": [],
"allow_extra_args": True, "ignore_unknown_options": True}``, mirroring
``search.py``/``query.py``) captures every token verbatim and replicates
that exact ``case`` statement in Python — see :func:`_default`. Each
sub-verb's OWN flag loop (:func:`_classify_impl`/:func:`_list_impl`) then
independently recognizes its own ``-h``/``--help`` token (bash: the SAME
``usage()`` call, reached a second way — from inside ``cmd_classify``'s/
``cmd_list``'s own ``for arg in "$@"`` loop) and unknown-flag branch
(``ERROR: unknown arg: <arg>``, exit **2** — note this is a DIFFERENT exit
code than ``search.py``'s own unknown-flag branch, which exits 1; bash
parity here is exit 2, matching ``cmd_issues.sh`` line-for-line).

**Project-id resolution** mirrors :mod:`shepherd_cli.commands.search`'s and
:mod:`shepherd_cli.commands.query`'s documented deviation from the more
common "read the ``projects`` table" pattern (:mod:`shepherd_cli.commands.mem`/
``.lock``): ``cmd_issues.sh`` calls ``_lib.sh``'s ``shctx_project_id()``,
which reads ``project.json`` (a FILE in the resolved shepherd work
directory), not a table. :func:`_read_project_id` duplicates that same
helper locally (not imported — every port module in this package is
self-contained), for the same reason ``search.py``/``query.py`` give.

**Sub-verb ordering, preserved exactly.** Both ``cmd_classify`` and
``cmd_list`` in bash run a ``command -v sqlite3`` availability check before
touching the database. This port has no equivalent step — it never shells
out to the ``sqlite3`` CLI binary at all (SQL runs through Tortoise's own
sqlite3 driver) — so that guard is simply absent here; there is no failure
mode in this port that check could ever catch. Every OTHER bash check
(missing DB file, missing ``project.json``, empty result set) is
reproduced, including bash's OWN distinct wording per subcommand (see
:data:`_CLASSIFY_NO_DB_MSG` vs :data:`_LIST_NO_DB_MSG`).

**``list --json`` reproduces ``sqlite3 -cmd ".mode json"`` byte-for-byte,**
not ``json.dumps``'s own default formatting. ``cmd_list.sh``'s ``--json``
branch streams ``sqlite3``'s own JSON-mode output straight to stdout: a
compact ``[{"k":"v","k2":"v2"},\\n{"k":...}]`` array — no space after
``:``/``,`` WITHIN an object, but a bare ``,\\n`` BETWEEN objects, ``utf-8``
un-escaped (not ``\\uXXXX``-escaped), and a trailing ``\\n`` after the
closing ``]`` — verified empirically against a real ``sqlite3`` binary (see
:func:`_render_sqlite_json`'s docstring). Critically, ``sqlite3`` prints
**zero bytes** (not ``"[]"``) for a zero-row result set — its own
``2>/dev/null || echo "[]"`` fallback in the bash source only fires on a
genuine SQL/connection ERROR (non-zero exit), which an empty-but-valid
result set never triggers. This port reproduces that exact empty-vs-error
distinction: :func:`_list_impl` prints nothing at all (not ``"[]"``, not
even a bare newline) when the ``--json`` query returns zero rows.

**``classify --json`` is completely different formatting** from ``list
--json`` (bash source: hand-built entries reparsed and re-serialized via
plain ``python3 -c 'print(json.dumps(arr))'``, i.e. Python's OWN default
``json.dumps`` separators — ``", "``/``": "``, no ``indent=``) — this port
reproduces THAT shape instead (plain ``json.dumps(entries)``, no
``separators=`` override), not the sqlite3-JSON-mode shape ``list --json``
uses. See :func:`_classify_impl`. Both are deliberately different — bash
itself renders them two different ways, and this is preserved rather than
unified.

**Two independent, non-interoperable per-format label-string transforms.**
``cmd_issues.sh`` derives a human-readable label string from the raw JSON
``labels`` column THREE different ways across its four render paths, and
this port reproduces all three separately (see :func:`_strip_brackets_quotes`,
:func:`_labels_compact`, :func:`_labels_spaced`, and
:func:`_labels_commas_kept_collapsed`):

1. ``classify``'s TEXT rows: ``tr -d '[]"' | tr ',' ' ' | xargs`` — commas
   become single spaces, THEN all whitespace runs collapse to one space and
   the result is trimmed (bash: piping through ``xargs`` with no arguments).
2. ``classify``'s MD rows: ``tr -d '[]"' | tr ',' ' '`` — commas become
   single spaces, but NO collapse/trim step (no trailing ``xargs``) — a
   ``labels`` column serialized with extra whitespace (none of the shipped
   writers produce this, but nothing prevents it) would show through
   unchanged, unlike (1).
3. ``list``'s MD rows: ``tr -d '[]"' | tr ',' ', ' | xargs`` — this LOOKS
   like it should turn ``,`` into ``, ``, but POSIX ``tr``'s own semantics
   for a SET2 longer than SET1 truncate SET2 down to SET1's length before
   building the mapping, so ``tr ',' ', '`` is actually IDENTICAL to
   ``tr ',' ','`` — a byte-for-byte no-op on every comma (verified
   empirically: ``printf '%s' '["bug","p0"]' | tr -d '[]"' | tr ',' ', ' |
   xargs`` prints ``bug,p0``, commas fully intact, no space inserted).
   ``list --md``'s label column therefore renders as a COMMA-JOINED string
   (``bug,p0``), not a space-joined one — a genuine bash quirk (almost
   certainly not the author's intent), preserved here rather than "fixed"
   per hard rule #4.

``classify``'s TEXT rows additionally truncate ``title`` to 55 chars and
the rendered label string to 40 chars (bash: ``${ttl:0:55}``/
``${lbl_str:0:40}``); ``list``'s TEXT rows truncate ``title`` to 50 and
``milestone`` to 15. Neither MD render path truncates anything. All
truncation widths are preserved exactly (see the render functions below).

**Column padding is BYTE-width, not codepoint-width** (see :func:`_bash_pad`):
this port's runtime/test environment runs under the C/POSIX locale
(``LANG``/``LC_ALL`` unset), under which bash's own ``printf '%-Ns'`` field
width is computed in raw UTF-8 BYTES, not Unicode codepoints. The
``COALESCE(milestone,'—')`` em-dash placeholder ``list``'s text/md queries
default every issue with no milestone to is a 3-byte UTF-8 character —
verified empirically (``printf '[%-15s]\\n' "—"`` under this same C locale
prints 12 trailing spaces, i.e. pads as if the em-dash were 3 columns
wide) — so Python's own codepoint-counting ``str.ljust``/f-string ``:<N``
under-pads that (extremely common — every milestone-less issue hits it)
value by 2 spaces relative to bash. :func:`_bash_pad` reproduces bash's
byte-counting instead. Truncation (``[:N]``, applied before padding)
remains ordinary Python codepoint slicing — a narrower, ASCII-exact-only
deviation from bash's own byte-oriented ``${var:0:N}`` — since none of
this port's shipped truncation widths (15/40/50/55) is likely to ever
actually be reached by a multi-byte value in practice, and bash's own
byte-slice can cut a multi-byte character in half into invalid UTF-8, a
failure mode not worth reproducing for that narrow a case.

**``classify --md``'s per-issue detail rows are a DELIBERATE correctness
fix, not bash parity** — bash's own ``cmd_issues.sh`` (verified against a
real ``bash 5.2`` binary) crashes here: ``printf '- #%-5s  %s%s\\n' "$num"
"$ttl" "$ms_str"`` — bash's ``printf`` builtin treats a FORMAT STRING that
itself begins with ``-`` as an attempt to pass it an unrecognized option
(``printf: - : invalid option``), aborting the whole command with exit
code 2 after printing only the bucket-count summary table and the FIRST
bucket's bare heading — every per-issue detail line is lost, for every
non-empty bucket, on every single invocation of ``classify --md`` against
any real project. This is unambiguously an unintentional bug in the
shipped bash source, not a documented or deliberate behavior — mirroring
:mod:`shepherd_cli.commands.search`'s own precedent (see its module
docstring's "malformed FTS5 query text" note) for when reproducing bash's
own crash would be strictly worse UX than fixing it, this port renders the
CORRECT, complete ``--md`` detail output (see :func:`_render_classify_md`)
instead of bash's truncated, exit-2 crash. Every OTHER format
(``classify``'s text/json, both of ``list``'s formats) works correctly in
bash and is matched byte-for-byte, not "improved."
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.resolution import resolve_db_path, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # See the module docstring's "Dispatch shape" note: cmd_issues.sh's own
    # dispatch is a hand-rolled `case "$sub"` outside of anything Click's
    # subcommand Group can reproduce without extra machinery (no-subcommand
    # -> usage/exit 0, `-h`/`--help` AS the sub-verb -> same, an unrecognized
    # sub-verb -> its own distinct ERROR+usage+exit-2 branch). Disabling
    # Click's own --help (`help_option_names: []`) and letting every token
    # flow into one variadic Argument (`allow_extra_args` /
    # `ignore_unknown_options`) — mirroring shepherd_cli.commands.search and
    # .query exactly — lets `_default` below replicate that `case` statement
    # directly instead of fighting Click's Group resolution for it.
    context_settings={
        "help_option_names": [],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Read-only issue triage over the index_issues cache (classify | list).",
)

#: Verbatim bash-parity usage text — cmd_issues.sh's usage() heredoc,
#: printed to STDOUT on no-subcommand/-h/--help (exit 0), and to STDERR
#: (prefixed by an ERROR line) on an unrecognized subcommand (exit 2).
_USAGE = (
    "shctx issues <classify|list> [args]\n"
    "\n"
    "  classify [--sprint=BRANCH] [--md] [--json] [--unclassified-only]\n"
    "           [--drift-days=N]\n"
    "      Bucket open issues using deterministic label/milestone rules.\n"
    "      --sprint     sprint branch to resolve current milestone (reads shepherd.toml)\n"
    "      --drift-days days since last update to qualify as drift-risk (default: 30)\n"
    "      --unclassified-only  print only the unclassified bucket (for LLM review)\n"
    "\n"
    "  list [--state=open|closed|all] [--limit=N] [--md] [--json]\n"
    "      List issues from cache.\n"
    "\n"
    "Buckets (classify):\n"
    "  blocking-this-sprint  milestone == sprint OR labels contain blocking/critical\n"
    "  labeled-non-issue     labels contain deferred/wontfix/invalid/duplicate/question\n"
    "  tracking-future       labels contain tracking/epic/enhancement, no sprint milestone\n"
    "  drift-risk            labels contain critical/high/bug + no sprint milestone +\n"
    "                        updated within --drift-days days\n"
    "  unclassified          everything else — review with LLM judgment"
)

#: cmd_classify's exact stderr message for a missing DB file.
_CLASSIFY_NO_DB_MSG = "ERROR: no root.db — run 'shctx init && shctx refresh'"

#: cmd_list's exact stderr message for a missing DB file (shorter — no
#: 'shctx init && shctx refresh' remediation hint).
_LIST_NO_DB_MSG = "ERROR: no root.db"

#: cmd_classify's exact stderr message (printed, not raised) when the
#: `state='open'` query returns zero rows — bash: `exit 0` from inside a
#: `set -eu -o pipefail` script, i.e. a clean, non-error early exit.
_NO_OPEN_ISSUES_MSG = "No open issues in cache. Run 'shctx refresh --scope=github' to populate."

#: `_classify_row`'s exact bucket order for the buckets-count TABLE (both
#: --md and text summary sections) — cmd_classify.sh's
#: `for bkt in blocking-this-sprint labeled-non-issue tracking-future drift-risk unclassified`.
_BUCKET_ORDER: tuple[str, ...] = (
    "blocking-this-sprint",
    "labeled-non-issue",
    "tracking-future",
    "drift-risk",
    "unclassified",
)

#: The FIVE `print_bucket` calls, in cmd_classify.sh's own (DIFFERENT from
#: `_BUCKET_ORDER` above) detail-section order, paired with each bucket's
#: heading text.
_BUCKET_DETAIL_ORDER: tuple[tuple[str, str], ...] = (
    ("blocking-this-sprint", "Blocking this sprint"),
    ("drift-risk", "Drift risk (high-severity, no sprint milestone)"),
    ("unclassified", "Unclassified (review manually)"),
    ("tracking-future", "Tracking / future work"),
    ("labeled-non-issue", "Labeled non-issue (deferred / wontfix / etc.)"),
)

#: `_has_label`'s candidate sets, in `_classify_row`'s exact check order.
_NON_ISSUE_LABELS: tuple[str, ...] = ("deferred", "wontfix", "won't fix", "invalid", "duplicate", "question")
_BLOCKING_LABELS: tuple[str, ...] = ("blocking", "blocker", "critical", "must-fix", "p0")
_TRACKING_LABELS: tuple[str, ...] = ("tracking", "epic", "enhancement", "feature", "roadmap")
_DRIFT_LABELS: tuple[str, ...] = ("critical", "high", "bug", "regression", "security")

#: `_current_milestone_from_branch`'s `sed 's/-dev\.[0-9]*$//'`, mirrored.
_DEV_SUFFIX_RE = re.compile(r"-dev\.[0-9]*$")

#: cmd_classify.sh's query — no LIMIT (classify always looks at every open
#: issue). `milestone` is COALESCE'd to '' (never NULL), matching the bash
#: query's own `COALESCE(milestone,'')` — NOT the '—' em-dash `list`'s own
#: text/md queries use (see `_LIST_TEXT_SQL`); `classify` never renders a
#: placeholder character for "no milestone", it checks for emptiness.
_CLASSIFY_SQL = (
    "SELECT number, title, state, labels, COALESCE(milestone,'') AS milestone, updated_at "
    "FROM index_issues WHERE project_id=? AND state='open' ORDER BY updated_at DESC"
)

#: `cmd_list`'s text/md query — `milestone` COALESCE'd to the em-dash
#: placeholder character '—' (bash: `COALESCE(milestone,'—')`), rendered
#: verbatim by both the text and md renderers when a row has no milestone.
_LIST_TEXT_SQL_TEMPLATE = (
    "SELECT number, title, state, COALESCE(milestone,'—') AS milestone, labels, url "
    "FROM index_issues WHERE {where} ORDER BY updated_at DESC LIMIT ?"
)

#: `cmd_list --json`'s SEPARATE query — `milestone` COALESCE'd to '' (NOT
#: '—'), matching `sqlite3 -cmd ".mode json"`'s own SQL text exactly. Bash
#: runs a SECOND, differently-COALESCE'd query for `--json` rather than
#: reusing the text/md rows; this port does the same (and, since the
#: text/md query's result is provably unused whenever `fmt == "json"`, never
#: bothers running it at all in that case — see the module docstring's
#: "Sub-verb ordering" note for why that's a safe, output-invisible
#: simplification).
_LIST_JSON_SQL_TEMPLATE = (
    "SELECT number, title, state, COALESCE(milestone,'') AS milestone, labels, url "
    "FROM index_issues WHERE {where} ORDER BY updated_at DESC LIMIT ?"
)


# --------------------------------------------------------------------------
# Shared helpers (project-id resolution, git branch, label-string transforms).
# --------------------------------------------------------------------------
def _read_project_id() -> str:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Duplicated from :mod:`shepherd_cli.commands.search`'s/
    :mod:`shepherd_cli.commands.query`'s identical helper (not imported —
    every module in this package is self-contained per the port's
    instructions). ``cmd_issues.sh`` calls this ``_lib.sh`` helper for both
    ``classify`` and ``list``: it reads ``<workdir>/project.json``
    (``jq -r '.id' "$(shctx_project_id_path)"``), a FILE, not the
    ``projects`` table.

    Returns:
        The project id string, or the literal three-character string
        ``"null"`` if ``project.json``'s ``"id"`` key is present-but-null
        or absent — jq -r's raw-output rendering of JSON ``null``,
        reproduced here for parity.

    Raises:
        typer.Exit: Code 1, with the exact bash stderr message
            (``"ERROR: <path> missing — run 'shctx init' first"``), if
            ``project.json`` does not exist. Also code 1 (with an
            equivalent, but not byte-identical, message) if the file
            exists but is not valid JSON; bash's ``jq`` would instead
            abort the whole script with jq's own parse-error message.
    """
    path = os.path.join(resolve_workdir(), "project.json")
    if not os.path.isfile(path):
        typer.echo(f"ERROR: {path} missing — run 'shctx init' first", err=True)
        raise typer.Exit(code=1)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR: failed to parse {path} as JSON", err=True)
        raise typer.Exit(code=1) from exc
    raw_id = data.get("id") if isinstance(data, dict) else None
    return "null" if raw_id is None else str(raw_id)


def _git_branch_or_empty() -> str:
    """Return the current git branch, or ``""`` if git is unavailable/fails.

    Bash parity with ``cmd_classify``'s own inline fallback (NOT
    ``_lib.sh``'s ``current_sprint()``, which falls back to the literal
    string ``"unknown"`` instead — a DIFFERENT helper, used by other
    commands such as ``shepherd dash``): ``sprint=$(git rev-parse
    --abbrev-ref HEAD 2>/dev/null || echo "")``.

    Returns:
        The current branch name (or ``"HEAD"`` in a detached-HEAD state,
        exactly as ``git rev-parse --abbrev-ref`` itself would render it),
        or the empty string if git is unavailable, not installed, not in a
        repo, or the command otherwise fails.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    # $(...) strips only trailing newlines, not all trailing whitespace.
    return result.stdout.rstrip("\n")


def _current_milestone_from_branch(branch: str) -> str:
    """Derive the expected milestone name from a sprint branch name.

    Bash: ``echo "$branch" | sed 's/-dev\\.[0-9]*$//'`` — strips a
    trailing ``-dev.N`` suffix (``[0-9]*`` is zero-or-more, so a bare
    trailing ``-dev.`` with no digits is also stripped), leaving the
    branch name unchanged if it has no such suffix.

    Args:
        branch: The sprint branch name (possibly empty).

    Returns:
        ``branch`` with any trailing ``-dev.<digits>`` suffix removed.
    """
    return _DEV_SUFFIX_RE.sub("", branch)


def _has_label(labels_lc: str, *candidates: str) -> bool:
    """Bash parity with ``_has_label()``: substring-contains check for a quoted label.

    Args:
        labels_lc: The raw ``labels`` JSON-array TEXT column, already
            lower-cased (bash: ``tr '[:upper:]' '[:lower:]'``).
        *candidates: Lower-case label strings to look for, each checked as
            the literal substring ``"<candidate>"`` (double-quoted) —
            matching bash's ``grep -qF "\\"$lbl\\""`` against the raw JSON
            array text, not a real JSON-array membership check.

    Returns:
        True if any candidate's quoted form appears anywhere in
        ``labels_lc``.
    """
    return any(f'"{candidate}"' in labels_lc for candidate in candidates)


def _classify_row(labels: str, milestone: str, updated_at: int, current_milestone: str, drift_thresh: int) -> str:
    """Bucket one open issue, bash-parity with ``_classify_row()``.

    Branch order matters and is preserved exactly (checked top-to-bottom,
    first match wins) — in particular, a ``"critical"`` label always
    resolves to ``blocking-this-sprint`` (checked second) and can never
    reach the ``drift-risk`` branch's own (also ``"critical"``-inclusive)
    label check, a direct consequence of bash's own branch ordering, not
    "fixed" here.

    Args:
        labels: The raw ``labels`` JSON-array TEXT column (unparsed).
        milestone: ``COALESCE(milestone,'')`` — empty string, never None.
        updated_at: The issue's ``updated_at`` column (epoch seconds, as
            stored — this port does no unit conversion on it).
        current_milestone: The resolved current-sprint milestone (from
            :func:`_current_milestone_from_branch`).
        drift_thresh: The epoch-seconds threshold a ``drift-risk``
            candidate's ``updated_at`` must be at-or-after.

    Returns:
        One of ``"labeled-non-issue"``, ``"blocking-this-sprint"``,
        ``"tracking-future"``, ``"drift-risk"``, or ``"unclassified"``.
    """
    labels_lc = labels.lower()

    if _has_label(labels_lc, *_NON_ISSUE_LABELS):
        return "labeled-non-issue"

    if milestone and milestone == current_milestone:
        return "blocking-this-sprint"
    if _has_label(labels_lc, *_BLOCKING_LABELS):
        return "blocking-this-sprint"

    if _has_label(labels_lc, *_TRACKING_LABELS):
        return "tracking-future"

    if _has_label(labels_lc, *_DRIFT_LABELS):
        if (not milestone or milestone != current_milestone) and updated_at >= drift_thresh:
            return "drift-risk"

    return "unclassified"


def _labels_json_or_empty(labels_text: str) -> object:
    """Parse the raw ``labels`` TEXT column as JSON, defensively.

    Bash embeds the raw column text directly into the ``--json`` entry
    (``"labels":$labels``, unquoted interpolation of already-valid-JSON
    text — the column carries a ``CHECK(json_valid(labels))`` constraint at
    the schema level, so this is always well-formed in practice). This port
    parses it explicitly (needed to embed it as a nested JSON array/object
    rather than a doubly-encoded string) and, as a ROBUSTNESS deviation
    matching this package's established precedent (see
    ``shepherd_cli.commands.status``'s corrupt-lock-file handling), never
    lets a malformed value crash the whole command — it degrades to an
    empty list instead of propagating a :class:`json.JSONDecodeError`.

    Args:
        labels_text: The raw ``labels`` column value.

    Returns:
        The parsed JSON value (normally a list of strings), or ``[]`` if
        ``labels_text`` is not valid JSON.
    """
    try:
        return json.loads(labels_text)
    except (json.JSONDecodeError, TypeError):
        return []


def _strip_brackets_quotes(labels_text: str) -> str:
    """Bash parity with ``tr -d '[]"'``: delete every ``[``, ``]``, ``"`` byte.

    Args:
        labels_text: The raw ``labels`` JSON-array TEXT column.

    Returns:
        ``labels_text`` with every ``[``, ``]``, and ``"`` character
        removed (commas and any other characters untouched).
    """
    return labels_text.translate(str.maketrans("", "", '[]"'))


def _labels_compact(labels_text: str) -> str:
    """``classify``'s TEXT-row label string: ``tr -d '[]"' | tr ',' ' ' | xargs``.

    Args:
        labels_text: The raw ``labels`` column value.

    Returns:
        Brackets/quotes stripped, commas turned into spaces, then every
        run of whitespace collapsed to one space with the result trimmed
        (bash: piping through ``xargs`` with no arguments) — e.g.
        ``'["bug","p0"]'`` -> ``"bug p0"``.
    """
    return " ".join(_strip_brackets_quotes(labels_text).replace(",", " ").split())


def _labels_spaced(labels_text: str) -> str:
    """``classify``'s MD-row label string: ``tr -d '[]"' | tr ',' ' '`` (no ``xargs``).

    Args:
        labels_text: The raw ``labels`` column value.

    Returns:
        Brackets/quotes stripped, commas turned into spaces — WITHOUT the
        whitespace-collapse/trim step :func:`_labels_compact` applies.
    """
    return _strip_brackets_quotes(labels_text).replace(",", " ")


def _labels_commas_kept_collapsed(labels_text: str) -> str:
    """``list``'s MD-row label string: ``tr -d '[]"' | tr ',' ', ' | xargs``.

    See the module docstring's "Two independent... label-string transforms"
    note, point 3: POSIX ``tr`` truncates a SET2 longer than SET1 down to
    SET1's length, so ``tr ',' ', '`` is byte-for-byte identical to
    ``tr ',' ','`` — commas are NEVER replaced with anything here, despite
    how the bash source reads. This helper reproduces that exact
    (almost-certainly-unintended) bash behavior rather than the
    ``, ``-joined string the source code's shape suggests.

    Args:
        labels_text: The raw ``labels`` column value.

    Returns:
        Brackets/quotes stripped, commas preserved verbatim, whitespace
        collapsed/trimmed (the trailing ``xargs`` IS a real, live step
        here, unlike :func:`_labels_spaced`) — e.g. ``'["bug","p0"]'`` ->
        ``"bug,p0"``.
    """
    return " ".join(_strip_brackets_quotes(labels_text).split())


def _parse_int_flag(raw: str, flag_name: str) -> int:
    """Parse a ``--drift-days``/``--limit`` raw string into an int, with a controlled failure.

    Bash interpolates both values directly into arithmetic
    (``$(( now - drift_days * 86400 ))``) or SQL text (``LIMIT $limit``)
    with no validation of its own; a non-numeric value crashes the WHOLE
    script non-zero via ``set -e`` (arithmetic-expansion failure, or a
    ``sqlite3 -bail`` syntax error) with bash's own uncontrolled error text.
    This port raises the SAME class of failure — abort with a non-zero exit
    and a stderr message — but with a controlled, this-port's-own message,
    mirroring :mod:`shepherd_cli.commands.search`'s ``_parse_limit`` (a
    documented, deliberate deviation, not silent parity — see hard rule #4).

    Args:
        raw: The raw string value from ``--drift-days=<value>`` or
            ``--limit=<value>``.
        flag_name: The flag's own name (``"--drift-days"`` or
            ``"--limit"``), interpolated into the error message.

    Returns:
        The parsed integer.

    Raises:
        typer.Exit: Code 1, with a stderr message naming the offending
            flag and value, if ``raw`` is not parseable as a base-10
            integer.
    """
    try:
        return int(raw)
    except ValueError as exc:
        typer.echo(f"ERROR: {flag_name} must be an integer, got: {raw}", err=True)
        raise typer.Exit(code=1) from exc


def _bash_pad(text: str, width: int) -> str:
    """Left-justify ``text`` to ``width`` the way bash's ``printf '%-Ns'`` does under C/POSIX locale.

    See the module docstring's "Column padding is BYTE-width" note: field
    width is computed in raw UTF-8 bytes (``len(text.encode("utf-8"))``),
    not Unicode codepoints — the only way to reproduce bash's own
    ``printf`` padding of the (extremely common) ``COALESCE(milestone,
    '—')`` em-dash placeholder byte-for-byte in this port's C/POSIX-locale
    runtime environment.

    Args:
        text: The (already truncated, if applicable) value to pad.
        width: The target field width, in bytes.

    Returns:
        ``text`` followed by however many ASCII spaces bring its UTF-8
        byte length up to ``width`` (zero if it is already at or past
        ``width``) — never truncates.
    """
    pad = width - len(text.encode("utf-8"))
    return text if pad <= 0 else text + " " * pad


def _render_sqlite_json(rows: list[dict[str, object]]) -> str:
    """Reproduce ``sqlite3 -cmd ".mode json"``'s exact compact-array formatting.

    See the module docstring's ``list --json`` note for the empirical
    verification this mirrors: each row renders as a compact JSON object
    (``json.dumps(row, separators=(",", ":"))`` — no space after ``:`` or
    ``,`` WITHIN an object), objects are joined with a bare ``,\\n``
    (comma, then newline, then the next object starts at column 0 — NOT
    ``", "`` or an indented continuation), the whole thing wrapped in
    ``[``/``]``, and non-ASCII text is emitted as raw UTF-8 (``ensure_ascii=
    False``), not ``\\uXXXX``-escaped.

    Args:
        rows: Query result rows (``execute_query_dict``'s dicts, in
            ``SELECT`` column order — ``number, title, state, milestone,
            labels, url`` — which Python dicts then preserve on
            iteration/serialization).

    Returns:
        The compact JSON array text, WITHOUT a trailing newline — the
        caller's ``typer.echo`` supplies exactly one, matching the real
        ``sqlite3`` binary's own single trailing ``\\n`` after the closing
        ``]``. Callers must not invoke this with an empty ``rows`` list —
        see :func:`_list_impl`'s empty-result handling, which prints
        nothing at all rather than calling this with ``rows == []``.
    """
    objects = [json.dumps(row, separators=(",", ":"), ensure_ascii=False) for row in rows]
    return "[" + ",\n".join(objects) + "]"


# --------------------------------------------------------------------------
# classify
# --------------------------------------------------------------------------
def _render_classify_text(
    sprint: str,
    current_milestone: str,
    drift_days: int,
    db_path: str,
    counts: dict[str, int],
    bucket_rows: dict[str, list[tuple[int, str, str, str]]],
    unclassified_only: bool,
) -> str:
    """Render ``classify``'s plain-text report, mirroring the bash ``else`` branch line-for-line.

    Args:
        sprint: The resolved sprint branch (``--sprint``, or the current
            git branch, or ``""``).
        current_milestone: :func:`_current_milestone_from_branch`'s output
            for ``sprint``.
        drift_days: The parsed ``--drift-days`` value.
        db_path: The resolved database path (rendered verbatim, bash-parity
            with ``db=$db``).
        counts: ``{bucket: row_count}`` for all five buckets.
        bucket_rows: ``{bucket: [(number, title, labels, milestone), ...]}``,
            each list already in the query's ``ORDER BY updated_at DESC``
            order.
        unclassified_only: When True, every detail section except
            ``unclassified`` is omitted entirely (bash: ``print_bucket``'s
            own early-return).

    Returns:
        The full multi-line report (no trailing newline — the caller's
        ``typer.echo`` supplies exactly one).
    """
    lines: list[str] = [
        f"Issue triage — sprint: {sprint}  current_milestone: {current_milestone}",
        f"drift_days={drift_days}  db={db_path}",
        "",
        f"{'Bucket':<26}  {'Count':>5}",
        f"{'-' * 26}  {'-' * 5}",
    ]
    for bucket in _BUCKET_ORDER:
        lines.append(f"{bucket:<26}  {counts[bucket]:>5}")

    for bucket, heading in _BUCKET_DETAIL_ORDER:
        if unclassified_only and bucket != "unclassified":
            continue
        rows = bucket_rows[bucket]
        if not rows:
            continue
        lines.append("")
        lines.append(f"{heading:<26} ({counts[bucket]})")
        lines.append(f"{'Issue':<7}  {'Title':<55}  {'Labels'}")
        lines.append(f"{'-' * 7}  {'-' * 55}  {'-' * 6}")
        for number, title, labels, _milestone in rows:
            label_str = _labels_compact(labels)
            lines.append(f"#{_bash_pad(str(number), 6)}  {_bash_pad(title[:55], 55)}  {label_str[:40]}")

    if not unclassified_only:
        lines.append("")
        lines.append("Tip: use --unclassified-only to show only the bucket requiring LLM review.")

    return "\n".join(lines)


def _render_classify_md(
    sprint: str,
    current_milestone: str,
    counts: dict[str, int],
    bucket_rows: dict[str, list[tuple[int, str, str, str]]],
    unclassified_only: bool,
) -> str:
    """Render ``classify``'s markdown report, mirroring the bash ``if fmt == md`` branch.

    Args:
        sprint: The resolved sprint branch.
        current_milestone: :func:`_current_milestone_from_branch`'s output.
        counts: ``{bucket: row_count}`` for all five buckets.
        bucket_rows: ``{bucket: [(number, title, labels, milestone), ...]}``.
        unclassified_only: When True, every detail section except
            ``unclassified`` is omitted.

    Returns:
        The full multi-line report (no trailing newline).
    """
    lines: list[str] = [f"## Issue triage — {sprint} (milestone: {current_milestone})", "", "| Bucket | Count |", "|---|---|"]
    for bucket in _BUCKET_ORDER:
        lines.append(f"| {bucket} | {counts[bucket]} |")

    for bucket, heading in _BUCKET_DETAIL_ORDER:
        if unclassified_only and bucket != "unclassified":
            continue
        rows = bucket_rows[bucket]
        if not rows:
            continue
        lines.append("")
        lines.append(f"### {heading} ({counts[bucket]})")
        lines.append("")
        for number, title, labels, milestone in rows:
            ms_str = f" · milestone: {milestone}" if milestone else ""
            lines.append(f"- #{str(number):<5}  {title}{ms_str}")
            label_str = _labels_spaced(labels)
            if label_str:
                lines.append(f"         labels: {label_str}")

    if not unclassified_only:
        lines.append("")
        lines.append("Tip: use --unclassified-only to show only the bucket requiring LLM review.")

    return "\n".join(lines)


async def _classify_impl(tokens: list[str]) -> None:
    """Run ``shctx issues classify``'s full body against the tokens after the sub-verb.

    Args:
        tokens: Every token given after ``classify``, in order (flags
            only — ``cmd_classify`` takes no free-text/positional
            arguments).

    Raises:
        typer.Exit: Code 0, after printing :data:`_USAGE`, on the first
            ``-h``/``--help`` token. Code 2, with bash's exact
            ``"ERROR: unknown arg: <arg>"`` message, on the first
            unrecognized token. Code 1 (via :func:`_parse_int_flag`) on an
            unparseable ``--drift-days``. Code 1, with
            :data:`_CLASSIFY_NO_DB_MSG`, if no database file exists at the
            resolved path. Code 1 (via :func:`_read_project_id`) if
            ``project.json`` is missing/unparseable. Code 0, with
            :data:`_NO_OPEN_ISSUES_MSG` on stderr and NO stdout at all
            (bash: a clean early ``exit 0``, not an error), if the
            ``state='open'`` query returns zero rows.
    """
    sprint = ""
    drift_days_raw = "30"
    fmt = "text"
    unclassified_only = False

    for token in tokens:
        if token.startswith("--sprint="):
            sprint = token[len("--sprint=") :]
        elif token.startswith("--drift-days="):
            drift_days_raw = token[len("--drift-days=") :]
        elif token == "--md":
            fmt = "md"
        elif token == "--json":
            fmt = "json"
        elif token == "--unclassified-only":
            unclassified_only = True
        elif token in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {token}", err=True)
            raise typer.Exit(code=2)

    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(_CLASSIFY_NO_DB_MSG, err=True)
        raise typer.Exit(code=1)

    if not sprint:
        sprint = _git_branch_or_empty()
    current_milestone = _current_milestone_from_branch(sprint)

    drift_days = _parse_int_flag(drift_days_raw, "--drift-days")
    now_s = int(time.time())
    drift_thresh = now_s - drift_days * 86400

    project_id = _read_project_id()

    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(_CLASSIFY_SQL, [project_id])

    if not rows:
        typer.echo(_NO_OPEN_ISSUES_MSG, err=True)
        raise typer.Exit(code=0)

    bucket_rows: dict[str, list[tuple[int, str, str, str]]] = {bucket: [] for bucket in _BUCKET_ORDER}
    json_entries: list[dict[str, object]] = []

    for row in rows:
        number = int(row["number"])
        title = str(row["title"])
        labels = str(row["labels"])
        milestone = str(row["milestone"])
        updated_at = int(row["updated_at"])

        bucket = _classify_row(labels, milestone, updated_at, current_milestone, drift_thresh)
        bucket_rows[bucket].append((number, title, labels, milestone))

        if fmt == "json":
            json_entries.append(
                {
                    "number": number,
                    "title": title,
                    "bucket": bucket,
                    "labels": _labels_json_or_empty(labels),
                    "milestone": milestone or None,
                }
            )

    if fmt == "json":
        # Bash-parity formatting note: plain `json.dumps`, matching the
        # bash source's own `python3 -c 'print(json.dumps(arr))'` call —
        # NOT `_render_sqlite_json`'s sqlite3-JSON-mode shape `list --json`
        # uses. See the module docstring.
        typer.echo(json.dumps(json_entries))
        return

    counts = {bucket: len(bucket_rows[bucket]) for bucket in _BUCKET_ORDER}
    if fmt == "md":
        typer.echo(_render_classify_md(sprint, current_milestone, counts, bucket_rows, unclassified_only))
    else:
        typer.echo(
            _render_classify_text(sprint, current_milestone, drift_days, db_path, counts, bucket_rows, unclassified_only)
        )


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------
def _render_list_text(rows: list[dict[str, object]]) -> str:
    """Render ``list``'s plain-text report (header always printed, even for zero rows).

    Args:
        rows: Query rows (``number, title, state, milestone, labels, url``
            — ``labels``/``url`` are selected but never rendered in text
            mode, bash-parity with ``cmd_list``'s own unused-column select).

    Returns:
        The full multi-line report (no trailing newline).
    """
    lines: list[str] = [
        f"#{'Issue':<6}  {'Title':<50}  {'State':<8}  {'Milestone':<15}",
        f"{'-' * 7}  {'-' * 50}  {'-' * 8}  {'-' * 15}",
    ]
    for row in rows:
        number = row["number"]
        title = str(row["title"])
        state = str(row["state"])
        milestone = str(row["milestone"])
        lines.append(
            f"#{_bash_pad(str(number), 6)}  {_bash_pad(title[:50], 50)}  "
            f"{_bash_pad(state, 8)}  {_bash_pad(milestone[:15], 15)}"
        )
    return "\n".join(lines)


def _render_list_md(rows: list[dict[str, object]]) -> str:
    """Render ``list``'s markdown table (header always printed, even for zero rows).

    Args:
        rows: Query rows (``number, title, state, milestone, labels, url``).

    Returns:
        The full multi-line table (no trailing newline).
    """
    lines: list[str] = ["| # | Title | State | Milestone | Labels |", "|---|---|---|---|---|"]
    for row in rows:
        number = row["number"]
        title = str(row["title"])
        state = str(row["state"])
        milestone = str(row["milestone"])
        labels = str(row["labels"])
        url = str(row["url"])
        label_str = _labels_commas_kept_collapsed(labels)
        lines.append(f"| [#{number}]({url}) | {title} | {state} | {milestone} | {label_str} |")
    return "\n".join(lines)


async def _list_impl(tokens: list[str]) -> None:
    """Run ``shctx issues list``'s full body against the tokens after the sub-verb.

    Args:
        tokens: Every token given after ``list``, in order.

    Raises:
        typer.Exit: Code 0, after printing :data:`_USAGE`, on the first
            ``-h``/``--help`` token. Code 2, with bash's exact
            ``"ERROR: unknown arg: <arg>"`` message, on the first
            unrecognized token. Code 1 (via :func:`_parse_int_flag`) on an
            unparseable ``--limit``. Code 1, with :data:`_LIST_NO_DB_MSG`,
            if no database file exists at the resolved path. Code 1 (via
            :func:`_read_project_id`) if ``project.json`` is
            missing/unparseable.
    """
    state = "open"
    limit_raw = "100"
    fmt = "text"

    for token in tokens:
        if token.startswith("--state="):
            state = token[len("--state=") :]
        elif token.startswith("--limit="):
            limit_raw = token[len("--limit=") :]
        elif token == "--md":
            fmt = "md"
        elif token == "--json":
            fmt = "json"
        elif token in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {token}", err=True)
            raise typer.Exit(code=2)

    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(_LIST_NO_DB_MSG, err=True)
        raise typer.Exit(code=1)

    limit = _parse_int_flag(limit_raw, "--limit")
    project_id = _read_project_id()

    where = "project_id=?"
    params: list[object] = [project_id]
    if state != "all":
        where += " AND state=?"
        params.append(state)
    params.append(limit)

    if fmt == "json":
        sql = _LIST_JSON_SQL_TEMPLATE.format(where=where)
        async with db.lifespan():
            connection = Tortoise.get_connection("default")
            rows = await connection.execute_query_dict(sql, params)
        # Bash-parity: zero rows -> zero bytes of output (not "[]"; the
        # bash source's own "|| echo '[]'" only fires on a genuine SQL
        # error, which an empty-but-valid result set never triggers). See
        # the module docstring's "list --json" note.
        if rows:
            typer.echo(_render_sqlite_json(rows))
        return

    sql = _LIST_TEXT_SQL_TEMPLATE.format(where=where)
    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(sql, params)

    if fmt == "md":
        typer.echo(_render_list_md(rows))
    else:
        typer.echo(_render_list_text(rows))


# --------------------------------------------------------------------------
# Dispatch.
# --------------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="<classify|list> [args]",
        help="Subcommand (classify|list), then that subcommand's own flags.",
    ),
) -> None:
    """Dispatch to ``classify``/``list``, bash-parity with ``cmd_issues.sh``'s ``case "$sub"``.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works like every other
            single-callback group in this package — see
            :mod:`shepherd_cli.commands.search`'s identical pattern).
        raw: Every token given after ``issues``, in order — the first
            token (if any) is the sub-verb, the rest are that sub-verb's
            own flags.

    Raises:
        typer.Exit: Code 0, after printing :data:`_USAGE` to stdout, when
            no sub-verb is given, or the sub-verb itself is ``-h``/
            ``--help`` (bash: ``""|-h|--help) usage; exit 0 ;;``). Code 2,
            with ``"ERROR: unknown subcommand: <sub>"`` plus
            :data:`_USAGE`, both on stderr, for any other unrecognized
            sub-verb. Otherwise propagates whatever
            :func:`_classify_impl`/:func:`_list_impl` raises.
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    tokens = raw or []
    sub = tokens[0] if tokens else ""
    rest = tokens[1:]

    if sub in ("", "-h", "--help"):
        typer.echo(_USAGE)
        raise typer.Exit(code=0)
    if sub == "classify":
        asyncio.run(_classify_impl(rest))
    elif sub == "list":
        asyncio.run(_list_impl(rest))
    else:
        typer.echo(f"ERROR: unknown subcommand: {sub}", err=True)
        typer.echo(_USAGE, err=True)
        raise typer.Exit(code=2)


__all__ = ["app"]
