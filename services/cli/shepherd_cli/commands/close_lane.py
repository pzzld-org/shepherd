"""``shepherd close-lane`` — record a mid-sprint lane closure Typer sub-app.

Native port of ``skills/context/scripts/cmd_close-lane.sh`` (v5.0.3): a
single flat verb, ``shctx close-lane <lane-id> --sprint=<branch>
[--issues=#a,#b] [--status=clean|partial|failed] [--acceptance=<path>]``,
that:

1. Upserts one ``lane_closures`` row (bash: ``INSERT ... ON
   CONFLICT(project_id, sprint_branch, lane_id) DO UPDATE SET ...`` — the
   table's own ``UNIQUE(project_id, sprint_branch, lane_id)`` constraint,
   added by migration ``0003_canonical_types_filter.sql``, is what makes
   this idempotent).
2. For each ``--issues=#N`` item, probes ``gh issue view <N> --json
   state`` (with bash's own transient-failure retry/backoff,
   ``_lib.sh``'s ``shctx_gh_retry``) and buckets it into "resolved"
   (issue state CLOSED) or "still open" (state OPEN, unknown, or the
   probe itself failed/was skipped).
3. Logs one ``logs_events`` row (``level='audit'``, ``source='close-lane'``,
   ``event='lane-closed'``) with a compact JSON payload.
4. Prints a carry-forward markdown patch to stdout (for the conductor to
   apply to the sprint's carry-forward ledger by hand) and a one-line
   summary to stderr.

**No sibling ``cmd_*.sh`` shelling** (unlike ``sprint.py``/``audit.py``/
``sync.py``): ``cmd_close-lane.sh`` never invokes another ``shctx``
subcommand. Its ONLY external-process dependency is the ``gh`` CLI (hard
rule #9 applies to that ``gh`` probe, not to any sibling script) — this
module subprocess-invokes the real ``gh`` binary with the EXACT same argv
(``gh issue view <n> --json state -q .state``) bash does, including its
retry/backoff shape (:func:`_gh_retry`, byte-for-byte mirroring
``shctx_gh_retry``'s attempt-count/backoff-base env vars and transient-
error substring matching), rather than reimplementing the GitHub API call
some other way.

**Raw SQL only — no ``models_close-lane.py``.** Both tables this module
writes already have a Tortoise model elsewhere in the package
(:class:`shepherd_cli.models_sprint.LaneClosure` for ``lane_closures``;
:class:`shepherd_cli.models_status.LogEvent` for ``logs_events``), but
BOTH are deliberately READ-scoped and declare only a handful of columns
(``LaneClosure``: ``id``/``project_id``/``sprint_branch``/``lane_id``/
``closed_at`` — no ``resolved_issues``/``acceptance_log``/``status``/
``notes``; ``LogEvent``: ``id`` only) — nowhere near enough for this
module's inserts. Per the port contract's COLLISION RULE, this module
does NOT redeclare either table (that would collide with the existing
models in the same Tortoise app registry) and does NOT even import
either model (neither is ever read here, only written) — every read
(the ``sqlite_master`` table-existence guard) and write (the
``lane_closures`` upsert, the ``logs_events`` insert) goes through raw
parameterized SQL via ``Tortoise.get_connection("default")``, exactly
:mod:`shepherd_cli.commands.lock`'s ``locks_history`` pattern. No new
model module is needed or written for this port.

**Project-id resolution** follows :mod:`shepherd_cli.commands.query`'s /
:mod:`shepherd_cli.commands.search`'s precedent, NOT
:mod:`shepherd_cli.commands.mem`'s "read the ``projects`` table"
deviation: ``cmd_close-lane.sh`` calls ``_lib.sh``'s ``shctx_project_id()``
unconditionally, which reads ``<workdir>/project.json`` off the
filesystem (``jq -r '.id'``), a file, not a table. :func:`_read_project_id`
below is duplicated (not imported) from those two modules' identical
helper, per this port's self-contained-module instruction.

**Timestamps are epoch SECONDS** throughout (``lane_closures.closed_at``,
``logs_events.ts``), matching ``_lib.sh``'s ``shctx_now`` (``date +%s``)
— NOT the epoch-millisecond unit ``deliverables``/``teammates`` use.

**Row id** is a UUIDv7 string (``_lib.sh``'s ``shctx_uuid7``), matching
every other UUID-keyed table's Python id generator in this package
(:func:`shepherd_cli.commands.mem._uuid7` and its several duplicates) —
duplicated here as :func:`_uuid7` for the same self-contained-module
reason.

Bash parity notes worth flagging up front (all preserved deliberately):

* ``--acceptance=<path>`` reads the FILE'S CONTENT immediately, at
  flag-parse time, tolerantly: a missing/unreadable file silently reads
  as ``""`` (bash: ``$(cat "$path" 2>/dev/null || true)``), never an
  error. An empty (or never-given) acceptance value is stored as SQL
  ``NULL`` in ``acceptance_log``, not an empty string (bash:
  ``${acc_esc:+'$acc_esc'}${acc_esc:-NULL}`` — the ``NULL`` bareword
  branch fires whenever the escaped value is empty).
* ``resolved_issues`` is a compact JSON array of ISSUE-NUMBER STRINGS
  (e.g. ``["12","34"]``), never integers — bash builds it with ``jq -R .``
  (raw-string-per-line), which quotes every element.
* The ``gh`` issue-state probe is only ever attempted when ``--issues=``
  is non-empty. If the ``gh`` binary is not on ``PATH``, every listed
  issue number is bucketed "still open" with a warning to stderr (bash:
  ``command -v gh`` gate) — the probe is never silently skipped without
  that warning.
* A probe that fails outright (non-transient ``gh`` error, or every retry
  attempt exhausted) reads as issue state ``"?"``, which — like an
  explicit ``OPEN``/``open`` state, or any other unrecognized string —
  buckets into "still open" (bash's ``case`` statement's ``*)`` arm is
  the SAME still-open branch as the explicit ``OPEN|open)`` arm).
* The generated markdown patch's ``_Generated <UTC timestamp>_`` line
  uses ``datetime.now(timezone.utc)`` captured at PRINT time (bash:
  ``date -u +%Y-%m-%dT%H:%M:%SZ``, its own separate ``date`` invocation,
  not the earlier ``$now`` epoch-seconds value used for the DB write) —
  callers comparing this command's stdout byte-for-byte need to treat
  that one line as time-varying, not literal.
* Exit codes: 0 on success; 1 on every argument-validation failure AND on
  a missing/unparseable ``project.json``; 2 if the ``lane_closures``
  table itself is absent (a DB that predates migration ``0003``) — this
  status code is deliberately DIFFERENT from the validation-failure
  code 1, mirroring bash's own ``exit 2`` on that specific guard.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.resolution import resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires full control over -h/--help's own output (see
    # _USAGE / _parse_args below) instead of Click's autogenerated help
    # text, so Click's own --help machinery is disabled entirely
    # (help_option_names=[]) -- mirroring shepherd_cli.commands.search's
    # identical technique. allow_extra_args + ignore_unknown_options let
    # every "--sprint=...", "--issues=...", "--status=...",
    # "--acceptance=..." token (plus the bare <lane-id> positional) flow
    # into the single variadic `raw` argument below instead of Click
    # trying (and failing) to parse them as its own options -- the bash
    # source interleaves the positional and every flag in ANY order on
    # one command line, and a single variadic positional argument is the
    # only Typer/Click shape that captures "every remaining token, in
    # order" without a Group's own subcommand-resolution step trying (and
    # failing) to treat the first leftover token as a subcommand name.
    context_settings={
        "help_option_names": [],
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Record a mid-sprint lane closure; auto-resolves carry-forward ledger items.",
)

#: Verbatim bash-parity usage text -- cmd_close-lane.sh's usage() heredoc,
#: printed to STDOUT (not stderr) on -h/--help, and to STDERR (prefixed by
#: an ERROR line) on the two validation failures that show it.
_USAGE = (
    "shctx close-lane <lane-id> --sprint=<branch> [--issues=#a,#b] "
    "[--status=clean|partial|failed] [--acceptance=<path>]\n"
    "\n"
    "Record a mid-sprint lane closure. Auto-resolves carry-forward ledger items\n"
    "whose underlying GH issues have transitioned to closed.\n"
    "\n"
    '  <lane-id>           short identifier (e.g. "lane-3", "wave-2-lane-b")\n'
    "  --sprint=<branch>   sprint branch this lane closed under\n"
    "  --issues=#a,#b      GH issue numbers the lane was supposed to resolve\n"
    "  --status=...        clean (gates green) | partial (gates green w/ scope cuts) | failed\n"
    "  --acceptance=<path> optional path to the lane's [ACCEPTANCE] markdown to record\n"
    "\n"
    "Output: markdown patch for the carry-forward ledger (apply manually or via diff)."
)

#: ``shctx_gh_retry``'s transient-failure substring markers (``_lib.sh``).
#: A ``gh`` invocation whose combined stdout+stderr contains any of these
#: is retried (up to ``SHCTX_GH_RETRY_MAX`` attempts); any other failure
#: fails immediately, with no retry.
_TRANSIENT_MARKERS = ("HTTP 504", "HTTP 502", "HTTP 503", "timeout", "timed out", "connection reset")

#: ``shctx_gh_retry``'s default max attempts / backoff base (``_lib.sh``),
#: overridable via the SAME env vars bash reads.
_DEFAULT_GH_RETRY_MAX = 3
_DEFAULT_GH_RETRY_BACKOFF = 2


# --------------------------------------------------------------------------
# Small stdlib helpers (duplicated across command modules by design -- see
# the module docstring's project-id / timestamp / uuid7 notes).
# --------------------------------------------------------------------------
def _now_s() -> int:
    """Return the current wall-clock time in epoch seconds.

    Returns:
        The current time as whole seconds since the Unix epoch, matching
        ``_lib.sh``'s ``shctx_now`` (``date +%s``) -- the unit
        ``lane_closures.closed_at`` and ``logs_events.ts`` both use.
    """
    return int(time.time())


def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for a new ``lane_closures`` row.

    Bash generates ids via ``_lib.sh``'s ``shctx_uuid7`` (a 48-bit
    millisecond-timestamp-prefixed, timestamp-sortable UUID built from
    ``date +%s%3N`` and ``/dev/urandom``). This is an independent,
    equally-valid UUIDv7 generator over the stdlib ``time``/``os.urandom``
    -- not byte-for-byte identical to bash's construction, but every id it
    produces is a spec-compliant, monotonically-sortable-by-creation-time
    UUIDv7, the only property either tool's rows actually depend on.

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


def _read_project_id() -> str:
    """Resolve the active project id, bash-parity with ``_lib.sh``'s ``shctx_project_id``.

    Duplicated from :mod:`shepherd_cli.commands.query`'s /
    :mod:`shepherd_cli.commands.search`'s identical helper (not imported
    -- every module in this package is self-contained per the port's
    instructions). ``cmd_close-lane.sh`` calls this ``_lib.sh`` helper
    unconditionally, BEFORE ever opening a database connection: it reads
    ``<workdir>/project.json`` (``jq -r '.id'``), a file, not a table.

    Returns:
        The project id string, or the literal three-character string
        ``"null"`` if ``project.json``'s ``"id"`` key is present-but-null
        or absent -- jq -r's raw-output rendering of JSON ``null``,
        reproduced here for parity.

    Raises:
        typer.Exit: Code 1, with the exact bash stderr message
            (``"ERROR: <path> missing — run 'shctx init' first"``), if
            ``project.json`` does not exist. Also code 1 (with an
            equivalent, but not byte-identical, message) if the file
            exists but is not valid JSON; bash's ``jq`` would instead
            abort the whole script with jq's own parse-error message and
            exit code.
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


def _read_file_tolerant(path: str) -> str:
    """Read ``path``'s content, tolerantly -- bash parity with ``$(cat "$path" 2>/dev/null || true)``.

    Args:
        path: The ``--acceptance=<path>`` value.

    Returns:
        The file's content with every TRAILING newline stripped (bash:
        command substitution strips all trailing newlines, not just
        one -- ``str.rstrip("\\n")`` reproduces that exactly), or ``""``
        if the file does not exist or cannot be read for any reason
        (bash: ``cat``'s failure is swallowed by ``2>/dev/null || true``,
        never aborting the script).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return ""
    return content.rstrip("\n")


# --------------------------------------------------------------------------
# Argument parsing -- mirrors cmd_close-lane.sh's `while (( $# > 0 ))` loop.
# --------------------------------------------------------------------------
def _parse_args(tokens: list[str]) -> tuple[str, str, str, str, str]:
    """Classify every token on the command line, bash-parity with the ``while`` loop.

    Walks ``tokens`` in order, mirroring the bash ``case`` chain's
    precedence per token (checked top-to-bottom, exactly this order):
    ``-h``/``--help`` (prints usage to stdout and exits 0 immediately --
    later tokens are never examined), ``--sprint=*``, ``--issues=*``,
    ``--status=*``, ``--acceptance=*`` (reads the named file's content
    immediately, via :func:`_read_file_tolerant` -- see the module
    docstring), any other ``--``-prefixed token (unknown flag -> error),
    and finally the first non-flag token becomes ``<lane-id>`` (a SECOND
    non-flag token is an error: bash's ``ERROR: extra arg: $1``).

    Args:
        tokens: Every token given after ``close-lane``, in order.

    Returns:
        A ``(lane_id, sprint_branch, issues_csv, status, acceptance_content)``
        tuple. ``lane_id``/``sprint_branch``/``issues_csv``/
        ``acceptance_content`` default to ``""`` when never given;
        ``status`` defaults to ``"clean"`` (bash: ``status="clean"`` at
        the top of the script). None of these are validated as
        "required" here -- bash validates AFTER the loop completes, and
        so does this function's caller (:func:`_default`).

    Raises:
        typer.Exit: Code 0, after printing :data:`_USAGE` to stdout, on
            the first ``-h``/``--help`` token. Code 1, with bash's exact
            stderr message (``"ERROR: unknown flag: <token>"`` followed
            by :data:`_USAGE`, both on stderr), on the first token that
            starts with ``--`` and matches none of the recognized flag
            shapes. Code 1, with bash's exact stderr message
            (``"ERROR: extra arg: <token>"``, no usage text), on a SECOND
            non-flag token.
    """
    lane_id = ""
    sprint_branch = ""
    issues_csv = ""
    status = "clean"
    acceptance_content = ""

    for token in tokens:
        if token in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        elif token.startswith("--sprint="):
            sprint_branch = token[len("--sprint=") :]
        elif token.startswith("--issues="):
            issues_csv = token[len("--issues=") :]
        elif token.startswith("--status="):
            status = token[len("--status=") :]
        elif token.startswith("--acceptance="):
            acceptance_content = _read_file_tolerant(token[len("--acceptance=") :])
        elif token.startswith("--"):
            typer.echo(f"ERROR: unknown flag: {token}", err=True)
            typer.echo(_USAGE, err=True)
            raise typer.Exit(code=1)
        else:
            if not lane_id:
                lane_id = token
            else:
                typer.echo(f"ERROR: extra arg: {token}", err=True)
                raise typer.Exit(code=1)

    return lane_id, sprint_branch, issues_csv, status, acceptance_content


def _parse_issue_numbers(issues_csv: str) -> list[str]:
    """Split ``--issues=`` into cleaned issue-number strings, bash-parity with the ``for raw in`` loop.

    Bash: ``IFS=',' read -ra issues_arr <<< "$issues_csv"``, then per
    element ``n="${raw#\\#}"`` (strip exactly one leading ``#``, if
    present) followed by ``n="${n// /}"`` (strip EVERY space, anywhere in
    the token, not just leading/trailing) and ``[[ -n "$n" ]] || continue``
    (drop anything that reduces to the empty string).

    Args:
        issues_csv: The raw ``--issues=`` value, e.g. ``"#12, #34,,56"``.

    Returns:
        The cleaned issue-number strings, in order, e.g.
        ``["12", "34", "56"]`` for that example (the empty element
        between the two commas is dropped).
    """
    numbers: list[str] = []
    for raw in issues_csv.split(","):
        n = raw[1:] if raw.startswith("#") else raw
        n = n.replace(" ", "")
        if n:
            numbers.append(n)
    return numbers


# --------------------------------------------------------------------------
# gh CLI issue-state probe -- mirrors _lib.sh's shctx_gh_retry.
# --------------------------------------------------------------------------
def _int_env(name: str, default: int) -> int:
    """Read a positive-int env var, bash-parity with ``${VAR:-default}`` then arithmetic use.

    Args:
        name: The env var name (``SHCTX_GH_RETRY_MAX`` or
            ``SHCTX_GH_RETRY_BACKOFF``).
        default: The value bash's own ``:-`` default falls back to when
            the var is unset OR empty.

    Returns:
        The parsed int, or ``default`` if the var is unset, empty, or not
        a valid base-10 integer. Bash's own ``(( ... ))`` arithmetic
        context would instead ABORT the script (under ``set -e``) on a
        non-numeric value; this port degrades to the default instead --
        a deliberate, minor robustness deviation, since no shipped caller
        ever sets these to a non-numeric value.
    """
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _is_transient_gh_failure(combined_output: str) -> bool:
    """Bash parity with ``shctx_gh_retry``'s transient-failure ``case`` pattern.

    Args:
        combined_output: ``gh``'s combined stdout+stderr text from one
            failed invocation.

    Returns:
        True if ``combined_output`` contains any of
        :data:`_TRANSIENT_MARKERS` (an HTTP 502/503/504, or any
        timeout/connection-reset wording) -- bash's ``case "$out" in
        *"HTTP 504"*|...) ... ;; esac`` glob-pattern match, reproduced as
        a plain substring test (equivalent for these literal, non-glob
        marker strings).
    """
    return any(marker in combined_output for marker in _TRANSIENT_MARKERS)


def _gh_retry(args: list[str]) -> str | None:
    """Run ``gh <args>``, retrying transient failures -- bash parity with ``shctx_gh_retry``.

    Bash::

        shctx_gh_retry() {
          local max_attempts="${SHCTX_GH_RETRY_MAX:-3}"
          local backoff_base="${SHCTX_GH_RETRY_BACKOFF:-2}"
          local attempt=1 rc=0 out=""
          while (( attempt <= max_attempts )); do
            if out=$(gh "$@" 2>&1); then printf '%s' "$out"; return 0; fi
            rc=$?
            case "$out" in
              *"HTTP 504"*|*"HTTP 502"*|*"HTTP 503"*|*"timeout"*|*"timed out"*|*"connection reset"*)
                if (( attempt < max_attempts )); then
                  sleep $(( backoff_base ** attempt )); attempt=$((attempt + 1)); continue
                fi ;;
              *) return "$rc" ;;
            esac
            attempt=$((attempt + 1))
          done
          return "$rc"
        }

    Every diagnostic message bash's own version writes to stderr (the
    per-attempt "retrying in Ns..." notice, the final "exhausted N
    attempts" notice, and the failed invocation's own captured output) is
    OMITTED here -- at ``cmd_close-lane.sh``'s one call site
    (``state=$(shctx_gh_retry ... 2>/dev/null || echo "?")``), the ENTIRE
    command substitution's stderr is redirected to ``/dev/null``, so none
    of that text is ever visible to a real bash user either; reproducing
    it here would be dead code with no observable parity benefit.

    Args:
        args: The ``gh`` subcommand and its arguments, e.g.
            ``["issue", "view", "12", "--json", "state", "-q", ".state"]``
            (WITHOUT the leading ``"gh"`` binary name itself).

    Returns:
        ``gh``'s stdout, with every trailing newline stripped (bash: the
        ``out=$(...)`` command substitution's own trailing-newline
        stripping), on a zero exit code. ``None`` if ``gh`` cannot be
        launched at all, if it fails non-transiently, or if every retry
        attempt is exhausted on a transient failure.
    """
    max_attempts = _int_env("SHCTX_GH_RETRY_MAX", _DEFAULT_GH_RETRY_MAX)
    backoff_base = _int_env("SHCTX_GH_RETRY_BACKOFF", _DEFAULT_GH_RETRY_BACKOFF)
    attempt = 1
    while attempt <= max_attempts:
        try:
            result = subprocess.run(
                ["gh", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError:
            return None
        out = (result.stdout or "").rstrip("\n")
        if result.returncode == 0:
            return out
        if attempt < max_attempts and _is_transient_gh_failure(out):
            time.sleep(backoff_base**attempt)
            attempt += 1
            continue
        return None
    return None


def _resolve_issues(issues_csv: str) -> tuple[list[str], list[str]]:
    """Bucket every ``--issues=`` entry into resolved (closed) vs. still-open.

    Bash parity with ``cmd_close-lane.sh``'s ``if [[ -n "$issues_csv" ]]
    && command -v gh ...; then ... elif [[ -n "$issues_csv" ]]; then
    <gh-not-found warning> ... fi`` block.

    Args:
        issues_csv: The raw ``--issues=`` value (``""`` when the flag was
            never given -- both returned lists stay empty in that case,
            with no ``gh`` probe and no stderr message).

    Returns:
        ``(resolved, still_open)`` -- the cleaned issue-number strings
        (:func:`_parse_issue_numbers`) bucketed by GH issue state. An
        issue whose ``gh`` probe returns ``CLOSED``/``closed`` lands in
        ``resolved``; every other outcome (``OPEN``/``open``, any other
        string, the probe itself failing) lands in ``still_open``.
    """
    resolved: list[str] = []
    still_open: list[str] = []
    if not issues_csv:
        return resolved, still_open

    numbers = _parse_issue_numbers(issues_csv)
    if shutil.which("gh") is None:
        typer.echo(
            "shctx close-lane: gh CLI not found; skipping issue-state probe "
            "(treating all listed as still-open)",
            err=True,
        )
        still_open.extend(numbers)
        return resolved, still_open

    for n in numbers:
        out = _gh_retry(["issue", "view", n, "--json", "state", "-q", ".state"])
        state = out if out is not None else "?"
        if state in ("CLOSED", "closed"):
            resolved.append(n)
        else:
            still_open.append(n)
    return resolved, still_open


# --------------------------------------------------------------------------
# Database half -- raw SQL only (see the module docstring's COLLISION-RULE
# note for why neither lane_closures nor logs_events gets a Tortoise model
# here).
# --------------------------------------------------------------------------
async def _lane_closures_table_exists() -> bool:
    """Check whether the ``lane_closures`` table exists in the live DB.

    Bash parity with ``cmd_close-lane.sh``'s defensive ``sqlite_master``
    introspection guard: ``shctx_sql "SELECT 1 FROM sqlite_master WHERE
    type='table' AND name='lane_closures';" | grep -q 1``. Duplicated
    from :mod:`shepherd_cli.commands.sprint`'s identical helper (same
    guard, same table, both self-contained modules per the port's
    instructions).

    Returns:
        True if ``lane_closures`` exists as a table in the current
        connection's database.
    """
    connection = Tortoise.get_connection("default")
    rows = await connection.execute_query_dict(
        "SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='lane_closures'"
    )
    return len(rows) > 0


async def _write_lane_closure(
    *,
    row_id: str,
    project_id: str,
    sprint_branch: str,
    lane_id: str,
    closed_at: int,
    resolved_json: str,
    acceptance_content: str,
    status: str,
) -> None:
    """Upsert one ``lane_closures`` row -- bash parity with the ``INSERT ... ON CONFLICT`` statement.

    Args:
        row_id: A freshly-minted UUIDv7 (:func:`_uuid7`) -- only used on
            first insert; an existing row's ``id`` is left untouched by
            the ``ON CONFLICT ... DO UPDATE`` clause (it updates
            ``closed_at``/``resolved_issues``/``acceptance_log``/
            ``status`` only, never ``id``).
        project_id: The active project id (:func:`_read_project_id`).
        sprint_branch: The ``--sprint=`` value.
        lane_id: The ``<lane-id>`` positional.
        closed_at: Epoch seconds (:func:`_now_s`).
        resolved_json: The compact JSON array of resolved issue-number
            strings (``"[]"`` when none).
        acceptance_content: The ``--acceptance=`` file's content
            (:func:`_read_file_tolerant`'s result, possibly ``""``).
        status: One of ``clean``/``partial``/``failed`` (already
            validated by the caller).
    """
    connection = Tortoise.get_connection("default")
    await connection.execute_query(
        "INSERT INTO lane_closures "
        "(id, project_id, sprint_branch, lane_id, closed_at, resolved_issues, acceptance_log, status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL) "
        "ON CONFLICT(project_id, sprint_branch, lane_id) DO UPDATE SET "
        "closed_at=excluded.closed_at, "
        "resolved_issues=excluded.resolved_issues, "
        "acceptance_log=excluded.acceptance_log, "
        "status=excluded.status",
        [
            row_id,
            project_id,
            sprint_branch,
            lane_id,
            closed_at,
            resolved_json,
            # Bash: ${acc_esc:+'$acc_esc'}${acc_esc:-NULL} -- an empty
            # acceptance value is stored as SQL NULL, never "".
            acceptance_content or None,
            status,
        ],
    )


async def _write_audit_log(
    *,
    project_id: str,
    ts: int,
    lane_id: str,
    sprint_branch: str,
    status: str,
    resolved: list[str],
) -> None:
    """Insert one ``logs_events`` audit row -- bash parity with the second ``shctx_sql`` call.

    Args:
        project_id: The active project id.
        ts: Epoch seconds (the SAME ``$now`` value used for
            ``lane_closures.closed_at`` -- bash computes it once and
            reuses it for both writes).
        lane_id: The ``<lane-id>`` positional.
        sprint_branch: The ``--sprint=`` value.
        status: One of ``clean``/``partial``/``failed``.
        resolved: The resolved issue-number strings (:func:`_resolve_issues`).
    """
    payload = json.dumps(
        {"lane": lane_id, "sprint": sprint_branch, "status": status, "resolved": resolved},
        separators=(",", ":"),
    )
    connection = Tortoise.get_connection("default")
    await connection.execute_query(
        "INSERT INTO logs_events (project_id, ts, level, source, event, payload, sprint_branch) "
        "VALUES (?, ?, 'audit', 'close-lane', 'lane-closed', ?, ?)",
        [project_id, ts, payload, sprint_branch],
    )


async def _close_lane_async(
    lane_id: str,
    sprint_branch: str,
    issues_csv: str,
    status: str,
    acceptance_content: str,
) -> None:
    """Run the full ``close-lane`` DB + gh-probe pipeline and print the carry-forward patch.

    Bash parity with ``cmd_close-lane.sh``'s body, in the SAME order:
    verify migration 0003 applied -> resolve project id -> resolve
    ``now``/a fresh uuid7 -> probe GH issue states -> upsert
    ``lane_closures`` -> insert the ``logs_events`` audit row -> emit the
    markdown patch to stdout -> emit the one-line summary to stderr.

    Args:
        lane_id: The validated (non-empty) ``<lane-id>`` positional.
        sprint_branch: The validated (non-empty) ``--sprint=`` value.
        issues_csv: The raw ``--issues=`` value (possibly ``""``).
        status: The validated (``clean``/``partial``/``failed``)
            ``--status=`` value.
        acceptance_content: The ``--acceptance=`` file's content
            (possibly ``""``).

    Raises:
        typer.Exit: Code 2, with bash's exact stderr message, if the
            ``lane_closures`` table is absent (a DB predating migration
            0003). Code 1 (via :func:`_read_project_id`) if
            ``project.json`` is missing or unparseable.
    """
    async with db.lifespan():
        if not await _lane_closures_table_exists():
            typer.echo(
                "ERROR: lane_closures table missing. Run `shctx migrate` to apply "
                "0003_canonical_types_filter.sql.",
                err=True,
            )
            raise typer.Exit(code=2)

        project_id = _read_project_id()
        now = _now_s()
        row_id = _uuid7()

        resolved, still_open = _resolve_issues(issues_csv)
        resolved_json = json.dumps(resolved, separators=(",", ":"))

        await _write_lane_closure(
            row_id=row_id,
            project_id=project_id,
            sprint_branch=sprint_branch,
            lane_id=lane_id,
            closed_at=now,
            resolved_json=resolved_json,
            acceptance_content=acceptance_content,
            status=status,
        )
        await _write_audit_log(
            project_id=project_id,
            ts=now,
            lane_id=lane_id,
            sprint_branch=sprint_branch,
            status=status,
            resolved=resolved,
        )

    _emit_carry_forward_patch(lane_id, sprint_branch, resolved, still_open, status)


def _emit_carry_forward_patch(
    lane_id: str,
    sprint_branch: str,
    resolved: list[str],
    still_open: list[str],
    status: str,
) -> None:
    """Print the carry-forward markdown patch (stdout) + summary line (stderr).

    Bash parity with ``cmd_close-lane.sh``'s final block, line-for-line
    (each list element below corresponds to exactly one bash ``echo``):
    header, blank, generated-timestamp, blank, then EITHER a "Resolved"
    section (only if ``resolved`` is non-empty, followed by its own
    trailing blank line) and/or a "Still open" section (only if
    ``still_open`` is non-empty, with NO trailing blank line of its own)
    -- OR, if BOTH are empty, a single "no issues recorded" line instead
    -- then an unconditional trailing blank line, then the one-line
    summary on STDERR (not stdout).

    Args:
        lane_id: The ``<lane-id>`` positional (rendered verbatim, backtick-
            quoted, never escaped -- bash parity).
        sprint_branch: The ``--sprint=`` value (same rendering caveat).
        resolved: Resolved issue-number strings, in probe order.
        still_open: Still-open issue-number strings, in probe order.
        status: One of ``clean``/``partial``/``failed``.
    """
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    typer.echo(f"# carry-forward patch — lane `{lane_id}` (sprint `{sprint_branch}`)")
    typer.echo("")
    typer.echo(f"_Generated {generated} by shctx close-lane._")
    typer.echo("")

    if resolved:
        typer.echo("## Resolved (move from Pending → Resolved)")
        for n in resolved:
            typer.echo(f"- [#{n}] ✅ Resolved by lane `{lane_id}` (status: {status})")
        typer.echo("")

    if still_open:
        typer.echo("## Still open (keep in Pending)")
        for n in still_open:
            typer.echo(f"- [#{n}] ⏳ Lane `{lane_id}` closed but issue still open — verify manually")

    if not resolved and not still_open:
        typer.echo("_No issues recorded for this lane closure._")

    typer.echo("")
    typer.echo(
        f"shctx close-lane: recorded {lane_id} under {sprint_branch} "
        f"(resolved={len(resolved)}, still-open={len(still_open)}, status={status})",
        err=True,
    )


# --------------------------------------------------------------------------
# Entry point.
# --------------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="<lane-id> --sprint=<branch> [--issues=#a,#b] [--status=clean|partial|failed] [--acceptance=<path>]",
        help="The lane id, plus any mix of --sprint/--issues/--status/--acceptance flags, in any order.",
    ),
) -> None:
    """Record a mid-sprint lane closure; auto-resolves carry-forward ledger items.

    Native port of ``shctx close-lane`` (``cmd_close-lane.sh``). Every
    token after ``close-lane`` is either the ``<lane-id>`` positional or a
    recognized flag; see :func:`_parse_args` for the exact per-token
    classification bash mirrors.

    Args:
        ctx: The Typer/Click context (unused directly; required so
            ``invoke_without_command`` dispatch works -- see
            :mod:`shepherd_cli.commands.search`'s identical pattern).
        raw: Every token given after ``close-lane``, in order.

    Raises:
        typer.Exit: Code 0 on ``-h``/``--help`` (usage printed to
            stdout). Code 1 on: an unknown ``--`` flag, an extra
            positional, a missing ``<lane-id>``, a missing ``--sprint=``,
            an invalid ``--status=``, or a missing/unparseable
            ``project.json``. Code 2 if the ``lane_closures`` table is
            absent (DB predates migration 0003).
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    tokens = raw or []
    lane_id, sprint_branch, issues_csv, status, acceptance_content = _parse_args(tokens)

    if not lane_id:
        typer.echo("ERROR: lane-id required", err=True)
        typer.echo(_USAGE, err=True)
        raise typer.Exit(code=1)
    if not sprint_branch:
        typer.echo("ERROR: --sprint= required", err=True)
        typer.echo(_USAGE, err=True)
        raise typer.Exit(code=1)
    if status not in ("clean", "partial", "failed"):
        typer.echo("ERROR: --status must be clean|partial|failed", err=True)
        raise typer.Exit(code=1)

    asyncio.run(_close_lane_async(lane_id, sprint_branch, issues_csv, status, acceptance_content))


__all__ = ["app"]
