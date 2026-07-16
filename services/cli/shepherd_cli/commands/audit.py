"""``shepherd audit`` — read-only validation pipeline (bash: ``cmd_audit.sh``).

Native port of ``skills/context/scripts/cmd_audit.sh`` (v5.0.4, ``insert``
subverb added v5.1.7): a three-stage read-only validation pipeline —

    lint  ->  doctor  ->  status

— plus a completely separate write-path subverb, ``shepherd audit insert``,
that appends one structured row to ``audit_findings``.

**Pipeline (bare ``shepherd audit`` / ``shepherd audit --verbose``).**
``cmd_audit.sh`` never inlines lint/doctor/status logic — it SHELLS OUT to
its three sibling scripts (``cmd_lint.sh``, ``cmd_doctor.sh``,
``cmd_status.sh``) via ``bash "$HERE/cmd_*.sh"``, exactly like
:mod:`shepherd_cli.commands.sync`'s ``refresh -> lint -> status`` pipeline
(this module reuses that same ``_scripts_dir()``/``_run_stage()`` shape,
duplicated here per hard rule #9's self-contained-module requirement rather
than imported cross-module). This port does the SAME: it locates the real
``cmd_lint.sh``/``cmd_doctor.sh``/``cmd_status.sh`` via
:func:`shepherd_cli.resolution.find_bash_shctx` and subprocess-invokes them,
rather than re-implementing any of their (considerable — ``doctor`` alone
has six diagnostic sections) logic natively. This is a deliberate port
choice, not a shortcut: ``doctor`` has NO Python port yet in this wave
(it is absent from ``shepherd_cli.__main__.PORTED``), and re-deriving its
binary/schema/lock/refresh-staleness checks here would (a) duplicate work
squarely owned by a future ``doctor`` port and (b) risk drifting from the
bash source of truth ``cmd_audit.sh`` itself defers to. Shelling out is
exactly what bash's own ``cmd_audit.sh`` does for all three stages, so this
is the highest-fidelity parity choice available, not merely the easiest.

Bash's own stage-running shape, verbatim::

    run_stage() {
      local name="$1"; shift
      if (( verbose )); then echo "─── $name ───"; "$@"
      else "$@" >/dev/null 2>&1 || return $?
      fi
    }

    rc_lint=0; rc_doctor=0; rc_status=0
    run_stage lint   bash "$HERE/cmd_lint.sh"   || rc_lint=$?
    bash "$HERE/cmd_doctor.sh" >/dev/null 2>&1 || rc_doctor=$?
    run_stage status bash "$HERE/cmd_status.sh" || rc_status=$?

    # Always print doctor at end (it's the user-relevant signal).
    bash "$HERE/cmd_doctor.sh"

Three details this module reproduces EXACTLY because they are easy to get
subtly wrong:

1. ``doctor`` is invoked TWICE, unconditionally, regardless of
   ``--verbose``: once silently (stdout+stderr discarded) purely to
   capture its exit code into ``rc_doctor``, and once more at the very end
   with output fully inherited (this is "the user-relevant signal" the
   bash comment calls out) — its exit code from that second call is
   discarded entirely. ``doctor`` NEVER goes through ``run_stage``, so it
   never prints a ``─── doctor ───`` header even when ``--verbose`` is
   given — only ``lint`` and ``status`` do.
2. ``lint``/``status`` each go through ``run_stage`` (verbose: header +
   inherited output; quiet: fully suppressed output) exactly like
   :mod:`shepherd_cli.commands.sync`'s stages.
3. The three-state summary line for ``doctor`` (``ok`` / ``warn`` /
   ``fail (rc=N)``) is DIFFERENT from ``lint``/``status``'s two-state
   summary (``ok`` / ``fail (rc=N)``) — ``doctor``'s own exit code 2 means
   "warnings only" (see ``cmd_doctor.sh``), which prints as ``warn``, not
   ``fail``.

Final exit code (bash: ``if (( rc_lint != 0 || rc_doctor == 1 ||
rc_status != 0 )); then exit 1; fi; if (( rc_doctor == 2 )); then exit 2;
fi; exit 0``): 1 if lint or status failed OR doctor hard-failed
(``rc_doctor == 1``, note NOT ``rc_doctor != 0``, since ``rc_doctor == 2``
is warn-only and must not trip this branch); else 2 if doctor warned only;
else 0.

**NO DATABASE for the pipeline path.** Exactly like ``cmd_sync.sh``, the
pipeline itself never touches ``sqlite3``/Tortoise directly — every table
read happens inside the subprocess stages it shells out to. No
``db.lifespan()``, no model module, for THIS half of the module.

**``insert`` subverb — DOES touch the database, raw SQL only.**
``audit_findings`` already has a READ-scoped Tortoise model
(:class:`shepherd_cli.models_report.AuditFinding` — ``id``,
``sprint_branch``, ``concern``, ``severity``, ``hypothesis``,
``falsification``, ``confidence``, ``finding``, ``gh_issue``,
``created_at``; no ``project_id``, no ``evidence_refs``). Per the port
contract's COLLISION RULE, a write to that same table (this module needs
``project_id`` and ``evidence_refs`` too, columns the existing model omits)
does NOT redeclare the table — it goes through
``Tortoise.get_connection("default").execute_query_dict(sql, [params])``
inside ``db.lifespan()``, exactly ``commands/lock.py``'s
``locks_history`` pattern. No ``models_audit.py`` is needed or written.

``cmd_audit.sh insert`` bash source, verbatim (the part this subverb
ports)::

    if [[ "${1:-}" == "insert" ]]; then
      shift
      concern=""; severity=""; hypothesis=""; falsification=""; confidence=""
      evidence=""; gh=""; sprint=""
      while [[ $# -gt 0 ]]; do case "$1" in
        --concern=*)       concern="${1#*=}";;
        --severity=*)      severity="${1#*=}";;
        --hypothesis=*)    hypothesis="${1#*=}";;
        --falsification=*) falsification="${1#*=}";;
        --confidence=*)    confidence="${1#*=}";;
        --evidence=*)      evidence="${1#*=}";;
        --gh-issue=*)      gh="${1#*=}";;
        --sprint=*)        sprint="${1#*=}";;
        *) echo "unknown flag: $1" >&2; exit 2;;
      esac; shift; done
      [[ -n "$concern" && -n "$severity" && -n "$hypothesis" ]] \
        || { echo "ERR: --concern, --severity, --hypothesis required" >&2; exit 2; }
      finding="$(cat)"
      if [[ -n "$evidence" ]]; then
        echo "$evidence" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' \
          >/dev/null 2>&1 || evidence=""
      fi
      DB="${SHCTX_DB:-$(shctx_db_path)}"
      [[ -f "$DB" ]] || { echo "ERR: registry DB not found at $DB" >&2; exit 1; }
      pid="$(sqlite3 "$DB" "SELECT id FROM projects LIMIT 1;")"
      ts=$(($(date +%s) * 1000))
      ... INSERT ... VALUES ('$pid', NULLIF('$safe_sp',''), '$concern', '$severity',
          '$safe_hyp', NULLIF('$safe_fal',''), NULLIF('$confidence',''), '$safe_fin',
          NULLIF('$safe_ev',''), NULLIF('$gh',''), $ts) RETURNING id;
      echo "$id"
      exit 0
    fi

Deliberate, documented deviations/notes:

- **``project_id`` resolution is NOT ``shctx_project_id()``.** Unlike
  most other bash subcommands (which read ``project.json`` via
  ``shctx_project_id``), ``insert`` resolves the owning project with a
  bare ``SELECT id FROM projects LIMIT 1`` straight against the DB — this
  port mirrors that exact query (via Tortoise) rather than
  :func:`shepherd_cli.resolution`'s project.json path, and — matching bash
  exactly — does NOT error before attempting the ``INSERT`` if no project
  row exists: ``project_id`` is simply the empty string, and the code path
  proceeds to the same ``INSERT`` call bash's own ``pid=""`` would (bash
  has no guard on ``pid`` being empty either).
- **An empty/orphaned ``project_id`` fails DIFFERENTLY here than in
  bash — a disclosed, deliberate platform-level divergence, not a bug.**
  Bash's raw ``sqlite3 "$DB" "INSERT ..."`` CLI invocation runs with
  ``PRAGMA foreign_keys`` at sqlite's own per-connection OFF default, so
  an ``INSERT`` with ``project_id=''`` (no matching ``projects`` row)
  SUCCEEDS in bash, silently writing an orphaned row. Tortoise's sqlite
  backend, by contrast, sets ``PRAGMA foreign_keys = ON`` by default for
  every connection it opens (``tortoise.backends.sqlite.client``'s
  ``self.pragmas.setdefault("foreign_keys", "ON")``) — a platform default
  shared by every OTHER ported command module's ``db.lifespan()``
  connection too, not something this module could selectively disable
  without becoming the one write path in the whole CLI with inconsistent
  referential-integrity enforcement. So when no ``projects`` row exists,
  this port's ``INSERT`` raises ``tortoise.exceptions.IntegrityError:
  FOREIGN KEY constraint failed`` — caught by the SAME ``except
  IntegrityError`` arm documented below for a bad ``--severity`` value,
  producing ``ERROR: FOREIGN KEY constraint failed`` on stderr, exit 1,
  with NO row written. In the only realistic shape of this scenario (a
  project whose ``shctx init`` never ran, i.e. an empty/absent
  ``projects`` table), refusing to write an orphaned finding row is
  strictly safer than bash's silent success, and every healthy project
  (the only case this subcommand is meant for) has exactly one
  ``projects`` row written once, together with ``project.json``, by
  ``shctx init`` — so this divergence never surfaces in practice.
- **Timestamp unit is epoch-MILLISECONDS, computed from whole seconds —
  NOT ``shctx_now()``.** ``ts=$(($(date +%s) * 1000))`` truncates to whole
  seconds FIRST, then multiplies by 1000 — this is deliberately
  ``int(time.time()) * 1000``, not ``int(time.time() * 1000)`` (the latter
  would retain sub-second precision bash's integer arithmetic cannot
  produce). See :mod:`shepherd_cli.models_report`'s module docstring,
  which documents this exact unit for ``audit_findings.created_at``.
- **SQL-escaping vs. parameter binding is a value-preserving swap.**
  Bash manually doubles every embedded single quote
  (``safe_hyp="${hypothesis//\\'/''}"``) so the raw string can be spliced
  into the SQL text without breaking out of its literal — sqlite decodes
  ``''`` back to one ``'`` when parsing that literal, so the STORED value
  is identical to the original unescaped text either way. This port binds
  every value as a query parameter instead (never string-interpolated),
  which stores the exact same final value with none of the injection-shaped
  fragility bash's approach has for adversarial input — an implementation
  detail with no user-visible behavior change.
- **Optional-field ``NULLIF(x, '')`` semantics are reproduced exactly**:
  ``sprint_branch``, ``falsification``, ``confidence``, ``evidence_refs``,
  and ``gh_issue`` all store SQL ``NULL`` when the corresponding flag was
  omitted/empty, vs. the literal empty string; ``project_id``, ``concern``,
  ``severity``, ``hypothesis``, and ``finding`` are always stored verbatim
  (never ``NULLIF``-wrapped), matching the bash ``VALUES`` list's own
  per-column split exactly.
- **``evidence`` JSON validation failure silently clears the field, not an
  error.** Bash pipes a non-empty ``--evidence`` value through
  ``python3 -c 'json.loads(...)'``; on ANY failure (invalid JSON, no
  ``python3`` on ``PATH``, etc.) it swallows the error and resets
  ``evidence=""`` (which then becomes SQL ``NULL`` via ``NULLIF``) rather
  than rejecting the ``insert`` call. :func:`_validated_evidence` does the
  same: ``json.loads`` failure clears the field, never raises.
- **A CHECK-constraint violation (e.g. an invalid ``--severity`` value —
  the column is ``CHECK(severity IN ('info','low','medium','high',
  'critical'))``) is UNVALIDATED by both bash and this port before the
  ``INSERT`` runs** — bash relies entirely on sqlite's own ``CHECK``
  rejecting it at insert time, which (under ``set -eu -o pipefail``, with
  no error trap) crashes the whole script with sqlite3's own diagnostic on
  stderr and its own non-zero exit code. This port catches the
  ``tortoise.exceptions.IntegrityError`` that same ``CHECK`` violation
  raises through Tortoise's raw connection and converts it into a clean
  ``ERROR: <message>`` on stderr with exit code 1 — the SAME robustness
  pattern :mod:`shepherd_cli.commands.mem`'s ``add`` command already
  documents and uses for its own ``CHECK(kind IN (...))``/
  ``CHECK(json_valid(tags))`` violations (see ``mem.py``'s
  ``except IntegrityError`` arm) — a deliberate, cleaner-than-bash
  robustness improvement, not a parity gap: the constraint is still
  enforced by the same DB-level ``CHECK``, only the failure's presentation
  differs (a legible one-line message instead of a raw sqlite3 crash), and
  the exit code (1) matches what bash's own uncaught crash would produce
  in practice.
- **``finding="$(cat)"`` strips ALL trailing newlines**, not just one —
  that is bash command-substitution's own universal behavior (strips
  every trailing ``\\n``, however many), reproduced here via
  ``.rstrip("\\n")`` on the full stdin read (a plain ``.rstrip()`` would
  additionally strip trailing spaces/tabs, which bash's ``$(...)`` does
  NOT do — only newlines).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

import typer
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from shepherd_cli import db
from shepherd_cli.resolution import find_bash_shctx, resolve_db_path

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    # help_option_names=[] disables Click's own --help so -h/--help reach the
    # callback's own token handling and print the verbatim bash usage text
    # (parity) — matching commands/sync.py / search.py / models.py / query.py.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    help="Read-only validation pipeline: lint -> doctor -> status. Also: 'insert' writes an audit_findings row.",
)

#: Verbatim bash-parity usage text — the ``-h|--help`` heredoc in
#: ``cmd_audit.sh``. Printed to stdout (bash parity: plain ``cat``, not
#: stderr) on ``-h``/``--help``, exit 0.
_HELP_TEXT = (
    "shctx audit [--verbose]\n"
    "shctx audit insert --concern=<c> --severity=<s> --hypothesis=<h>\n"
    "                   [--falsification=<f>] [--confidence=<low|medium|high>]\n"
    "                   [--evidence=<json>] [--gh-issue=<n>] [--sprint=<branch>]\n"
    "                   < finding-body.md\n"
    "\n"
    "Read-only validation: lint → doctor → status.\n"
    "Exits 0 if all green, 1 if any FAIL, 2 if only WARNs (matches doctor).\n"
    "\n"
    "v5.1.7+: `insert` subverb writes a structured row into audit_findings."
)

#: Every ``insert`` flag bash recognizes, mapped to the local variable name
#: it sets — mirrors ``cmd_audit.sh``'s ``while ... case`` loop's eight
#: ``--flag=*)`` arms, in the SAME order (order is immaterial here since
#: each is a distinct, non-overlapping prefix, but kept source-aligned for
#: traceability).
_INSERT_FLAGS = (
    "--concern=",
    "--severity=",
    "--hypothesis=",
    "--falsification=",
    "--confidence=",
    "--evidence=",
    "--gh-issue=",
    "--sprint=",
)


# --------------------------------------------------------------------------
# Sibling-script location + stage runner (same shape as
# shepherd_cli.commands.sync's own helpers, kept self-contained here per
# hard rule #9 — each ported module owns its own copy rather than
# cross-importing a sibling command module).
# --------------------------------------------------------------------------
def _scripts_dir() -> str:
    """Resolve the directory containing the sibling ``cmd_*.sh`` scripts.

    Mirrors ``cmd_audit.sh``'s own ``HERE="$(cd "$(dirname "$0")" && pwd)"``
    — the directory holding ``cmd_audit.sh`` itself is the same directory
    that holds ``cmd_lint.sh``, ``cmd_doctor.sh``, and ``cmd_status.sh``.

    Returns:
        The absolute path to ``skills/context/scripts``.

    Raises:
        typer.Exit: code 1, with a stderr message, if the bash ``shctx``
            tooling cannot be located at all — every stage of the audit
            pipeline shells out to it, so there is nothing useful this
            command can do without it.
    """
    shctx_path = find_bash_shctx()
    if shctx_path is None:
        typer.echo("ERROR: bash shctx tooling not found (skills/context/scripts/)", err=True)
        raise typer.Exit(code=1)
    return os.path.dirname(shctx_path)


def _run_stage(name: str, argv: list[str], verbose: bool) -> int:
    """Run one pipeline stage, mirroring ``cmd_audit.sh``'s ``run_stage()`` helper.

    Bash::

        run_stage() {
          local name="$1"; shift
          if (( verbose )); then echo "─── $name ───"; "$@"
          else "$@" >/dev/null 2>&1 || return $?
          fi
        }

    Args:
        name: Human label for the stage header, printed only when
            ``verbose`` (bash: the ``echo "─── $name ───"`` line).
        argv: The full argv to execute, e.g.
            ``["bash", "<scripts>/cmd_lint.sh"]``.
        verbose: When True, print the stage header and let the child
            process inherit this process's stdout/stderr. When False,
            discard the child's stdout AND stderr entirely — only the
            exit code is observed either way.

    Returns:
        The child process's exit code (0 on success).
    """
    if verbose:
        typer.echo(f"─── {name} ───")
        result = subprocess.run(argv, check=False)
    else:
        result = subprocess.run(argv, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode


# --------------------------------------------------------------------------
# Pipeline path (bare `shepherd audit` / `shepherd audit --verbose`).
# --------------------------------------------------------------------------
def _parse_pipeline_args(argv: list[str]) -> bool:
    """Parse the pipeline path's arguments, mirroring ``cmd_audit.sh``'s ``for arg`` loop.

    Bash::

        verbose=0
        for arg in "$@"; do
          case "$arg" in
            --verbose|-v) verbose=1 ;;
            -h|--help)
              cat <<'EOF' ... EOF
              exit 0 ;;
            *) echo "ERROR: unknown arg: $arg" >&2; exit 1 ;;
          esac
        done

    Every token is visited in order; ``-h``/``--help`` and an unrecognized
    token both short-circuit immediately, from ANY position in ``argv``.
    Only reached when ``argv`` is empty or ``argv[0] != "insert"`` — the
    caller checks the ``insert`` subverb FIRST, exactly mirroring bash's
    own ``if [[ "${1:-}" == "insert" ]]; then ... fi`` guard running before
    this loop even starts.

    Args:
        argv: Every token given to ``shepherd audit`` after the command
            name itself (with the ``insert`` case already ruled out by the
            caller), in order.

    Returns:
        ``verbose`` — True if ``--verbose``/``-v`` was given (any number
        of times, in any position); False for a bare invocation (bash: the
        ``for`` loop simply never executes on empty ``$@``).

    Raises:
        typer.Exit: code 0, after printing :data:`_HELP_TEXT` to stdout,
            the instant an ``-h``/``--help`` token is reached. Code 1,
            after printing ``"ERROR: unknown arg: <token>"`` to stderr,
            the instant a token matching none of the recognized shapes is
            reached.
    """
    verbose = False
    for arg in argv:
        if arg in ("--verbose", "-v"):
            verbose = True
        elif arg in ("-h", "--help"):
            typer.echo(_HELP_TEXT)
            raise typer.Exit(code=0)
        else:
            typer.echo(f"ERROR: unknown arg: {arg}", err=True)
            raise typer.Exit(code=1)
    return verbose


def _audit_pipeline(verbose: bool) -> None:
    """Run lint -> doctor -> status and print bash-parity summary + exit code.

    Bash parity with ``cmd_audit.sh``'s main body: ``doctor`` is invoked
    TWICE (once silently for its exit code, once more at the very end with
    output fully inherited — see the module docstring point 1); ``lint``
    and ``status`` each go through :func:`_run_stage` exactly once.

    Args:
        verbose: ``--verbose``/``-v`` — forwarded to ``lint``'s and
            ``status``'s :func:`_run_stage` calls only (``doctor`` never
            receives a stage header, matching bash exactly).

    Raises:
        typer.Exit: code 1 if ``lint`` or ``status`` failed, or ``doctor``
            hard-failed (exit 1, NOT exit 2); else code 2 if ``doctor``
            warned only (exit 2); else code 0.
    """
    scripts_dir = _scripts_dir()
    doctor_argv = ["bash", os.path.join(scripts_dir, "cmd_doctor.sh")]

    rc_lint = _run_stage("lint", ["bash", os.path.join(scripts_dir, "cmd_lint.sh")], verbose)
    # doctor's rc-capturing call is ALWAYS silent, regardless of --verbose,
    # and never goes through _run_stage (no "─── doctor ───" header ever).
    rc_doctor = subprocess.run(
        doctor_argv, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode
    rc_status = _run_stage("status", ["bash", os.path.join(scripts_dir, "cmd_status.sh")], verbose)

    # Always print doctor's own output at the end (it's the user-relevant
    # signal) — a SEPARATE invocation from the rc-capturing one above, with
    # output fully inherited (unredirected), whose own exit code is
    # discarded (rc_doctor was already captured from the FIRST call).
    subprocess.run(doctor_argv, check=False)

    typer.echo("")
    typer.echo("shctx audit:")
    typer.echo(f"  lint:   {'ok' if rc_lint == 0 else f'fail (rc={rc_lint})'}")
    if rc_doctor == 0:
        doctor_summary = "ok"
    elif rc_doctor == 2:
        doctor_summary = "warn"
    else:
        doctor_summary = f"fail (rc={rc_doctor})"
    typer.echo(f"  doctor: {doctor_summary}")
    typer.echo(f"  status: {'ok' if rc_status == 0 else f'fail (rc={rc_status})'}")

    if rc_lint != 0 or rc_doctor == 1 or rc_status != 0:
        raise typer.Exit(code=1)
    if rc_doctor == 2:
        raise typer.Exit(code=2)
    raise typer.Exit(code=0)


# --------------------------------------------------------------------------
# `insert` subverb (v5.1.7+) — the ONLY write path in this module.
# --------------------------------------------------------------------------
def _now_ms() -> int:
    """Return the current wall-clock time in epoch MILLISECONDS, truncated-seconds-first.

    Bash parity with ``cmd_audit.sh``'s ``ts=$(($(date +%s) * 1000))``:
    truncates to whole seconds FIRST (``date +%s``), THEN multiplies by
    1000 — deliberately NOT ``int(time.time() * 1000)``, which would carry
    sub-second precision bash's integer arithmetic cannot produce. This is
    the epoch-MILLISECONDS unit ``audit_findings.created_at`` uses (see
    :mod:`shepherd_cli.models_report`'s module docstring) — a different
    unit than most other ported command modules' epoch-SECONDS
    ``shctx_now()``.

    Returns:
        The current time as whole milliseconds since the Unix epoch,
        computed from whole seconds.
    """
    return int(time.time()) * 1000


def _parse_insert_flags(argv: list[str]) -> dict[str, str]:
    """Parse ``insert``'s ``--flag=value`` tokens, mirroring bash's ``while ... case`` loop.

    Bash::

        while [[ $# -gt 0 ]]; do case "$1" in
          --concern=*)       concern="${1#*=}";;
          ...
          *) echo "unknown flag: $1" >&2; exit 2;;
        esac; shift; done

    Args:
        argv: Every token given after ``insert`` on the command line, in
            order.

    Returns:
        A dict from bare flag name (e.g. ``"concern"``, without the
        leading ``--``/trailing ``=``) to its string value. A flag never
        given is simply absent from the dict (callers default via
        ``.get(name, "")``, matching bash's empty-string-initialized
        locals).

    Raises:
        typer.Exit: code 2, after printing ``"unknown flag: <token>"`` to
            stderr, the instant a token matches none of
            :data:`_INSERT_FLAGS`' prefixes.
    """
    values: dict[str, str] = {}
    for arg in argv:
        matched = False
        for flag in _INSERT_FLAGS:
            if arg.startswith(flag):
                values[flag[2:-1]] = arg[len(flag) :]
                matched = True
                break
        if not matched:
            typer.echo(f"unknown flag: {arg}", err=True)
            raise typer.Exit(code=2)
    return values


def _validated_evidence(evidence: str) -> str:
    """Validate ``--evidence`` as JSON, silently clearing it on failure.

    Bash::

        if [[ -n "$evidence" ]]; then
          echo "$evidence" | python3 -c 'import sys,json;json.loads(sys.stdin.read())' \\
            >/dev/null 2>&1 || evidence=""
        fi

    Args:
        evidence: The raw ``--evidence`` value (already known non-empty by
            the caller; an empty string is returned unchanged without
            attempting to parse it, matching bash's ``[[ -n "$evidence" ]]``
            guard).

    Returns:
        ``evidence`` unchanged if it parses as valid JSON (or is already
        empty); the empty string if it is non-empty but fails to parse —
        NEVER raises, matching bash's swallowed-error behavior exactly.
    """
    if not evidence:
        return evidence
    try:
        json.loads(evidence)
    except json.JSONDecodeError:
        return ""
    return evidence


async def _insert_async(flags: dict[str, str], finding: str) -> None:
    """Insert one ``audit_findings`` row and print its id.

    Bash parity with ``cmd_audit.sh``'s ``insert`` subverb body (DB half):
    resolve the DB path, verify it exists, resolve ``project_id`` via a
    bare ``SELECT id FROM projects LIMIT 1`` (NOT ``shctx_project_id()``
    — see the module docstring), stamp ``created_at`` in epoch
    milliseconds, ``INSERT ... RETURNING id``, print the id.

    Args:
        flags: The parsed ``--flag=value`` map from
            :func:`_parse_insert_flags` (already validated non-empty for
            ``concern``/``severity``/``hypothesis`` by the caller).
        finding: The finding body read from stdin (already
            newline-stripped by the caller).

    Raises:
        typer.Exit: code 1 if the registry DB file does not exist (stderr
            message, bash parity: ``ERR: registry DB not found at $DB``);
            code 1 (stderr ``ERROR: <message>``) if the ``INSERT``
            violates a DB-level ``CHECK`` constraint (e.g. an invalid
            ``--severity`` value) — see the module docstring's
            IntegrityError-handling deviation note.
    """
    db_path = resolve_db_path()
    if not os.path.isfile(db_path):
        typer.echo(f"ERR: registry DB not found at {db_path}", err=True)
        raise typer.Exit(code=1)

    evidence = _validated_evidence(flags.get("evidence", ""))

    async with db.lifespan():
        connection = Tortoise.get_connection("default")
        project_rows = await connection.execute_query_dict("SELECT id FROM projects LIMIT 1")
        project_id = str(project_rows[0]["id"]) if project_rows else ""

        try:
            rows = await connection.execute_query_dict(
                "INSERT INTO audit_findings "
                "(project_id, sprint_branch, concern, severity, hypothesis, falsification, "
                "confidence, finding, evidence_refs, gh_issue, created_at) "
                "VALUES (?, NULLIF(?, ''), ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, "
                "NULLIF(?, ''), NULLIF(?, ''), ?) "
                "RETURNING id",
                [
                    project_id,
                    flags.get("sprint", ""),
                    flags["concern"],
                    flags["severity"],
                    flags["hypothesis"],
                    flags.get("falsification", ""),
                    flags.get("confidence", ""),
                    finding,
                    evidence,
                    flags.get("gh-issue", ""),
                    _now_ms(),
                ],
            )
        except IntegrityError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    typer.echo(str(rows[0]["id"]))


def _insert_dispatch(argv: list[str]) -> None:
    """Synchronous entry point for the ``insert`` subverb.

    Bash parity with ``cmd_audit.sh``'s ``insert`` subverb ordering: parse
    flags (unknown flag -> exit 2) -> require ``concern``/``severity``/
    ``hypothesis`` non-empty (exit 2) -> read+strip stdin -> hand off to
    :func:`_insert_async` for the DB half.

    Args:
        argv: Every token given after ``insert`` on the command line.

    Raises:
        typer.Exit: code 2 if a flag is unrecognized or a required flag is
            missing/empty; code 1 if the DB half fails (see
            :func:`_insert_async`).
    """
    flags = _parse_insert_flags(argv)
    if not (flags.get("concern") and flags.get("severity") and flags.get("hypothesis")):
        typer.echo("ERR: --concern, --severity, --hypothesis required", err=True)
        raise typer.Exit(code=2)

    # Bash parity: `finding="$(cat)"` — command substitution strips EVERY
    # trailing newline (however many), not spaces/tabs and not just one.
    finding = sys.stdin.read().rstrip("\n")

    asyncio.run(_insert_async(flags, finding))


# --------------------------------------------------------------------------
# Top-level dispatch: `insert` (checked FIRST, bash parity) vs. the
# pipeline path. A single callback (not a Click subcommand for `insert`)
# because bash's own routing checks the LITERAL first token
# (`${1:-}" == "insert"`) before any flag parsing begins — anything else
# in position 0 (including "insert" appearing LATER in argv) falls through
# to the pipeline's flag loop, where it is just another unrecognized
# token. This matches commands/sync.py's context_settings shape: a single
# variadic hidden argument, `ignore_unknown_options`/`allow_extra_args` so
# Click never intercepts a bash-style flag, and `help_option_names=[]` so
# `-h`/`--help` reach this module's own bash-verbatim help text instead of
# Click's.
# --------------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def audit(
    args: list[str] = typer.Argument(
        None,
        metavar="[insert --concern=<c> --severity=<s> --hypothesis=<h> [...] | --verbose|-v] [-h|--help]",
        hidden=True,
        help=(
            "'insert ...' (reads finding body from stdin) writes one audit_findings row; "
            "otherwise flags only — see cmd_audit.sh's usage text (-h/--help)."
        ),
    ),
) -> None:
    """Read-only validation pipeline (lint -> doctor -> status), or the ``insert`` subverb.

    Native port of ``shctx audit`` (``cmd_audit.sh``). Bash checks
    ``${1:-}" == "insert"`` BEFORE any flag parsing — this callback does
    the same, dispatching to :func:`_insert_dispatch` only when the
    LITERAL first token is ``"insert"``, and to the pipeline path
    (:func:`_parse_pipeline_args` + :func:`_audit_pipeline`) otherwise.

    Args:
        args: Every token given after ``audit`` on the command line, or
            None/empty for a bare ``shepherd audit`` (bash parity: runs
            the full pipeline with ``verbose=0``, not a usage screen).

    Raises:
        typer.Exit: See :func:`_insert_dispatch` (the ``insert`` path) or
            :func:`_parse_pipeline_args`/:func:`_audit_pipeline` (every
            other path) for the full matrix of exit codes.
    """
    argv = list(args) if args else []
    if argv and argv[0] == "insert":
        _insert_dispatch(argv[1:])
        return
    verbose = _parse_pipeline_args(argv)
    _audit_pipeline(verbose)


__all__ = ["app"]
