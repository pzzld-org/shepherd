#!/usr/bin/env python3
"""Generate the byte-exact compiler content shipped in its Cargo package."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path


class ProjectionError(Exception):
    """The authored corpus or generated projection violates its contract."""


def source_files(root: Path) -> dict[str, bytes]:
    content = root / "content"
    groups = (
        sorted((content / "roles").glob("*.md")),
        sorted((content / "skills").glob("*/SKILL.md")),
        sorted((content / "predicates").glob("*.toml")),
        [content / "templates/handoff.md"],
    )
    if any(not group for group in groups):
        raise ProjectionError("source projection category is empty")

    selected: dict[str, bytes] = {}
    for path in (path for group in groups for path in group):
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as error:
            raise ProjectionError(f"missing source entry: {path}") from error
        if stat.S_ISLNK(mode):
            raise ProjectionError(f"symlink source entry: {path}")
        if not stat.S_ISREG(mode):
            raise ProjectionError(f"special source entry: {path}")
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProjectionError(f"non-UTF-8 source entry: {relative}") from error
        selected[relative] = raw
    return dict(sorted(selected.items()))


def checksum_bytes(files: dict[str, bytes]) -> bytes:
    lines = [f"{hashlib.sha256(raw).hexdigest()}  {relative}" for relative, raw in files.items()]
    return ("\n".join(lines) + "\n").encode()


def write_projection(output: Path, files: dict[str, bytes]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for relative, raw in files.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        (staging / "SHA256SUMS").write_bytes(checksum_bytes(files))
        previous = output.with_name(f".{output.name}.previous-{os.getpid()}")
        if previous.exists():
            shutil.rmtree(previous)
        if output.exists():
            output.rename(previous)
        staging.rename(output)
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def check_projection(output: Path, expected: dict[str, bytes]) -> None:
    expected_with_manifest = {**expected, "SHA256SUMS": checksum_bytes(expected)}
    actual: dict[str, bytes] = {}
    problems: list[str] = []
    if not output.is_dir() or output.is_symlink():
        raise ProjectionError(f"missing projection directory: {output}")

    for path in sorted(output.rglob("*")):
        relative = path.relative_to(output).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            problems.append(f"symlink entry: {relative}")
        elif stat.S_ISDIR(mode):
            continue
        elif not stat.S_ISREG(mode):
            problems.append(f"special entry: {relative}")
        else:
            actual[relative] = path.read_bytes()

    missing = sorted(set(expected_with_manifest) - set(actual))
    extra = sorted(set(actual) - set(expected_with_manifest))
    if missing:
        problems.append(f"missing entries: {', '.join(missing)}")
    if extra:
        problems.append(f"extra entries: {', '.join(extra)}")
    for relative in sorted(set(actual).intersection(expected_with_manifest)):
        if actual[relative] != expected_with_manifest[relative]:
            problems.append(f"byte drift: {relative}")
    if problems:
        raise ProjectionError("; ".join(problems))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    output = args.output or root / "crates/compiler/package-content"
    try:
        expected = source_files(root)
        if args.write:
            write_projection(output, expected)
        else:
            check_projection(output, expected)
    except (OSError, ProjectionError) as error:
        print(f"compiler-package-content: {error}", file=sys.stderr)
        return 1
    print(f"ok: compiler package content has {len(expected)} byte-exact sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
