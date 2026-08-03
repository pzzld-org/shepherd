"""``shepherd inject`` — role-tailored ``[DB-CONTEXT]`` block Typer sub-app.

Native port of ``skills/context/scripts/cmd_inject.sh`` (v5.0.4): emits a
token-budget-aware ``[DB-CONTEXT] ... [/DB-CONTEXT]`` brief block
tailored per role — the engineer sees the full context surface, the
coder a file-scope-filtered canonical-types subset, the auditor
cross-cutting state only, the planter the seed-author surface. ``--full``
removes the per-role line cap for any role.

Where bash shells out to ``cmd_query.sh`` and ``cmd_adapt.sh`` as child
processes, this module invokes the ported sibling Typer apps
(:mod:`shepherd_cli.commands.query`, :mod:`shepherd_cli.commands.adapt`)
IN-PROCESS via :class:`typer.testing.CliRunner` — public Typer API that
reproduces exactly what bash's command substitution did: run the
command, capture its stdout (stderr discarded, matching every call
site's ``2>/dev/null``), observe its exit code. Each sub-invocation
opens and closes its own DB lifespan sequentially, just as each bash
child process did. No subprocess is ever spawned for a sibling command.

Single-callback app with ONE variadic argument (the
:mod:`shepherd_cli.commands.query` shape, for the same reason its
module-level ``context_settings`` comment documents): the role is a bare
positional and the flags follow it, so a callback with separate Typer
params would let Click's Group machinery misread the first token after
``role`` as a subcommand name. Manual parsing also preserves bash's
exact flag semantics — only ``--scope=<glob>``/``--limit=N``/``--full``
are recognized, and every OTHER token is silently ignored (the bash
``for arg ... case`` loop has no ``*)`` error arm).

Deliberate, documented deviations from a byte-for-byte bash port:

1. **Section order (issue #243 — cache-head discipline).** Bash ordered
   the engineer body ``Open issues -> Drift risk -> Canonical types``
   and the planter body ``Open issues -> Drift risk``, putting the most
   volatile content FIRST — the opposite of the cache-tail discipline
   its own priors comment teaches. This port deliberately reorders each
   role's body most-stable-first: engineer ``Canonical types -> Drift
   risk -> Open issues``, planter ``Drift risk -> Open issues``. The
   tail keeps the doctrine exactly: the dispatch recommendation
   (semi-stable, changes only at close) precedes the lesson priors, and
   priors — the most variable content — are appended LAST. (Bash
   appended ``recommend`` after ``priors``; swapping those two is part
   of the same #243 reordering.) Every section's header text, fallback
   text, cap, and omit-if-empty contract is unchanged; only the order
   moved. Auditor (issues -> PRs, both volatile) and coder (one
   section) are unchanged.
2. **``--limit`` validation**: a non-numeric ``--limit`` makes bash die
   on a shell arithmetic error (nonzero exit, shell's own stderr); this
   module prints ``ERROR: --limit must be numeric (got '<v>')`` and
   exits 1. A NEGATIVE limit behaves like GNU ``head -n -N`` in both
   (all but the last N lines — Python's ``lines[:N]`` coincides
   exactly).
3. **``--scope`` regex dialect**: bash filters through ``grep -E``
   (POSIX ERE); this module uses Python :mod:`re` — identical for the
   path-fragment patterns the conductor passes (e.g. ``crates/store``).
   An INVALID pattern matches bash's observable behavior (grep exits 2,
   swallowed by ``|| true`` -> empty filter output, error text on
   stderr): a note goes to stderr and the filter yields nothing.

Run-scoped artifact note (``<workdir>/runs/{run}/`` migration): this
command reads/writes ONLY stdout (its DB access happens inside the
sibling apps it invokes) — it has no ``<workdir>/graph/`` or other file
state, so the runs/{run} compat shim does not apply here.
"""

from __future__ import annotations

import re
import sys

import typer
from typer.testing import CliRunner

from shepherd_cli.commands import adapt as adapt_cmd
from shepherd_cli.commands import query as query_cmd

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    # Same shape (and reason) as shepherd_cli.commands.query: one variadic
    # argument consumes every token so Click's Group machinery never
    # misreads a post-role flag as a subcommand name, and unknown tokens
    # flow to our bash-parity parser instead of a Click exit-2 error.
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Emit the role-tailored [DB-CONTEXT] brief block.",
)

#: Verbatim bash-parity usage/error text — ``cmd_inject.sh``'s
#: missing-role guard.
_USAGE = "ERROR: usage: shctx inject <engineer|coder|auditor|planter> [--scope=<glob>] [--limit=N] [--full]"

#: Default per-role line caps — ``default_limit_for`` verbatim (the
#: fallthrough 50 is unreachable in practice: an unknown role errors out
#: below, after the limit is computed, exactly like bash).
_DEFAULT_LIMITS = {"engineer": 80, "coder": 30, "auditor": 25, "planter": 60}
_FALLBACK_LIMIT = 50

#: One shared in-process runner for every sibling-app invocation.
_RUNNER = CliRunner()


def _invoke(subapp: typer.Typer, args: list[str]) -> tuple[int, str]:
    """Invoke a sibling Typer app in-process, capturing stdout + exit code.

    The in-process equivalent of bash's ``$(bash cmd_X.sh ... 2>/dev/null)``:
    stdout is captured raw, stderr is captured-and-discarded, exceptions
    (including a ``typer.Exit``) resolve to an exit code instead of
    propagating.

    Args:
        subapp: The sibling module's ``app`` (``query_cmd.app`` /
            ``adapt_cmd.app``).
        args: The argv tokens for that app.

    Returns:
        ``(exit_code, raw_stdout)`` — stdout NOT yet
    trailing-newline-stripped (callers apply :func:`_strip` at the same
    point bash's ``$( )`` capture would).
    """
    result = _RUNNER.invoke(subapp, args)
    return result.exit_code, result.stdout


def _strip(text: str) -> str:
    """Strip trailing newlines only, exactly like a bash ``$( )`` capture.

    Args:
        text: Raw captured stdout.

    Returns:
        ``text`` with every trailing ``\\n`` removed (interior blank
        lines untouched).
    """
    return text.rstrip("\n")


def _cap_md(text: str, limit: int) -> str:
    """Keep the first ``limit`` lines (``cap_md``: ``head -n``; 0 = no cap).

    Args:
        text: The raw upstream stdout.
        limit: The line cap; 0 means unlimited; a negative value drops
            the last ``|limit|`` lines (GNU ``head -n -N`` semantics,
            which ``lines[:limit]`` reproduces exactly).

    Returns:
        The capped text (no trailing newline; the caller's
        :func:`_strip` would remove it anyway, exactly like bash's
        capture).
    """
    if limit == 0:
        return text
    return "\n".join(text.splitlines()[:limit])


def _filter_by_scope(text: str, scope_glob: str) -> str:
    """Keep only lines matching the scope pattern (``filter_by_scope``: ``grep -E``).

    Args:
        text: The raw canonical-types markdown.
        scope_glob: The ``--scope`` regex; empty means pass-through.

    Returns:
        The matching lines only (header/separator rows drop out too when
        they don't match, exactly like bash's line-grep). An invalid
        pattern yields ``""`` with a note on stderr (see module
        deviation #3).
    """
    if not scope_glob:
        return text
    try:
        pattern = re.compile(scope_glob)
    except re.error as exc:
        sys.stderr.write(f"shepherd inject: invalid --scope pattern: {exc}\n")
        return ""
    return "\n".join(line for line in text.splitlines() if pattern.search(line))


def _emit_block(body: str) -> None:
    """Print the ``[DB-CONTEXT]`` block (``emit_block`` verbatim).

    Args:
        body: The assembled, already-trailing-stripped body.
    """
    typer.echo("[DB-CONTEXT]")
    typer.echo(body)
    typer.echo("[/DB-CONTEXT]")


def _query_or(args: list[str], fallback: str, *, cap: int | None = None) -> str:
    """Run a query sub-invocation with an ``|| echo <fallback>`` tail.

    Mirrors ``$(bash cmd_query.sh <args> 2>/dev/null [| cap_md N] || echo
    <fallback>)`` byte-for-byte: the capture concatenates the (possibly
    capped) stdout with the fallback line ONLY when the invocation
    failed, then strips trailing newlines. An EMPTY successful result
    stays empty — the fallback fires on failure, not on emptiness.

    Args:
        args: The ``shepherd query`` argv tokens.
        fallback: The ``|| echo`` text.
        cap: Line cap applied before the fallback (None = no cap stage
            in the pipeline).

    Returns:
        The captured section text.
    """
    code, out = _invoke(query_cmd.app, args)
    if cap is not None:
        out = _cap_md(out, cap)
    if code != 0:
        out = (out + "\n" if out else "") + fallback + "\n"
    return _strip(out)


def _query_fatal(args: list[str], *, cap: int) -> str:
    """Run a query sub-invocation whose failure aborts inject (no ``||`` tail).

    Mirrors ``types=$(bash cmd_query.sh canonical-types --md 2>/dev/null
    | cap_md N)`` under ``set -eu -o pipefail``: a failing query fails
    the capture, which aborts the whole script with the query's exit
    code.

    Args:
        args: The ``shepherd query`` argv tokens.
        cap: Line cap applied to the successful output.

    Returns:
        The captured, capped, stripped text.

    Raises:
        typer.Exit: With the sub-invocation's exit code on failure.
    """
    code, out = _invoke(query_cmd.app, args)
    if code != 0:
        raise typer.Exit(code=code if code else 1)
    return _strip(_cap_md(out, cap))


def _adapt_tolerant(args: list[str]) -> str:
    """Run an adapt sub-invocation with an ``|| true`` tail.

    Mirrors ``$(bash cmd_adapt.sh <args> 2>/dev/null || true)``: failure
    is swallowed entirely; whatever stdout was produced (normally
    nothing) is still the capture.

    Args:
        args: The ``shepherd adapt`` argv tokens.

    Returns:
        The captured, stripped text (``""`` on a silent failure).
    """
    _, out = _invoke(adapt_cmd.app, args)
    return _strip(out)


def _append_tail(body: str, section: str) -> str:
    """Append one tail section (``body=$(printf '%s\\n\\n%s\\n' ...)`` verbatim).

    Args:
        body: The body so far.
        section: The non-empty section to append.

    Returns:
        ``body`` + blank line + ``section``.
    """
    return f"{body}\n\n{section}"


def _engineer_body(limit: int) -> str:
    """Assemble the engineer's full-surface body.

    Section order per module deviation #1 (issue #243): canonical types
    (stable) -> drift risk -> open issues (volatile), then the tail —
    dispatch recommendation, then lesson priors LAST (cache-tail
    discipline; both omitted when empty, and the recommendation is also
    omitted on its "no history yet" cold-start note, matching bash's
    ``case`` guard).

    Args:
        limit: The resolved line cap (0 = uncapped).

    Returns:
        The assembled body.

    Raises:
        typer.Exit: If the canonical-types query fails (bash parity: the
            uncushioned capture aborts the script).
    """
    issues = _query_or(["open-issues", "--md"], "_(no open issues / gh unavailable)_")
    drift = _query_or(["drift-risk", "--md"], "_(no drift-risk index)_")
    types = _query_fatal(["canonical-types", "--md"], cap=limit)
    body = _strip(
        f"## Canonical types (top {limit})\n{types}\n\n## Drift risk\n{drift}\n\n## Open issues\n{issues}\n"
    )
    # Dispatch recommendation (v6.0.8) — semi-stable, so it precedes the
    # priors tail (#243). Omitted on empty output AND on the cold-start
    # "no history yet" note (bash's `case "$rec" in *'no history yet'*|'')`).
    rec = _adapt_tolerant(["recommend", "--md"])
    if rec and "no history yet" not in rec:
        body = _append_tail(body, rec)
    # Lesson priors are the most variable content -> appended LAST
    # (cache-tail per brief-cache-discipline). Omitted entirely when the
    # store is empty (#95).
    priors = _adapt_tolerant(["priors", "--lessons", "--md"])
    if priors:
        body = _append_tail(body, priors)
    return body


def _coder_body(limit: int, scope_glob: str) -> str:
    """Assemble the coder's file-scope-filtered canonical-types body.

    Args:
        limit: The resolved line cap (0 = uncapped).
        scope_glob: The ``--scope`` regex over file paths (may be empty).

    Returns:
        The assembled body.

    Raises:
        typer.Exit: If the canonical-types query fails (bash parity).
    """
    code, out = _invoke(query_cmd.app, ["canonical-types", "--md"])
    if code != 0:
        raise typer.Exit(code=code if code else 1)
    types = _strip(_cap_md(_filter_by_scope(out, scope_glob), limit))
    if not types:
        types = "_(no matches; coder should read canonical-types.md catalog directly)_"
    if scope_glob:
        header = f"## Existing canonical types in scope `{scope_glob}` — REUSE; do not duplicate"
    else:
        header = f"## Existing canonical types (top {limit}) — REUSE; do not duplicate"
    return _strip(f"{header}\n{types}\n")


def _auditor_body(limit: int) -> str:
    """Assemble the auditor's cross-cutting body (issues + PRs, both capped).

    Order unchanged from bash (both sections are equally volatile — see
    module deviation #1).

    Args:
        limit: The resolved line cap (0 = uncapped).

    Returns:
        The assembled body.
    """
    issues = _query_or(["open-issues", "--md"], "_(none)_", cap=limit)
    prs = _query_or(["open-prs", "--md"], "_(none)_", cap=limit)
    return _strip(f"## Open issues (cross-cutting)\n{issues}\n\n## Open PRs\n{prs}\n")


def _planter_body(limit: int) -> str:
    """Assemble the planter's seed-author body.

    Section order per module deviation #1 (issue #243): drift risk
    (stabler) before open issues (volatile); lesson priors appended LAST
    when present (#95).

    Args:
        limit: The resolved line cap (0 = uncapped) — applied to the
            open-issues section only, like bash.

    Returns:
        The assembled body.
    """
    issues = _query_or(["open-issues", "--md"], "_(no open issues / gh unavailable)_", cap=limit)
    drift = _query_or(["drift-risk", "--md"], "_(no drift-risk index)_")
    body = _strip(f"## Drift risk\n{drift}\n\n## Open issues\n{issues}\n")
    priors = _adapt_tolerant(["priors", "--lessons", "--md"])
    if priors:
        body = _append_tail(body, priors)
    return body


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    raw: list[str] = typer.Argument(
        None,
        metavar="ROLE [--scope=<glob>] [--limit=N] [--full]",
        help="Role (engineer|coder|auditor|planter), then optional flags.",
    ),
) -> None:
    """Emit the role-tailored ``[DB-CONTEXT]`` block.

    Native port of ``shctx inject`` (``cmd_inject.sh``). The role is the
    first token; ``--scope=<glob>``, ``--limit=N``, and ``--full``
    follow in any order; every other token is silently ignored (bash
    parity — its flag loop has no error arm).

    Args:
        ctx: The Typer/Click context (required for
            ``invoke_without_command`` dispatch; unused otherwise).
        raw: ``[role, *flags]``, or None/empty when no arguments were
            given.

    Raises:
        typer.Exit: Code 1 with the bash usage message if no role is
            given; code 1 for a non-numeric ``--limit`` (module
            deviation #2) or an unknown role (bash's exact
            ``ERROR: unknown role: <role>``); the canonical-types
            query's own exit code when the engineer/coder body aborts
            (bash's uncushioned capture under ``set -e``).
    """
    del ctx  # required by invoke_without_command dispatch; unused otherwise.
    if not raw:
        typer.echo(_USAGE, err=True)
        raise typer.Exit(code=1)

    role, *flags = raw
    scope_glob = ""
    limit_raw = ""
    full = False
    for flag in flags:
        if flag.startswith("--scope="):
            scope_glob = flag[len("--scope="):]
        elif flag.startswith("--limit="):
            limit_raw = flag[len("--limit="):]
        elif flag == "--full":
            full = True
        # Anything else: silently ignored (bash parity).

    if limit_raw:
        try:
            limit = int(limit_raw)
        except ValueError:
            typer.echo(f"ERROR: --limit must be numeric (got '{limit_raw}')", err=True)
            raise typer.Exit(code=1) from None
    else:
        limit = _DEFAULT_LIMITS.get(role, _FALLBACK_LIMIT)
    if full:
        limit = 0  # 0 = no cap

    if role == "engineer":
        _emit_block(_engineer_body(limit))
    elif role == "coder":
        _emit_block(_coder_body(limit, scope_glob))
    elif role == "auditor":
        _emit_block(_auditor_body(limit))
    elif role == "planter":
        _emit_block(_planter_body(limit))
    else:
        typer.echo(f"ERROR: unknown role: {role}", err=True)
        raise typer.Exit(code=1)


__all__ = ["app"]
