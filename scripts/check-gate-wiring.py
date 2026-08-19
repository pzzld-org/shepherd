#!/usr/bin/env python3
"""Every test file in the repository must be reachable from a runner.

WHY THIS EXISTS.

`scripts/tests/test_cli_authority_gate.sh` was correct, falsifiable, and
referenced by NOTHING. Because nothing ran it, it was free to rot, and it did:
by the time it was found it had accumulated three independent failures --
a ripgrep sweep over `$ROOT/bin` (a directory D4 retired, so rg exited 2 and
the `if` scored "no legacy bootstrap found" forever), a hooks.json assertion
that demanded the native dispatch shape for every hook and so broke the moment
the seven carrier hook scripts were restored, and three lifecycle assertions
still aimed at `claude_hook.rs` after the lifecycle moved to the harness-neutral
`native_hook.rs`. A correct unwired gate is worth exactly what an inert one is,
and it decays into a wrong one.

That is the third occurrence of this shape. `hooks/tests/run.sh` already had
it (a hand-maintained array covering 6 of 27 files, so 21 tests never ran) and
fixed it the right way: glob discovery, which cannot drift from the directory.
`scripts/tests/` has no runner of its own -- `scripts/gate.sh` names its
members one `step` at a time -- so the same drift is available there, and this
checker closes it.

THE RULE. A test file counts as wired when some OTHER tracked file names it:
`scripts/gate.sh`, a GitHub workflow, or another test that is itself wired
(reachability is transitive and computed to a fixed point, because
`test-release-workflow.sh` legitimately drives several others). Prose alone
does not wire anything: a mention in CHANGELOG.md or docs/ is a reference to a
test, not an execution of one, so those are excluded from the evidence set.

Run with --self-test to prove the rule can still fail.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent

# Directories holding files that are tests, not helpers of tests.
TEST_DIRS = ("scripts/tests", "hooks/tests")

# A test is a file that a runner could execute. `fixtures/` holds inputs, and
# `run.sh` is itself the runner.
TEST_SUFFIXES = (".sh", ".py", ".ps1")
NOT_TESTS = {"run.sh"}

# Files whose mention of a test is documentation, not execution. Counting these
# as wiring is what would let this checker pass a test that only CHANGELOG.md
# talks about.
PROSE = (".md", ".txt")


def tracked_files() -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [pathlib.Path(line) for line in out if line]


def discover_tests(root: pathlib.Path, tracked: list[pathlib.Path]) -> list[pathlib.Path]:
    found = []
    for rel in tracked:
        if not any(str(rel).startswith(d + "/") for d in TEST_DIRS):
            continue
        if "fixtures" in rel.parts:
            continue
        if rel.name in NOT_TESTS or rel.suffix not in TEST_SUFFIXES:
            continue
        if not rel.name.startswith(("test-", "test_", "lint_")):
            continue
        found.append(rel)
    return sorted(found)


def wiring_evidence(root: pathlib.Path, tracked: list[pathlib.Path]) -> dict[pathlib.Path, str]:
    """Map every candidate evidence file to its text, prose excluded."""
    evidence = {}
    for rel in tracked:
        if rel.suffix in PROSE:
            continue
        # This checker must never be its own evidence. The docstring above
        # names `test_cli_authority_gate.sh` while explaining that nothing
        # executed it -- and because `.py` is not prose, that mention silently
        # marked the file wired and made the live scan green on the exact
        # defect this file was written to catch. A checker that launders its
        # own finding is worse than no checker.
        if rel == pathlib.Path("scripts/check-gate-wiring.py"):
            continue
        # `.shepherd/` holds run records -- plans, worklists, evidence dumps.
        # They describe work; they never execute it. A sprint artifact naming a
        # test was enough to mark it wired, so this scan passed on the strength
        # of the very lane worklist that REPORTED the file as unwired.
        if rel.parts and rel.parts[0] == ".shepherd":
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            evidence[rel] = path.read_text(errors="replace")
        except OSError:
            continue
    return evidence


def glob_runners(root: pathlib.Path, evidence: dict[pathlib.Path, str]) -> dict[str, pathlib.Path]:
    """Find runners that discover their suite by glob rather than by name.

    `hooks/tests/run.sh` executes every `*.sh` beside it via `find`, on purpose:
    a hand-maintained array is what let 21 of its 27 tests go unrun. Those
    tests are therefore wired in the strongest available sense while appearing,
    to a name-matching scan, to be referenced by nothing. Treating them as
    unwired would be exactly backwards -- it would pressure the runner back
    toward the enumeration that caused the original defect.

    A runner counts when it globs its own directory AND is itself reachable.
    """
    runners = {}
    for rel, text in evidence.items():
        if rel.name not in NOT_TESTS:
            continue
        directory = str(rel.parent)
        if directory not in TEST_DIRS:
            continue
        globs = "find " in text and "-name '*.sh'" in text
        if not globs:
            continue
        # The runner itself must be executed by something, or the whole
        # directory is unreachable through it.
        referenced = any(
            other != rel and str(rel) in other_text
            for other, other_text in evidence.items()
        )
        if referenced:
            runners[directory] = rel
    return runners


def resolve(root: pathlib.Path) -> tuple[list[pathlib.Path], dict[pathlib.Path, list[str]]]:
    """Return (tests, wired) where wired maps a test to the files naming it.

    Reachability is transitive: a test named only by another test counts as
    wired exactly when that other test is itself wired. Iterating to a fixed
    point is what lets `test-release-workflow.sh` legitimately drive
    `test-glibc-floor.sh` without either being special-cased.
    """
    tracked = tracked_files() if root == REPO else [
        p.relative_to(root) for p in root.rglob("*") if p.is_file()
    ]
    tests = discover_tests(root, tracked)
    evidence = wiring_evidence(root, tracked)
    test_names = {t.name for t in tests}
    runners = glob_runners(root, evidence)

    # A test is a ROOT if a non-test file names it: gate.sh, a workflow, a hook.
    wired: dict[pathlib.Path, list[str]] = {}
    for test in tests:
        runner = runners.get(str(test.parent))
        if runner is not None:
            wired[test] = [f"{runner} (glob discovery)"]
            continue
        sources = [
            str(rel)
            for rel, text in evidence.items()
            if rel != test and rel.name not in test_names and test.name in text
        ]
        if sources:
            wired[test] = sorted(sources)

    # Then propagate: a wired test wires whatever it names.
    changed = True
    while changed:
        changed = False
        for test in tests:
            if test in wired:
                continue
            sources = []
            for other in tests:
                if other == test or other not in wired:
                    continue
                if test.name in evidence.get(other, ""):
                    sources.append(str(other))
            if sources:
                wired[test] = sorted(sources)
                changed = True
    return tests, wired


def check(root: pathlib.Path, quiet: bool = False) -> int:
    tests, wired = resolve(root)
    if not tests:
        print("FAIL: discovered zero test files -- pathspec drift?", file=sys.stderr)
        return 1
    unwired = [t for t in tests if t not in wired]
    if unwired:
        print(
            f"FAIL: {len(unwired)} test file(s) are executed by nothing "
            f"(of {len(tests)} discovered):",
            file=sys.stderr,
        )
        for test in unwired:
            print(f"  {test}", file=sys.stderr)
        print(
            "\nWire each into scripts/gate.sh, a workflow, or an already-wired "
            "test. An unwired gate does not fail when the code regresses -- it "
            "rots until it is wrong in its own right.",
            file=sys.stderr,
        )
        return 1
    if not quiet:
        print(f"check-gate-wiring: OK ({len(tests)} test files, all reachable from a runner)")
    return 0


def self_test() -> int:
    """The rule must fail on an unwired file and pass once it is wired."""
    cases = 0
    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        (scratch / "scripts" / "tests").mkdir(parents=True)
        gate = scratch / "scripts" / "gate.sh"

        wired_test = scratch / "scripts" / "tests" / "test-wired.sh"
        wired_test.write_text("#!/usr/bin/env bash\nexit 0\n")
        gate.write_text("bash scripts/tests/test-wired.sh\n")

        # Control: a wired-only tree must PASS. A checker that fails on
        # everything is indistinguishable from one that works.
        cases += 1
        if check(scratch, quiet=True) != 0:
            print("FAIL self-test: a fully wired tree was reported unwired", file=sys.stderr)
            return 1

        # An unwired test must be caught.
        cases += 1
        orphan = scratch / "scripts" / "tests" / "test-orphan.sh"
        orphan.write_text("#!/usr/bin/env bash\nexit 0\n")
        if check(scratch, quiet=True) == 0:
            print("FAIL self-test: an unwired test file was NOT detected", file=sys.stderr)
            return 1

        # Wiring it transitively (named by an already-wired test) must clear it.
        cases += 1
        wired_test.write_text("#!/usr/bin/env bash\nbash scripts/tests/test-orphan.sh\n")
        if check(scratch, quiet=True) != 0:
            print("FAIL self-test: transitive wiring was not honored", file=sys.stderr)
            return 1

        # Prose must NOT count as wiring: a test only CHANGELOG.md mentions is
        # still executed by nothing.
        cases += 1
        lonely = scratch / "scripts" / "tests" / "test-prose-only.sh"
        lonely.write_text("#!/usr/bin/env bash\nexit 0\n")
        (scratch / "CHANGELOG.md").write_text("we added scripts/tests/test-prose-only.sh\n")
        if check(scratch, quiet=True) == 0:
            print("FAIL self-test: a prose-only mention was accepted as wiring", file=sys.stderr)
            return 1

        # A glob runner wires its whole directory -- but only when the runner
        # is itself reachable. Both directions are checked, because a checker
        # that credits an UNREACHABLE runner would launder every test under it.
        (scratch / "hooks" / "tests").mkdir(parents=True)
        globbed = scratch / "hooks" / "tests" / "test_globbed.sh"
        globbed.write_text("#!/usr/bin/env bash\nexit 0\n")
        runner = scratch / "hooks" / "tests" / "run.sh"
        runner.write_text(
            "#!/usr/bin/env bash\nfind . -maxdepth 1 -name '*.sh' ! -name 'run.sh'\n"
        )
        (scratch / "CHANGELOG.md").unlink()
        lonely.unlink()

        cases += 1
        if check(scratch, quiet=True) == 0:
            print(
                "FAIL self-test: a glob runner that nothing executes was "
                "accepted as wiring its directory",
                file=sys.stderr,
            )
            return 1

        cases += 1
        gate.write_text(
            "bash scripts/tests/test-wired.sh\nbash hooks/tests/run.sh\n"
        )
        if check(scratch, quiet=True) != 0:
            print(
                "FAIL self-test: a reachable glob runner did not wire its directory",
                file=sys.stderr,
            )
            return 1

    print(f"check-gate-wiring: self-test OK ({cases} cases passed)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove the rule can fail")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return check(REPO)


if __name__ == "__main__":
    sys.exit(main())
