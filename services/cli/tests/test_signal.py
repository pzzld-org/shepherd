"""Tests for `shepherd signal` — the dedicated cross-session channel (#206).

Native port of bash `shctx signal`. Drives the real CLI as a subprocess (the
#198 contract) against a full-schema fixture DB, asserting bash-parity: send
prints the new row id, poll orders by sent_at and filters by recipient/kind,
--consume is one-shot, and the usage/validation exit codes match cmd_signal.sh
(missing --kind → 2, invalid JSON payload → 1).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, build_full_schema_db, cli_env, insert_project, run_cli


@pytest.fixture
def signal_db(tmp_path: Path) -> Path:
    """A full-schema fixture DB with one registered project (FK target).

    Args:
        tmp_path: pytest's per-test temp directory.

    Returns:
        Path to a fresh ``shepherd.db`` migrated to HEAD (so ``session_signals``
        from migration 0020 exists) with a single ``projects`` row.
    """
    db_path = tmp_path / "shepherd.db"
    build_full_schema_db(db_path)
    insert_project(db_path)
    return db_path


def _send(db_path: Path, recipient: str, kind: str, payload: str) -> subprocess.CompletedProcess[str]:
    """Run ``shepherd signal send`` feeding ``payload`` on stdin.

    Args:
        db_path: The fixture DB to write into (via SHCTX_DB).
        recipient: ``--to`` value.
        kind: ``--kind`` value.
        payload: The raw stdin payload (JSON, or deliberately-invalid text).

    Returns:
        The completed subprocess, stdout/stderr captured as text.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "signal", "send", "--to", recipient, "--kind", kind],
        env=cli_env(db_path),
        input=payload,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_send_prints_numeric_id_and_poll_finds_it(signal_db: Path) -> None:
    sent = _send(signal_db, "spawn-a", "seed-ready", '{"event":"seed-ready"}')
    assert sent.returncode == 0, sent.stderr
    assert sent.stdout.strip().isdigit(), f"send did not print a numeric id: {sent.stdout!r}"

    peek = run_cli(["signal", "poll", "--as", "spawn-a", "--json"], cli_env(signal_db))
    assert peek.returncode == 0, peek.stderr
    rows = json.loads(peek.stdout)
    assert len(rows) == 1
    assert rows[0]["kind"] == "seed-ready"
    assert rows[0]["recipient"] == "spawn-a"
    assert rows[0]["consumed_at"] is None


def test_poll_text_shape_is_id_kind_payload(signal_db: Path) -> None:
    _send(signal_db, "spawn-a", "seed-ready", '{"k":1}')
    out = run_cli(["signal", "poll", "--as", "spawn-a"], cli_env(signal_db))
    assert out.returncode == 0, out.stderr
    line = out.stdout.strip()
    parts = line.split(" ", 2)
    assert parts[0].isdigit()
    assert parts[1] == "seed-ready"
    assert parts[2] == '{"k":1}'


def test_recipient_scoping_and_kind_filter(signal_db: Path) -> None:
    _send(signal_db, "spawn-a", "seed-ready", "{}")
    # Different recipient sees nothing.
    other = run_cli(["signal", "poll", "--as", "spawn-b", "--json"], cli_env(signal_db))
    assert json.loads(other.stdout) == []
    # Non-matching kind sees nothing.
    wrong = run_cli(["signal", "poll", "--as", "spawn-a", "--kind", "other", "--json"], cli_env(signal_db))
    assert json.loads(wrong.stdout) == []


def test_consume_is_one_shot(signal_db: Path) -> None:
    _send(signal_db, "spawn-a", "seed-ready", "{}")
    consumed = run_cli(["signal", "poll", "--as", "spawn-a", "--consume", "--json"], cli_env(signal_db))
    assert len(json.loads(consumed.stdout)) == 1
    again = run_cli(["signal", "poll", "--as", "spawn-a", "--json"], cli_env(signal_db))
    assert json.loads(again.stdout) == []


def test_ordering_by_sent_at(signal_db: Path) -> None:
    for i in range(3):
        _send(signal_db, "spawn-a", f"kind-{i}", "{}")
    rows = json.loads(run_cli(["signal", "poll", "--as", "spawn-a", "--json"], cli_env(signal_db)).stdout)
    sent_ats = [r["sent_at"] for r in rows]
    assert sent_ats == sorted(sent_ats), "poll must order by sent_at ascending (bash parity)"


def test_missing_kind_exits_2(signal_db: Path) -> None:
    proc = subprocess.run(
        [PY, "-m", "shepherd_cli", "signal", "send", "--to", "spawn-a"],
        env=cli_env(signal_db), input="{}", capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 2, f"missing --kind should exit 2 (usage), got {proc.returncode}"


def test_invalid_json_payload_exits_1(signal_db: Path) -> None:
    proc = _send(signal_db, "spawn-a", "seed-ready", "not-json")
    assert proc.returncode == 1, f"invalid JSON payload should exit 1, got {proc.returncode}"
    assert "not valid JSON" in proc.stderr


def test_no_subcommand_prints_usage_and_exits_0(signal_db: Path) -> None:
    # Bash parity: `shctx signal` (no subcommand) prints usage on stdout, exit 0.
    proc = run_cli(["signal"], cli_env(signal_db))
    assert proc.returncode == 0, f"no-subcommand should exit 0 (bash parity), got {proc.returncode}"
    assert "CROSS-SESSION ONLY" in proc.stdout
