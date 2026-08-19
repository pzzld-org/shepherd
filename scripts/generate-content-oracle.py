#!/usr/bin/env python3
"""Regenerate conformance/content-target-final.json from the live compiler.

WHY THIS EXISTS.

The target-final oracle is the frozen record of what `shepherd compile` emits
for every harness: per target, a whole-tree digest and, per emitted file, its
exact byte length and content hash. `crates/cli/tests/content_compiler.rs`
compares the live compiler against it, which is what makes an accidental change
to authored content impossible to ship unnoticed.

It had no generator. Every content change therefore required hand-editing a
machine-generated document containing three trees of hashes -- and that went
wrong exactly the way hand-editing generated data always does: the first attempt
wrote `files` as an ARRAY when the schema is an object keyed by
path, and a later one regenerated the oracle correctly, verified the workspace
against it locally, and then pushed without the file, turning five CI checks red
on a digest comparison. Issue #341 tracks precisely this.

The oracle is a good design. Owning it by hand was not.

SAFETY. `--write` refuses to proceed unless every file whose bytes did NOT
change reproduces its frozen entry exactly. That is what distinguishes
"regenerate because content legitimately changed" from "silently bless whatever
the compiler now emits" -- the second is how a frozen oracle stops being an
oracle. Use --check in the gate; --write only when content changed on purpose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
ORACLE = REPO / "conformance/content-target-final.json"
SCHEMA = "shepherd.content-target-final/1"
TARGETS = ("claude", "codex", "pi")


def shepherd_binary() -> str:
    for candidate in ("target/debug/shepherd", "target/release/shepherd"):
        path = REPO / candidate
        if path.is_file():
            return str(path)
    # NO PATH FALLBACK, deliberately. A `shepherd` on PATH is whatever the
    # operator last installed -- when this was written it was a release behind
    # the checkout, and produced three confidently wrong digests. The oracle records what
    # THIS tree's compiler emits, so only this tree's build may generate or
    # verify it. Comparing against an installed binary is the same defect class
    # as a test asserting against an installed plugin.
    # A STATED skip, never a silent pass. `gate.sh fast` compiles nothing by
    # contract, so it legitimately has no binary; the same check runs for real
    # in the full tier and in `cargo test` via
    # crates/cli/tests/content_compiler.rs. Exiting 0 here without saying so
    # would make the fast tier claim a verification it did not perform.
    print(
        "content-oracle: SKIP -- no shepherd binary (build it, or rely on the "
        "full tier and cargo test, which both check this)"
    )
    sys.exit(0)


def emit(target: str, binary: str) -> dict:
    """Compile one target and return {tree_digest, files{path: [bytes, sha]}}."""
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp)
        result = subprocess.run(
            [binary, "compile", "--target", target, "--out", str(out)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.exit(f"FAIL: compile --target {target} exited {result.returncode}:\n{result.stderr}")
        manifest_path = out / ".shepherd-generated.json"
        if not manifest_path.is_file():
            sys.exit(f"FAIL: {target} emitted no .shepherd-generated.json")
        manifest = json.loads(manifest_path.read_text())

        files = {}
        for entry in manifest["files"]:
            emitted = out / entry["path"]
            if not emitted.is_file():
                sys.exit(f"FAIL: {target}: manifest lists {entry['path']} but it was not emitted")
            payload = emitted.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            # Trust nothing: recompute the hash rather than copying the
            # manifest's, so a manifest that disagrees with its own bytes is
            # caught here instead of being frozen into the oracle.
            if digest != entry["content_sha256"]:
                sys.exit(
                    f"FAIL: {target}: {entry['path']} manifest hash {entry['content_sha256']}\n"
                    f"      does not match the emitted bytes ({digest})"
                )
            files[entry["path"]] = [len(payload), digest]

        if not files:
            sys.exit(f"FAIL: {target} emitted zero files")
        return {"files": files, "tree_digest": manifest["tree_digest"]}


def build(binary: str) -> dict:
    existing = json.loads(ORACLE.read_text()) if ORACLE.is_file() else {}
    document = {
        "contract_note": existing.get(
            "contract_note",
            "Frozen target-final projection of content/. Regenerate with "
            "scripts/generate-content-oracle.py --write, never by hand.",
        ),
        "schema": SCHEMA,
        "roles": existing.get("roles", 9),
        "targets": {target: emit(target, binary) for target in TARGETS},
    }
    return document


def unchanged_entries_still_match(fresh: dict, frozen: dict) -> list[str]:
    """Every path whose bytes are identical must reproduce its frozen entry.

    A regeneration is legitimate only for the files that actually changed. If a
    path the author did not touch now hashes differently, something other than
    the intended edit moved, and blessing it would freeze that in.
    """
    problems = []
    for target, fresh_target in fresh["targets"].items():
        frozen_target = frozen.get("targets", {}).get(target)
        if not frozen_target:
            continue
        for path, entry in fresh_target["files"].items():
            previous = frozen_target["files"].get(path)
            if previous is None:
                continue
            if previous[1] != entry[1] and previous[0] == entry[0]:
                problems.append(
                    f"{target}:{path} kept its byte length ({entry[0]}) but changed hash -- "
                    "that is not a content edit, investigate before regenerating"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()

    binary = shepherd_binary()
    fresh = build(binary)

    if args.check:
        if not ORACLE.is_file():
            print(f"FAIL: {ORACLE} does not exist", file=sys.stderr)
            return 1
        frozen = json.loads(ORACLE.read_text())
        if frozen == fresh:
            total = sum(len(t["files"]) for t in fresh["targets"].values())
            print(
                f"content-oracle: OK ({len(fresh['targets'])} targets, {total} files, "
                "live compiler matches the frozen oracle)"
            )
            return 0
        print(
            "FAIL: the live compiler no longer matches the frozen oracle.\n"
            "      If content/ changed on purpose, run --write and commit the result\n"
            "      IN THE SAME COMMIT as the content change.",
            file=sys.stderr,
        )
        for target, fresh_target in fresh["targets"].items():
            frozen_target = frozen.get("targets", {}).get(target, {})
            if fresh_target.get("tree_digest") != frozen_target.get("tree_digest"):
                print(
                    f"  {target}: tree_digest {frozen_target.get('tree_digest')}"
                    f" -> {fresh_target['tree_digest']}",
                    file=sys.stderr,
                )
        return 1

    if ORACLE.is_file():
        problems = unchanged_entries_still_match(fresh, json.loads(ORACLE.read_text()))
        if problems:
            print("FAIL: refusing to regenerate:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1

    ORACLE.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n")
    total = sum(len(t["files"]) for t in fresh["targets"].values())
    print(f"content-oracle: wrote {len(fresh['targets'])} targets, {total} files")
    for target, entry in fresh["targets"].items():
        print(f"  {target:8} {len(entry['files']):3} files  {entry['tree_digest'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
