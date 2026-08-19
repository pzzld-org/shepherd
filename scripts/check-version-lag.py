#!/usr/bin/env python3
"""check-version-lag -- the shepherd binary on this machine must be THIS repository's.

WHY THIS EXISTS.

On 2026-08-19 every hook in a live session ran `~/.cargo/bin/shepherd`
reporting `6.5.0` against a working tree whose `.claude-plugin/plugin.json`
declared `6.5.1`. Nothing noticed, because nothing looked:
`git grep -n "shepherd --version" hooks/ scripts/ .github/` returned nothing.

That is worse than a stale tool. Hooks are the enforcement surface, so a
lagging binary means the rules being enforced are the PREVIOUS release's
rules while the tree under test is this release's tree. Every gate that
passed proved something about a version nobody was shipping.

The comparison is one line. It is the REPORT that has to be careful:

    MATCH        -> exit 0, stating the count and both versions.
    MISMATCH     -> exit 1, naming both versions and a reinstall command
                    that runs verbatim from the repository root.
    NO BINARY    -> exit 0 with an explicit `skip:` and `checked: 0`. A
                    fresh CI runner that never installed a release binary
                    cannot lag one and must not be failed for it. The zero
                    is printed loudly so the pass is never mistaken for a
                    comparison that happened.
    CANNOT LOOK  -> exit 2. A missing or unparseable manifest, or a binary
                    whose `--version` cannot be read, is an ERROR, not a
                    verdict. "Could not look" is not "found nothing", and
                    must never be reported as success.

The name says "lag" because that is the defect it was built for, but it
reports a MISMATCH in either direction on purpose: a binary AHEAD of the
manifest is equally "the binary under test is not this repository", and the
remediation is identical.

Usage:
    scripts/check-version-lag.py              # compare, and print the count
    scripts/check-version-lag.py --self-test  # prove both verdicts on synthetic versions
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

TOOL = "check-version-lag"

# Resolved from the script's own location, so the check works from any cwd --
# a hook, a CI step, and an interactive shell do not agree on one.
ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / ".claude-plugin" / "plugin.json"

BIN_ENV = "SHEPHERD_BIN"
BINARY_NAME = "shepherd"

# Runnable verbatim from the repository root: `crates/cli` is package
# `shepherd-cli` with `[[bin]] name = "shepherd"`, and `Cargo.lock` is
# committed at the root, so `--locked` resolves. Printing a remediation that
# does not work as written is the defect family this gate belongs to.
REINSTALL_COMMAND = "cargo install --path crates/cli --locked --force"

# `shepherd --version` prints `shepherd-cli 6.5.1`. Match the version token
# rather than a fixed column, so a clap format change does not silently turn
# a real comparison into an unparse.
VERSION_TOKEN = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")

VERSION_TIMEOUT_S = 30
SELF_TEST_TIMEOUT_S = 60

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_CANNOT_LOOK = 2


class LookFailure(RuntimeError):
    """The check could not look. Always exit 2 -- never 0, never 1."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """One run's entire verdict: exit status, comparison count, and report body."""

    code: int
    checked: int
    lines: tuple[str, ...]


def manifest_version(path: Path) -> str:
    """The `version` string from a plugin manifest, or a LookFailure saying why not."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise LookFailure(f"cannot read {_display(path)}: {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LookFailure(f"{_display(path)} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise LookFailure(f"{_display(path)} must contain a JSON object")
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise LookFailure(f'{_display(path)} has no usable "version" string')
    return version.strip()


def binary_version(binary: str) -> str:
    """The version `binary --version` reports, or a LookFailure saying why not."""
    try:
        completed = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=VERSION_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as error:
        raise LookFailure(f"{binary} --version did not finish in {VERSION_TIMEOUT_S}s") from error
    except OSError as error:
        raise LookFailure(f"cannot execute {binary}: {error}") from error
    if completed.returncode != 0:
        raise LookFailure(f"{binary} --version exited {completed.returncode}")
    # Some builds print the banner on stderr; read both rather than guess.
    output = f"{completed.stdout}\n{completed.stderr}"
    match = VERSION_TOKEN.search(output)
    if match is None:
        raise LookFailure(f"no version token in {binary} --version output: {output.strip()!r}")
    return match.group(0)


def resolve_binary(env: Mapping[str, str]) -> tuple[str | None, str]:
    """(binary, where it came from). `SHEPHERD_BIN` wins; PATH is the fallback.

    Returns `(None, "nothing")` when neither names a binary -- the skip case.
    An explicitly-set `SHEPHERD_BIN` is honoured even when it does not exist,
    because the operator asserted a binary there: failing to run it is a
    "could not look" (exit 2), not a "nothing was installed" (exit 0).
    """
    override = (env.get(BIN_ENV) or "").strip()
    if override:
        return override, BIN_ENV
    found = shutil.which(BINARY_NAME, path=env.get("PATH"))
    if found:
        return found, "PATH"
    return None, "nothing"


def evaluate(manifest_path: Path, binary: str | None, source: str) -> Outcome:
    """The whole contract, as a pure function: no printing, no escaping exceptions."""
    # The manifest is read BEFORE the skip is considered. A repository whose
    # manifest cannot be read is broken whether or not a binary exists, and
    # calling that a skip would be exactly the vacuous pass this gate exists
    # to prevent. It also means `checked: 0` on the skip path still proves
    # one of the two inputs was readable.
    try:
        declared = manifest_version(manifest_path)
    except LookFailure as error:
        return Outcome(EXIT_CANNOT_LOOK, 0, _cannot_look(error))

    if binary is None:
        # The zero is named in the verdict line itself, not left to be inferred
        # from the absence of a finding. A silent vacuous pass is the failure
        # mode this branch is most likely to be mistaken for.
        comparisons = 0
        return Outcome(
            EXIT_OK,
            comparisons,
            (
                f"{TOOL}: skip: {comparisons} comparisons -- no shepherd binary resolvable "
                f"({BIN_ENV} is unset and no '{BINARY_NAME}' is on PATH)",
                f"  manifest: {_display(manifest_path)} -> {declared}",
                "  A machine that never installed a release binary cannot lag one.",
                f"  Set {BIN_ENV}=<path> to check a specific binary.",
            ),
        )

    try:
        installed = binary_version(binary)
    except LookFailure as error:
        return Outcome(EXIT_CANNOT_LOOK, 0, _cannot_look(error))

    provenance = f"  binary:   {binary} -> {installed}  (resolved from {source})"
    declaration = f"  manifest: {_display(manifest_path)} -> {declared}"
    # One binary, one manifest, one comparison. Bound to the Outcome's own
    # count below so the sentence and the machine-readable total cannot drift.
    comparisons = 1

    if installed == declared:
        return Outcome(
            EXIT_OK,
            comparisons,
            (
                f"{TOOL}: ok -- {comparisons} comparison, "
                f"binary {installed} matches manifest {declared}",
                provenance,
                declaration,
            ),
        )

    return Outcome(
        EXIT_MISMATCH,
        comparisons,
        (
            f"::error::{TOOL}: binary {installed} does not match manifest {declared}",
            provenance,
            declaration,
            "  Every hook and gate in this repository runs that binary, so what is being",
            "  enforced is not what is in this tree. Reinstall from the repository root:",
            "",
            # Unindented on purpose: the remediation has to survive copy-paste
            # verbatim, with no prefix for the reader to strip.
            REINSTALL_COMMAND,
            "",
        ),
    )


def render(outcome: Outcome) -> str:
    """The full report. `checked:` is appended HERE, so no code path can omit the count."""
    return "\n".join((*outcome.lines, f"checked: {outcome.checked}"))


def report(outcome: Outcome) -> int:
    # One stream on purpose: a CI capture that split verdict from detail could
    # show half a report. `::error::` carries the severity instead.
    print(render(outcome))
    return outcome.code


def _cannot_look(error: LookFailure) -> tuple[str, ...]:
    return (
        f"::error::{TOOL}: could not look -- {error}",
        "  This is an error, not a verdict: 'could not look' is not 'found nothing',",
        "  and is never reported as success.",
    )


def _display(path: Path) -> str:
    """Repo-relative inside the repo, absolute outside it (self-test fixtures)."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# self-test: the falsification proof
# --------------------------------------------------------------------------

# (label, actual exit code, actual report text, expected exit code, required substrings)
Case = tuple[str, int, str, int, tuple[str, ...]]

# Every expectation below is a LITERAL 0/1/2, never the EXIT_* symbol. Asserting
# `code == EXIT_CANNOT_LOOK` is a tautology: redefine the constant and the test
# agrees with the new wrong value. Mutation-testing this file caught exactly
# that. The published contract is the NUMBER another lane's CI step branches on,
# so the number is what gets pinned.
WANT_OK = 0
WANT_MISMATCH = 1
WANT_CANNOT_LOOK = 2

# Same reason, for the remediation: asserting the report contains
# REINSTALL_COMMAND passes no matter what REINSTALL_COMMAND is changed to.
# Mutation-testing swapped it for `cargo build` and nothing noticed. This is
# the independently-written copy the report is held against.
WANT_REINSTALL = "cargo install --path crates/cli --locked --force"

# Synthetic on purpose. Pinning the self-test to the current release version
# would make it rot on the next bump -- the exact class of staleness this gate
# was written to detect.
SELF_TEST_LAGGING = "0.0.1-selftest"
SELF_TEST_DECLARED = "0.0.2-selftest"


def _write_manifest(path: Path, version: str | None) -> Path:
    payload: dict[str, object] = {"name": "shepherd"}
    if version is not None:
        payload["version"] = version
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def _write_stub(path: Path, line: str, *, status: int = 0) -> str:
    """A fake shepherd: prints one `--version` line, exits `status`."""
    path.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(line)}\nexit {status}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def _run_script(env: Mapping[str, str]) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        capture_output=True,
        text=True,
        check=False,
        timeout=SELF_TEST_TIMEOUT_S,
        env=dict(env),
    )
    return completed.returncode, completed.stdout + completed.stderr


def _pure_cases(work: Path) -> list[Case]:
    """Both required verdicts, plus every way the check can refuse to answer."""
    manifest = _write_manifest(work / "plugin.json", SELF_TEST_DECLARED)
    matching = _write_stub(work / "shepherd-match", f"shepherd-cli {SELF_TEST_DECLARED}")
    lagging = _write_stub(work / "shepherd-lag", f"shepherd-cli {SELF_TEST_LAGGING}")
    unparseable = _write_stub(work / "shepherd-mute", "shepherd-cli (unknown build)")
    failing = _write_stub(work / "shepherd-angry", "boom", status=3)
    absent = str(work / "shepherd-absent")

    unparseable_manifest = work / "broken.json"
    unparseable_manifest.write_text("{not json", encoding="utf-8")
    versionless_manifest = _write_manifest(work / "no-version.json", None)
    missing_manifest = work / "missing.json"

    def case(label: str, outcome: Outcome, expected: int, needles: tuple[str, ...]) -> Case:
        return (label, outcome.code, render(outcome), expected, needles)

    return [
        case(
            "matching pair verdicts ok",
            evaluate(manifest, matching, BIN_ENV),
            WANT_OK,
            (SELF_TEST_DECLARED, "ok --", "checked: 1"),
        ),
        case(
            "lagging pair verdicts mismatch",
            evaluate(manifest, lagging, BIN_ENV),
            WANT_MISMATCH,
            (SELF_TEST_LAGGING, SELF_TEST_DECLARED, WANT_REINSTALL, "checked: 1"),
        ),
        case(
            "no binary resolvable skips loudly",
            evaluate(manifest, None, "nothing"),
            WANT_OK,
            ("skip:", SELF_TEST_DECLARED, "checked: 0"),
        ),
        case(
            "missing manifest cannot look",
            evaluate(missing_manifest, matching, BIN_ENV),
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
        case(
            "unparseable manifest cannot look",
            evaluate(unparseable_manifest, matching, BIN_ENV),
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
        case(
            "versionless manifest cannot look",
            evaluate(versionless_manifest, matching, BIN_ENV),
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
        case(
            "unparseable --version cannot look",
            evaluate(manifest, unparseable, BIN_ENV),
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
        case(
            "failing --version cannot look",
            evaluate(manifest, failing, BIN_ENV),
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
        case(
            f"unexecutable {BIN_ENV} cannot look",
            evaluate(manifest, absent, BIN_ENV),
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
    ]


def _process_cases(work: Path) -> list[Case]:
    """Prove the PROCESS exit status, not just the returned Outcome.

    What another lane's CI step consumes is the exit code of a real
    invocation, so every one of the three codes gets proven by an actual
    process here, not just by a returned Outcome. These run against the REAL
    manifest with synthetic stub binaries: the mismatch is guaranteed without
    hardcoding today's release version anywhere.
    """
    stub = _write_stub(work / "shepherd-e2e", f"shepherd-cli {SELF_TEST_LAGGING}")
    empty_path = work / "empty-path"
    empty_path.mkdir(exist_ok=True)

    mismatch_env = dict(os.environ, **{BIN_ENV: stub})
    skip_env = dict(os.environ, PATH=str(empty_path))
    skip_env.pop(BIN_ENV, None)
    unlookable_env = dict(os.environ, **{BIN_ENV: str(work / "shepherd-does-not-exist")})

    mismatch_code, mismatch_text = _run_script(mismatch_env)
    skip_code, skip_text = _run_script(skip_env)
    unlookable_code, unlookable_text = _run_script(unlookable_env)
    return [
        (
            "process exits 1 on a real mismatch run",
            mismatch_code,
            mismatch_text,
            WANT_MISMATCH,
            (SELF_TEST_LAGGING, WANT_REINSTALL, "checked: 1"),
        ),
        (
            "process exits 0 on a real skip run",
            skip_code,
            skip_text,
            WANT_OK,
            ("skip:", "checked: 0"),
        ),
        (
            "process exits 2 on a real cannot-look run",
            unlookable_code,
            unlookable_text,
            WANT_CANNOT_LOOK,
            ("could not look", "checked: 0"),
        ),
    ]


def _remediation_cases() -> list[Case]:
    """The printed fix must run verbatim, so check that its parts really exist.

    A remediation naming a moved crate is a lie the reader only discovers after
    pasting it, and this branch opened on exactly that defect. Running `cargo
    install` here is not an option (it is minutes of work and a shared build
    cache), so the command is taken apart instead: the crate `--path` points at
    must exist and must actually build a binary called `shepherd`.
    """
    tokens = shlex.split(REINSTALL_COMMAND)
    findings: list[str] = []
    if tokens[:2] != ["cargo", "install"]:
        findings.append(f"remediation is not a cargo install: {REINSTALL_COMMAND!r}")
    if "--locked" not in tokens:
        findings.append("remediation omits --locked, so it can install a different dependency set")

    crate = tokens[tokens.index("--path") + 1] if "--path" in tokens else ""
    if not crate:
        findings.append("remediation has no --path argument")
    else:
        manifest = ROOT / crate / "Cargo.toml"
        if not manifest.is_file():
            findings.append(f"remediation --path {crate} has no Cargo.toml under {ROOT}")
        elif f'name = "{BINARY_NAME}"' not in manifest.read_text(encoding="utf-8"):
            findings.append(f"{crate}/Cargo.toml builds no binary named {BINARY_NAME}")

    return [
        (
            "printed remediation is the published string",
            0 if REINSTALL_COMMAND == WANT_REINSTALL else 1,
            REINSTALL_COMMAND,
            0,
            (WANT_REINSTALL,),
        ),
        (
            "printed remediation resolves in this repo",
            len(findings),
            "\n".join(findings) or f"resolves: {REINSTALL_COMMAND}",
            0,
            (),
        ),
    ]


def self_test() -> int:
    print("self-test: both verdicts, on synthetic versions\n")
    with tempfile.TemporaryDirectory(prefix="shepherd-version-lag-") as temp:
        work = Path(temp)
        cases = _pure_cases(work) + _process_cases(work) + _remediation_cases()

        # An empty case set is not a pass. Checked structurally, so deleting
        # every case can never produce a green self-test.
        if not cases:
            print(f"::error::{TOOL}: self-test has no cases -- an empty case set is not a pass.")
            return 1

        failures = 0
        for label, code, text, expected_code, needles in cases:
            problems = [f"exit {code}, expected {expected_code}"] if code != expected_code else []
            problems += [f"report never says {needle!r}" for needle in needles if needle not in text]
            if problems:
                failures += 1
                print(f"  {label:<46} FAILED")
                for problem in problems:
                    print(f"      {problem}")
            else:
                print(f"  {label:<46} passed")

        print()
        if failures:
            print(f"::error::{TOOL}: {failures} of {len(cases)} self-test case(s) failed.")
            return 1
        print(f"self-test: {len(cases)} cases passed")
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description=(
            "Compare the resolved shepherd binary's version against "
            ".claude-plugin/plugin.json. Exit 0 match or no binary, 1 mismatch, 2 cannot look."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove both verdicts against synthetic versions in a temp dir",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    binary, source = resolve_binary(os.environ)
    return report(evaluate(MANIFEST_PATH, binary, source))


if __name__ == "__main__":
    raise SystemExit(main())
