"""``shepherd render`` — deterministic template rendering Typer sub-app.

NEW surface (v6.5.0, #244/#243/#181) — no bash counterpart existed; this
command RETIRES the repo's five placeholder dialects by fronting the one
``shepherd_cli.render`` engine. Contract:

- ``render <template> [--var k=v]... [--vars-json FILE|-] [--out FILE]
  [--manifest]`` — render one template with the given variables.
  ``--vars-json -`` reads a JSON object from stdin. ``--var`` values are
  strings; typed values come in via ``--vars-json``. When both are given,
  ``--var`` wins per key (explicit beats bulk).
- ``render --list`` (or ``render list``) — enumerate available templates
  with their source root, project overrides shadowing user shadowing
  bundled.

Determinism contract: identical template + identical variables =
byte-identical stdout, byte-identical ``--out`` file, byte-identical
manifest. The manifest (``<out>.manifest.json``, written only with
``--out`` + ``--manifest``) carries template/vars/output sha256 digests
and NO timestamp — mirroring the graph-compile manifest precedent where
volatile provenance never enters diffable artifacts.

Exit codes: 0 success; 2 usage error (bad ``--var`` shape, unreadable
vars file); 3 template not found; 4 undefined template variable
(StrictUndefined violation).
"""

from __future__ import annotations

import json
import os
import sys

import typer

from shepherd_cli.render import (
    TemplateMissingError,
    TemplateVarError,
    list_templates,
    render_template,
)

# Registered on the ROOT app as a plain command (``app.command("render")``)
# rather than a sub-app: render is a single verb with flags, not a command
# group — ``shepherd render <template> [flags]`` must parse in one level.


def _fail(message: str, code: int) -> None:
    """Print one ``ERROR:`` line to stderr and exit with ``code``."""
    typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(code)


def _parse_var_options(pairs: list[str]) -> dict[str, object]:
    """Parse repeated ``--var k=v`` options.

    Args:
        pairs: Raw option values, each ``key=value`` (value may contain
            ``=``; the split is on the first only).

    Returns:
        The parsed mapping (all values strings).
    """
    parsed: dict[str, object] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            _fail(f"--var expects key=value, got: {pair!r}", 2)
        parsed[key] = value
    return parsed


def _load_vars_json(source: str) -> dict[str, object]:
    """Load a JSON object from a file path or ``-`` (stdin).

    Args:
        source: File path, or ``-`` for stdin.

    Returns:
        The decoded object.
    """
    try:
        raw = sys.stdin.read() if source == "-" else open(source, "r", encoding="utf-8").read()
    except OSError as exc:
        _fail(f"cannot read --vars-json {source}: {exc}", 2)
        raise  # unreachable; _fail raises
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"--vars-json {source} is not valid JSON: {exc}", 2)
        raise
    if not isinstance(decoded, dict):
        _fail(f"--vars-json {source} must decode to a JSON object", 2)
    return decoded


def _emit_listing() -> None:
    """Print the available-template table (name + source root)."""
    entries = list_templates()
    if not entries:
        typer.echo("(no templates found)")
        return
    for name, root in entries:
        typer.echo(f"{name}\t{root}")


def render_command(  # noqa: PLR0913 - CLI surface, mirrors documented flags
    template: str = typer.Argument(
        "",
        help="Template name (e.g. handoff.md.j2; bare stems try a .j2 suffix).",
    ),
    var: list[str] = typer.Option(
        [], "--var", help="One template variable as key=value (repeatable; string-typed)."
    ),
    vars_json: str = typer.Option(
        "", "--vars-json", help="JSON object of template variables — a file path, or - for stdin."
    ),
    out: str = typer.Option(
        "", "--out", help="Write the rendered output to this path instead of stdout."
    ),
    manifest: bool = typer.Option(
        False,
        "--manifest",
        help="With --out: also write <out>.manifest.json (template/vars/output sha256 lineage).",
    ),
    list_flag: bool = typer.Option(
        False, "--list", help="List available templates (project -> user -> bundled) and exit."
    ),
) -> None:
    """Render ``template`` with the merged variable set, deterministically."""
    if list_flag or template in ("", "list"):
        if list_flag or template == "list":
            _emit_listing()
            return
        _fail("usage: shepherd render <template> [--var k=v]... [--vars-json FILE|-] [--out FILE]", 2)

    variables: dict[str, object] = {}
    if vars_json:
        variables.update(_load_vars_json(vars_json))
    variables.update(_parse_var_options(var))

    try:
        result = render_template(template, variables)
    except TemplateMissingError as exc:
        _fail(str(exc), 3)
        raise
    except TemplateVarError as exc:
        _fail(f"undefined template variable — {exc}", 4)
        raise

    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(result.text)
        if manifest:
            with open(f"{out}.manifest.json", "w", encoding="utf-8") as handle:
                json.dump(result.manifest(), handle, indent=2, sort_keys=True)
                handle.write("\n")
        typer.echo(out)
    else:
        typer.echo(result.text, nl=False)


__all__ = ["render_command"]
