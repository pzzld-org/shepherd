"""``shepherd eval`` — quality-score a latent agent output against a rubric.

Native port of ``skills/context/scripts/cmd_eval.sh`` (v6.2.3): the
shepherd-side STATEFUL boundary for the eval harness. ``services/eval`` is
a pure, stateless judge (``(kind, input) -> verdict JSON``) — this command
resolves a subject from the registry (e.g. the reflection note for a
sprint), shells out to that service (which itself routes the judge call
through the local-Claude-Code ``services/llm`` contract — never a hosted
API, per this repo's own top-level doctrine), and records the verdict into
``eval_runs`` (migration ``0018_eval_runs.sql``) so ``shctx dash`` and
``shctx eval report``/``list`` can surface eval scores over time.

The latent/deterministic split this plugin teaches, applied to itself: the
per-dimension scores are the JUDGE MODEL's own output (latent — owned
entirely by ``services/eval``/``services/llm``, never re-judged here); the
subject resolution, the service invocation, the recorded row, and every
rendered format below are deterministic (this module's own job).

::

    eval run --kind=K [--sprint=B] [--input-file=F | --input=TXT | -] \\
             [--threshold=N] [--model=M] [--timeout=S] [--record] [--json|--md]
    eval report [--kind=K] [--sprint=B] [--json|--md]
    eval list   [--kind=K] [--limit=N] [--json|--md]
    eval help

Exit (run): 0 pass · 1 below threshold · 2 usage · 4 judge/parse error.
``report``/``list`` always exit 0 (bash parity — neither ever calls its own
``die`` at the top level; every branch either prints something and returns,
or falls through to the end of the function).

WHY ONE VARIADIC CALLBACK, NOT THREE ``@app.command()``s
==========================================================
``cmd_eval.sh`` is one ``case "$cmd" in run|report|list|help|...|*) ...
esac`` dispatch (``cmd="${1:-help}"`` — a bare ``shctx eval`` defaults to
``help``, NOT a usage error, and an unrecognized subcommand exits 2 with a
bash-specific message, NOT Click's own exit 2 "No such command"), and each
of ``run``/``report``/``list`` is itself a hand-rolled ``for a in "$@"; do
case "$a" in --flag=* ... esac; done`` token loop accepting ONLY the
``--flag=value`` shape (never a space-separated ``--flag value`` form —
unlike some sibling scripts, ``cmd_eval.sh`` has no bare-token positional
args at all besides the literal ``-`` stdin sentinel), with its own
``-h|--help`` arm printing the SAME global usage text from ANY position in
its own remaining tokens, and its own "unrecognized flag -> ``ERROR:
unknown arg: <token>``, exit 2" catch-all. None of that matches Typer/
Click's own subcommand-dispatch or option-parsing defaults. Exactly like
:mod:`shepherd_cli.commands.dups`/``search``/``sync`` (self-parsed
variadic token loops), this module registers ZERO ``@app.command()``s and
instead defines one ``@app.callback(invoke_without_command=True)`` that
captures every token after ``eval`` as a raw ``list[str]``
(``context_settings={"ignore_unknown_options": True, "help_option_names":
[]}``, so a token like ``--json`` or ``-h`` lands here as a literal string
instead of Click intercepting it) and dispatches on ``argv[0]`` exactly
like bash's ``case`` statement — see :func:`_dispatch`.

PROJECT-ID RESOLUTION — TWO DIFFERENT CONTRACTS, BOTH FROM ``project.json``
=============================================================================
Unlike :mod:`shepherd_cli.commands.mem`/``lock``'s documented deviation
(resolving the active project via ``SELECT id FROM projects LIMIT 1``
instead of the file), ``cmd_eval.sh`` calls ``_lib.sh``'s
``shctx_project_id()`` directly — which reads ``<workdir>/project.json``,
a FILE, not a table — exactly like
:mod:`shepherd_cli.commands.search`/``query``. This module mirrors that:
:func:`_tolerant_project_id`/:func:`_require_registry_project_id` both
resolve off ``project.json``, never the ``projects`` table. The two
functions differ only in what a MISSING/unreadable project registry means
for the caller, mirroring ``cmd_eval.sh``'s own two distinct call sites
verbatim:

* ``run``'s reflection-note pull and its ``--record`` write both call
  ``shctx_project_id()`` WRAPPED in ``|| die "registry not initialized —
  run 'shctx init'" 4`` — i.e. a missing/unreadable registry is FATAL
  (exit 4, not ``shctx_project_id``'s own bare exit 1), and — because
  bash's ``$(...)`` command substitution only captures STDOUT, never
  STDERR — ``shctx_project_id``'s own ``echo ... >&2`` fires unsuppressed
  BEFORE ``die``'s own message, so a real bash run prints BOTH lines to
  stderr. :func:`_require_registry_project_id` reproduces both lines and
  the exit-4 override.
* ``report``/``list`` instead call ``shctx_project_id() 2>/dev/null ||
  true`` — fully tolerant; a missing/unreadable registry silently resolves
  to an empty ``pid``, which their own callers treat as "no evals yet"
  (exit 0), never an error. :func:`_tolerant_project_id` reproduces this:
  it never raises, always returning ``""`` on any failure.

``_tolerant_project_id`` is duplicated (not imported) from
:mod:`shepherd_cli.commands.dups`'s identically-behaved ``_read_project_id``
— both modules are self-contained per this port's instructions.

SUBPROCESS ORCHESTRATION, NOT A REIMPLEMENTED JUDGE
======================================================
Per hard rule #9 (subprocess for anything that shells out) and exactly
like :mod:`shepherd_cli.commands.sprint`'s ``run_stage``, ``run`` shells
out to the REAL ``services/eval/eval.sh`` (via :func:`_eval_svc_path`,
mirroring ``cmd_eval.sh``'s own ``_eval_svc`` resolution order:
``SHEPHERD_EVAL_SVC`` env override > an existing
``$CLAUDE_PLUGIN_ROOT/services/eval/eval.sh`` > a skill-root-relative
fallback) as ``["bash", svc, "run", "--kind=...", "--input-file=...",
"--json", ...]``, exactly reproducing ``cmd_eval.sh``'s own
``svc_args``/``bash "$svc" "${svc_args[@]}"`` construction. Only the
subprocess's STDOUT is captured (mirroring bash's ``verdict="$(bash "$svc"
...)"``, which only captures stdout via command substitution); stderr is
left to flow straight through to this process's own stderr, matching
bash's un-redirected inheritance. Reimplementing the judge-prompt-build /
rubric-load / weighted-overall arithmetic here would risk silent
behavioral drift from the one true engine both the bash tooling and this
port depend on — the exact reasoning ``dups.py``'s module docstring gives
for shelling out to ``dups-core.py`` rather than reimplementing it.

``eval run --json``'s OWN stdout is therefore the service's raw captured
text, reprinted VERBATIM (bash: ``printf '%s\\n' "$verdict"``) — never
re-serialized through ``json.dumps`` — so this port's ``--json`` output is
byte-for-byte whatever ``jq``'s own pretty-printer inside
``services/eval/eval.sh`` produced, key order and all. The ``--md``/text
renderers instead work off the PARSED verdict (``json.loads``), since bash
itself re-derives those two formats from the same parsed fields via
``jq -r``/``jq -c`` rather than reusing the raw text.

``EvalRun``/``EvalLatest`` (:mod:`shepherd_cli.models_eval`) are genuinely
NEW mirror models — no existing ``models*.py`` module maps ``eval_runs``/
``v_eval_latest`` (grepped per hard rule #3's collision check; see that
module's own docstring for the full accounting, including why
:mod:`shepherd_cli.models_dash` explicitly declined to model either
object). The ONE piece of raw SQL this module still needs despite that —
:func:`_has_eval_table`'s ``sqlite_master`` existence probe — is exactly
the shape hard rule #8 calls out (``sqlite_master`` introspection), mirroring
:mod:`shepherd_cli.commands.sprint`'s ``_lane_closures_table_exists`` and
:mod:`shepherd_cli.commands.dash`'s identical ``eval_runs`` probe.

Timestamps: ``eval_runs.created_at`` is epoch **SECONDS** (``_lib.sh``'s
``shctx_now`` == ``date +%s`` — the same unit
:class:`shepherd_cli.models_mem.MemEntry` uses).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import NoReturn

import typer
from tortoise import Tortoise

from shepherd_cli import db
from shepherd_cli.models_eval import EvalLatest, EvalRun
from shepherd_cli.models_mem import MemEntry
from shepherd_cli.resolution import find_bash_shctx, resolve_repo_root, resolve_workdir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Bash parity requires full control over -h/--help's own output (the
    # single global usage() heredoc, printed verbatim from any dispatch
    # point) instead of Click's autogenerated help text — see the module
    # docstring's "WHY ONE VARIADIC CALLBACK" section.
    context_settings={"ignore_unknown_options": True, "help_option_names": []},
    help="Quality-score a latent agent output against a rubric (bash: cmd_eval.sh).",
)

#: Verbatim bash-parity usage text — ``cmd_eval.sh``'s ``usage()`` heredoc
#: (lines 26-41), printed on a bare invocation / ``help`` / ``-h`` /
#: ``--help`` (exit 0, from ANY dispatch point — the top-level callback and
#: every subcommand's own ``-h``/``--help`` token all print this SAME
#: text). No trailing newline: every caller prints it via ``typer.echo``,
#: which appends exactly one — matching bash's ``cat <<'EOF' ... EOF``,
#: whose own output already ends with exactly one trailing newline.
_USAGE = (
    "shctx eval — quality-score a latent agent output against a rubric.\n"
    "\n"
    "  eval run --kind=K [--sprint=B] [--input-file=F | --input=TXT | -] \\\n"
    "           [--threshold=N] [--model=M] [--timeout=S] [--record] [--json|--md]\n"
    "      Score one item. With --kind=reflection --sprint=B (and no explicit input),\n"
    "      the stored reflection note for that sprint is pulled from the registry.\n"
    "      --record writes the verdict to eval_runs (surfaced by `shctx dash`).\n"
    "  eval report [--kind=K] [--sprint=B] [--json|--md]   Latest recorded verdicts.\n"
    "  eval list   [--kind=K] [--limit=N] [--json|--md]     Recent eval_runs.\n"
    "  eval help\n"
    "\n"
    "Judge model: --model > [eval].judge_model > opus. Threshold: --threshold > rubric.\n"
    "Exit (run): 0 pass · 1 below threshold · 2 usage · 4 judge/parse error."
)

#: The middle-dot bash substitutes for a NULL ``subject_ref``/``model`` in
#: the ``md``/text renderers (``COALESCE(subject_ref,'·')`` /
#: ``COALESCE(model,'·')``). Matches
#: :mod:`shepherd_cli.commands.dash`'s identically-named constant.
_MIDDLE_DOT = "·"


def _die(message: str, code: int = 1) -> NoReturn:
    """Bash parity with ``cmd_eval.sh``'s ``die()``: ``echo "shctx eval: $1" >&2; exit "${2:-1}"``.

    Args:
        message: The message text (bash prefixes it with ``"shctx eval:
            "`` — reproduced here verbatim).
        code: The process exit code (bash default: 1).

    Raises:
        typer.Exit: Always, with the given code.
    """
    typer.echo(f"shctx eval: {message}", err=True)
    raise typer.Exit(code=code)


# --------------------------------------------------------------------------
# cfg_get — bash-parity section-agnostic line scan (NOT tomllib), duplicated
# from shepherd_cli.commands.config/dups's identically-named helpers (see
# config.py's module docstring deviation note #2 for the full rationale:
# `[eval].judge_model` is read via the bare-key, section-agnostic `cfg_get`
# path — same convention as `[dups]`'s prefixed keys — not the section-aware
# `cfg_section_get` `[models]` uses).
# --------------------------------------------------------------------------
_CFG_VALUE_PREFIX_RE = re.compile(r"^[^=]*=\s*")
_CFG_TRAILING_COMMENT_RE = re.compile(r"\s+#.*$")


def _config_search_paths(repo_root: str) -> tuple[str, str, str]:
    """The three config file paths ``cfg_get`` checks, in precedence order.

    Args:
        repo_root: The resolved repository root.

    Returns:
        ``(local_override, project, xdg_global)`` — the exact three
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
    """Resolve one config key via bash-parity ``cfg_get`` semantics.

    Args:
        key: The config key to resolve, e.g. ``"eval_judge_model"``.
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
# project_id resolution — see the module docstring's dedicated section.
# --------------------------------------------------------------------------
def _tolerant_project_id() -> str:
    """Resolve the active project id from ``project.json``, never raising.

    Bash parity with ``cmd_eval.sh``'s ``report``/``list`` call sites:
    ``pid="$(shctx_project_id 2>/dev/null || true)"``. Duplicated
    (not imported) from :mod:`shepherd_cli.commands.dups`'s identically-
    behaved ``_read_project_id`` — both modules are self-contained per
    this port's instructions.

    Returns:
        The project id string; the literal string ``"null"`` when
        ``project.json``'s ``"id"`` key is present-but-JSON-null (``jq
        -r '.id'``'s own raw-output rendering of JSON ``null``); or
        ``""`` on any failure (missing file, unreadable, invalid JSON,
        non-object top level, or a missing ``"id"`` key with no explicit
        null).
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


def _require_registry_project_id() -> str:
    """Resolve the active project id, or exit 4 (``run``'s strict gate).

    Bash parity with ``cmd_eval.sh``'s TWO ``run``-path call sites (the
    reflection-note pull, and the ``--record`` write), both wrapped as
    ``pid="$(shctx_project_id)" || die "registry not initialized — run
    'shctx init'" 4``. See the module docstring's "PROJECT-ID RESOLUTION"
    section for why this prints BOTH of bash's stderr lines (
    ``shctx_project_id``'s own, unconditionally, since bash's ``$(...)``
    only captures stdout — followed by ``cmd_eval.sh``'s own ``die``
    line) rather than just one.

    Returns:
        The resolved project id (via :func:`_tolerant_project_id`).

    Raises:
        typer.Exit: Code 4, after printing both stderr lines, if
            :func:`_tolerant_project_id` resolves to an empty string.
    """
    pid = _tolerant_project_id()
    if pid:
        return pid
    path = os.path.join(resolve_workdir(), "project.json")
    typer.echo(f"ERROR: {path} missing — run 'shctx init' first", err=True)
    _die("registry not initialized — run 'shctx init'", 4)


# --------------------------------------------------------------------------
# eval service location — bash parity with cmd_eval.sh's _eval_svc().
# --------------------------------------------------------------------------
def _eval_svc_path() -> str:
    """Locate ``services/eval/eval.sh``, bash-parity with ``_eval_svc()``.

    Precedence, mirroring ``cmd_eval.sh`` exactly:

    1. ``SHEPHERD_EVAL_SVC`` env override (tests, custom installs) — used
       as-is, existence NOT checked here (the caller checks).
    2. ``$CLAUDE_PLUGIN_ROOT/services/eval/eval.sh``, if it exists.
    3. A skill-root-relative fallback: bash computes this as ``(cd
       "$(shctx_skill_root)/../.." && pwd)/services/eval/eval.sh`` — i.e.
       two directories up from the skill root
       (``<repo>/skills/context``), which is the repo root, plus
       ``services/eval/eval.sh``. This module has no ``BASH_SOURCE``
       equivalent of its own (unlike ``_lib.sh``'s final ``shctx_skill_
       root`` fallback, which climbs from the sourcing script's own
       on-disk location), so it locates the skill root via
       :func:`shepherd_cli.resolution.find_bash_shctx` instead (same
       directory as the bash ``shctx`` dispatcher —
       ``skills/context/scripts`` — one level below the skill root
       itself), falling back to
       :func:`shepherd_cli.resolution.resolve_repo_root` directly if even
       that cannot be found (a scenario bash itself never hits, since
       ``BASH_SOURCE`` always resolves to *some* path).

    Returns:
        The resolved candidate path (existence is the caller's concern,
        exactly like bash's own ``[[ -f "$svc" ]] || die ...`` check
        happening one step later in ``_cmd_run``).
    """
    override = os.environ.get("SHEPHERD_EVAL_SVC", "")
    if override:
        return override

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        candidate = os.path.join(plugin_root, "services", "eval", "eval.sh")
        if os.path.isfile(candidate):
            return candidate

    shctx_path = find_bash_shctx()
    if shctx_path is not None:
        # shctx_path == .../skills/context/scripts/shctx
        scripts_dir = os.path.dirname(shctx_path)  # .../skills/context/scripts
        skill_root = os.path.dirname(scripts_dir)  # .../skills/context
        repo_root_guess = os.path.dirname(os.path.dirname(skill_root))  # .../
        return os.path.join(repo_root_guess, "services", "eval", "eval.sh")

    return os.path.join(resolve_repo_root(), "services", "eval", "eval.sh")


# --------------------------------------------------------------------------
# eval_runs existence probe — raw sqlite_master introspection (hard rule #8),
# mirroring shepherd_cli.commands.sprint._lane_closures_table_exists and
# shepherd_cli.commands.dash's identical eval_runs probe.
# --------------------------------------------------------------------------
async def _has_eval_table() -> bool:
    """Check whether ``eval_runs`` exists in the live DB.

    Bash parity: ``[[ -n "$(shctx_sql "SELECT 1 FROM sqlite_master WHERE
    type='table' AND name='eval_runs' LIMIT 1;" 2>/dev/null || true)" ]]``.

    Returns:
        True if ``eval_runs`` exists as a table in the current
        connection's database.
    """
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict(
        "SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='eval_runs';"
    )
    return len(rows) > 0


# --------------------------------------------------------------------------
# misc small helpers.
# --------------------------------------------------------------------------
def _uuid7() -> str:
    """Generate a UUIDv7 (RFC 9562) id for a new ``eval_runs`` row.

    Bash generates this via ``_lib.sh``'s ``shctx_uuid7``. This is an
    independent, equally-valid UUIDv7 generator over the stdlib
    ``time``/``os.urandom`` — NOT byte-for-byte identical to bash's
    construction, but every id it produces is a spec-compliant,
    monotonically-sortable-by-creation-time UUIDv7, the only property
    either tool depends on. Duplicated verbatim from
    :mod:`shepherd_cli.commands.lock`'s identically-named helper (small
    intentional duplication — self-contained modules per the port
    contract).

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


def _age(then: int | None) -> str:
    """Render an age string, bash-parity with ``cmd_eval.sh``'s ``_age()``.

    Args:
        then: An epoch-seconds timestamp, or None/0 for "never".

    Returns:
        ``"-"`` for None/0; otherwise ``"<n>s"``/``"<n>m"``/``"<n>h"``/
        ``"<n>d"`` depending on elapsed time, exactly matching bash's
        threshold ladder (< 90s -> seconds, < 5400s -> minutes, < 172800s
        -> hours, else days). A negative delta (a future-dated ``then``)
        is clamped to 0, matching bash's ``(( d < 0 )) && d=0``.
    """
    if then is None or then == 0:
        return "-"
    now = int(time.time())
    d = now - then
    if d < 0:
        d = 0
    if d < 90:
        return f"{d}s"
    if d < 5400:
        return f"{d // 60}m"
    if d < 172800:
        return f"{d // 3600}h"
    return f"{d // 86400}d"


def _invoke_eval_service(
    svc_path: str, kind: str, item: str, threshold: str, model: str, timeout: str
) -> tuple[int, str]:
    """Write ``item`` to a temp file and run ``services/eval/eval.sh run ... --json``.

    Bash parity with ``cmd_eval.sh``'s tmp-file + ``svc_args``
    construction: ``printf '%s' "$item" > "$tmp"`` (no trailing newline),
    then ``bash "$svc" run --kind=K --input-file=TMP --json [--threshold=]
    [--model=] [--timeout=]``. Only the subprocess's STDOUT is captured
    (mirroring bash's own ``verdict="$(bash "$svc" ...)"``, which only
    ever captures stdout via command substitution) — stderr is left to
    flow straight through to this process's own stderr, matching bash's
    un-redirected inheritance.

    Args:
        svc_path: The resolved ``eval.sh`` path (existence already
            checked by the caller).
        kind: The rubric kind, forwarded as ``--kind``.
        item: The exact text to evaluate (already resolved by the
            caller).
        threshold: The raw ``--threshold`` string, or ``""`` to omit the
            flag entirely (letting the service fall back to the rubric's
            own default).
        model: The raw ``--model`` string, or ``""`` to omit the flag.
        timeout: The raw ``--timeout`` string, or ``""`` to omit the
            flag.

    Returns:
        ``(returncode, verdict_text)`` — ``verdict_text`` is the
        subprocess's stdout with every trailing newline stripped
        (mirroring bash's own command-substitution trailing-newline
        stripping), possibly empty.
    """
    fd, tmp_path = tempfile.mkstemp(prefix="shctxeval")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(item)

        argv = ["bash", svc_path, "run", f"--kind={kind}", f"--input-file={tmp_path}", "--json"]
        if threshold:
            argv.append(f"--threshold={threshold}")
        if model:
            argv.append(f"--model={model}")
        if timeout:
            argv.append(f"--timeout={timeout}")

        result = subprocess.run(argv, stdout=subprocess.PIPE, text=True, check=False)
        return result.returncode, result.stdout.rstrip("\n")
    finally:
        os.remove(tmp_path)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
async def _cmd_run_async(tokens: list[str]) -> None:
    """``shctx eval run`` — score one item, optionally recording the verdict.

    Bash parity with ``cmd_eval.sh``'s ``_cmd_run``. See the module
    docstring for the subprocess-orchestration and project-id-resolution
    contracts this reproduces.

    Args:
        tokens: Every token given after ``eval run``, in order.

    Raises:
        typer.Exit: Code 0 (usage printed) on ``-h``/``--help``. Code 2 on
            any usage/validation error (unknown arg, missing ``--kind``,
            missing ``--input-file``, empty resolved input, no input
            source given). Code 4 if the eval service cannot be located,
            the service call itself fails (exit >= 2, forwarded verbatim),
            the service prints no verdict, ``--record`` is given but
            ``eval_runs`` does not exist, or the active project cannot be
            resolved. Code 0 if the verdict passed; code 1 if it did not
            (bash: ``[[ "$passed_int" == 1 ]] && exit 0 || exit 1``).
    """
    kind = ""
    sprint = ""
    inputfile = ""
    input_value = ""
    use_stdin = False
    threshold = ""
    model = ""
    timeout = ""
    record = False
    fmt = "text"

    for a in tokens:
        if a.startswith("--kind="):
            kind = a[len("--kind=") :]
        elif a.startswith("--sprint="):
            sprint = a[len("--sprint=") :]
        elif a.startswith("--input-file="):
            inputfile = a[len("--input-file=") :]
        elif a.startswith("--input="):
            input_value = a[len("--input=") :]
        elif a.startswith("--threshold="):
            threshold = a[len("--threshold=") :]
        elif a.startswith("--model="):
            model = a[len("--model=") :]
        elif a.startswith("--timeout="):
            timeout = a[len("--timeout=") :]
        elif a == "--record":
            record = True
        elif a == "--json":
            fmt = "json"
        elif a == "--md":
            fmt = "md"
        elif a == "--text":
            fmt = "text"
        elif a == "-":
            use_stdin = True
        elif a in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            _die(f"unknown arg: {a}", 2)

    if not kind:
        _die("run needs --kind=<rubric>", 2)

    svc = _eval_svc_path()
    if not os.path.isfile(svc):
        _die(f"eval service not found at {svc} (set SHEPHERD_EVAL_SVC)", 4)

    if not model:
        model = _cfg_get("eval_judge_model", resolve_repo_root())

    async with db.lifespan():
        item = ""
        subject_ref = ""
        if inputfile:
            if not os.path.isfile(inputfile):
                _die(f"--input-file not found: {inputfile}", 2)
            with open(inputfile, encoding="utf-8") as fh:
                item = fh.read().rstrip("\n")
            subject_ref = os.path.basename(inputfile)
        elif input_value:
            item = input_value
            subject_ref = sprint if sprint else "inline"
        elif use_stdin:
            item = sys.stdin.read().rstrip("\n")
            subject_ref = sprint if sprint else "stdin"
        elif sprint and kind == "reflection":
            pid = _require_registry_project_id()
            entry = await MemEntry.filter(
                project_id=pid, kind="prior", title=f"prior: reflection ({sprint})"
            ).first()
            body = entry.body if entry is not None else ""
            if not body:
                _die(
                    f"no reflection stored for '{sprint}' "
                    f"(run: shctx adapt reflect --sprint={sprint} --note=…)",
                    2,
                )
            # body shape: "[reflection] sprint <branch>: <note>" — keep just the note.
            item = re.sub(r"^\[reflection\] sprint [^:]*: ", "", body, count=1)
            subject_ref = sprint
        else:
            _die("no input — pass --input-file/--input/-, or (--kind=reflection --sprint=B)", 2)

        if not item.strip():
            _die("nothing to evaluate (empty input)", 2)

        rc, verdict_text = _invoke_eval_service(svc, kind, item, threshold, model, timeout)
        if rc >= 2:
            _die(f"eval service error (exit {rc})", rc)
        if not verdict_text:
            _die("eval service returned no verdict", 4)

        verdict = json.loads(verdict_text)
        overall = verdict["overall"]
        passed_int = 1 if verdict["passed"] else 0
        thr = verdict["threshold"]
        usedmodel = verdict["model"]
        scores = verdict["scores"]
        rationale = verdict["rationale"]

        if record:
            if not await _has_eval_table():
                _die("eval_runs table missing — run 'shctx migrate'", 4)
            pid = _require_registry_project_id()
            scores_compact = json.dumps(scores, separators=(",", ":"))
            await EvalRun.create(
                id=_uuid7(),
                project_id=pid,
                kind=kind,
                subject_ref=subject_ref,
                score=overall,
                threshold=thr,
                passed=passed_int,
                model=usedmodel,
                scores_json=scores_compact,
                rationale=rationale,
                created_at=int(time.time()),
            )

    verd = "PASS" if passed_int == 1 else "FAIL"
    if fmt == "json":
        typer.echo(verdict_text)
    elif fmt == "md":
        suffix = " · recorded" if record else ""
        typer.echo(
            f"**EVAL `{kind}`** ({subject_ref}) — **{overall}/100** (threshold {thr}) — "
            f"{verd} · model `{usedmodel}`{suffix}"
        )
        typer.echo("")
        for score_key, score_value in scores.items():
            typer.echo(f"- {score_key}: {score_value}")
        typer.echo("")
        typer.echo(f"_{rationale}_")
    else:
        suffix = "  [recorded]" if record else ""
        typer.echo(
            f"EVAL {kind} ({subject_ref}) — score={overall}/100 threshold={thr} "
            f"{verd}  model={usedmodel}{suffix}"
        )
        scores_compact = json.dumps(scores, separators=(",", ":"))
        typer.echo(f"  scores: {scores_compact}")
        typer.echo(f"  rationale: {rationale}")

    raise typer.Exit(code=0 if passed_int == 1 else 1)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
async def _cmd_report_async(tokens: list[str]) -> None:
    """``shctx eval report`` — latest recorded verdict per subject.

    Bash parity with ``cmd_eval.sh``'s ``_cmd_report``. Always exits 0.

    Args:
        tokens: Every token given after ``eval report``, in order.

    Raises:
        typer.Exit: Code 0 (usage printed) on ``-h``/``--help``. Code 2 on
            an unrecognized token.
    """
    kind = ""
    sprint = ""
    fmt = "text"

    for a in tokens:
        if a.startswith("--kind="):
            kind = a[len("--kind=") :]
        elif a.startswith("--sprint="):
            sprint = a[len("--sprint=") :]
        elif a == "--json":
            fmt = "json"
        elif a == "--md":
            fmt = "md"
        elif a in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            _die(f"unknown arg: {a}", 2)

    async with db.lifespan():
        if not await _has_eval_table():
            typer.echo("[]" if fmt == "json" else "no evals yet (run: shctx eval run … --record)")
            return

        pid = _tolerant_project_id()
        if not pid:
            typer.echo("[]" if fmt == "json" else "no evals yet")
            return

        qs = EvalLatest.filter(project_id=pid)
        if kind:
            qs = qs.filter(kind=kind)
        if sprint:
            qs = qs.filter(subject_ref=sprint)
        rows = await qs.order_by("-created_at", "-id").all()

        if fmt == "json":
            payload = [
                {
                    "kind": row.kind,
                    "subject_ref": row.subject_ref,
                    "score": row.score,
                    "threshold": row.threshold,
                    "passed": row.passed == 1,
                    "model": row.model,
                    "rationale": row.rationale,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
            typer.echo(json.dumps(payload))
            return

        if fmt == "md":
            if not rows:
                typer.echo("_no evals recorded yet._")
                return
            typer.echo("### Eval scores (latest per subject)")
            typer.echo("")
            typer.echo("| kind | subject | score | thr | verdict | model |")
            typer.echo("|------|---------|-------|-----|---------|-------|")
            for row in rows:
                subject = row.subject_ref if row.subject_ref is not None else _MIDDLE_DOT
                model_disp = row.model if row.model is not None else _MIDDLE_DOT
                verdict = "PASS" if row.passed == 1 else "FAIL"
                typer.echo(f"| {row.kind} | {subject} | {row.score} | {row.threshold} | {verdict} | {model_disp} |")
            return

        if not rows:
            typer.echo("no evals recorded yet (run: shctx eval run … --record)")
            return
        typer.echo(f"{'KIND':<12} {'SUBJECT':<16} {'SCORE':>5} {'THR':>4} {'VERD':<5} {'MODEL':<8} AGE")
        for row in rows:
            subject = row.subject_ref if row.subject_ref is not None else _MIDDLE_DOT
            model_disp = row.model if row.model is not None else _MIDDLE_DOT
            verdict = "PASS" if row.passed == 1 else "FAIL"
            typer.echo(
                f"{row.kind:<12} {subject:<16} {row.score:>4}% {row.threshold:>4} "
                f"{verdict:<5} {model_disp:<8} {_age(row.created_at)}"
            )


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------
async def _cmd_list_async(tokens: list[str]) -> None:
    """``shctx eval list`` — recent ``eval_runs`` rows.

    Bash parity with ``cmd_eval.sh``'s ``_cmd_list``. Always exits 0. Note
    the bash quirk this reproduces faithfully: unlike ``report``, ``list``
    has NO dedicated markdown table renderer — its own ``if [[ "$fmt" ==
    json ]] ... else ...`` has only two branches, so ``--md`` silently
    falls into the SAME plain-text row rendering as the default (no flag)
    case.

    Args:
        tokens: Every token given after ``eval list``, in order.

    Raises:
        typer.Exit: Code 0 (usage printed) on ``-h``/``--help``. Code 2 on
            an unrecognized token, or a non-integer ``--limit``.
    """
    kind = ""
    limit_raw = "10"
    fmt = "text"

    for a in tokens:
        if a.startswith("--kind="):
            kind = a[len("--kind=") :]
        elif a.startswith("--limit="):
            limit_raw = a[len("--limit=") :]
        elif a == "--json":
            fmt = "json"
        elif a == "--md":
            fmt = "md"
        elif a in ("-h", "--help"):
            typer.echo(_USAGE)
            raise typer.Exit(code=0)
        else:
            _die(f"unknown arg: {a}", 2)

    if not re.fullmatch(r"[0-9]+", limit_raw):
        _die("--limit must be an integer", 2)
    limit = int(limit_raw)

    async with db.lifespan():
        if not await _has_eval_table():
            typer.echo("[]" if fmt == "json" else "no evals yet")
            return

        pid = _tolerant_project_id()
        if not pid:
            typer.echo("[]" if fmt == "json" else "no evals yet")
            return

        qs = EvalRun.filter(project_id=pid)
        if kind:
            qs = qs.filter(kind=kind)
        rows = await qs.order_by("-created_at", "-id").limit(limit).all()

        if fmt == "json":
            payload = [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "subject_ref": row.subject_ref,
                    "score": row.score,
                    "threshold": row.threshold,
                    "passed": row.passed == 1,
                    "model": row.model,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
            typer.echo(json.dumps(payload))
            return

        if not rows:
            typer.echo("no evals recorded yet")
            return
        for row in rows:
            subject = row.subject_ref if row.subject_ref is not None else _MIDDLE_DOT
            score_thr = f"{row.score}/{row.threshold}"
            verdict = "PASS" if row.passed == 1 else "FAIL"
            typer.echo(f"{row.kind:<12} {subject:<16} {score_thr:<8} {verdict:<5} {_age(row.created_at)} ago")


# --------------------------------------------------------------------------
# Top-level dispatcher + Typer wiring.
# --------------------------------------------------------------------------
def _dispatch(argv: list[str]) -> None:
    """Dispatch on ``argv[0]``, bash-parity with ``cmd_eval.sh``'s top-level ``case``.

    Args:
        argv: The raw remaining command-line tokens after ``eval``, e.g.
            ``["run", "--kind=reflection", "--sprint=b1"]`` or ``[]``.

    Raises:
        typer.Exit: Whatever the dispatched subcommand raises (every
            subcommand handler ends by raising ``typer.Exit`` or
            returning normally, which Typer treats as exit 0). Code 2,
            with a bash-parity stderr message, on an unrecognized
            subcommand name.
    """
    sub = argv[0] if argv else "help"
    rest = argv[1:]

    if sub == "run":
        asyncio.run(_cmd_run_async(rest))
        return
    if sub == "report":
        asyncio.run(_cmd_report_async(rest))
        return
    if sub == "list":
        asyncio.run(_cmd_list_async(rest))
        return
    if sub in ("help", "-h", "--help"):
        typer.echo(_USAGE)
        return

    _die(f"unknown subcommand: {sub} (try: run | report | list | help)", 2)


@app.callback(invoke_without_command=True)
def eval_cmd(
    args: list[str] = typer.Argument(
        None,
        metavar="<run|report|list|help> [args]",
        help=(
            "Subcommand + args: 'run --kind=K [...]' | 'report [--kind=K] [--sprint=B] [...]' "
            "| 'list [--kind=K] [--limit=N] [...]'. Defaults to help."
        ),
    ),
) -> None:
    """Quality-score a latent agent output against a rubric — native port of ``shctx eval``.

    See the module docstring for why this is ONE variadic callback rather
    than three ``@app.command()``s: bash's own hand-rolled per-subcommand
    token loops (``--flag=value`` only, no space-separated form),
    default-to-``help``, and exit-2-on-unknown-subcommand contracts don't
    match Typer/Click's own subcommand-dispatch defaults.

    Args:
        args: Every token after ``eval`` on the command line, in order,
            with NOTHING pre-parsed as flags/options by Click (see this
            app's ``context_settings={"ignore_unknown_options": True,
            "help_option_names": []}``). ``None``/empty means a bare
            ``shepherd eval`` — dispatched as the ``help`` arm, per
            bash's ``cmd="${1:-help}"``.
    """
    _dispatch(list(args or []))


__all__ = ["app"]
