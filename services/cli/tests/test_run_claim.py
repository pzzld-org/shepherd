"""Tests for ``shepherd run claim`` — the #286 cross-harness resumption path.

``run init`` on an already-existing canonical run always exits 5 (never
reinitializes, never duplicates) — before #286 there was no sanctioned way
for a second Shepherd implementation to verify and resume such a run.
``run claim`` is the third door: READ-ONLY against ``run.json``, loaded
through the exact same schema/migration reader ``run show`` uses. These
tests pin the acceptance criteria from GitHub issue #286 point for point:
exit-0 evidence for an existing schema-1 run, the SAME no-such-run exit
class ``run show`` returns for a missing run, closed failure on a malformed
or higher-schema document, byte-identical ``run.json`` before/after a claim
(never mutates), idempotent repeated claims, and that ``run init``'s own
refusal behavior is unaffected by this addition.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import clean_env_dict, run_cli


def _env(tmp_path: Path) -> dict[str, str]:
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(tmp_path / ".shepherd")
    return env


def _run_json_path(tmp_path: Path, run: str) -> Path:
    return tmp_path / ".shepherd" / "runs" / run / "run.json"


def _write_run_json_raw(tmp_path: Path, run: str, text: str) -> Path:
    """Plant a run.json BY HAND at the path ``run init`` would write to."""
    run_dir = tmp_path / ".shepherd" / "runs" / run
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run.json"
    path.write_text(text)
    return path


def _write_run_json(tmp_path: Path, run: str, doc: dict) -> Path:
    return _write_run_json_raw(tmp_path, run, json.dumps(doc))


def _plant_axiom_style_run(tmp_path: Path, env: dict[str, str]) -> None:
    """Reproduce #286's live repro shape: a schema-1 run, status executing,
    five lanes in-progress — FL03/axiom's real ``v039-dev1``."""
    run_cli(
        ["run", "init", "v039-dev1", "--branch", "v0.3.9-dev.1", "--base", "v0.3.8"],
        env,
    )
    for i in range(5):
        run_cli(["run", "lane", "add", "v039-dev1", f"lane-{i}"], env)
        run_cli(["run", "lane", "set", "v039-dev1", f"lane-{i}", "--state", "in-progress"], env)
    run_cli(["run", "set", "v039-dev1", "--status", "executing"], env)


# --------------------------------------------------------------------------
# #286 acceptance point 1/4/5 — existing schema-1 run: exit 0 + exact JSON.
# --------------------------------------------------------------------------
def test_claim_existing_schema1_run_exits_0_with_exact_json(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _plant_axiom_style_run(tmp_path, env)

    claimed = run_cli(["run", "claim", "v039-dev1", "--json"], env)
    assert claimed.returncode == 0, claimed.stderr
    assert json.loads(claimed.stdout) == {
        "run": "v039-dev1",
        "schema_version": 1,
        "status": "executing",
        "lane_count": 5,
        "path": str(_run_json_path(tmp_path, "v039-dev1")),
    }


def test_claim_text_output_reports_run_schema_status_lanes(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _plant_axiom_style_run(tmp_path, env)

    claimed = run_cli(["run", "claim", "v039-dev1"], env)
    assert claimed.returncode == 0, claimed.stderr
    assert "v039-dev1" in claimed.stdout
    assert "executing" in claimed.stdout
    assert "5 lane" in claimed.stdout
    assert str(_run_json_path(tmp_path, "v039-dev1")) in claimed.stdout


# --------------------------------------------------------------------------
# #286 acceptance point 2 — missing run: the SAME no-such-run exit class
# ``run show`` already returns (byte-identical stderr, not just "some
# nonzero code").
# --------------------------------------------------------------------------
def test_claim_missing_run_matches_run_shows_no_such_run_class(tmp_path: Path) -> None:
    env = _env(tmp_path)

    shown = run_cli(["run", "show", "nope"], env)
    claimed = run_cli(["run", "claim", "nope"], env)

    assert shown.returncode == 5
    assert claimed.returncode == shown.returncode == 5
    assert claimed.stderr == shown.stderr, "claim must report the identical no-such-run class run show does"
    assert "no such run: nope" in claimed.stderr


# --------------------------------------------------------------------------
# #286 acceptance point 2/3 — malformed or higher-schema run.json fails
# CLOSED (never a partial/silent success).
# --------------------------------------------------------------------------
def test_claim_malformed_json_fails_closed(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _write_run_json_raw(tmp_path, "broken", "{not json at all")

    claimed = run_cli(["run", "claim", "broken"], env)
    assert claimed.returncode != 0, "malformed run.json must never claim successfully"
    assert claimed.returncode == 2
    assert claimed.stdout == ""
    assert "could not be read" in claimed.stderr


def test_claim_schema_invalid_json_fails_closed(tmp_path: Path) -> None:
    """A document missing the required ``run``/``run_id`` field cannot be
    normalized — the schema-shaped failure, same as ``run show``'s."""
    env = _env(tmp_path)
    _write_run_json(tmp_path, "no-run-field", {"status": "executing"})

    claimed = run_cli(["run", "claim", "no-run-field"], env)
    assert claimed.returncode != 0
    assert claimed.returncode == 2
    assert claimed.stdout == ""


def test_claim_higher_schema_version_fails_closed(tmp_path: Path) -> None:
    """A run.json a FUTURE CLI wrote (schema_version 2) parses fine under
    this model's ``extra=\"allow\"`` config — claim must still refuse to
    vouch for it rather than silently succeeding on fields it might not
    fully understand."""
    env = _env(tmp_path)
    _write_run_json(
        tmp_path,
        "future-run",
        {
            "schema_version": 2,
            "run": "future-run",
            "kind": "sprint",
            "status": "executing",
            "lanes": [],
        },
    )

    claimed = run_cli(["run", "claim", "future-run"], env)
    assert claimed.returncode != 0, "a higher schema version must never claim successfully"
    assert claimed.returncode == 2
    assert claimed.stdout == ""
    assert "schema_version 2" in claimed.stderr


# --------------------------------------------------------------------------
# #286 acceptance point 3 — NEVER mutates the run: byte-identical run.json
# before and after a claim (assert the bytes, not merely "no error").
# --------------------------------------------------------------------------
def test_claim_never_mutates_run_json_bytes(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _plant_axiom_style_run(tmp_path, env)
    path = _run_json_path(tmp_path, "v039-dev1")

    before = path.read_bytes()
    claimed = run_cli(["run", "claim", "v039-dev1", "--json"], env)
    after = path.read_bytes()

    assert claimed.returncode == 0, claimed.stderr
    assert after == before, "run claim must never write to run.json — it is READ-ONLY"


def test_claim_never_mutates_a_legacy_document_it_would_otherwise_normalize(tmp_path: Path) -> None:
    """Even a legacy-shaped document (#247 ``run_id``/dict-lanes) that
    ``_load_with_migrations_or_fail`` normalizes IN MEMORY must be left
    byte-identical on disk — normalization is display-only here, exactly
    like ``run show`` (never ``run migrate``, which is the only verb
    allowed to rewrite a run.json)."""
    env = _env(tmp_path)
    doc = {
        "run_id": "legacy-claim",
        "kind": "sprint",
        "status": "executing",
        "lanes": {"lane-a": {"state": "in-progress"}},
    }
    path = _write_run_json(tmp_path, "legacy-claim", doc)

    before = path.read_bytes()
    claimed = run_cli(["run", "claim", "legacy-claim", "--json"], env)
    after = path.read_bytes()

    assert claimed.returncode == 0, claimed.stderr
    assert after == before
    payload = json.loads(claimed.stdout)
    assert payload["run"] == "legacy-claim"
    assert payload["lane_count"] == 1


# --------------------------------------------------------------------------
# #286 acceptance point 6 — idempotent: the SAME claim run twice both exit
# 0 (repeated claims by the same, or a different, harness never fail).
# --------------------------------------------------------------------------
def test_claim_is_idempotent_across_repeated_calls(tmp_path: Path) -> None:
    env = _env(tmp_path)
    _plant_axiom_style_run(tmp_path, env)

    first = run_cli(["run", "claim", "v039-dev1", "--json"], env)
    second = run_cli(["run", "claim", "v039-dev1", "--json"], env)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert json.loads(first.stdout) == json.loads(second.stdout)


# --------------------------------------------------------------------------
# "run init's behavior must not change" — pin it directly against this
# addition (test_run.py already covers it independently; this asserts it
# again in the same file that adds `claim`, per #286's acceptance).
# --------------------------------------------------------------------------
def test_run_init_still_refuses_an_existing_run_after_adding_claim(tmp_path: Path) -> None:
    env = _env(tmp_path)
    first = run_cli(["run", "init", "v039-dev1", "--branch", "v0.3.9-dev.1", "--base", "v0.3.8"], env)
    assert first.returncode == 0, first.stderr

    second = run_cli(["run", "init", "v039-dev1"], env)
    assert second.returncode == 5
    assert "already exists" in second.stderr

    # And claim on that same run still works — the "third door" `run init`
    # itself will never open.
    claimed = run_cli(["run", "claim", "v039-dev1"], env)
    assert claimed.returncode == 0, claimed.stderr
