"""``shepherd guard`` — the CLI surface over :mod:`shepherd_cli.predicates` (DF-76).

All three harness adapters (``packages/harness-claude``, ``packages/harness-codex``,
``packages/harness-pi``) relay guard-predicate evaluation to a ``shepherd guard
eval`` CLI surface — ``packages/harness-claude/src/guard.mjs``'s own header
names the exact stdin/stdout contract it expects. This module is a THIN
relay to :mod:`shepherd_cli.predicates`'s :class:`~shepherd_cli.predicates.Engine`
and carries no predicate logic of its own — every decision lives in that
module, which is the behavioral oracle a later Rust port replays against.

Four subcommands, matching the dispatch brief's own contract exactly:

- ``eval``: one JSON request on stdin, one JSON verdict on stdout, exit 0
  whenever a verdict (allow, deny, OR unresolved) was successfully reached.
  Exit != 0 means the ENGINE failed (malformed stdin, unreadable
  ``content/predicates/``) — never a verdict; nothing is printed to stdout
  in that case, so a caller parsing stdout can never mistake an engine
  crash for a silent allow.
- ``serve`` (S2-guard-serve): the long-lived shape ``packages/harness-pi/src/guard.ts``'s
  own header names as the thing that would let it collapse onto this engine
  instead of keeping a second, hand-rolled interpreter — ``eval``'s per-call
  cost was measured (W10 auditor, five runs) at 0.67–0.84s/call, worse than
  the coder's own 0.43–0.60s claim, and ``packages/harness-codex``'s guard
  now shells out to it on every single Write/Edit/Bash (a real regression,
  commit ``1a0cf20``). ``serve`` loads the engine ONCE, then answers one
  line-delimited JSON request per input line with exactly one JSON
  response line, through the SAME :meth:`~shepherd_cli.predicates.Engine.evaluate` /
  :meth:`~shepherd_cli.predicates.Verdict.to_json` path ``eval`` itself
  uses — the two commands can never diverge in what they decide, only in
  how many times they pay to load the corpus.
- ``test``: replays EVERY ``content/predicates/*.toml`` ``[[example]]``
  through the engine — the falsifiability harness. Exits non-zero on any
  mismatch, AND on zero examples loaded (DF-59: a conformance runner that
  reports a green ``0/0`` is worse than one that never ran).
- ``explain <predicate-id>``: prints one predicate's rules and examples,
  for an operator debugging a deny.

Four separate ``@app.command()``s (not one callback dispatching on a
positional subcommand string) for the same reason
:mod:`shepherd_cli.commands.lock`'s module docstring documents at length:
Click's ``Group`` machinery disables interspersed option parsing for a
callback-dispatched shape, so each verb's own options (``guard test
--content-dir``) would not parse correctly under it.
"""

from __future__ import annotations

import json
import sys

import typer

from shepherd_cli.predicates import PredicateError, load_engine

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Evaluate content/predicates/*.toml guard predicates (DF-76).",
)


def _load_engine_or_exit(content_dir: str | None):
    """Load the engine, or print the failure and exit 1 (never a verdict).

    Args:
        content_dir: ``--content-dir`` override, or None for the default
            ``$CLAUDE_PLUGIN_ROOT``-then-repo-walk-up resolution.

    Returns:
        The loaded :class:`~shepherd_cli.predicates.Engine`.

    Raises:
        typer.Exit: code 1, after printing the failure to stderr.
    """
    try:
        return load_engine(content_dir)
    except PredicateError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command(name="eval")
def run_eval(
    content_dir: str | None = typer.Option(None, "--content-dir", help="Override content/ root (testing only)."),
) -> None:
    """Evaluate one guard request read as JSON from stdin; print one JSON verdict.

    Args:
        content_dir: ``--content-dir`` override for the ``content/`` root.

    Raises:
        typer.Exit: code 1, printing to stderr and NEVER to stdout, when
            stdin is not valid JSON or the engine itself cannot be loaded
            — an engine failure, never a verdict.
    """
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"ERROR: malformed JSON on stdin: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    engine = _load_engine_or_exit(content_dir)
    verdict = engine.evaluate(payload)
    typer.echo(json.dumps(verdict.to_json()))


#: The first line ``serve`` ever prints, once the engine has finished loading
#: — a client waits for exactly this line (deterministic readiness, never a
#: guessed ``sleep``) before writing its first request. Distinguishable from
#: every :meth:`~shepherd_cli.predicates.Verdict.to_json` shape (none of
#: which carry a ``ready`` key) and from the malformed-line error shape
#: below (which carries ``error``, not ``ready``).
_READY_LINE: dict[str, object] = {"ready": True}


def _malformed_line_response(exc: Exception) -> dict[str, object]:
    """The one response shape ``eval`` never had to produce: a per-line parse/engine failure.

    ``eval`` exits non-zero on malformed stdin because it reads exactly one
    request and then the process is done — there is no "next request" for a
    non-zero exit to endanger. ``serve`` cannot do that: dying on one bad
    line would silently drop every request queued behind it and orphan the
    client's read loop mid-session. So a bad line gets its own JSON object,
    ``{"error": "..."}``, and the loop continues — never a
    ``{"decision": ...}`` shape (that would make a caller think an engine
    failure was a real verdict) and never silence (a caller blocked on
    ``readline()`` for a response that never comes).
    """
    return {"error": str(exc)}


@app.command(name="serve")
def run_serve(
    content_dir: str | None = typer.Option(None, "--content-dir", help="Override content/ root (testing only)."),
) -> None:
    """Serve guard verdicts over line-delimited JSON on stdio until stdin closes.

    Loads the engine exactly ONCE (predicates parse cost, ~12–16ms measured,
    is paid here rather than on every request), prints :data:`_READY_LINE` so
    a caller can wait deterministically instead of sleeping a guessed
    duration, then reads one JSON request per input line and writes exactly
    one JSON response line per request, in order — the SAME
    :meth:`~shepherd_cli.predicates.Engine.evaluate` /
    :meth:`~shepherd_cli.predicates.Verdict.to_json` call ``eval`` makes, so
    the two commands can never answer the same request differently.

    A line that fails to parse as JSON, or that the engine itself chokes on,
    answers with :func:`_malformed_line_response` and the loop keeps
    running — this process must survive a bad request, not die on it, and it
    must never let a later request see a verdict computed for an earlier
    (or no) line: each iteration builds its own ``payload``/``verdict`` from
    scratch, nothing is cached or reused across requests. The loop ends, and
    the process exits 0, the moment stdin reaches EOF — no orphan process
    left waiting on a pipe nobody will ever write to again.

    Args:
        content_dir: ``--content-dir`` override for the ``content/`` root.

    Raises:
        typer.Exit: code 1, printing to stderr, ONLY if the engine itself
            cannot be loaded at startup — the same fail-closed contract
            ``eval`` uses. Once serving begins, a bad request never raises
            out of this function; it becomes an ``{"error": ...}`` line.
    """
    engine = _load_engine_or_exit(content_dir)
    typer.echo(json.dumps(_READY_LINE))

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        try:
            payload = json.loads(line)
            verdict = engine.evaluate(payload)
        except Exception as exc:  # noqa: BLE001 -- process boundary: serve must outlive one bad line, see docstring
            typer.echo(json.dumps(_malformed_line_response(exc)))
            continue
        typer.echo(json.dumps(verdict.to_json()))


@app.command(name="test")
def run_test(
    content_dir: str | None = typer.Option(None, "--content-dir", help="Override content/ root (testing only)."),
) -> None:
    """Replay every ``content/predicates/*.toml`` ``[[example]]`` through the engine.

    Args:
        content_dir: ``--content-dir`` override for the ``content/`` root.

    Raises:
        typer.Exit: code 1 on any example mismatch, OR when zero examples
            were loaded at all (DF-59 -- an empty/missing predicates
            directory must never report a green suite).
    """
    engine = _load_engine_or_exit(content_dir)
    passed, total, failures = engine.run_conformance_suite()

    for failure in failures:
        typer.echo(failure, err=True)
    typer.echo(f"{passed}/{total} examples passed")

    if total == 0:
        typer.echo("ERROR: zero content/predicates/*.toml examples loaded -- refusing to report a green suite", err=True)
        raise typer.Exit(code=1)
    if passed != total:
        raise typer.Exit(code=1)


@app.command()
def explain(
    predicate_id: str = typer.Argument(..., metavar="PREDICATE-ID", help="e.g. write-boundary, git-custody."),
    content_dir: str | None = typer.Option(None, "--content-dir", help="Override content/ root (testing only)."),
) -> None:
    """Print one predicate's rules and examples.

    Args:
        predicate_id: the ``[predicate].id`` to explain, e.g. ``git-custody``.
        content_dir: ``--content-dir`` override for the ``content/`` root.

    Raises:
        typer.Exit: code 1 if no predicate with that id is loaded.
    """
    engine = _load_engine_or_exit(content_dir)
    doc = engine.predicates.get(predicate_id)
    if doc is None:
        known = ", ".join(sorted(engine.predicates)) or "(none loaded)"
        typer.echo(f"ERROR: no such predicate `{predicate_id}` -- known: {known}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"{doc.id} (v{doc.version}) -- {doc.description}")
    typer.echo("")
    typer.echo("Rules:")
    for rule in doc.rules:
        typer.echo(f"  [{rule.id}] action={rule.action} effect={rule.effect}")
        typer.echo(f"    {rule.description}")
    typer.echo("")
    typer.echo("Examples:")
    for example in doc.examples:
        halt = f" halt_code={example['halt_code']}" if example.get("halt_code") else ""
        typer.echo(f"  [{example.get('kind')}] {example.get('name')} -> {example.get('result')}{halt}")


__all__ = ["app"]
