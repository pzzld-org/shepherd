"""Verdict-derivation tests for `shepherd teammate liveness` (#193/#200).

Covers the exact verdict order the contract specifies for Teammate.verdict():
  declared_state=='in-progress' -> 'ok'      (even past the stale window —
                                               the #193 field-incident fix:
                                               a declaration wins over the
                                               last_seen_at timing heuristic)
  declared_state=='error'       -> 'error'
  declared_state=='complete'    -> 'complete'
  declared_state=='idle'        -> 'idle'
  undeclared + stale + status in (booting, active) -> 'presumed-crashed'
  else                          -> 'ok'

The bash-parity test at the bottom is the real regression gate (#200): it
runs the legacy skills/context/scripts/cmd_teammate.sh liveness against the
IDENTICAL sqlite file the Python CLI just read, and asserts every teammate's
verdict matches exactly. A Python reimplementation that silently drifts from
the bash source of truth is exactly the bug class this guards against.
"""

from __future__ import annotations

import json
import subprocess

from conftest import CMD_TEAMMATE_SH, SeededDb, cli_env, run_cli


def _python_verdicts(seeded_db: SeededDb) -> dict[str, str]:
    env = cli_env(seeded_db.db_path)
    proc = run_cli(["teammate", "liveness", "--all", "--json", "--stale-mins", "5"], env)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    return {row["teammate_name"]: row["verdict"] for row in rows}


def test_declared_in_progress_wins_over_stale_timing(seeded_db: SeededDb) -> None:
    """The #193 fix: a stale in-progress declaration never reads presumed-crashed."""
    assert _python_verdicts(seeded_db)["engineer-inprogress"] == "ok"


def test_undeclared_stale_active_is_presumed_crashed(seeded_db: SeededDb) -> None:
    assert _python_verdicts(seeded_db)["engineer-undeclared-stale"] == "presumed-crashed"


def test_undeclared_fresh_booting_is_ok(seeded_db: SeededDb) -> None:
    assert _python_verdicts(seeded_db)["engineer-undeclared-fresh"] == "ok"


def test_declared_error_maps_to_error(seeded_db: SeededDb) -> None:
    assert _python_verdicts(seeded_db)["engineer-error"] == "error"


def test_declared_complete_maps_to_complete(seeded_db: SeededDb) -> None:
    assert _python_verdicts(seeded_db)["engineer-complete"] == "complete"


def test_declared_idle_maps_to_idle(seeded_db: SeededDb) -> None:
    assert _python_verdicts(seeded_db)["engineer-idle"] == "idle"


def test_undeclared_stale_ghost_is_presumed_crashed(seeded_db: SeededDb) -> None:
    """The ghost teammate (undeclared, 30 days stale, status=active) is exactly
    the shape #193/#194's presumed-crashed derivation targets."""
    assert _python_verdicts(seeded_db)["ghost-alpha"] == "presumed-crashed"


def _parse_bash_liveness_table(stdout: str) -> dict[str, str]:
    """Parse `sqlite3 -header -column` output into {teammate_name: verdict}.

    Every field in this suite's fixture data is a single whitespace-free
    token (team/teammate names, agent_type, status, declared state, digits),
    so a plain split() per line is exact regardless of the column padding
    width sqlite3 happened to choose. The header/data separator row (sqlite3
    -column's own "----  ----  ----" line) is skipped explicitly — it is not
    a teammate row.
    """
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "empty bash `cmd_teammate.sh liveness` output"
    header = lines[0].split()
    name_idx = header.index("teammate_name")
    verdict_idx = header.index("verdict")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if set(line.strip()) <= {"-", " "}:
            continue  # sqlite3 -column's header/data separator row, e.g. "----  ----"
        values = line.split()
        result[values[name_idx]] = values[verdict_idx]
    return result


def test_bash_parity_every_teammate_verdict_matches(seeded_db: SeededDb) -> None:
    """The real parity gate: Python and bash must agree, teammate-by-teammate,
    on the SAME sqlite file with the SAME stale-mins threshold."""
    python_verdicts = _python_verdicts(seeded_db)

    env = cli_env(seeded_db.db_path)
    proc = subprocess.run(
        ["bash", str(CMD_TEAMMATE_SH), "liveness", "--stale-mins=5"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    bash_verdicts = _parse_bash_liveness_table(proc.stdout)

    assert bash_verdicts, "bash cmd_teammate.sh liveness returned no rows"
    assert set(bash_verdicts) == set(python_verdicts), (
        f"row set mismatch: bash={sorted(bash_verdicts)} python={sorted(python_verdicts)}"
    )
    mismatches = {
        name: {"python": python_verdicts[name], "bash": bash_verdicts[name]}
        for name in python_verdicts
        if python_verdicts[name] != bash_verdicts[name]
    }
    assert not mismatches, f"python vs bash verdict mismatch: {mismatches}"
