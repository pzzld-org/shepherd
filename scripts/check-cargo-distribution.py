#!/usr/bin/env python3
"""Fail-closed static contract for Cargo packages and Binstall assets."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION = "6.4.9"
TARGETS = (
    "aarch64-apple-darwin",
    "x86_64-apple-darwin",
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-gnu",
    "x86_64-pc-windows-msvc",
)
PUBLIC = (
    "shepherd-core",
    "shepherd-compiler",
    "shepherd-registry",
    "shepherd-render",
    "shepherd-sdk",
    "shepherd-cli",
)


def load(relative: str) -> dict:
    with (ROOT / relative).open("rb") as handle:
        return tomllib.load(handle)


def check() -> list[str]:
    errors: list[str] = []
    root = load("Cargo.toml")
    sdk = load("crates/sdk/Cargo.toml")
    cli = load("crates/cli/Cargo.toml")
    component = load("crates/component/Cargo.toml")
    alias = root["workspace"]["dependencies"].get("shepherd", {})
    if alias.get("package") != "shepherd-sdk":
        errors.append("workspace dependency shepherd must alias package shepherd-sdk")
    if sdk["package"].get("name") != "shepherd-sdk" or sdk.get("lib", {}).get("name") != "shepherd":
        errors.append("SDK package shepherd-sdk must expose Rust crate shepherd")
    if component["package"].get("publish") is not False:
        errors.append("shepherd-component must set publish = false")

    manifests = {
        load(str(path.relative_to(ROOT)))["package"]["name"]
        for path in sorted((ROOT / "crates").glob("*/Cargo.toml"))
        if path.parent.name != "component"
    }
    if manifests != set(PUBLIC):
        errors.append(f"public Cargo package set differs: {sorted(manifests)!r}")

    metadata = cli["package"].get("metadata", {}).get("binstall", {})
    expected_url = "{ repo }/releases/download/v{ version }/shepherd-{ version }-{ target }.tar.gz"
    if metadata.get("pkg-url") != expected_url:
        errors.append("Binstall Unix URL must name the immutable .tar.gz asset")
    if metadata.get("bin-dir") != "{ bin }{ binary-ext }" or metadata.get("pkg-fmt") != "tgz":
        errors.append("Binstall binary must be at archive root with tgz as the default format")
    if metadata.get("disabled-strategies") != ["quick-install", "compile"]:
        errors.append("Binstall must disable quick-install and compile fallback")
    windows = metadata.get("overrides", {}).get("x86_64-pc-windows-msvc", {})
    windows_url = "{ repo }/releases/download/v{ version }/shepherd-{ version }-{ target }.zip"
    if windows.get("pkg-url") != windows_url or windows.get("pkg-fmt") != "zip":
        errors.append("Binstall Windows override must select the immutable ZIP")

    inventory = (ROOT / "scripts/verify-release-assets.sh").read_text(encoding="utf-8")
    for target in TARGETS:
        suffix = ".zip" if target.endswith("windows-msvc") else ".tar.gz"
        asset = f"shepherd-${{version}}-{target}{suffix}"
        if asset not in inventory:
            errors.append(f"release inventory is missing {asset}")

    projection = subprocess.run(
        ["python3", "scripts/generate-compiler-package-content.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if projection.returncode != 0:
        errors.append(projection.stderr.strip() or "compiler package projection check failed")
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(f"cargo-distribution: {error}", file=sys.stderr)
        return 1
    print("ok: Cargo package identities, compiler projection, and five Binstall assets agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
