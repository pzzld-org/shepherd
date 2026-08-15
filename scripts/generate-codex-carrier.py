#!/usr/bin/env python3
"""Generate or verify Codex's regular-file skill projection."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "skills"
TARGET = ROOT / "plugins" / "shepherd" / "codex" / "skills"


def inventory(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def check() -> list[str]:
    source = inventory(SOURCE)
    projected = inventory(TARGET)
    failures = []
    if set(source) != set(projected):
        failures.append(
            f"skill inventory differs: source={sorted(source)} projected={sorted(projected)}"
        )
    for relative in sorted(set(source) & set(projected)):
        if source[relative].read_bytes() != projected[relative].read_bytes():
            failures.append(f"plugins/shepherd/codex/skills/{relative} has byte drift")
    for path in TARGET.rglob("*") if TARGET.is_dir() else ():
        if path.is_symlink():
            failures.append(f"{path.relative_to(ROOT)} must be a regular carrier entry")
    return failures


def generate() -> None:
    expected = inventory(SOURCE)
    existing = inventory(TARGET) if TARGET.is_dir() else {}
    extras = sorted(set(existing) - set(expected))
    if extras:
        raise SystemExit(f"refusing to overwrite a carrier with extra files: {extras}")
    for relative, source in expected.items():
        target = TARGET / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        generate()
    failures = check()
    if failures:
        for failure in failures:
            print(f"generate-codex-carrier: ERROR: {failure}")
        return 1
    print("ok: Codex skill carrier is a byte-exact regular-file projection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
