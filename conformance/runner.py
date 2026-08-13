#!/usr/bin/env python3
"""conformance/runner.py -- the ``--impl=python`` execution path for run.sh.

Not invoked directly (``run.sh`` resolves the venv interpreter and always
calls this by absolute path); kept as a thin argparse wrapper so
:mod:`conformance.lib.harness` stays free of CLI-parsing concerns.

Usage:
    runner.py --cases-dir DIR [--suite NAME] [--count] [--record]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import harness  # noqa: E402  (sys.path must be set first)


def main(argv: list[str]) -> int:
    """Parse args, discover cases, and either count/record/verify them.

    Args:
        argv: Command-line arguments (excluding the program name).

    Returns:
        0 on success (or ``--count``, unconditionally); 1 if any case
        failed verification, or if ``--suite`` matched zero cases.
    """
    parser = argparse.ArgumentParser(description="Run the shepherd CLI conformance corpus against --impl=python.")
    parser.add_argument("--cases-dir", required=True, help="Corpus root (conformance/cases).")
    parser.add_argument("--suite", default=None, help="Only run cases tagged with this suite.")
    parser.add_argument("--count", action="store_true", help="Print the (suite-filtered) case count and exit.")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Author-time only: (re)freeze expected/ from a live run instead of verifying against it.",
    )
    args = parser.parse_args(argv)

    cases_dir = Path(args.cases_dir)
    cases = harness.discover_cases(cases_dir, args.suite)

    if args.count:
        print(len(cases))
        return 0

    if not cases:
        print(f"conformance: no cases found (suite={args.suite!r}, cases_dir={cases_dir})", file=sys.stderr)
        return 1

    if args.record:
        for case in cases:
            harness.record_case(case)
            print(f"RECORDED  {case.case_id}")
        return 0

    failures = 0
    for case in cases:
        verdict = harness.verify_case(case)
        if verdict.passed:
            print(f"PASS  {case.case_id}")
        else:
            failures += 1
            print(f"FAIL  {case.case_id}")
            for diff in verdict.diffs:
                print(f"        {diff}")

    total = len(cases)
    print(f"conformance: {total - failures}/{total} passed (suite={args.suite or 'ALL'})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
