#!/usr/bin/env python3
"""The WIT component contract and the native request structs must agree.

WHY THIS EXISTS.

Two independent field-level breaks shipped across this boundary and neither was
caught by any test:

  1. Every dispatch request struct in crates/core/src/dispatch/portable.rs
     declares `pub schema: String`, and the WIT records deliberately do not.
     Nothing stamped that envelope, so EVERY request the component produced was
     rejected -- bind-root, start, resolve, stop, resume.
  2. WIT calls it `tool-use-id`; Rust calls it `tool_call_id`. Because the
     structs are `#[serde(deny_unknown_fields)]`, every resolve request was
     rejected, so the Pi guard denied every write, edit and bash call.

Both were invisible because the Pi extension was never loaded at all (no `pi`
key in its package.json), so none of this code had ever run in production. The
tests that did exist checked how the CLI BINARY NAME is resolved, never whether
a request the transport built was accepted by the CLI it was built for.

WHAT THIS CHECKS.

Field-name parity between each WIT record and its Rust counterpart, with two
categories of deliberate, declared exception:

  WIRE_ONLY     fields the transport adds as framing; absent from WIT by design.
  RENAMES       names the transport reconciles, because the WIT is a published
                contract and renaming a field there breaks every embedder.

Anything else is drift and fails. The point is that a divergence must be
DECLARED here to be legal -- a new one cannot appear silently.

Run with --self-test to prove the comparison can fail.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
WIT_DIR = REPO / "crates/component/wit"
PORTABLE = REPO / "crates/core/src/dispatch/portable.rs"
# Framing lives where the wire is written, not where the plan is built.
TRANSPORT = REPO / "packages/component-runtime/src/native-transport.mjs"

# Framing the transport adds. Present in Rust, absent from WIT, by design:
# the component owns the semantic payload, the transport owns the envelope.
WIRE_ONLY = {"schema"}

# WIT name -> Rust name, reconciled by the transport. Every entry here must
# also be implemented in WIRE_FIELD_RENAMES on the JS side, which this script
# verifies rather than trusts.
RENAMES = {"tool_use_id": "tool_call_id"}

# Records that are component outputs and never sent to the CLI as a request.
# Their shape does not have to match a request struct.
NOT_WIRE_REQUESTS = {"normalized-identity"}


def wit_records(text: str) -> dict[str, list[str]]:
    records = {}
    for match in re.finditer(r"record ([a-z0-9-]+) \{(.*?)\n  \}", text, re.S):
        fields = re.findall(r"\n\s+([a-z0-9-]+):", match.group(2))
        records[match.group(1)] = [f.replace("-", "_") for f in fields]
    return records


def rust_structs(text: str) -> dict[str, list[str]]:
    structs = {}
    for match in re.finditer(r"pub struct (\w+) \{(.*?)\n\}", text, re.S):
        structs[match.group(1)] = re.findall(r"\n\s+pub (\w+):", match.group(2))
    return structs


def rust_name(wit_name: str) -> str:
    return "".join(part.capitalize() for part in wit_name.split("-"))


def compare(wit_text: str, rust_text: str) -> list[str]:
    problems = []
    wit = wit_records(wit_text)
    rust = rust_structs(rust_text)
    compared = 0
    for wit_record, wit_fields in sorted(wit.items()):
        if wit_record in NOT_WIRE_REQUESTS:
            continue
        struct = rust_name(wit_record)
        if struct not in rust:
            continue
        compared += 1
        projected = [RENAMES.get(field, field) for field in wit_fields]
        rust_fields = [f for f in rust[struct] if f not in WIRE_ONLY]
        missing = [f for f in rust_fields if f not in projected]
        extra = [f for f in projected if f not in rust_fields]
        if missing:
            problems.append(
                f"{wit_record} -> {struct}: the native struct requires {missing}, "
                f"which the component never sends (deny_unknown_fields makes this fatal)"
            )
        if extra:
            problems.append(
                f"{wit_record} -> {struct}: the component sends {extra}, which the "
                f"native struct rejects (deny_unknown_fields makes this fatal). "
                f"Add a declared entry to RENAMES if this is a naming divergence."
            )
    if compared == 0:
        problems.append("compared zero records -- the WIT or Rust parser matched nothing")
    return problems


def check() -> int:
    wit_text = "\n".join(p.read_text() for p in sorted(WIT_DIR.glob("*.wit")))
    problems = compare(wit_text, PORTABLE.read_text())

    # Every declared rename must actually be implemented by the transport, or
    # the exemption above is a lie that hides a live break.
    transport = TRANSPORT.read_text()
    for wit_field, rust_field in RENAMES.items():
        if f'"{wit_field}", "{rust_field}"' not in transport.replace("[", "").replace("]", ""):
            problems.append(
                f"RENAMES declares {wit_field} -> {rust_field} but the transport does not "
                f"implement it (expected in WIRE_FIELD_RENAMES)"
            )
    for field in WIRE_ONLY:
        if field == "schema" and "DISPATCH_REQUEST_SCHEMA" not in transport:
            problems.append("the transport does not stamp the schema envelope")

    if problems:
        print("FAIL: WIT and native request structs disagree:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("check-wire-contract: OK (WIT records and native request structs agree)")
    return 0


def self_test() -> int:
    cases = 0
    good_wit = "  record probe-request {\n    session-id: string,\n    tool-use-id: option<string>,\n  }\n"
    good_rust = (
        "pub struct ProbeRequest {\n    pub schema: String,\n"
        "    pub session_id: SessionId,\n    pub tool_call_id: Option<SessionId>,\n}\n"
    )

    cases += 1
    if compare(good_wit, good_rust):
        print("FAIL self-test: an agreeing pair was reported as divergent", file=sys.stderr)
        return 1

    # A field the native struct requires and the component never sends.
    cases += 1
    if not compare("  record probe-request {\n    session-id: string,\n  }\n", good_rust):
        print("FAIL self-test: a missing required field was not detected", file=sys.stderr)
        return 1

    # A field the component sends that the struct rejects.
    cases += 1
    extra_wit = "  record probe-request {\n    session-id: string,\n    tool-use-id: option<string>,\n    surprise: string,\n  }\n"
    if not compare(extra_wit, good_rust):
        print("FAIL self-test: an unknown extra field was not detected", file=sys.stderr)
        return 1

    # Parsing nothing must fail rather than pass vacuously.
    cases += 1
    if not compare("", good_rust):
        print("FAIL self-test: comparing zero records was accepted", file=sys.stderr)
        return 1

    print(f"check-wire-contract: self-test OK ({cases} cases passed)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else check()


if __name__ == "__main__":
    sys.exit(main())
