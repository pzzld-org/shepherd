"""Tests for ``shepherd_cli.verdicts`` — the v6.4.3 ledger custody + step/verdict
join pure-function core (#261/#262).

``shepherd_cli.verdicts`` is a pure-function module: no typer, no CLI
surface, no ``sys.exit``. It is exercised here via ``${PY} -c "..."``
snippets against a small dispatcher script (:data:`_VERDICTS_SNIPPET`) run
as a fresh subprocess per call — the SAME "never import ``shepherd_cli``
into the pytest process itself" convention ``conftest.py``'s own module
docstring establishes and ``test_config_schema.py``/``test_db_readonly.py``
already follow for testing a library function without a full CLI
invocation. This keeps every test's environment (cwd, ``SHEPHERD_WORKDIR``,
etc.) fully explicit, exactly like the rest of this suite, even though
``shepherd run ledger``/``shepherd run wave verify`` — the thin typer
wrapper commands that will actually call this module in production — do
not exist yet (a follow-on change; not this file's scope).

Two field incidents shape the two most load-bearing tests below, named so
the reason is obvious without reading the body:

- ``test_verdict_field_is_positional_pass_row_prose_containing_redo_still_parses_pass``
  — the verdict is field 3, POSITIONAL. A real PASS row's free-form prose
  once read "REDO iter 2 cleared"; a grep-``PASS|REDO|FAIL``-across-the-line
  reader misparses that row as REDO.
- ``test_last_matching_row_wins_redo_then_pass_resolves_pass_not_first`` (plus
  its mirror, ``..._pass_then_redo_resolves_redo``) — the LAST matching row
  wins, never the first. A cleared REDO -> PASS loop is the normal shape of
  a step that failed once and passed on retry.

Exit-code-shaped spec bullets (0 / 6 / 5 for ``shepherd run wave verify``)
are pinned here at THIS module's actual return-value level, since the exit
codes themselves belong to a typer command that does not exist in this
diff: :attr:`JoinResult.ok` is the pure-function analog of exit 0 (True) vs
exit 6 (False, findings present), and :func:`enumerate_plan_steps` raising
``FileNotFoundError`` is the analog of exit 5 (missing run/lane-plan
directory) that a CLI wrapper will catch and translate. Likewise, the
already-tested ``resolve_repo_root()``/``resolve_workdir()`` primary-worktree
binding (spec section 1, #221/#231) is NOT re-tested here in isolation --
``test_resolution.py`` already pins it -- this file adds exactly one test
confirming :func:`shepherd_cli.verdicts.ledger_path` inherits that binding
correctly when called from inside a linked worktree, since that's the one
new code path spec section 1 adds on top of it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, clean_env_dict

# --------------------------------------------------------------------------
# Dispatcher snippet: one small script, many modes, run as a fresh
# subprocess per call (see module docstring). Input is JSON on stdin,
# output is one JSON value on stdout. Pydantic models are dumped via
# ``.model_dump(mode="json")`` so the test process only ever deals in
# plain dicts/lists/scalars decoded from stdout.
# --------------------------------------------------------------------------
_VERDICTS_SNIPPET = """\
import json
import sys

from shepherd_cli import verdicts as v

mode = sys.argv[1]
payload = json.loads(sys.stdin.read())


def _dump(x):
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, (list, tuple)):
        return [_dump(i) for i in x]
    return x


if mode == "parse_ledger_line":
    print(json.dumps(_dump(v.parse_ledger_line(payload["line"]))))

elif mode == "parse_ledger":
    rows, malformed = v.parse_ledger(payload["text"])
    print(json.dumps({"rows": _dump(rows), "malformed": _dump(malformed)}))

elif mode == "resolve_step_verdict":
    step = v.StepId(**payload["step"])
    rows, _malformed = v.parse_ledger(payload["ledger_text"])
    print(json.dumps(v.resolve_step_verdict(step, rows)))

elif mode == "join":
    steps = [v.StepId(**s) for s in payload["steps"]]
    rows, malformed = v.parse_ledger(payload["ledger_text"])
    result = v.join(steps, rows, malformed=malformed)
    print(json.dumps({
        "steps": _dump(result.steps),
        "findings": _dump(result.findings),
        "ok": result.ok,
    }))

elif mode == "enumerate_plan_steps":
    try:
        steps = v.enumerate_plan_steps(payload["run_dir"])
        print(json.dumps({"ok": True, "steps": _dump(steps)}))
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": "FileNotFoundError", "message": str(exc)}))

elif mode == "ledger_path":
    print(json.dumps(v.ledger_path(payload["run"], payload.get("workdir"))))

elif mode == "compare_worktree_ledgers":
    divs = v.compare_worktree_ledgers(payload["primary_text"], payload["worktrees"])
    print(json.dumps(_dump(divs)))

else:
    raise SystemExit(f"unknown mode: {mode}")
"""


def _run(
    mode: str,
    payload: dict,
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one ``_VERDICTS_SNIPPET`` mode as a fresh subprocess.

    Args:
        mode: The dispatcher mode (first positional argv token).
        payload: JSON-encoded on stdin.
        env: Full environment for the subprocess; defaults to
            :func:`conftest.clean_env_dict`.
        cwd: Working directory for the subprocess; defaults to
            ``CLI_ROOT`` (mirrors ``conftest.run_cli``'s default).

    Returns:
        The completed subprocess (stdout/stderr captured as text).
    """
    return subprocess.run(
        [PY, "-c", _VERDICTS_SNIPPET, mode],
        input=json.dumps(payload),
        env=env if env is not None else clean_env_dict(),
        cwd=str(cwd) if cwd is not None else str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


def _parse_ledger_line(line: str) -> dict | None:
    proc = _run("parse_ledger_line", {"line": line})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _parse_ledger(text: str) -> tuple[list[dict], list[dict]]:
    proc = _run("parse_ledger", {"text": text})
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    return out["rows"], out["malformed"]


def _resolve_step_verdict(step: dict, ledger_text: str) -> str | None:
    proc = _run("resolve_step_verdict", {"step": step, "ledger_text": ledger_text})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _join(steps: list[dict], ledger_text: str) -> dict:
    proc = _run("join", {"steps": steps, "ledger_text": ledger_text})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _enumerate_plan_steps(run_dir: Path) -> dict:
    proc = _run("enumerate_plan_steps", {"run_dir": str(run_dir)})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _ledger_path(run: str, *, workdir: str | None = None, env: dict[str, str], cwd: Path) -> str:
    proc = _run("ledger_path", {"run": run, "workdir": workdir}, env=env, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _compare_worktree_ledgers(primary_text: str, worktrees: dict[str, str | None]) -> list[dict]:
    proc = _run("compare_worktree_ledgers", {"primary_text": primary_text, "worktrees": worktrees})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _step(wave: int, lane: int, step: int) -> dict:
    return {"wave": wave, "lane": lane, "step": step}


def _plan_md(*step_ids: str) -> str:
    """Build a minimal lane plan.md with one ``### <id>: title`` heading per step id."""
    return "".join(f"### {sid}: some step\n\nbody text\n\n" for sid in step_ids)


def _plan_id(step: dict) -> str:
    """The plan-file spelling of a dumped StepId dict (``plan_id`` is a
    computed property, not a pydantic field, so ``model_dump`` never
    serializes it -- reconstruct it from the three plain fields instead)."""
    return f"W{step['wave']}-L{step['lane']}-S{step['step']}"


# ==========================================================================
# Ledger line grammar (spec section 2) — parse_ledger_line / parse_ledger.
# ==========================================================================
def test_verdict_field_is_positional_pass_row_prose_containing_redo_still_parses_pass() -> None:
    """The verdict is field 3, POSITIONAL. Never grep PASS|REDO|FAIL across
    the line — a real PASS row's prose once read "REDO iter 2 cleared",
    which a grep-based reader would misparse as REDO."""
    row = _parse_ledger_line("L3 w3-s1 PASS REDO iter 2 cleared")
    assert row is not None
    assert row["verdict"] == "PASS"
    assert row["prose"] == "REDO iter 2 cleared"


def test_verdict_field_is_positional_fail_row_prose_containing_pass_still_parses_fail() -> None:
    """Same rule, the other direction: a FAIL row whose prose contains the
    word PASS must still parse as FAIL, not be grepped into PASS."""
    row = _parse_ledger_line("L2 w1-s4 FAIL almost PASSed but broke at the end")
    assert row is not None
    assert row["verdict"] == "FAIL"


def test_lane_token_case_insensitive() -> None:
    upper = _parse_ledger_line("L3 w3-s1 PASS ok")
    lower = _parse_ledger_line("l3 w3-s1 PASS ok")
    assert upper is not None and lower is not None
    assert upper["lane"] == lower["lane"] == "L3"
    assert upper["lane_num"] == lower["lane_num"] == 3


def test_verdict_token_case_insensitive_normalizes_uppercase() -> None:
    for token in ("pass", "Pass", "PASS"):
        row = _parse_ledger_line(f"L1 w1-s1 {token} ok")
        assert row is not None
        assert row["verdict"] == "PASS"


def test_scope_bare_wave_has_no_step() -> None:
    row = _parse_ledger_line("L4 w3 REDO whole wave redo")
    assert row is not None
    assert row["wave"] == 3
    assert row["step"] is None


def test_scope_exact_step() -> None:
    row = _parse_ledger_line("L4 w3-s1 PASS ok")
    assert row is not None
    assert row["wave"] == 3
    assert row["step"] == 1


def test_scope_substep_rolls_up_to_parent_step_number() -> None:
    """``w2-s1g2``/``w2-s1b`` both carry step=1 once parsed — parse-time
    rollup, no special-casing needed at match time (see verdicts.py's
    module docstring)."""
    g2 = _parse_ledger_line("L1 w2-s1g2 PASS sub-step g2")
    b = _parse_ledger_line("L1 w2-s1b PASS sub-step b")
    assert g2 is not None and b is not None
    assert (g2["wave"], g2["step"]) == (2, 1)
    assert (b["wave"], b["step"]) == (2, 1)


def test_blank_and_comment_lines_return_none() -> None:
    assert _parse_ledger_line("") is None
    assert _parse_ledger_line("   ") is None
    assert _parse_ledger_line("# a comment") is None
    assert _parse_ledger_line("   # indented comment") is None


def test_malformed_lane_token_returns_none() -> None:
    assert _parse_ledger_line("X3 w3-s1 PASS ok") is None
    assert _parse_ledger_line("lane3 w3-s1 PASS ok") is None


def test_malformed_verdict_token_returns_none() -> None:
    assert _parse_ledger_line("L3 w3-s1 MAYBE ok") is None
    assert _parse_ledger_line("L3 w3-s1 PASSED ok") is None  # not an exact PASS token


def test_malformed_scope_token_returns_none() -> None:
    assert _parse_ledger_line("L3 wave3 PASS ok") is None
    assert _parse_ledger_line("L3 w3-1 PASS ok") is None  # missing 's' before step digits


def test_too_few_fields_returns_none() -> None:
    assert _parse_ledger_line("L3 w3-s1") is None
    assert _parse_ledger_line("L3") is None


def test_parse_ledger_skips_comments_and_blanks_without_reporting_malformed() -> None:
    text = "# header comment\n\nL1 w1-s1 PASS ok\n   \n  # indented comment\n"
    rows, malformed = _parse_ledger(text)
    assert len(rows) == 1
    assert malformed == []


def test_parse_ledger_reports_malformed_row_not_crashed_on() -> None:
    """A ledger line that does not parse is reported, never silently
    dropped and never crashed on."""
    text = "L1 w1-s1 PASS ok\nnot a valid ledger line\nL1 w1-s2 PASS also ok\n"
    rows, malformed = _parse_ledger(text)
    assert [r["line_no"] for r in rows] == [1, 3]
    assert len(malformed) == 1
    assert malformed[0]["line_no"] == 2
    assert malformed[0]["raw"] == "not a valid ledger line"
    assert "lane token" in malformed[0]["reason"]


def test_parse_ledger_line_numbers_are_one_based_and_in_file_order() -> None:
    text = "\n".join(["L1 w1-s1 PASS a", "L1 w1-s2 PASS b", "L1 w1-s3 PASS c"])
    rows, malformed = _parse_ledger(text)
    assert malformed == []
    assert [r["line_no"] for r in rows] == [1, 2, 3]


# ==========================================================================
# Last-wins resolution (spec section 4.3).
# ==========================================================================
def test_last_matching_row_wins_redo_then_pass_resolves_pass_not_first() -> None:
    """LAST matching row wins, never first. REDO -> PASS is the normal
    cleared-redo shape; a first-wins reader would report this step as
    still failing."""
    ledger_text = "L3 w3-s1 REDO needs more work\nL3 w3-s1 PASS cleared on retry\n"
    verdict = _resolve_step_verdict(_step(3, 3, 1), ledger_text)
    assert verdict == "PASS"


def test_last_matching_row_wins_pass_then_redo_resolves_redo() -> None:
    """The reverse ordering: PASS then REDO must resolve REDO — proves
    this is genuinely last-wins, not a "PASS always sticks" shortcut."""
    ledger_text = "L3 w3-s1 PASS looked fine at first\nL3 w3-s1 REDO actually broke it\n"
    verdict = _resolve_step_verdict(_step(3, 3, 1), ledger_text)
    assert verdict == "REDO"


def test_resolve_step_verdict_none_when_no_matching_row() -> None:
    ledger_text = "L1 w1-s1 PASS unrelated step\n"
    assert _resolve_step_verdict(_step(3, 3, 1), ledger_text) is None


def test_resolve_step_verdict_bare_wave_subsumes_step() -> None:
    ledger_text = "L3 w3 PASS whole wave cleared\n"
    assert _resolve_step_verdict(_step(3, 3, 1), ledger_text) == "PASS"
    assert _resolve_step_verdict(_step(3, 3, 2), ledger_text) == "PASS"


def test_resolve_step_verdict_last_wins_across_bare_wave_and_exact_step() -> None:
    """A bare-wave row and a later exact-step row for the SAME step: the
    later one (file order) wins regardless of which spelling it uses."""
    ledger_text = "L3 w3 REDO whole wave needs work\nL3 w3-s1 PASS this one cleared\n"
    assert _resolve_step_verdict(_step(3, 3, 1), ledger_text) == "PASS"
    # A sibling step in the same wave still sees only the bare-wave REDO.
    assert _resolve_step_verdict(_step(3, 3, 2), ledger_text) == "REDO"


# ==========================================================================
# join() — the step/ledger join (spec section 4.4).
# ==========================================================================
def test_join_bare_wave_subsumes_every_step_of_that_lane_in_that_wave() -> None:
    steps = [_step(3, 3, 1), _step(3, 3, 2)]
    ledger_text = "L3 w3 PASS whole wave cleared\n"
    result = _join(steps, ledger_text)
    assert result["ok"] is True
    assert [(s["step"], s["verdict"]) for s in result["steps"]] == [
        ("W3-L3-S1", "PASS"),
        ("W3-L3-S2", "PASS"),
    ]
    assert result["findings"] == []


def test_join_substeps_resolve_against_parent_step() -> None:
    steps = [_step(2, 1, 1)]
    ledger_text = "L1 w2-s1g2 PASS sub g2\nL1 w2-s1b PASS sub b\n"
    result = _join(steps, ledger_text)
    assert result["ok"] is True
    assert result["steps"][0]["step"] == "W2-L1-S1"
    assert result["steps"][0]["verdict"] == "PASS"


def test_join_no_verdict_for_every_step_with_no_row() -> None:
    """The #262 headline case: all three W3-L4-S* steps have zero matching
    ledger rows and must each surface as their own NO-VERDICT finding."""
    steps = [_step(3, 4, 1), _step(3, 4, 2), _step(3, 4, 3)]
    ledger_text = ""  # nothing recorded for lane 4 at all
    result = _join(steps, ledger_text)
    assert result["ok"] is False
    assert [s["verdict"] for s in result["steps"]] == [None, None, None]
    assert sorted(f["step"] for f in result["findings"] if f["kind"] == "NO-VERDICT") == [
        "W3-L4-S1",
        "W3-L4-S2",
        "W3-L4-S3",
    ]


def test_join_unresolved_verdict_for_last_redo_or_fail() -> None:
    steps = [_step(1, 1, 1), _step(1, 1, 2)]
    ledger_text = "L1 w1-s1 REDO still broken\nL1 w1-s2 FAIL outright\n"
    result = _join(steps, ledger_text)
    assert result["ok"] is False
    kinds_by_step = {f["step"]: f["kind"] for f in result["findings"]}
    assert kinds_by_step["W1-L1-S1"] == "UNRESOLVED-VERDICT"
    assert kinds_by_step["W1-L1-S2"] == "UNRESOLVED-VERDICT"


def test_join_orphan_verdict_for_row_naming_step_in_no_lane_plan() -> None:
    """A field incident: a step minted in the task list but never written
    into any lane plan. A step-based check alone never mentions it — only
    the reverse (ledger -> plan) direction catches it."""
    steps = [_step(3, 1, 1)]  # lane 1's plan only has step 1
    ledger_text = "L1 w3-s3 PASS a step no plan ever declared\n"
    result = _join(steps, ledger_text)
    orphans = [f for f in result["findings"] if f["kind"] == "ORPHAN-VERDICT"]
    assert len(orphans) == 1
    assert orphans[0]["step"] == "W3-L1-S3"


def test_join_bare_wave_orphan_only_when_lane_has_no_steps_in_that_wave_at_all() -> None:
    """A bare w{n} row is an orphan ONLY when lane l has no steps in wave n
    at all — not merely for failing to match one specific step."""
    # lane 5 has a step in wave 3: a bare w3 row for lane 5 legitimately
    # subsumes it and must NOT be flagged orphan.
    steps = [_step(3, 5, 1)]
    not_orphan = _join(steps, "L5 w3 PASS subsumes the one step\n")
    assert not_orphan["findings"] == []

    # lane 9 has NO steps in wave 3 (or anywhere) -- its bare w3 row is a
    # genuine orphan.
    is_orphan = _join(steps, "L9 w3 PASS lane 9 has no steps anywhere\n")
    orphans = [f for f in is_orphan["findings"] if f["kind"] == "ORPHAN-VERDICT"]
    assert len(orphans) == 1
    assert orphans[0]["step"] is None
    assert "w3" in orphans[0]["detail"]


def test_join_ok_true_iff_no_findings_the_exit_0_analog() -> None:
    """JoinResult.ok is the pure-function analog of ``shepherd run wave
    verify``'s exit 0 (clean) — the CLI wrapper (not built here) maps this
    directly to its exit code."""
    steps = [_step(1, 1, 1)]
    clean = _join(steps, "L1 w1-s1 PASS ok\n")
    assert clean["ok"] is True

    dirty = _join(steps, "L1 w1-s1 REDO not ok\n")
    assert dirty["ok"] is False


def test_join_folds_malformed_rows_into_findings_reported_not_crashed_on() -> None:
    steps: list[dict] = []
    ledger_text = "L1 w1-s1 PASS ok\ngarbage line\n"
    result = _join(steps, ledger_text)
    malformed_findings = [f for f in result["findings"] if f["kind"] == "MALFORMED-ROW"]
    assert len(malformed_findings) == 1
    assert malformed_findings[0]["raw"] == "garbage line"


# ==========================================================================
# enumerate_plan_steps (spec section 3).
# ==========================================================================
def test_enumerate_plan_steps_reads_headings_dedups_preserves_first_seen_order(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    lane_a = run_dir / "lanes" / "lane-a"
    lane_b = run_dir / "lanes" / "lane-b"
    lane_a.mkdir(parents=True)
    lane_b.mkdir(parents=True)
    (lane_a / "plan.md").write_text(_plan_md("W2-L1-S1", "W2-L1-S1", "W3-L1-S3"))
    (lane_b / "plan.md").write_text(_plan_md("W3-L4-S1", "W3-L4-S2", "W3-L4-S3"))

    out = _enumerate_plan_steps(run_dir)
    assert out["ok"] is True
    plan_ids = [_plan_id(s) for s in out["steps"]]
    assert plan_ids == ["W2-L1-S1", "W3-L1-S3", "W3-L4-S1", "W3-L4-S2", "W3-L4-S3"]


def test_enumerate_plan_steps_missing_lanes_dir_raises_the_exit_5_analog(tmp_path: Path) -> None:
    """The pure-function analog of exit 5 ("run or lane-plan directory
    missing") — a CLI wrapper (not built here) is expected to catch this
    and translate it."""
    out = _enumerate_plan_steps(tmp_path / "runs" / "does-not-exist")
    assert out["ok"] is False
    assert out["error"] == "FileNotFoundError"


def test_enumerate_plan_steps_ignores_non_heading_step_id_mentions_too(tmp_path: Path) -> None:
    """Enumeration is "a regex over the whole file" (spec section 3), not
    heading-only — a step id mentioned in body prose still counts."""
    run_dir = tmp_path / "runs" / "r1"
    lane_a = run_dir / "lanes" / "lane-a"
    lane_a.mkdir(parents=True)
    (lane_a / "plan.md").write_text(
        "### W1-L1-S1: title\n\nSee also W1-L1-S2 mentioned in prose, no heading for it.\n"
    )
    out = _enumerate_plan_steps(run_dir)
    assert out["ok"] is True
    assert [_plan_id(s) for s in out["steps"]] == ["W1-L1-S1", "W1-L1-S2"]


# ==========================================================================
# ledger_path (spec section 1) — custody.
# ==========================================================================
def test_ledger_path_is_workdir_runs_run_auditor_verdicts_txt(tmp_path: Path) -> None:
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(tmp_path / ".shepherd")
    path = _ledger_path("v641-dev0", env=env, cwd=tmp_path)
    assert path == str(tmp_path / ".shepherd" / "runs" / "v641-dev0" / "auditor-verdicts.txt")


def test_ledger_path_rejects_invalid_run_id(tmp_path: Path) -> None:
    env = clean_env_dict()
    env["SHEPHERD_WORKDIR"] = str(tmp_path / ".shepherd")
    proc = _run("ledger_path", {"run": "../escape", "workdir": None}, env=env, cwd=tmp_path)
    assert proc.returncode != 0
    assert "invalid run id" in proc.stderr


def _init_repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a real git repo with one linked worktree (mirrors
    test_resolution.py's ``_init_repo_with_worktree`` — small intentional
    duplication, this suite's established self-contained-module
    convention; see test_config_schema.py's module docstring)."""
    main = tmp_path / "main"
    main.mkdir()
    env = clean_env_dict()
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
    )
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(args, cwd=main, env=env, check=True, capture_output=True)
    wt = tmp_path / "lane-wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(wt), "-b", "lane-1", "main"],
        cwd=main,
        env=env,
        check=True,
        capture_output=True,
    )
    return main, wt


def test_ledger_path_from_linked_worktree_resolves_to_primary_checkout(tmp_path: Path) -> None:
    """#261/#221/#231: ledger_path() called from inside a linked worktree
    must resolve to the PRIMARY checkout's ledger, never a divorced copy
    under the worktree's own .shepherd/ — the exact custody guarantee
    spec section 1 says must not regress."""
    main, wt = _init_repo_with_worktree(tmp_path)
    (main / ".shepherd").mkdir()
    (wt / ".shepherd").mkdir()  # a tracked subtree exists in the worktree checkout too

    env = clean_env_dict()  # no SHEPHERD_WORKDIR override -- auto-detect via git
    path = _ledger_path("v641-dev0", env=env, cwd=wt)

    assert path == str(
        (main / ".shepherd" / "runs" / "v641-dev0" / "auditor-verdicts.txt").resolve()
    )
    assert not path.startswith(str(wt.resolve()))


# ==========================================================================
# compare_worktree_ledgers (spec section 1.2) — divergence, both directions.
# ==========================================================================
def test_worktree_row_absent_from_primary_is_flagged_a_divergence() -> None:
    """FAIL case: a linked worktree holds a row the primary lacks -- the
    destructive shape (merging it could silently drop a sibling row)."""
    primary_text = "L1 w3-s1 PASS ok\n"
    worktrees = {"wt-ahead": "L1 w3-s1 PASS ok\nL2 w3-s1 PASS only the worktree has this\n"}
    divs = _compare_worktree_ledgers(primary_text, worktrees)
    assert len(divs) == 1
    assert divs[0]["worktree"] == "wt-ahead"
    assert "L2 w3-s1 PASS only the worktree has this" == divs[0]["row"]


def test_worktree_merely_behind_primary_is_never_flagged() -> None:
    """HARD requirement: a worktree missing rows the PRIMARY has (every
    lane's normal state between merges) must never be flagged -- that
    would fire constantly and get ignored within the hour."""
    primary_text = "L1 w3-s1 PASS ok\nL2 w3-s1 PASS also ok\nL3 w3-s1 PASS still ok\n"
    worktrees = {"wt-behind": "L1 w3-s1 PASS ok\n"}  # missing L2 and L3's rows
    divs = _compare_worktree_ledgers(primary_text, worktrees)
    assert divs == []


def test_worktree_absent_copy_is_not_a_finding() -> None:
    """A worktree with no ledger file at all is fine, not a finding."""
    divs = _compare_worktree_ledgers("L1 w3-s1 PASS ok\n", {"wt-no-copy": None})
    assert divs == []


def test_compare_worktree_ledgers_both_directions_in_one_call() -> None:
    """Ahead and behind together: only the ahead worktree's extra row is
    flagged; the behind worktree contributes nothing."""
    primary_text = "L1 w3-s1 PASS ok\nL2 w3-s1 PASS ok\n"
    worktrees = {
        "wt-ahead": "L1 w3-s1 PASS ok\nL2 w3-s1 PASS ok\nL9 w9-s1 PASS extra\n",
        "wt-behind": "L1 w3-s1 PASS ok\n",
        "wt-absent": None,
    }
    divs = _compare_worktree_ledgers(primary_text, worktrees)
    assert [(d["worktree"], d["row"]) for d in divs] == [("wt-ahead", "L9 w9-s1 PASS extra")]


def test_compare_worktree_ledgers_normalizes_trailing_whitespace_and_skips_comments() -> None:
    """Row comparison is on the NORMALIZED row -- trailing whitespace
    stripped, blank lines and #-comment lines skipped -- never raw bytes."""
    primary_text = "L1 w3-s1 PASS ok   \n\n# a comment\n"
    worktrees = {"wt": "L1 w3-s1 PASS ok\n\n# a different comment\n"}
    # Same row content once trailing whitespace is stripped, and both
    # comment lines are ignored entirely -- no divergence.
    divs = _compare_worktree_ledgers(primary_text, worktrees)
    assert divs == []


def test_compare_worktree_ledgers_dedups_repeated_row_within_one_worktree() -> None:
    primary_text = ""
    worktrees = {"wt": "L1 w3-s1 PASS dup\nL1 w3-s1 PASS dup\n"}
    divs = _compare_worktree_ledgers(primary_text, worktrees)
    assert len(divs) == 1
