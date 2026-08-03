"""Tests for ``shepherd run`` — run-directory lifecycle + the #242 ledger.

The run.json document is CLI-written and schema-validated; these tests pin
the id grammar, the lifecycle vocabulary, atomicity side-effects (valid
sorted-key JSON on disk), and the boundary-merge pending-set gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import clean_env_dict, run_cli


def _env(tmp_path: Path) -> dict[str, str]:
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(tmp_path / ".shepherd")
    return env


def _run_json(tmp_path: Path, run: str) -> dict:
    return json.loads((tmp_path / ".shepherd" / "runs" / run / "run.json").read_text())


def test_init_scaffolds_run_dir(tmp_path: Path) -> None:
    env = _env(tmp_path)
    proc = run_cli(["run", "init", "v650-dev0", "--branch", "v6.5.0-dev.0", "--base", "v6.5.0"], env)
    assert proc.returncode == 0, proc.stderr
    doc = _run_json(tmp_path, "v650-dev0")
    assert doc["schema_version"] == 1
    assert doc["run"] == "v650-dev0"
    assert doc["status"] == "planted"
    assert doc["branch"] == "v6.5.0-dev.0"
    assert (tmp_path / ".shepherd" / "runs" / "v650-dev0" / "lanes").is_dir()


def test_init_refuses_existing_run(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert run_cli(["run", "init", "v650-dev0"], env).returncode == 0
    proc = run_cli(["run", "init", "v650-dev0"], env)
    assert proc.returncode == 5
    assert "already exists" in proc.stderr


def test_init_rejects_bad_ids(tmp_path: Path) -> None:
    env = _env(tmp_path)
    for bad in ("V650", "a/b", "..", "-leading", ""):
        proc = run_cli(["run", "init", bad], env)
        assert proc.returncode == 2, f"{bad!r} accepted (exit {proc.returncode})"


def test_show_and_list_round_trip(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v650-dev0"], env)
    run_cli(["run", "init", "v650-dev1"], env)

    listing = run_cli(["run", "list"], env)
    assert listing.stdout.splitlines() == ["v650-dev0", "v650-dev1"]

    shown = run_cli(["run", "show", "v650-dev0", "--json"], env)
    assert shown.returncode == 0
    assert json.loads(shown.stdout)["run"] == "v650-dev0"

    missing = run_cli(["run", "show", "nope"], env)
    assert missing.returncode == 5


def test_set_validates_status_vocabulary(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v650-dev0"], env)
    bad = run_cli(["run", "set", "v650-dev0", "--status", "vibing"], env)
    assert bad.returncode == 2

    good = run_cli(
        ["run", "set", "v650-dev0", "--status", "planned", "--seed", "runs/v650-dev0/seed.md"], env
    )
    assert good.returncode == 0, good.stderr
    doc = _run_json(tmp_path, "v650-dev0")
    assert doc["status"] == "planned"
    assert doc["seed"] == "runs/v650-dev0/seed.md"


def test_lane_lifecycle(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v650-dev0"], env)
    added = run_cli(["run", "lane", "add", "v650-dev0", "lane-cli", "--branch", "lane-cli"], env)
    assert added.returncode == 0, added.stderr
    assert (tmp_path / ".shepherd" / "runs" / "v650-dev0" / "lanes" / "lane-cli").is_dir()

    doc = _run_json(tmp_path, "v650-dev0")
    assert doc["lanes"][0]["id"] == "lane-cli"
    assert doc["lanes"][0]["plan"] == "lanes/lane-cli/plan.md"
    assert doc["lanes"][0]["state"] == "pending"

    dup = run_cli(["run", "lane", "add", "v650-dev0", "lane-cli"], env)
    assert dup.returncode == 2

    flipped = run_cli(["run", "lane", "set", "v650-dev0", "lane-cli", "--state", "in-progress"], env)
    assert flipped.returncode == 0
    assert _run_json(tmp_path, "v650-dev0")["lanes"][0]["state"] == "in-progress"

    unknown = run_cli(["run", "lane", "set", "v650-dev0", "ghost", "--state", "complete"], env)
    assert unknown.returncode == 5


def test_wave_ledger_pending_gate(tmp_path: Path) -> None:
    """#242: accepted-but-unmerged lanes fail the pending gate (exit 6) until
    each is marked merged — the mechanical boundary-merge enumeration."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v650-dev0"], env)
    run_cli(["run", "lane", "add", "v650-dev0", "lane-a"], env)
    run_cli(["run", "lane", "add", "v650-dev0", "lane-b"], env)

    clean = run_cli(["run", "wave", "pending", "v650-dev0"], env)
    assert clean.returncode == 0
    assert clean.stdout == ""

    run_cli(["run", "wave", "accept", "v650-dev0", "lane-a", "--commit", "aaa1111"], env)
    run_cli(["run", "wave", "accept", "v650-dev0", "lane-b", "--commit", "bbb2222"], env)

    pending = run_cli(["run", "wave", "pending", "v650-dev0"], env)
    assert pending.returncode == 6
    assert "lane-a\taaa1111" in pending.stdout
    assert "lane-b\tbbb2222" in pending.stdout

    run_cli(["run", "wave", "merged", "v650-dev0", "lane-a"], env)
    still = run_cli(["run", "wave", "pending", "v650-dev0", "--json"], env)
    assert still.returncode == 6
    assert json.loads(still.stdout) == [{"lane": "lane-b", "commit": "bbb2222"}]

    run_cli(["run", "wave", "merged", "v650-dev0", "lane-b"], env)
    done = run_cli(["run", "wave", "pending", "v650-dev0"], env)
    assert done.returncode == 0
    assert done.stdout == ""


def test_wave_merged_requires_prior_accept(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v650-dev0"], env)
    run_cli(["run", "lane", "add", "v650-dev0", "lane-a"], env)
    proc = run_cli(["run", "wave", "merged", "v650-dev0", "lane-a"], env)
    assert proc.returncode == 2
    assert "no accepted commit" in proc.stderr


def test_run_json_is_sorted_and_stable_on_disk(tmp_path: Path) -> None:
    """Atomic writer emits sorted-key JSON — no dict-order nondeterminism."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v650-dev0"], env)
    raw = (tmp_path / ".shepherd" / "runs" / "v650-dev0" / "run.json").read_text()
    doc = json.loads(raw)
    assert raw == json.dumps(doc, indent=2, sort_keys=True) + "\n"
