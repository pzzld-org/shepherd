#!/usr/bin/env python3
"""Reject any remediation that names a gated subcommand without its flag.

WHY this exists: `shepherd init` mints `.shepherd/project.json`, the registry,
and the `projects` row, so it is gated behind `--confirm`. Five separate
user-facing messages nonetheless told the operator to run a bare
`shepherd init`, which exits 2 and scaffolds nothing. The one message whose
job is unblocking a cold project sent the operator in a circle, and
`shepherd doctor` had the correct wording the whole time -- drift, not an
unknown.

WHY the gated-command map is derived rather than hard-coded: a maintained
list of mutating subcommands drifts the moment one is added, and a lint that
silently stops covering a command is worse than no lint. The authority is
the CLI's own refusal text (`X is mutating; re-run with --FLAG`), so a new
gated subcommand is covered the day it lands with no edit here.

Not registered in hooks.json. This is a repo lint, invoked by
hooks/tests/test_remediation_flags.sh, never a hook authority.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# The CLI's own refusal text is the single source of truth for "this
# subcommand mutates and requires an authorization flag".
GATE_RE = re.compile(
    r'"(?P<cmd>[a-z][a-z0-9 -]*?) is mutating; re-run with (?P<flag>--[a-z-]+)"'
)

# Surfaces an operator actually reads. Comments are excluded at scan time:
# prose describing what `init` does is not remediation handed to anyone.
SEARCH = (
    ("crates", "*.rs"),
    ("hooks/scripts", "*.sh"),
    ("skills", "*.md"),
    ("agents", "*.md"),
)

COMMENT_PREFIXES = ("///", "//!", "//", "#")


def _skip(path: pathlib.Path) -> bool:
    posix = path.as_posix()
    return "/tests/" in posix or "/target/" in posix


def derive_gates(root: pathlib.Path) -> dict[str, str]:
    gates: dict[str, str] = {}
    crates = root / "crates"
    if not crates.exists():
        return gates
    for path in crates.rglob("*.rs"):
        if _skip(path):
            continue
        for match in GATE_RE.finditer(path.read_text(encoding="utf-8")):
            gates[match.group("cmd")] = match.group("flag")
    return gates


def scan(root: pathlib.Path, gates: dict[str, str]) -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0
    # Longest command first so `config init` is attributed to its own gate
    # rather than being mistaken for the bare `init` gate.
    ordered = sorted(gates.items(), key=lambda kv: -len(kv[0]))
    for relative, glob in SEARCH:
        base = root / relative
        if not base.exists():
            continue
        for path in base.rglob(glob):
            if _skip(path):
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if line.lstrip().startswith(COMMENT_PREFIXES):
                    continue
                for cmd, flag in ordered:
                    if f"shepherd {cmd}" not in line:
                        continue
                    checked += 1
                    # The flag has to ride on the same line as the command it
                    # authorizes. A flag mentioned elsewhere is not something
                    # an operator can copy.
                    if flag not in line:
                        rel = path.relative_to(root).as_posix()
                        problems.append(
                            f"{rel}:{lineno}: names `shepherd {cmd}` without {flag}"
                        )
    return problems, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    gates = derive_gates(root)
    problems, checked = scan(root, gates)

    if args.json:
        json.dump(
            {
                "gates": gates,
                "checked": checked,
                "problems": problems,
                "ok": not problems and bool(gates),
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")

    # Deriving zero gates means the refusal-text pattern moved and this lint
    # is scanning nothing. Reporting success there is the exact silent-drift
    # failure the file exists to prevent.
    if not gates:
        if not args.json:
            print(
                "derived zero gated subcommands from the CLI refusal text -- pattern drift?",
                file=sys.stderr,
            )
        return 2

    if problems:
        if not args.json:
            print(
                "remediation names a gated command without its authorization flag:",
                file=sys.stderr,
            )
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
        return 1

    if not args.json:
        print(f"{len(gates)} gated subcommand(s), {checked} remediation mention(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
