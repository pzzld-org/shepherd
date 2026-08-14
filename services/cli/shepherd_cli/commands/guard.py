"""``shepherd guard`` — the CLI surface over :mod:`shepherd_cli.predicates` (DF-76).

All three harness adapters (``packages/harness-claude``, ``packages/harness-codex``,
``packages/harness-pi``) relay guard-predicate evaluation to a ``shepherd guard
eval`` CLI surface — ``packages/harness-claude/src/guard.mjs``'s own header
names the exact stdin/stdout contract it expects. This module is a THIN
relay to :mod:`shepherd_cli.predicates`'s :class:`~shepherd_cli.predicates.Engine`
and carries no predicate logic of its own — every decision lives in that
module, which is the behavioral oracle a later Rust port replays against.

Three subcommands, matching the dispatch brief's own contract exactly:

- ``eval``: one JSON request on stdin, one JSON verdict on stdout, exit 0
  whenever a verdict (allow, deny, OR unresolved) was successfully reached.
  Exit != 0 means the ENGINE failed (malformed stdin, unreadable
  ``content/predicates/``) — never a verdict; nothing is printed to stdout
  in that case, so a caller parsing stdout can never mistake an engine
  crash for a silent allow.
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
