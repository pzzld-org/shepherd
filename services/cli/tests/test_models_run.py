"""Direct unit tests for ``shepherd_cli.models_run.parse_declared_lane_ids`` (W9-F3).

W8R-R5 (commit ``6f540a1``) bounded this function's table scan at the next
markdown heading, fixing a defect where an EMPTY ``## Lane projection``
section (exactly what ``templates/plan.md.j2``'s ``run init`` scaffold
renders -- the section holds only a Jinja comment until PLAN-GATE appends
the real table) let the scan wander past the section into a LATER,
unrelated section and adopt the first pipe-table it found there, provided
that table was also headed ``lane_id``. That made ``run wave pending`` exit
6 on lanes the run never actually declared. W8R-R5 shipped the fix with NO
regression test -- an explicit CLAUDE.md violation this file closes.

``test_run.py`` already exercises this function, but only INDIRECTLY, at
CLI-subprocess granularity (``shepherd run wave pending``), and only for
the "declared lane never registered" (#1 GATE-EXIT-CODE-MISMATCH / DF-63)
scenario -- never the "section renders empty, a later section confuses the
scan" shape this file exists for, and never the parser's own edge cases
(separator-cell variants, decorated/mixed-case cell values, a table with
no separator row) in isolation. ``test_run_ledger.py`` covers a disjoint
module (``verdicts.py``) entirely and has no coverage of this function at
all. Extending either would bury a pure-function unit-test concern inside
a CLI-subprocess-granularity suite; this file is new rather than an
extension of either, matching this package's established split between
CLI-level suites and pure-library-level suites (``test_verdicts.py``,
``test_config_schema.py``).

Every assertion below runs ``parse_declared_lane_ids`` in a fresh ``${PY}
-c`` subprocess rather than importing ``shepherd_cli`` into the pytest
process -- the "never import shepherd_cli into the pytest process itself"
convention ``conftest.py``'s own module docstring states and
``test_verdicts.py``/``test_config_schema.py`` already follow for testing a
pure library function without a full CLI invocation.

PROVE-IT-CAN-FAIL evidence (recorded here, not re-run by this suite): a
standalone script re-implementing the PRE-W8R-R5 algorithm verbatim (heading
-> end-of-file, no markdown-heading bound) was run against
``test_empty_lane_projection_section_never_adopts_a_later_lane_id_tables``'s
exact fixture text. The CURRENT (fixed) ``parse_declared_lane_ids`` returned
``[]``; the unbounded replica returned ``['l9-decoy']`` -- i.e. this test
fails (wrong list, not an error) against the unfixed algorithm and passes
against the shipped fix:

    current (bounded, fixed) parse_declared_lane_ids -> []
    pre-fix (unbounded) replica                       -> ['l9-decoy']
    OK: fixture is falsifiable -- fixed==[] , pre-fix==['l9-decoy']

``shepherd_cli/models_run.py`` is outside this file's ``[FILE-SCOPE]``, so
the replica lives only in that throwaway script, never as a temporary edit
to the shipped module -- and per #256 resource discipline this suite is not
run here either; the central verifier runs it once, after this phase.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import PY, REPO_ROOT, clean_env_dict

#: The live, running sprint's own plan -- its exact declared-lane table
#: (``.shepherd/runs/v645/plan.md`` §Lane projection) is the real-world
#: shape ``parse_declared_lane_ids``'s docstring cites verbatim.
_V645_PLAN = REPO_ROOT / ".shepherd" / "runs" / "v645" / "plan.md"

#: Dispatcher snippet: reads ``{"plan_text": ...}`` JSON on stdin, prints
#: ``parse_declared_lane_ids(plan_text)``'s JSON-encoded return value on
#: stdout. One process per call (module docstring: never an in-process
#: import).
_SNIPPET = """\
import json
import sys

from shepherd_cli.models_run import parse_declared_lane_ids

plan_text = json.loads(sys.stdin.read())["plan_text"]
print(json.dumps(parse_declared_lane_ids(plan_text)))
"""


def _parse(plan_text: str) -> list[str]:
    """Run ``parse_declared_lane_ids(plan_text)`` in a fresh subprocess.

    Args:
        plan_text: The full text of a run's ``plan.md``.

    Returns:
        The declared lane ids, in table order.
    """
    proc = subprocess.run(
        [PY, "-c", _SNIPPET],
        input=json.dumps({"plan_text": plan_text}),
        env=clean_env_dict(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"parse_declared_lane_ids snippet failed (exit {proc.returncode}): "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# The headline regression: an EMPTY ``## Lane projection`` section must
# never fall through into a later section's pipe-table, even when that
# later table is also headed ``lane_id``.
# --------------------------------------------------------------------------
def test_empty_lane_projection_section_never_adopts_a_later_lane_id_tables() -> None:
    """``## Lane projection`` renders empty (``run init``'s real scaffold
    shape: heading, blank, blank, next heading -- verified by rendering
    ``templates/plan.md.j2`` itself) while a LATER, unrelated section (a
    lane-status table, a deviations table -- anything else headed
    ``lane_id``) carries a pipe-table. The declared set must be EMPTY, not
    that later table's rows -- the exact W8R-R5 defect: an unbounded scan
    reads past ``## Lane projection`` to end-of-file and adopts the first
    ``lane_id``-headed table it finds anywhere after the heading."""
    plan_text = (
        "# plan\n\n"
        "## Lane projection\n\n\n"  # exact rendered shape: heading + 2 blank lines
        "## Proof of dispatch\n\n"
        "Some unrelated prose that follows the empty section.\n\n"
        "## Lane status\n\n"
        "| lane_id | state |\n"
        "|---|---|\n"
        "| l9-decoy | complete |\n"
    )
    assert _parse(plan_text) == [], (
        "an empty Lane projection section must declare nothing, even when a "
        "later section carries a lane_id-headed table (W8R-R5 regression)"
    )


def test_lane_projection_heading_with_no_body_at_all_is_also_empty() -> None:
    """A plan that ends immediately after the heading (no next heading, no
    table, no prose) is the same "nothing declared" case -- must not crash
    scanning past end-of-file."""
    plan_text = "# plan\n\n## Lane projection\n"
    assert _parse(plan_text) == []


# --------------------------------------------------------------------------
# The normal, populated case -- pinned at the unit level (not just the
# CLI-subprocess level test_run.py already covers).
# --------------------------------------------------------------------------
def test_populated_lane_projection_parses_correctly() -> None:
    plan_text = (
        "## Lane projection\n\n"
        "Prose paragraph before the table, matching the live doc shape.\n\n"
        "| lane_id | member_steps | file_scope.exclusive | parallel_with |\n"
        "|---|---|---|---|\n"
        "| `l1-alpha` | W1-S1 | `crates/alpha` | - |\n"
        "| `l2-beta` | W1-S2 | `crates/beta` | l1-alpha |\n"
        "\n"
        "## Proof of dispatch\n"
    )
    assert _parse(plan_text) == ["l1-alpha", "l2-beta"]


def test_live_v645_plan_still_yields_its_five_lanes() -> None:
    """Regression guard for the RUNNING sprint's own plan: a change to this
    parser must not silently stop recognizing ``.shepherd/runs/v645/plan.md``'s
    real, current 5-lane projection."""
    assert _V645_PLAN.is_file(), f"expected the live run plan at {_V645_PLAN}"
    lane_ids = _parse(_V645_PLAN.read_text())
    assert lane_ids == [
        "l1-engine",
        "l2-registry",
        "l3-surface",
        "l4-conformance",
        "l5-harness",
    ]


# --------------------------------------------------------------------------
# Parser edge cases named explicitly by the W9-F3 brief.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "separator_row",
    ["|---|---|", "|:--|:--|", "|--:|--:|", "|:-:|:-:|", "| :-- | --: |"],
)
def test_separator_row_variants_are_recognized_not_mistaken_for_data(separator_row: str) -> None:
    """``:--``/``--:``/``:-:`` alignment markers must be recognized as the
    header/data divider, not misread as an extra data row."""
    plan_text = f"## Lane projection\n\n| lane_id | notes |\n{separator_row}\n| `Lane-One` | ok |\n"
    assert _parse(plan_text) == ["lane-one"]


def test_backtick_and_mixed_case_cell_values_are_normalized() -> None:
    """Plan prose decorates lane ids with backticks or emphasis and drifts
    on casing -- every variant normalizes to the same lowercase, bare id
    :func:`validate_id` already holds registered lane ids to."""
    plan_text = (
        "## Lane projection\n\n"
        "| lane_id | notes |\n"
        "|---|---|\n"
        "| `L1-Engine` | backtick-wrapped, mixed case |\n"
        "| **L2-Registry** | emphasis-wrapped, mixed case |\n"
        "| L3-SURFACE | bare, upper case |\n"
    )
    assert _parse(plan_text) == ["l1-engine", "l2-registry", "l3-surface"]


def test_table_with_no_separator_row_still_parses_its_data_rows() -> None:
    """A malformed-but-common shape (header row immediately followed by
    data, no ``|---|---|`` divider at all) must still yield every data row
    -- the first non-separator-shaped row after the header is data, not a
    reason to stop."""
    plan_text = (
        "## Lane projection\n\n"
        "| lane_id | notes |\n"
        "| lane-a | first row, no separator |\n"
        "| lane-b | second row |\n"
    )
    assert _parse(plan_text) == ["lane-a", "lane-b"]


# --------------------------------------------------------------------------
# Pre-existing false-positive-free baselines (mirrors test_run.py's own
# no-section coverage, pinned here at the unit level too).
# --------------------------------------------------------------------------
def test_no_lane_projection_section_at_all_declares_nothing() -> None:
    assert _parse("# plan\n\nno lane table here.\n") == []


def test_empty_plan_text_declares_nothing() -> None:
    assert _parse("") == []
