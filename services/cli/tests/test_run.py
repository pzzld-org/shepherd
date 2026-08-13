"""Tests for ``shepherd run`` — run-directory lifecycle + the #242 ledger.

The run.json document is CLI-written and schema-validated; these tests pin
the id grammar, the lifecycle vocabulary, atomicity side-effects (valid
sorted-key JSON on disk), and the boundary-merge pending-set gate.
"""

from __future__ import annotations

import json
import shutil
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
    proc = run_cli(["run", "init", "v641-dev0", "--branch", "v6.4.1-dev.0", "--base", "v6.4.1"], env)
    assert proc.returncode == 0, proc.stderr
    doc = _run_json(tmp_path, "v641-dev0")
    assert doc["schema_version"] == 1
    assert doc["run"] == "v641-dev0"
    assert doc["status"] == "planted"
    assert doc["branch"] == "v6.4.1-dev.0"
    assert (tmp_path / ".shepherd" / "runs" / "v641-dev0" / "lanes").is_dir()


def test_init_refuses_existing_run(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert run_cli(["run", "init", "v641-dev0"], env).returncode == 0
    proc = run_cli(["run", "init", "v641-dev0"], env)
    assert proc.returncode == 5
    assert "already exists" in proc.stderr


def test_init_rejects_bad_ids(tmp_path: Path) -> None:
    env = _env(tmp_path)
    for bad in ("V650", "a/b", "..", "-leading", ""):
        proc = run_cli(["run", "init", bad], env)
        assert proc.returncode == 2, f"{bad!r} accepted (exit {proc.returncode})"


def test_show_and_list_round_trip(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    run_cli(["run", "init", "v641-dev1"], env)

    listing = run_cli(["run", "list"], env)
    assert listing.stdout.splitlines() == ["v641-dev0", "v641-dev1"]

    shown = run_cli(["run", "show", "v641-dev0", "--json"], env)
    assert shown.returncode == 0
    assert json.loads(shown.stdout)["run"] == "v641-dev0"

    missing = run_cli(["run", "show", "nope"], env)
    assert missing.returncode == 5


def test_set_validates_status_vocabulary(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    bad = run_cli(["run", "set", "v641-dev0", "--status", "vibing"], env)
    assert bad.returncode == 2

    good = run_cli(
        ["run", "set", "v641-dev0", "--status", "planned", "--seed", "runs/v641-dev0/seed.md"], env
    )
    assert good.returncode == 0, good.stderr
    doc = _run_json(tmp_path, "v641-dev0")
    assert doc["status"] == "planned"
    assert doc["seed"] == "runs/v641-dev0/seed.md"


def test_lane_lifecycle(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    added = run_cli(["run", "lane", "add", "v641-dev0", "lane-cli", "--branch", "lane-cli"], env)
    assert added.returncode == 0, added.stderr
    assert (tmp_path / ".shepherd" / "runs" / "v641-dev0" / "lanes" / "lane-cli").is_dir()

    doc = _run_json(tmp_path, "v641-dev0")
    assert doc["lanes"][0]["id"] == "lane-cli"
    assert doc["lanes"][0]["plan"] == "lanes/lane-cli/plan.md"
    assert doc["lanes"][0]["state"] == "pending"

    dup = run_cli(["run", "lane", "add", "v641-dev0", "lane-cli"], env)
    assert dup.returncode == 2

    flipped = run_cli(["run", "lane", "set", "v641-dev0", "lane-cli", "--state", "in-progress"], env)
    assert flipped.returncode == 0
    assert _run_json(tmp_path, "v641-dev0")["lanes"][0]["state"] == "in-progress"

    unknown = run_cli(["run", "lane", "set", "v641-dev0", "ghost", "--state", "complete"], env)
    assert unknown.returncode == 5


def test_wave_ledger_pending_gate(tmp_path: Path) -> None:
    """#242: accepted-but-unmerged lanes fail the pending gate (exit 6) until
    each is marked merged — the mechanical boundary-merge enumeration."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    run_cli(["run", "lane", "add", "v641-dev0", "lane-a"], env)
    run_cli(["run", "lane", "add", "v641-dev0", "lane-b"], env)

    clean = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert clean.returncode == 0
    assert clean.stdout == ""

    run_cli(["run", "wave", "accept", "v641-dev0", "lane-a", "--commit", "aaa1111"], env)
    run_cli(["run", "wave", "accept", "v641-dev0", "lane-b", "--commit", "bbb2222"], env)

    pending = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert pending.returncode == 6
    assert "lane-a\taaa1111" in pending.stdout
    assert "lane-b\tbbb2222" in pending.stdout

    run_cli(["run", "wave", "merged", "v641-dev0", "lane-a"], env)
    still = run_cli(["run", "wave", "pending", "v641-dev0", "--json"], env)
    assert still.returncode == 6
    still_payload = json.loads(still.stdout)
    assert still_payload["pending"] == [{"lane": "lane-b", "commit": "bbb2222"}]
    assert still_payload["missing_lanes"] == []
    assert still_payload["ok"] is False

    run_cli(["run", "wave", "merged", "v641-dev0", "lane-b"], env)
    done = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert done.returncode == 0
    assert done.stdout == ""


# --------------------------------------------------------------------------
# #1 GATE-EXIT-CODE-MISMATCH / DF-63 -- ledger-completeness check.
#
# pending_merges() alone only ever looks AT registered rows; a lane that
# was never `run lane add`-ed at all has zero rows, which read as "not
# pending" rather than "missing" -- the gate exited 0 against a live
# ledger missing a lane entirely (dogfood.md DF-63). These tests are the
# falsifiability the finding itself demands: the first MUST fail (report a
# wrong exit code) against an unfixed `wave_pending_cmd` and pass once the
# completeness check is wired; the second pins the false-positive-free
# baseline (a plan with no declared lanes at all never trips the check).
# --------------------------------------------------------------------------
def _write_lane_projection_plan(tmp_path: Path, run: str, lane_ids: list[str]) -> None:
    """Plant a minimal ``plan.md`` with a ``## Lane projection`` table.

    Mirrors ``.shepherd/runs/v645/plan.md``'s own table shape exactly (the
    live plan DF-63 was measured against: prose paragraph, then a
    ``| lane_id | member_steps | file_scope.exclusive | parallel_with |``
    table with backtick-wrapped ids) so :func:`parse_declared_lane_ids` is
    exercised against the real doc shape, not a synthetic one.
    """
    rows = "\n".join(f"| `{lane_id}` | W1-S1 | `crates/{lane_id}` | - |" for lane_id in lane_ids)
    text = (
        "# plan\n\n"
        "## Lane projection\n\n"
        "Prose paragraph before the table, matching the live doc shape.\n\n"
        "| lane_id | member_steps | file_scope.exclusive | parallel_with |\n"
        "|---|---|---|---|\n"
        f"{rows}\n"
    )
    (tmp_path / ".shepherd" / "runs" / run / "plan.md").write_text(text)


def test_wave_pending_gate_exit_code_mismatch_df63(tmp_path: Path) -> None:
    """Falsifiability for #1 GATE-EXIT-CODE-MISMATCH: FAILS (reports the
    wrong exit code) against a ``wave_pending_cmd`` with no
    ledger-completeness check, PASSES once it is wired.

    Mirrors DF-63's exact live repro shape: a run plan declares 3 lanes,
    only 2 are ever ``run lane add``-ed -- the omitted lane (fully worked,
    just never registered) is precisely the shape that measured exit 0 on
    a 5-defect live ledger before this fix."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    _write_lane_projection_plan(tmp_path, "v641-dev0", ["l1-engine", "l2-registry", "l3-surface"])
    # l3-surface is declared by the plan but NEVER registered -- DF-63's
    # exact defect shape (a fully-worked lane nobody `run lane add`-ed).
    run_cli(["run", "lane", "add", "v641-dev0", "l1-engine"], env)
    run_cli(["run", "lane", "add", "v641-dev0", "l2-registry"], env)

    incomplete = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert incomplete.returncode == 6, (
        "ledger-completeness check regressed: a plan-declared but "
        f"unregistered lane must exit 6, not {incomplete.returncode} (DF-63)"
    )
    assert "l3-surface\tMISSING-DECLARED-LANE" in incomplete.stdout

    payload = json.loads(run_cli(["run", "wave", "pending", "v641-dev0", "--json"], env).stdout)
    assert payload["missing_lanes"] == ["l3-surface"]
    assert payload["pending"] == []
    assert payload["ok"] is False

    # Registering the omitted lane completes the ledger: exit 0, no output.
    run_cli(["run", "lane", "add", "v641-dev0", "l3-surface"], env)
    complete = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert complete.returncode == 0, complete.stdout
    assert complete.stdout == ""


def test_wave_pending_no_lane_projection_is_never_a_false_positive(tmp_path: Path) -> None:
    """A run with no ``## Lane projection`` section (or no plan.md at all)
    declares nothing, so the completeness check must never fire -- only
    the pre-existing #242 pending-set check can still gate it."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    run_cli(["run", "lane", "add", "v641-dev0", "lane-a"], env)

    no_plan = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert no_plan.returncode == 0, "no plan.md at all must not trip the completeness check"

    (tmp_path / ".shepherd" / "runs" / "v641-dev0" / "plan.md").write_text("# plan\n\nno lane table here.\n")
    no_section = run_cli(["run", "wave", "pending", "v641-dev0"], env)
    assert no_section.returncode == 0, "a plan with no Lane projection section must not trip the check"


def test_wave_merged_requires_prior_accept(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    run_cli(["run", "lane", "add", "v641-dev0", "lane-a"], env)
    proc = run_cli(["run", "wave", "merged", "v641-dev0", "lane-a"], env)
    assert proc.returncode == 2
    assert "no accepted commit" in proc.stderr


def test_run_json_is_sorted_and_stable_on_disk(tmp_path: Path) -> None:
    """Atomic writer emits sorted-key JSON — no dict-order nondeterminism."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    raw = (tmp_path / ".shepherd" / "runs" / "v641-dev0" / "run.json").read_text()
    doc = json.loads(raw)
    assert raw == json.dumps(doc, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------
# #247 — legacy/foreign run.json tolerance (normalize_run_document + the
# extra="allow" schema). Every scenario below writes a run.json BY HAND
# (bypassing `run init`, which only ever writes canonical documents) so it
# can plant exactly the on-disk shapes prior shepherd versions and
# codex-shepherd are known to produce, then drives the real CLI against it
# — matching this file's subprocess-only fixture idiom throughout.
# --------------------------------------------------------------------------


def _write_run_json_raw(tmp_path: Path, run: str, text: str) -> Path:
    """Plant a run.json BY HAND at the path ``run init`` would write to."""
    run_dir = tmp_path / ".shepherd" / "runs" / run
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run.json"
    path.write_text(text)
    return path


def _write_run_json(tmp_path: Path, run: str, doc: dict) -> Path:
    return _write_run_json_raw(tmp_path, run, json.dumps(doc))


#: A representative sample (>10, per issue #247) of the 27 extra top-level
#: keys measured on live FL03/axiom run.json files, covering every JSON
#: value shape (list, dict, str, int, float, bool, null) so a naive
#: str()-based round trip could not accidentally pass.
_LEGACY_EXTRA_KEYS: dict[str, object] = {
    "decisions": ["use pydantic", "extra=allow"],
    "blockers": [],
    "concerns": {"schema": "was closed"},
    "operator_decisions": [{"who": "joe", "what": "approve"}],
    "acceptance": {"lane-a": True, "lane-b": False},
    "audits": ["audit-1"],
    "close_audits": None,
    "redo_counts": {"lane-a": 2},
    "subtract_paths": ["a/b.py"],
    "subtract_target": 120,
    "expected_loc_delta": -45,
    "subtract_floor": 0.1,
    "execution_evidence": {"lane-a": "https://example/ci/1"},
    "external_evidence": [],
    "active_node": "engineer",
    "canonical_seed": "runs/legacy/seed.md",
    "outcome": "in-progress",
}


def _legacy_doc(run_id: str, updated_at: object, lanes: object) -> dict:
    doc: dict = {
        "run_id": run_id,
        "kind": "sprint",
        "status": "executing",
        "branch": "v6.4.1-dev.0",
        "base": "v6.4.1",
        "updated_at": updated_at,
        "lanes": lanes,
    }
    doc.update(_LEGACY_EXTRA_KEYS)
    return doc


def test_show_normalizes_legacy_document_and_round_trips_extras(tmp_path: Path) -> None:
    """A legacy run.json (``run_id``, dict-lanes, ISO ``updated_at``, 17
    extra top-level keys) loads clean and every extra key survives
    verbatim — #247's central claim."""
    env = _env(tmp_path)
    lanes = {
        "lane-b": {"state": "complete", "worktree": "wt-b"},
        "lane-a": {"state": "pending", "branch": "br-a"},
    }
    doc = _legacy_doc("legacy-run", "2026-07-01T12:34:56Z", lanes)
    _write_run_json(tmp_path, "legacy-run", doc)

    shown = run_cli(["run", "show", "legacy-run", "--json"], env)
    assert shown.returncode == 0, shown.stderr
    out = json.loads(shown.stdout)

    assert out["run"] == "legacy-run"
    assert "run_id" not in out
    assert out["updated_at"] == 1782909296  # 2026-07-01T12:34:56Z, computed independently
    assert [lane["id"] for lane in out["lanes"]] == ["lane-a", "lane-b"]  # dict -> sorted list
    for key, value in _LEGACY_EXTRA_KEYS.items():
        assert out[key] == value, f"extra key {key!r} did not round trip: {out.get(key)!r} != {value!r}"

    text_shown = run_cli(["run", "show", "legacy-run"], env)
    assert text_shown.returncode == 0, text_shown.stderr
    first_line = text_shown.stdout.splitlines()[0]
    assert first_line == "(normalized: run_id->run, lanes:dict->list, updated_at:iso->epoch)"


def test_lanes_dict_to_list_preserves_ids_and_sorts_deterministically(tmp_path: Path) -> None:
    """dict-key -> id wins over any (mismatched) inline ``id`` a lane dict
    might itself carry, and the resulting list is sorted by id."""
    env = _env(tmp_path)
    lanes = {
        "lane-z": {"id": "not-lane-z", "state": "complete"},
        "lane-a": {"state": "pending"},
        "lane-m": {"id": "also-wrong", "state": "in-progress"},
    }
    _write_run_json(tmp_path, "unsorted-lanes", _legacy_doc("unsorted-lanes", 0, lanes))

    shown = run_cli(["run", "show", "unsorted-lanes", "--json"], env)
    assert shown.returncode == 0, shown.stderr
    out_lanes = json.loads(shown.stdout)["lanes"]
    assert [lane["id"] for lane in out_lanes] == ["lane-a", "lane-m", "lane-z"]
    assert [lane["state"] for lane in out_lanes] == ["pending", "in-progress", "complete"]


def test_updated_at_accepts_iso_and_int_garbage_becomes_zero(tmp_path: Path) -> None:
    """ISO8601 and int ``updated_at`` both load; an unparseable value
    becomes 0, never a crash."""
    env = _env(tmp_path)
    _write_run_json(tmp_path, "iso-run", _legacy_doc("iso-run", "2025-01-15T08:00:00Z", {}))
    _write_run_json(tmp_path, "int-run", _legacy_doc("int-run", 1700000000, {}))
    _write_run_json(tmp_path, "garbage-run", _legacy_doc("garbage-run", "not-a-timestamp", {}))

    iso_out = json.loads(run_cli(["run", "show", "iso-run", "--json"], env).stdout)
    assert iso_out["updated_at"] == 1736928000

    int_out = run_cli(["run", "show", "int-run", "--json"], env)
    assert json.loads(int_out.stdout)["updated_at"] == 1700000000
    # An already-canonical int updated_at contributes no "updated_at:iso->epoch"
    # migration (the run's other legacy fields still do trigger a note).
    int_text = run_cli(["run", "show", "int-run"], env).stdout
    assert "updated_at:iso->epoch" not in int_text.splitlines()[0]

    garbage_shown = run_cli(["run", "show", "garbage-run", "--json"], env)
    assert garbage_shown.returncode == 0, garbage_shown.stderr
    assert json.loads(garbage_shown.stdout)["updated_at"] == 0


def test_run_migrate_rewrites_legacy_file_and_is_idempotent(tmp_path: Path) -> None:
    """``run migrate`` rewrites a legacy file into canonical shape (loadable
    without any further normalization) and is idempotent."""
    env = _env(tmp_path)
    lanes = {"lane-b": {"state": "complete"}, "lane-a": {"state": "pending"}}
    doc = _legacy_doc("migrate-me", "2026-03-01T00:00:00Z", lanes)
    _write_run_json(tmp_path, "migrate-me", doc)

    first = run_cli(["run", "migrate", "migrate-me"], env)
    assert first.returncode == 0, first.stderr
    assert "run_id->run" in first.stdout
    assert "lanes:dict->list" in first.stdout
    assert "updated_at:iso->epoch" in first.stdout

    on_disk = _run_json(tmp_path, "migrate-me")
    # Canonical shape, directly, with no reliance on a further normalize pass.
    assert on_disk["run"] == "migrate-me"
    assert "run_id" not in on_disk
    assert isinstance(on_disk["lanes"], list)
    assert [lane["id"] for lane in on_disk["lanes"]] == ["lane-a", "lane-b"]
    assert isinstance(on_disk["updated_at"], int)
    for key, value in _LEGACY_EXTRA_KEYS.items():
        assert on_disk[key] == value, f"extra key {key!r} lost on migrate: {on_disk.get(key)!r} != {value!r}"

    second = run_cli(["run", "migrate", "migrate-me"], env)
    assert second.returncode == 0, second.stderr
    assert "no changes" in second.stdout


def test_run_migrate_all(tmp_path: Path) -> None:
    """``--all`` migrates every run under runs/, mixed legacy + canonical."""
    env = _env(tmp_path)
    # "already-canonical" describes its run.json SHAPE (no #247 migration
    # needed), not its #P4 run-id SHAPE -- it doesn't match the configured
    # slug patterns, so --force is required post-#P4.
    run_cli(["run", "init", "already-canonical", "--force"], env)
    _write_run_json(tmp_path, "legacy-a", _legacy_doc("legacy-a", 0, {}))
    _write_run_json(tmp_path, "legacy-b", _legacy_doc("legacy-b", 0, {}))

    proc = run_cli(["run", "migrate", "--all"], env)
    assert proc.returncode == 0, proc.stderr
    lines = {line.split(" ", 2)[1]: line for line in proc.stdout.splitlines()}
    assert lines.keys() == {"already-canonical", "legacy-a", "legacy-b"}
    assert "no changes" in lines["already-canonical"]
    assert "run_id->run" in lines["legacy-a"]
    assert "run_id->run" in lines["legacy-b"]


def test_run_migrate_requires_exactly_one_of_run_or_all(tmp_path: Path) -> None:
    env = _env(tmp_path)
    neither = run_cli(["run", "migrate"], env)
    assert neither.returncode == 2
    assert "exactly one" in neither.stderr

    run_cli(["run", "init", "v641-dev0"], env)
    both = run_cli(["run", "migrate", "v641-dev0", "--all"], env)
    assert both.returncode == 2
    assert "exactly one" in both.stderr


def test_show_malformed_json_gives_could_not_be_read_wording(tmp_path: Path) -> None:
    """A genuinely non-JSON run.json is NOT called "corrupt", exits 2, and
    (since it's not schema-shaped) does not suggest ``run migrate``."""
    env = _env(tmp_path)
    _write_run_json_raw(tmp_path, "broken", "{not json at all")

    proc = run_cli(["run", "show", "broken"], env)
    assert proc.returncode == 2
    assert "run.json for broken could not be read:" in proc.stderr
    assert "corrupt" not in proc.stderr.lower()
    assert "run migrate" not in proc.stderr


def test_show_schema_shaped_failure_suggests_migrate(tmp_path: Path) -> None:
    """A document with neither ``run`` nor ``run_id`` cannot be normalized
    away — the schema-shaped failure gets the ``run migrate`` hint."""
    env = _env(tmp_path)
    _write_run_json(tmp_path, "no-run-field", {"status": "executing"})

    proc = run_cli(["run", "show", "no-run-field"], env)
    assert proc.returncode == 2
    assert "run.json for no-run-field could not be read:" in proc.stderr
    assert "corrupt" not in proc.stderr.lower()
    assert "try: shepherd run migrate no-run-field" in proc.stderr


# --------------------------------------------------------------------------
# v6.4.3 — canonical run layout (`run init` scaffold + `run layout` verb).
#
# Before v6.4.3 `run init` created only `lanes/`; `graph/`, `dispatch/`,
# `reports/`, and `audits/` appeared only if something happened to write into
# them. So a run's shape encoded what the sprint had DONE, not what a run IS,
# and nothing reading the layout could rely on it.
# --------------------------------------------------------------------------
CANONICAL_SUBDIRS = ("lanes", "graph", "dispatch", "reports", "audits")


def _run_base(tmp_path: Path, run: str = "v641-dev0") -> Path:
    return tmp_path / ".shepherd" / "runs" / run


def test_init_scaffolds_every_canonical_subdir(tmp_path: Path) -> None:
    env = _env(tmp_path)
    assert run_cli(["run", "init", "v641-dev0"], env).returncode == 0
    base = _run_base(tmp_path)
    for name in CANONICAL_SUBDIRS:
        assert (base / name).is_dir(), f"{name}/ not scaffolded by run init"


def test_layout_reports_ok_on_a_fresh_run(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    proc = run_cli(["run", "layout", "v641-dev0"], env)
    assert proc.returncode == 0, proc.stderr
    assert "missing" not in proc.stdout


def test_layout_exits_6_on_drift_and_does_not_repair(tmp_path: Path) -> None:
    """Read-only by default so it is safe against a live sprint; exit 6 is the
    mechanical stop, matching `wave pending` / `wave verify`."""
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    base = _run_base(tmp_path)
    shutil.rmtree(base / "graph")
    proc = run_cli(["run", "layout", "v641-dev0"], env)
    assert proc.returncode == 6, proc.stdout
    assert "graph" in proc.stdout
    assert not (base / "graph").exists(), "read-only default must not repair"


def test_layout_repair_is_idempotent(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    base = _run_base(tmp_path)
    shutil.rmtree(base / "audits")
    first = run_cli(["run", "layout", "v641-dev0", "--repair"], env)
    assert first.returncode == 0, first.stderr
    assert (base / "audits").is_dir()
    second = run_cli(["run", "layout", "v641-dev0", "--repair"], env)
    assert second.returncode == 0
    assert "created" not in second.stdout


def test_layout_json_lists_present_tracked_artifacts(tmp_path: Path) -> None:
    env = _env(tmp_path)
    run_cli(["run", "init", "v641-dev0"], env)
    (_run_base(tmp_path) / "seed.md").write_text("# seed\n")
    proc = run_cli(["run", "layout", "v641-dev0", "--json"], env)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["missing"] == []
    assert payload["tracked_files_present"] == ["seed.md"]


def test_layout_missing_run_exits_5(tmp_path: Path) -> None:
    proc = run_cli(["run", "layout", "v641-dev0"], _env(tmp_path))
    assert proc.returncode == 5, proc.stdout
