#!/usr/bin/env python3
"""Keep the byte-exact conformance corpus reachable from the full gate."""

from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED_STEP = 'step "native conformance corpus" conformance/run.sh --impl=rust'


def check(text: str) -> bool:
    return REQUIRED_STEP in text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if not check(REQUIRED_STEP) or check('step "native conformance corpus" true'):
            print("FAIL: conformance gate checker is not falsifiable")
            return 1
        print("ok: conformance gate checker is falsifiable")
        return 0
    gate = Path(__file__).resolve().parents[1] / "gate.sh"
    if not check(gate.read_text()):
        print("FAIL: scripts/gate.sh full does not replay conformance/run.sh --impl=rust")
        return 1
    print("ok: full gate replays the native conformance corpus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
