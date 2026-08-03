"""Typer root app for the shepherd CLI.

Registers the ``teammate`` sub-app (the only Typer-ported surface as of
issue #198) and exposes a ``--version``/``-V`` flag on the root callback.
Every other subcommand is handled by the bash ``shctx`` shim in
``shepherd_cli.__main__`` — this module owns only the Typer app object
itself, not the passthrough decision.
"""

from __future__ import annotations

import typer

from shepherd_cli import __version__
from shepherd_cli.commands import (
    audit,
    close_lane,
    config,
    dash,
    deliverable,
    discovery,
    doctor,
    dups,
    eval,
    export,
    handoff,
    init,
    insights,
    issues,
    lint,
    lock,
    mem,
    migrate,
    models,
    prune,
    query,
    ready,
    refresh,
    render,
    report,
    run,
    search,
    seed,
    signal,
    sprint,
    status,
    style,
    sync,
    teammate,
    worktree,
)

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(teammate.app, name="teammate")
app.add_typer(signal.app, name="signal")
app.add_typer(deliverable.app, name="deliverable")
app.add_typer(mem.app, name="mem")
app.add_typer(status.app, name="status")
app.add_typer(lock.app, name="lock")
app.add_typer(sprint.app, name="sprint")
app.add_typer(models.app, name="models")
app.add_typer(query.app, name="query")
app.add_typer(style.app, name="style")
app.add_typer(report.app, name="report")
app.add_typer(search.app, name="search")
app.add_typer(export.app, name="export")
app.add_typer(lint.app, name="lint")
app.add_typer(seed.app, name="seed")
app.add_typer(config.app, name="config")
app.add_typer(sync.app, name="sync")
app.add_typer(dash.app, name="dash")
app.add_typer(insights.app, name="insights")
app.add_typer(dups.app, name="dups")
app.add_typer(handoff.app, name="handoff")
app.add_typer(ready.app, name="ready")
app.add_typer(discovery.app, name="discovery")
app.add_typer(audit.app, name="audit")
app.add_typer(eval.app, name="eval")
app.add_typer(doctor.app, name="doctor")
app.add_typer(migrate.app, name="migrate")
app.add_typer(init.app, name="init")
app.add_typer(close_lane.app, name="close-lane")
app.add_typer(issues.app, name="issues")
app.add_typer(worktree.app, name="worktree")
app.add_typer(refresh.app, name="refresh")
app.add_typer(prune.app, name="prune")
app.add_typer(run.app, name="run")
app.command("render", help="Render a shepherd template deterministically (project -> user -> bundled).")(
    render.render_command
)


def _version_callback(value: bool) -> None:
    """Print the shepherd CLI version and exit, if requested.

    Args:
        value: True when ``--version``/``-V`` was passed on the command line.

    Raises:
        typer.Exit: Always, when ``value`` is True, after printing the
            version. This is the standard Typer eager-option pattern and
            short-circuits the rest of argument parsing.
    """
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the shepherd CLI version and exit.",
    ),
) -> None:
    """shepherd — teammate liveness and coordination CLI.

    Args:
        version: Eager ``--version``/``-V`` flag; handled by
            :func:`_version_callback` before any subcommand runs.
    """
    return None


__all__ = ["app"]
