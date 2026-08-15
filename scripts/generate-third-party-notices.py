#!/usr/bin/env python3
"""Render locked dependency notices and deduplicated bundled license texts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LICENSE_PREFIXES = ("license", "copying", "notice", "copyright", "unlicense")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def license_texts(package_root: Path, declared_license: str | None) -> list[tuple[str, bytes]]:
    if not package_root.is_dir() or package_root.is_symlink():
        raise RuntimeError(f"dependency source is unavailable for bundled license text: {package_root}")
    candidates = sorted(
        path
        for path in package_root.iterdir()
        if path.is_file() and path.name.casefold().startswith(LICENSE_PREFIXES)
    )
    if not candidates:
        raise RuntimeError(f"dependency has no bundled license or notice text: {package_root}")
    return [(path.name, path.read_bytes()) for path in candidates]


def cargo_closure(metadata: dict[str, object], package_name: str) -> list[dict[str, object]]:
    """Return precisely the resolved packages reachable from one shipped crate."""
    packages = {package["id"]: package for package in metadata["packages"]}  # type: ignore[index]
    roots = [package_id for package_id, package in packages.items() if package["name"] == package_name]
    if len(roots) != 1:
        raise RuntimeError(f"expected one Cargo package named {package_name!r}, found {len(roots)}")
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}  # type: ignore[index]
    pending = [roots[0]]
    selected: set[str] = set()
    while pending:
        package_id = pending.pop()
        if package_id in selected:
            continue
        selected.add(package_id)
        try:
            pending.extend(nodes[package_id].get("dependencies", []))
        except KeyError as error:
            raise RuntimeError(f"Cargo resolve graph omitted package {package_id}") from error
    return [packages[package_id] for package_id in sorted(selected)]


def cargo_rows(target: str, package_name: str) -> list[dict[str, object]]:
    metadata = subprocess.run(
        ["cargo", "metadata", "--locked", "--format-version", "1", "--filter-platform", target],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    checksums = {
        (item["name"], item["version"], item["source"]): item.get("checksum", "not supplied")
        for item in tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8")).get("package", [])
        if item.get("source")
    }
    rows = []
    for package in cargo_closure(json.loads(metadata.stdout), package_name):
        if not package.get("source"):
            continue
        root = Path(package["manifest_path"]).parent
        rows.append({
            "kind": "Rust crate",
            "name": package["name"],
            "version": package["version"],
            "origin": package["source"],
            "integrity": checksums[(package["name"], package["version"], package["source"])],
            "license": package.get("license") or "not supplied",
            "texts": license_texts(root, package.get("license")),
        })
    return sorted(rows, key=lambda row: (str(row["name"]), str(row["version"])))


def node_closure(lock: dict[str, object], package_names: list[str]) -> list[str]:
    """Resolve production dependencies from shipped workspace package roots.

    package-lock records every developer tool and every platform optional
    binary. Neither is evidence that it is bundled in an adapter payload.
    """
    packages: dict[str, dict[str, object]] = lock["packages"]  # type: ignore[index]
    by_name: dict[str, list[str]] = {}
    for lock_path, package in packages.items():
        name = package.get("name")
        if isinstance(name, str):
            by_name.setdefault(name, []).append(lock_path)
    roots: list[str] = []
    for name in package_names:
        candidates = sorted(path for path in by_name.get(name, []) if path.startswith("packages/"))
        if not candidates:
            raise RuntimeError(f"no workspace package-lock entry for shipped Node package {name!r}")
        if len(candidates) != 1:
            raise RuntimeError(f"ambiguous workspace package-lock entries for {name!r}")
        roots.append(candidates[0])

    def dependency_path(parent: str, name: str) -> str:
        workspace = sorted(path for path in by_name.get(name, []) if path.startswith("packages/"))
        if workspace:
            if len(workspace) != 1:
                raise RuntimeError(f"ambiguous workspace dependency {name!r}")
            return workspace[0]
        candidate = f"node_modules/{name}"
        if candidate in packages:
            return candidate
        raise RuntimeError(f"package-lock does not resolve shipped dependency {name!r} from {parent!r}")

    pending = roots[:]
    selected: set[str] = set()
    while pending:
        lock_path = pending.pop()
        if lock_path in selected:
            continue
        package = packages[lock_path]
        if (
            lock_path.startswith("node_modules/")
            and (package.get("optional") or package.get("os") or package.get("cpu"))
        ):
            continue
        selected.add(lock_path)
        dependencies = dict(package.get("dependencies", {}))
        dependencies.update(package.get("optionalDependencies", {}))
        for name in sorted(dependencies):
            pending.append(dependency_path(lock_path, name))

    return sorted(
        lock_path for lock_path in selected
        if lock_path.startswith("node_modules/")
    )


def node_rows(package_names: list[str], node_root: Path = ROOT) -> list[dict[str, object]]:
    lock: dict[str, object] = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    rows = []
    packages: dict[str, dict[str, object]] = lock["packages"]  # type: ignore[index]
    for lock_path in node_closure(lock, package_names):
        package = packages[lock_path]
        root = node_root / lock_path
        rows.append({
            "kind": "Node package",
            "name": lock_path.removeprefix("node_modules/"),
            "version": package.get("version", "not supplied"),
            "origin": package.get("resolved", "not supplied"),
            "integrity": package.get("integrity", "not supplied"),
            "license": package.get("license", "not supplied"),
            "texts": license_texts(root, package.get("license")),
        })
    return sorted(rows, key=lambda row: str(row["name"]))


def build(scope: str, target: str) -> tuple[str, dict[str, bytes]]:
    scopes: dict[str, tuple[list[str], list[str]]] = {
        "native": (["shepherd-cli"], []),
        "component": (["shepherd-component"], []),
        "npm-component-runtime": (["shepherd-component"], ["@fl03/component-runtime"]),
        "npm-harness-claude": ([], ["@fl03/harness-claude"]),
        "npm-harness-codex": ([], ["@fl03/harness-codex"]),
        "npm-harness-pi": ([], ["@fl03/harness-pi"]),
        "claude": (["shepherd-component"], ["@fl03/harness-claude"]),
        "full": (["shepherd-cli", "shepherd-component"], ["@fl03/harness-claude"]),
    }
    cargo_packages, node_packages = scopes[scope]
    rows = [row for package_name in cargo_packages for row in cargo_rows(target, package_name)]
    if node_packages:
        rows.extend(node_rows(node_packages))
    unique_rows: dict[tuple[str, str, str, str, str], dict[str, object]] = {}
    for row in rows:
        identity = tuple(str(row[field]) for field in ("kind", "name", "version", "origin", "integrity"))
        unique_rows.setdefault(identity, row)
    rows = [unique_rows[identity] for identity in sorted(unique_rows)]
    texts: dict[str, bytes] = {}
    rendered_rows = []
    for row in rows:
        text_ids = []
        for _, content in row["texts"]:  # type: ignore[index]
            text_id = digest(content)
            texts.setdefault(text_id, content)
            text_ids.append(f"`THIRD_PARTY_LICENSES/{text_id}.txt`")
        rendered_rows.append(
            "| {kind} | `{name}` | `{version}` | `{license}` | `{origin}` | `{integrity}` | {texts} |\n".format(
                kind=row["kind"], name=row["name"], version=row["version"],
                license=row["license"], origin=row["origin"], integrity=row["integrity"],
                texts="<br>".join(sorted(set(text_ids))),
            )
        )
    header = "# Third-Party Notices\n\n"
    header += "This inventory is generated from the exact locked dependency graph shipped in this distribution. "
    header += "Every `Bundled license text` entry names a byte-for-byte file included next to this notice. "
    header += "Do not edit this file by hand. Regenerate it with `python3 scripts/generate-third-party-notices.py`.\n\n"
    header += "## Dependency inventory\n\n"
    header += "| Kind | Name | Version | Declared license | Origin | Locked integrity | Bundled license text |\n"
    header += "| --- | --- | --- | --- | --- | --- | --- |\n"
    return header + "".join(rendered_rows), texts


def write_tree(directory: Path, texts: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    expected = {f"{text_id}.txt" for text_id in texts}
    for existing in directory.iterdir():
        if existing.name not in expected or not existing.is_file():
            if existing.is_dir():
                raise RuntimeError(f"refusing to delete unexpected directory in license output: {existing}")
            existing.unlink()
    for text_id, content in texts.items():
        (directory / f"{text_id}.txt").write_bytes(content)


def check_tree(directory: Path, texts: dict[str, bytes]) -> bool:
    expected = {f"{text_id}.txt" for text_id in texts}
    actual = {path.name for path in directory.iterdir()} if directory.is_dir() else set()
    return actual == expected and all(
        (directory / f"{text_id}.txt").read_bytes() == content
        for text_id, content in texts.items()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=("native", "component", "npm-component-runtime", "npm-harness-claude", "npm-harness-codex", "npm-harness-pi", "claude", "full"),
        default="full",
    )
    parser.add_argument("--target", default="wasm32-wasip2")
    parser.add_argument("--output", type=Path, default=ROOT / "THIRD_PARTY_NOTICES.md")
    parser.add_argument("--licenses-dir", type=Path, default=ROOT / "THIRD_PARTY_LICENSES")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        notices, texts = build(args.scope, args.target)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"third-party notices: {error}", file=sys.stderr)
        return 1
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != notices or not check_tree(args.licenses_dir, texts):
            print("third-party notices are stale or incomplete", file=sys.stderr)
            return 1
        return 0
    args.output.write_text(notices, encoding="utf-8")
    write_tree(args.licenses_dir, texts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
