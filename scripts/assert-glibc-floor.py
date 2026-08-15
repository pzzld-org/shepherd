#!/usr/bin/env python3
"""Reject ELF dependencies newer than the release compatibility floor."""

from __future__ import annotations

import re
import sys


SYMBOL_RE = re.compile(r"\bName:\s+GLIBC_(\d+)\.(\d+)\b")


def version(value: str) -> tuple[int, int]:
    try:
        major, minor = value.split(".", 1)
        return int(major), int(minor)
    except (ValueError, AttributeError):
        raise SystemExit(f"invalid GLIBC compatibility floor: {value}")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} MAJOR.MINOR", file=sys.stderr)
        return 2

    floor_text = sys.argv[1]
    floor = version(floor_text)
    versions = [
        (int(major), int(minor))
        for major, minor in SYMBOL_RE.findall(sys.stdin.read())
    ]
    if not versions:
        print("no GLIBC symbol versions found", file=sys.stderr)
        return 1

    maximum = max(versions)
    if maximum > floor:
        maximum_text = f"{maximum[0]}.{maximum[1]}"
        print(
            f"requires GLIBC_{maximum_text}, exceeds supported GLIBC_{floor_text}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
