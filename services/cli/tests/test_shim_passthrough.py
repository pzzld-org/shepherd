"""Shim passthrough test: an un-ported subcommand delegates to bash shctx.

`shepherd_cli.__main__.main()` is a drop-in superset over bash shctx: any
subcommand not in PORTED ({"teammate"}) is handed off via `os.execv` so the
bash script transparently inherits stdio and exit code. This test proves
real delegation happened — the legacy shctx dispatcher's own
"unknown subcommand" message and exit code — rather than Typer/Click
independently failing to resolve the subcommand with its own "No such
command" error (which would look superficially similar but prove the
opposite: that the shim never fired).
"""

from __future__ import annotations

from pathlib import Path

from conftest import build_full_schema_db, cli_env, insert_project, run_cli


def test_unported_subcommand_delegates_to_bash_shctx(tmp_path: Path) -> None:
    db_path = tmp_path / "shepherd.db"  # unused by this subcommand; cli_env just needs a value
    env = cli_env(db_path)

    proc = run_cli(["__nope__"], env)

    combined = proc.stdout + proc.stderr
    assert "unknown subcommand" in combined.lower(), (
        f"expected bash shctx's unknown-subcommand message, got: "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "__nope__" in combined
    # Bash shctx's catch-all `*)` branch exits 1. A Typer/Click "No such
    # command" failure exits 2 instead — the exit code is the load-bearing
    # proof this was a real delegation, not Typer failing on its own terms.
    assert proc.returncode == 1, f"expected bash shctx's exit code 1, got {proc.returncode}: {combined}"
    assert "No such command" not in combined


def test_ported_subcommand_is_never_shimmed(tmp_path: Path) -> None:
    """Sanity/negative control: 'teammate' (the one #198-ported subcommand)
    must be handled by the real Typer app and never reach the bash shim."""
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path)
    env = cli_env(db_path)

    proc = run_cli(["teammate", "liveness", "--all", "--json"], env)

    assert proc.returncode == 0, proc.stderr
    assert "unknown subcommand" not in (proc.stdout + proc.stderr).lower()


def test_root_help_is_handled_by_typer_not_shimmed(tmp_path: Path) -> None:
    """A leading-dash-free but still Typer-owned invocation (no args -> help,
    no_args_is_help=True) must not fall through to the bash shim either."""
    db_path = tmp_path / "shepherd.db"
    env = cli_env(db_path)

    proc = run_cli([], env)

    combined = proc.stdout + proc.stderr
    assert "unknown subcommand" not in combined.lower()
    assert "teammate" in combined  # the ported sub-app shows up in Typer's own help
