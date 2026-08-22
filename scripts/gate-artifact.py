#!/usr/bin/env python3
"""Run a gate and persist explicit, correlated invocation/result evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if os.name != "nt":
    import fcntl

SCHEMA = "shepherd.gate-attempt/1"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_ARTIFACT_BYTES = 1_048_576
MAX_RECORD_BYTES = 16_384
MAX_RECORDS = 1_024


def identifier(value: str, name: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def artifact_path(root: Path, run: str, wave: str, lane: str, gate: str) -> Path:
    for name, value in (("run", run), ("wave", wave), ("lane", lane), ("gate", gate)):
        identifier(value, name)
    return root / ".shepherd" / "runs" / run / "lanes" / lane / "evidence" / "gates" / f"{wave}-{gate}.jsonl"


def command(args: argparse.Namespace) -> list[str]:
    value = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not value or any(not item for item in value):
        raise ValueError(f"{args.action} requires a non-empty command after --")
    return value


def open_parent(root: Path, path: Path, *, create: bool) -> tuple[int, str]:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError("gate artifact escapes the repository") from error
    if os.name == "nt" or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("gate artifacts require no-follow directory descriptors")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in relative.parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, relative.name
    except FileNotFoundError:
        os.close(descriptor)
        raise
    except OSError as error:
        os.close(descriptor)
        raise ValueError("gate artifact parent is unsafe or not a directory") from error


@contextmanager
def open_artifact(root: Path, path: Path, flags: int, *, create_parent: bool) -> Iterator[int]:
    parent, name = open_parent(root, path, create=create_parent)
    try:
        descriptor = os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("gate artifact must be a regular non-symlink file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield descriptor
    finally:
        os.close(descriptor)


def append_record(root: Path, path: Path, record: dict[str, Any]) -> None:
    payload = json.dumps(record, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("gate artifact record exceeds the bounded size")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    with open_artifact(root, path, flags, create_parent=True) as descriptor:
        if os.fstat(descriptor).st_size + len(payload) > MAX_ARTIFACT_BYTES:
            raise ValueError("gate artifact exceeds the bounded size")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("gate artifact append made no progress")
            view = view[written:]
        os.fsync(descriptor)


def common_record(kind: str, args: argparse.Namespace, attempt_id: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "kind": kind,
        "run": args.run,
        "wave": args.wave,
        "lane": args.lane,
        "gate": args.gate,
        "attempt_id": attempt_id,
    }


def parse_records(stream: Any, expected: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    invocations: set[str] = set()
    results: set[str] = set()
    for index, raw in enumerate(stream, 1):
        if index > MAX_RECORDS or len(raw) > MAX_RECORD_BYTES:
            raise ValueError("gate artifact exceeds bounded record limits")
        if not raw.endswith(b"\n"):
            raise ValueError(f"gate artifact record {index} is not newline-terminated")
        try:
            record = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid gate artifact record {index}") from error
        if not isinstance(record, dict):
            raise ValueError(f"gate artifact record {index} is not an object")
        for field in ("run", "wave", "lane", "gate"):
            if record.get(field) != getattr(expected, field):
                raise ValueError(f"gate artifact record {index} has mismatched {field}")
        attempt_id = record.get("attempt_id")
        if record.get("schema") != SCHEMA or not isinstance(attempt_id, str) or not IDENTIFIER.fullmatch(attempt_id):
            raise ValueError(f"gate artifact record {index} has invalid identity")
        kind = record.get("kind")
        if kind == "invocation":
            command = record.get("command")
            if attempt_id in invocations or not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
                raise ValueError(f"gate artifact invocation {index} is invalid")
            invocations.add(attempt_id)
        elif kind == "result":
            exit_code = record.get("exit_code")
            if attempt_id not in invocations or attempt_id in results or not isinstance(exit_code, int) or isinstance(exit_code, bool) or not 0 <= exit_code <= 255:
                raise ValueError(f"gate artifact result {index} is invalid")
            if record.get("status") != ("passed" if exit_code == 0 else "failed"):
                raise ValueError(f"gate artifact result {index} contradicts its exit code")
            results.add(attempt_id)
        else:
            raise ValueError(f"gate artifact record {index} has invalid kind")
        records.append(record)
    return records




def read_records(root: Path, path: Path, expected: argparse.Namespace) -> list[dict[str, Any]] | None:
    try:
        with open_artifact(root, path, os.O_RDONLY, create_parent=False) as descriptor:
            if os.fstat(descriptor).st_size > MAX_ARTIFACT_BYTES:
                raise ValueError("gate artifact exceeds the bounded size")
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                return parse_records(stream, expected)
    except FileNotFoundError:
        return None

def status(args: argparse.Namespace, root: Path, path: Path) -> int:
    expected_command = command(args)
    records = read_records(root, path, args)
    if records is None:
        print(json.dumps({"schema": SCHEMA, "state": "unverified"}, sort_keys=True))
        return 3
    invocations = [record for record in records if record["kind"] == "invocation"]
    if not invocations:
        raise ValueError("gate artifact contains no invocation")
    latest = invocations[-1]
    if latest["command"] != expected_command:
        raise ValueError("latest gate invocation does not match the expected command")
    result = next((record for record in records if record["kind"] == "result" and record["attempt_id"] == latest["attempt_id"]), None)
    state = "invoked" if result is None else result["status"]
    output: dict[str, Any] = {
        "schema": SCHEMA,
        "state": state,
        "attempt_id": latest["attempt_id"],
        "artifact": str(path),
        "command": expected_command,
    }
    if result is not None:
        output["exit_code"] = result["exit_code"]
    print(json.dumps(output, sort_keys=True))
    return {"passed": 0, "failed": 1, "unverified": 3, "invoked": 4}[state]


def run(args: argparse.Namespace, root: Path, path: Path) -> int:
    invoked = command(args)
    attempt_id = secrets.token_hex(16)
    invocation = common_record("invocation", args, attempt_id)
    invocation["command"] = invoked
    append_record(root, path, invocation)
    try:
        completed = subprocess.run(invoked, check=False)
        exit_code = completed.returncode
        if exit_code < 0:
            exit_code = min(255, 128 - exit_code)
    except OSError:
        exit_code = 127
    result = common_record("result", args, attempt_id)
    result.update({"status": "passed" if exit_code == 0 else "failed", "exit_code": exit_code})
    append_record(root, path, result)
    return exit_code


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("action", choices=("run", "status"))
    for field in ("run", "wave", "lane", "gate"):
        result.add_argument(f"--{field}", required=True)
    result.add_argument("command", nargs=argparse.REMAINDER)
    return result


def main() -> int:
    args = parser().parse_args()
    root = Path(__file__).resolve().parent.parent
    path = artifact_path(root, args.run, args.wave, args.lane, args.gate)
    try:
        if args.action == "run":
            return run(args, root, path)
        return status(args, root, path)
    except (OSError, ValueError) as error:
        print(f"gate-artifact: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
