#!/usr/bin/env python3
"""Prepare and resume Shepherd's immutable crates.io publication waves."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
WAVES = (
    ("shepherd-core", "shepherd-compiler"),
    ("shepherd-registry", "shepherd-render"),
    ("shepherd-sdk",),
    ("shepherd-cli",),
)
PACKAGE_DIRS = {
    "shepherd-core": "crates/core",
    "shepherd-compiler": "crates/compiler",
    "shepherd-registry": "crates/registry",
    "shepherd-render": "crates/render",
    "shepherd-sdk": "crates/sdk",
    "shepherd-cli": "crates/cli",
}
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
USER_AGENT = "shepherd-cargo-publish/1"


class PublishError(Exception):
    """A release invariant failed before or during publication."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_state(path: Path, version: str) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError(f"cannot read state {path}: {error}") from error
    if state.get("schema_version") != SCHEMA_VERSION:
        raise PublishError("state schema mismatch")
    if state.get("version") != version:
        raise PublishError(
            f"state version mismatch: expected {version}, found {state.get('version')}"
        )
    return state


def public_state(state: dict) -> dict:
    """Drop legacy fields that could contain credential-bearing remote URLs."""
    return {key: value for key, value in state.items() if key != "remote_url"}


def build_state(version: str, source_head: str, crates: dict[str, dict[str, object]]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "source_head": source_head,
        "crates": crates,
    }


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() if capture else f"exit {result.returncode}"
        raise PublishError(f"command failed: {command[0]} {command[1]}: {detail}")
    return result.stdout.strip() if capture else ""


def ensure_version(version: str) -> None:
    if SEMVER.fullmatch(version) is None:
        raise PublishError(f"version must be exact MAJOR.MINOR.PATCH: {version!r}")
    run(
        ["python3", "scripts/version-bump.py", "check", "--root", ".", "--version", version],
        capture=True,
    )


def prepare(args: argparse.Namespace) -> None:
    ensure_version(args.version)
    run(["python3", "scripts/check-cargo-distribution.py"])
    if not args.allow_dirty:
        dirty = run(["git", "status", "--porcelain"], capture=True)
        if dirty:
            raise PublishError("prepare requires a clean checkout")
    command = [
        "cargo",
        "package",
        "--locked",
        "--workspace",
        "--exclude",
        "shepherd-component",
    ]
    if args.allow_dirty:
        command.append("--allow-dirty")
    run(command)

    package_root = Path(os.environ.get("CARGO_TARGET_DIR", ROOT / "target")) / "package"
    crates: dict[str, dict[str, object]] = {}
    for wave_index, wave in enumerate(WAVES, 1):
        for name in wave:
            artifact = package_root / f"{name}-{args.version}.crate"
            if not artifact.is_file():
                raise PublishError(f"missing prepared crate: {artifact}")
            crates[name] = {
                "artifact": str(artifact.resolve()),
                "local_sha256": sha256(artifact),
                "published_sha256": None,
                "status": "prepared",
                "wave": wave_index,
            }
    state = build_state(
        args.version,
        run(["git", "rev-parse", "HEAD"], capture=True),
        crates,
    )
    atomic_json(args.state, state)
    print(f"prepared {len(crates)} immutable crates in {args.state}")


def crate_metadata(api: str, name: str, version: str) -> dict | None:
    """Return authoritative crates.io metadata, or None for an absent version."""
    url = f"{api.rstrip('/')}/api/v1/crates/{name}/{version}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            try:
                value = json.loads(response.read())
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise PublishError(
                    f"registry metadata was not valid JSON for {name}@{version}"
                ) from error
            if not isinstance(value, dict):
                raise PublishError(
                    f"registry metadata was not an object for {name}@{version}"
                )
            return value
    except urllib.error.HTTPError as error:
        if error.code == 404:
            error.close()
            return None
        error.close()
        raise PublishError(
            f"registry query failed for {name}@{version}: HTTP {error.code}"
        ) from error
    except OSError as error:
        raise PublishError(f"registry query failed for {name}@{version}: {error}") from error


def metadata_checksum(metadata: dict, name: str, version: str) -> str:
    version_data = metadata.get("version")
    if not isinstance(version_data, dict) or version_data.get("num") != version:
        raise PublishError(f"registry metadata has no exact version for {name}@{version}")
    checksum = version_data.get("checksum")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise PublishError(f"registry metadata has no valid checksum for {name}@{version}")
    return checksum


def download_crate(api: str, name: str, version: str) -> bytes:
    """Download the actual crate bytes, following the registry's binary redirect."""
    url = f"{api.rstrip('/')}/api/v1/crates/{name}/{version}/download"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
            if content_type == "application/json":
                raise PublishError(
                    f"registry archive response was a JSON envelope, not crate bytes "
                    f"for {name}@{version}"
                )
            if body.lstrip().startswith(b"{"):
                try:
                    envelope = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    envelope = None
                if isinstance(envelope, dict) and isinstance(envelope.get("url"), str):
                    raise PublishError(
                        f"registry archive response was a JSON envelope, not crate bytes "
                        f"for {name}@{version}"
                    )
            if not body:
                raise PublishError(f"registry archive was empty for {name}@{version}")
            return body
    except urllib.error.HTTPError as error:
        error.close()
        raise PublishError(
            f"registry archive download failed for {name}@{version}: HTTP {error.code}"
        ) from error
    except OSError as error:
        raise PublishError(
            f"registry archive download failed for {name}@{version}: {error}"
        ) from error


def verify_archive_bytes(raw: bytes, expected: str, *, name: str, version: str, phase: str) -> str:
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise PublishError(
            f"{phase} archive checksum mismatch for {name}@{version}: "
            f"expected {expected}, found {actual}"
        )
    return actual


def wait_for_checksum(args: argparse.Namespace, name: str, expected: str) -> str:
    deadline = time.monotonic() + args.timeout
    delay = 1.0
    while True:
        metadata = crate_metadata(args.registry_api, name, args.version)
        if metadata is not None:
            published = metadata_checksum(metadata, name, args.version)
            if published != expected:
                raise PublishError(
                    f"published checksum mismatch for {name}@{args.version}: "
                    f"expected {expected}, found {published}"
                )
            raw = download_crate(args.registry_api, name, args.version)
            return verify_archive_bytes(
                raw,
                expected,
                name=name,
                version=args.version,
                phase="published",
            )
        if time.monotonic() >= deadline:
            raise PublishError(f"timed out waiting for {name}@{args.version}")
        time.sleep(delay)
        delay = min(delay * 2, 15.0)


def publish(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise PublishError("publish requires explicit --confirm")
    state = public_state(load_state(args.state, args.version))
    current_head = run(["git", "rev-parse", "HEAD"], capture=True)
    if current_head != state.get("source_head"):
        raise PublishError("checkout HEAD differs from prepared state")

    for wave in WAVES:
        for name in wave:
            receipt = state["crates"].get(name)
            if not isinstance(receipt, dict):
                raise PublishError(f"state has no receipt for {name}")
            artifact = Path(str(receipt["artifact"]))
            expected = str(receipt["local_sha256"])
            if not artifact.is_file() or sha256(artifact) != expected:
                raise PublishError(f"prepared artifact drifted: {artifact}")
            existing = crate_metadata(args.registry_api, name, args.version)
            if existing is None:
                run(["cargo", "publish", "--locked", "--package", name])
                receipt["published_sha256"] = wait_for_checksum(args, name, expected)
            else:
                published = metadata_checksum(existing, name, args.version)
                if published != expected:
                    raise PublishError(
                        f"existing immutable crate differs: {name}@{args.version}: "
                        f"expected {expected}, found {published}"
                    )
                receipt["published_sha256"] = verify_archive_bytes(
                    download_crate(args.registry_api, name, args.version),
                    expected,
                    name=name,
                    version=args.version,
                    phase="existing",
                )
            receipt["status"] = "published"
            atomic_json(args.state, state)
            print(f"verified {name}@{args.version} {expected}")


def plan(args: argparse.Namespace) -> None:
    ensure_version(args.version)
    value = {"version": args.version, "waves": [list(wave) for wave in WAVES]}
    print(json.dumps(value, sort_keys=True) if args.json else "\n".join(" + ".join(w) for w in WAVES))


def status(args: argparse.Namespace) -> None:
    state = public_state(load_state(args.state, args.version))
    print(json.dumps(state, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("plan", "prepare", "publish", "status"):
        command = commands.add_parser(name)
        command.add_argument("--version", required=True)
        if name != "plan":
            command.add_argument("--state", required=True, type=Path)
        if name == "plan":
            command.add_argument("--json", action="store_true")
        elif name == "prepare":
            command.add_argument("--allow-dirty", action="store_true")
        elif name == "publish":
            command.add_argument("--confirm", action="store_true")
            command.add_argument("--registry-api", default="https://crates.io")
            command.add_argument("--timeout", type=float, default=300.0)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        {"plan": plan, "prepare": prepare, "publish": publish, "status": status}[args.command](args)
    except PublishError as error:
        print(f"cargo-publish: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
