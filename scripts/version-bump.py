#!/usr/bin/env python3
"""Validate and advance Shepherd's release-version authority surfaces.

The tool intentionally does not scan-and-replace every matching version in the
repository. Historical conformance authorities, migration fixtures, changelog
entries, and run artifacts retain the version that gave them meaning. Only the
closed list below is release authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


SEMVER_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

CRATE_MANIFESTS = {
    "crates/cli/Cargo.toml": "shepherd-cli",
    "crates/compiler/Cargo.toml": "shepherd-compiler",
    "crates/component/Cargo.toml": "shepherd-component",
    "crates/core/Cargo.toml": "shepherd-core",
    "crates/registry/Cargo.toml": "shepherd-registry",
    "crates/render/Cargo.toml": "shepherd-render",
    "crates/sdk/Cargo.toml": "shepherd-sdk",
}

INTERNAL_CARGO_DEPENDENCIES = {
    "shepherd": "crates/sdk",
    "shepherd-cli": "crates/cli",
    "shepherd-compiler": "crates/compiler",
    "shepherd-core": "crates/core",
    "shepherd-registry": "crates/registry",
    "shepherd-render": "crates/render",
}

INTERNAL_CARGO_PACKAGE_ALIASES = {"shepherd": "shepherd-sdk"}

NPM_PACKAGES = {
    "packages/component-runtime/package.json": "@pzzld/component-runtime",
    "packages/harness-claude/package.json": "@pzzld/pi-claude",
    "packages/harness-codex/package.json": "@pzzld/pi-codex",
    "packages/harness-pi/package.json": "@pzzld/pi-shepherd",
}

ADAPTER_PACKAGE_PATHS = tuple(
    path for path in NPM_PACKAGES if path != "packages/component-runtime/package.json"
)

CARGO_LOCK_PACKAGES = frozenset(CRATE_MANIFESTS.values())


class VersionAuthorityError(Exception):
    """A release version cannot be checked or changed safely."""


@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str, *, label: str) -> SemVer:
        match = SEMVER_PATTERN.fullmatch(raw)
        if match is None:
            raise VersionAuthorityError(
                f"{label} must be an exact MAJOR.MINOR.PATCH value without a v prefix: {raw!r}"
            )
        version = cls(*(int(part) for part in match.groups()))
        if version.minor > 9 or version.patch > 9:
            raise VersionAuthorityError(
                f"{label} violates Shepherd's mod-10 release policy: {raw!r}"
            )
        return version

    def successor(self) -> SemVer:
        if self.patch < 9:
            return SemVer(self.major, self.minor, self.patch + 1)
        if self.minor < 9:
            return SemVer(self.major, self.minor + 1, 0)
        return SemVer(self.major + 1, 0, 0)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


LAYOUT_V5_INTRODUCTION = SemVer(6, 4, 5)

TEXT_SUFFIXES = frozenset(
    {".json", ".lock", ".md", ".mjs", ".py", ".rs", ".sh", ".toml", ".ts", ".yaml", ".yml"}
)
SCAN_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".remember",
        ".shepherd",
        ".superpowers",
        ".venv",
        ".worktrees",
        "node_modules",
        "target",
    }
)
HISTORICAL_PREFIXES = ("conformance/", "hooks/", "services/", "skills/")
HISTORICAL_PATHS = frozenset(
    {
        ".gitignore",
        "CHANGELOG.md",
        "crates/cli/src/cmd/wave_f_knowledge.rs",
        "crates/render/src/env.rs",
        "scripts/tests/test-version-bump.py",
    }
)


@dataclass(frozen=True, slots=True)
class TextRule:
    path: str
    old: str
    new: str
    expected_count: int
    label: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    path: Path
    content: bytes
    mode: int
    device: int
    inode: int
    modified_ns: int
    size: int


def _whole(path: str, current: SemVer, next_version: SemVer, count: int) -> TextRule:
    return TextRule(path, str(current), str(next_version), count, "release version")


def _literal(
    path: str,
    current: SemVer,
    next_version: SemVer,
    template: str,
    label: str,
) -> TextRule:
    return TextRule(
        path,
        template.format(version=current),
        template.format(version=next_version),
        1,
        label,
    )


def version_rules(current: SemVer, next_version: SemVer) -> tuple[TextRule, ...]:
    rules = [
        _whole("Cargo.toml", current, next_version, 7),
        _whole("Cargo.lock", current, next_version, 7),
        _whole("package.json", current, next_version, 1),
        _whole("package-lock.json", current, next_version, 9),
        _whole("bun.lock", current, next_version, 7),
        _whole("packages/component-runtime/package.json", current, next_version, 1),
        _whole("packages/harness-claude/package.json", current, next_version, 2),
        _whole("packages/harness-codex/package.json", current, next_version, 2),
        _whole("packages/harness-pi/package.json", current, next_version, 2),
        _whole(".claude-plugin/plugin.json", current, next_version, 2),
        _whole("plugins/shepherd/.claude-plugin/plugin.json", current, next_version, 2),
        _whole("plugins/shepherd/.codex-plugin/plugin.json", current, next_version, 1),
        _whole(".claude-plugin/marketplace.json", current, next_version, 3),
        _whole("packages/harness-pi/shepherd.pi.json", current, next_version, 1),
        _literal(
            "README.md",
            current,
            next_version,
            "# Shepherd v{version}",
            "README release heading",
        ),
        TextRule(
            "README.md",
            f"The v{current} component is published as `fl03:shepherd@{current}`.",
            f"The v{next_version} component is published as `fl03:shepherd@{next_version}`.",
            1,
            "README component contract",
        ),
        _literal(
            "README.md",
            current,
            next_version,
            "FL03/shepherd/v{version}/scripts/install-shepherd.sh",
            "README Unix installer tag",
        ),
        _literal(
            "README.md",
            current,
            next_version,
            "SHEPHERD_VERSION={version} bash",
            "README Unix installer version",
        ),
        _literal(
            "README.md",
            current,
            next_version,
            "FL03/shepherd/v{version}/scripts/install-shepherd.ps1",
            "README PowerShell installer tag",
        ),
        _literal(
            "README.md",
            current,
            next_version,
            "$env:SHEPHERD_VERSION = '{version}'",
            "README PowerShell installer version",
        ),
        _literal(
            "README.md",
            current,
            next_version,
            "codex plugin marketplace add FL03/shepherd --ref v{version}",
            "README Codex marketplace release ref",
        ),
        _whole("docs/configuration.md", current, next_version, 1),
        _whole("docs/customization.md", current, next_version, 1),
        _whole("docs/integration.md", current, next_version, 3),
        _whole("content/RECONCILIATION.md", current, next_version, 1),
        _whole("crates/compiler/README.md", current, next_version, 1),
        _whole("crates/component/README.md", current, next_version, 1),
        _whole("crates/sdk/README.md", current, next_version, 1),
        _whole("packages/component-runtime/README.md", current, next_version, 1),
        _whole("packages/harness-claude/README.md", current, next_version, 1),
        _whole("packages/harness-codex/README.md", current, next_version, 1),
        _whole("packages/harness-pi/README.md", current, next_version, 1),
        _whole("packages/harness-pi/src/extension.mjs", current, next_version, 1),
        _literal(
            "crates/component/src/lib.rs",
            current,
            next_version,
            'COMPONENT_CONTRACT_VERSION: &str = "fl03:shepherd@{version}";',
            "Rust component contract constant",
        ),
        _literal(
            "crates/core/src/guard/json.rs",
            current,
            next_version,
            "Byte-exact verdict serialization for the v{version} guard wire.",
            "Rust guard wire version",
        ),
        _literal(
            "crates/core/src/guard/tokenizer.rs",
            current,
            next_version,
            "This intentionally preserves the v{version} token-level compatibility limits:",
            "Rust guard tokenizer compatibility version",
        ),
        _literal(
            "packages/component-runtime/src/index.mjs",
            current,
            next_version,
            'COMPONENT_CONTRACT_VERSION = "fl03:shepherd@{version}";',
            "JavaScript component contract constant",
        ),
        _literal(
            "crates/component/wit/shepherd.wit",
            current,
            next_version,
            "package fl03:shepherd@{version};",
            "WIT package version",
        ),
        _literal(
            "crates/component/tests/component.rs",
            current,
            next_version,
            'wit.contains("package fl03:shepherd@{version};")',
            "Rust component version assertion",
        ),
        _literal(
            "packages/harness-pi/test/subagent-provider.test.mjs",
            current,
            next_version,
            'assert.equal(contract.contract, "fl03:shepherd@{version}");',
            "Pi component version assertion",
        ),
        _literal(
            "scripts/check-features.sh",
            current,
            next_version,
            "'package fl03:shepherd@{version};'",
            "feature-gate WIT assertion",
        ),
        _whole("scripts/check-workspace.sh", current, next_version, 2),
        _whole("scripts/check-cargo-distribution.py", current, next_version, 1),
        _whole("scripts/tests/test-cargo-distribution.py", current, next_version, 1),
        _literal(
            "scripts/gate.sh",
            current,
            next_version,
            "'export fl03:shepherd/engine@{version};'",
            "full-gate WIT assertion",
        ),
        # `.github/workflows/rust-wasm.yml` deliberately is NOT an authority.
        # It derives the version from Cargo.toml, because a literal there made
        # the bump rewrite a workflow file, and GITHUB_TOKEN cannot push such a
        # change -- there is no `workflows` permission scope to grant. Any new
        # version literal in a workflow file recreates that dead end.
        _whole("scripts/test-packed-plugin.sh", current, next_version, 10),
        TextRule(
            "scripts/tests/test-release-installers.sh",
            str(next_version),
            str(next_version.successor()),
            3,
            "installer wrong-version negative control",
        ),
        _whole("scripts/tests/test-release-installers.sh", current, next_version, 25),
        TextRule(
            "scripts/tests/test-release-assets.sh",
            str(next_version),
            str(next_version.successor()),
            2,
            "asset wrong-version negative control",
        ),
        _whole("scripts/tests/test-release-assets.sh", current, next_version, 15),
        _whole("scripts/tests/test-release-distribution-license.sh", current, next_version, 7),
        _whole("packages/scripts/check-package-boundary.mjs", current, next_version, 3),
        _whole("scripts/verify-release-assets.sh", current, next_version, 1),
    ]
    return tuple(rules)


def authority_paths(current: SemVer) -> tuple[str, ...]:
    paths = {rule.path for rule in version_rules(current, current.successor())}
    paths.update(CRATE_MANIFESTS)
    return tuple(sorted(paths))


def _read_snapshots(root: Path, paths: Sequence[str]) -> dict[str, Snapshot]:
    errors: list[str] = []
    snapshots: dict[str, Snapshot] = {}
    for relative in paths:
        path = root / relative
        cursor = root
        symlink = False
        for part in Path(relative).parts:
            cursor /= part
            if cursor.is_symlink():
                symlink = True
                break
        if symlink:
            errors.append(
                f"{relative}: version authority path must not traverse a symlink"
            )
            continue
        try:
            details = path.stat()
        except FileNotFoundError:
            errors.append(f"{relative}: required version authority is missing")
            continue
        if not stat.S_ISREG(details.st_mode):
            errors.append(f"{relative}: version authority is not a regular file")
            continue
        try:
            content = path.read_bytes()
            content.decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"{relative}: cannot read UTF-8 authority: {error}")
            continue
        snapshots[relative] = Snapshot(
            path=path,
            content=content,
            mode=stat.S_IMODE(details.st_mode),
            device=details.st_dev,
            inode=details.st_ino,
            modified_ns=details.st_mtime_ns,
            size=details.st_size,
        )
    if errors:
        raise VersionAuthorityError("\n".join(errors))
    return snapshots


def _parse_toml(relative: str, text: str, errors: list[str]) -> Mapping[str, object] | None:
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        errors.append(f"{relative}: invalid TOML: {error}")
        return None
    return value


def _parse_json(relative: str, text: str, errors: list[str]) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        errors.append(f"{relative}: invalid JSON: {error}")
        return None


def _at(value: object, pointer: Sequence[str], relative: str, errors: list[str]) -> object | None:
    current = value
    walked: list[str] = []
    for part in pointer:
        walked.append(part)
        if not isinstance(current, Mapping) or part not in current:
            errors.append(f"{relative}: missing JSON/TOML path {'.'.join(walked)}")
            return None
        current = current[part]
    return current


def _expect(
    value: object,
    pointer: Sequence[str],
    expected: object,
    relative: str,
    errors: list[str],
) -> None:
    actual = _at(value, pointer, relative, errors)
    if actual is not None and actual != expected:
        errors.append(
            f"{relative}: {'.'.join(pointer)} must be {expected!r}, found {actual!r}"
        )


def _validate_inventory(root: Path, errors: list[str]) -> None:
    actual_crates = {
        str(path.relative_to(root)) for path in (root / "crates").glob("*/Cargo.toml")
    }
    expected_crates = set(CRATE_MANIFESTS)
    if actual_crates != expected_crates:
        errors.append(
            "crates/*/Cargo.toml inventory changed: "
            f"expected {sorted(expected_crates)!r}, found {sorted(actual_crates)!r}"
        )

    actual_packages = {
        str(path.relative_to(root)) for path in (root / "packages").glob("*/package.json")
    }
    expected_packages = set(NPM_PACKAGES)
    if actual_packages != expected_packages:
        errors.append(
            "packages/*/package.json inventory changed: "
            f"expected {sorted(expected_packages)!r}, found {sorted(actual_packages)!r}"
        )


def _validate_cargo(contents: Mapping[str, str], version: SemVer, errors: list[str]) -> None:
    cargo = _parse_toml("Cargo.toml", contents["Cargo.toml"], errors)
    if cargo is not None:
        _expect(cargo, ("workspace", "package", "version"), str(version), "Cargo.toml", errors)
        dependencies = _at(cargo, ("workspace", "dependencies"), "Cargo.toml", errors)
        if isinstance(dependencies, Mapping):
            for name, expected_path in INTERNAL_CARGO_DEPENDENCIES.items():
                dependency = dependencies.get(name)
                if not isinstance(dependency, Mapping):
                    errors.append(f"Cargo.toml: workspace.dependencies.{name} must be a table")
                    continue
                if dependency.get("path") != expected_path:
                    errors.append(
                        f"Cargo.toml: workspace.dependencies.{name}.path must be "
                        f"{expected_path!r}, found {dependency.get('path')!r}"
                    )
                if dependency.get("version") != str(version):
                    errors.append(
                        f"Cargo.toml: workspace.dependencies.{name}.version must be "
                        f"{str(version)!r}, found {dependency.get('version')!r}"
                    )
                expected_package = INTERNAL_CARGO_PACKAGE_ALIASES.get(name)
                if expected_package is not None and dependency.get("package") != expected_package:
                    errors.append(
                        f"Cargo.toml: workspace.dependencies.{name}.package must be "
                        f"{expected_package!r}, found {dependency.get('package')!r}"
                    )

    for relative, expected_name in CRATE_MANIFESTS.items():
        manifest = _parse_toml(relative, contents[relative], errors)
        if manifest is None:
            continue
        _expect(manifest, ("package", "name"), expected_name, relative, errors)
        _expect(manifest, ("package", "version", "workspace"), True, relative, errors)

    lock = _parse_toml("Cargo.lock", contents["Cargo.lock"], errors)
    if lock is None:
        return
    packages = lock.get("package")
    if not isinstance(packages, list):
        errors.append("Cargo.lock: package array is missing")
        return
    shepherd_packages: dict[str, object] = {}
    for package in packages:
        if not isinstance(package, Mapping):
            continue
        name = package.get("name")
        if isinstance(name, str) and (name == "shepherd" or name.startswith("shepherd-")):
            shepherd_packages[name] = package.get("version")
    if set(shepherd_packages) != CARGO_LOCK_PACKAGES:
        errors.append(
            "Cargo.lock: Shepherd package inventory changed: "
            f"expected {sorted(CARGO_LOCK_PACKAGES)!r}, found {sorted(shepherd_packages)!r}"
        )
    for name in sorted(CARGO_LOCK_PACKAGES):
        if shepherd_packages.get(name) != str(version):
            errors.append(
                f"Cargo.lock: {name} version must be {str(version)!r}, "
                f"found {shepherd_packages.get(name)!r}"
            )


def _validate_npm(contents: Mapping[str, str], version: SemVer, errors: list[str]) -> None:
    root = _parse_json("package.json", contents["package.json"], errors)
    if root is not None:
        _expect(root, ("name",), "@pzzld/shepherd-workspace", "package.json", errors)
        _expect(root, ("version",), str(version), "package.json", errors)
        _expect(root, ("workspaces",), ["packages/*"], "package.json", errors)

    for relative, expected_name in NPM_PACKAGES.items():
        manifest = _parse_json(relative, contents[relative], errors)
        if manifest is None:
            continue
        _expect(manifest, ("name",), expected_name, relative, errors)
        _expect(manifest, ("version",), str(version), relative, errors)
        if relative in ADAPTER_PACKAGE_PATHS:
            _expect(
                manifest,
                ("dependencies", "@pzzld/component-runtime"),
                str(version),
                relative,
                errors,
            )

    package_lock = _parse_json("package-lock.json", contents["package-lock.json"], errors)
    if package_lock is not None:
        _expect(package_lock, ("name",), "@pzzld/shepherd-workspace", "package-lock.json", errors)
        _expect(package_lock, ("version",), str(version), "package-lock.json", errors)
        _expect(
            package_lock,
            ("packages", "", "version"),
            str(version),
            "package-lock.json",
            errors,
        )
        for relative, expected_name in NPM_PACKAGES.items():
            package_path = relative.removesuffix("/package.json")
            _expect(
                package_lock,
                ("packages", package_path, "name"),
                expected_name,
                "package-lock.json",
                errors,
            )
            _expect(
                package_lock,
                ("packages", package_path, "version"),
                str(version),
                "package-lock.json",
                errors,
            )
            if relative in ADAPTER_PACKAGE_PATHS:
                _expect(
                    package_lock,
                    ("packages", package_path, "dependencies", "@pzzld/component-runtime"),
                    str(version),
                    "package-lock.json",
                    errors,
                )


def _validate_plugin(contents: Mapping[str, str], version: SemVer, errors: list[str]) -> None:
    contract = f"fl03:shepherd@{version}"
    canonical_plugin = contents[".claude-plugin/plugin.json"]
    carrier_plugin = contents["plugins/shepherd/.claude-plugin/plugin.json"]
    if carrier_plugin != canonical_plugin:
        errors.append(
            "plugins/shepherd/.claude-plugin/plugin.json: must be byte-identical to "
            ".claude-plugin/plugin.json"
        )
    plugin = _parse_json(
        ".claude-plugin/plugin.json",
        canonical_plugin,
        errors,
    )
    if plugin is not None:
        _expect(plugin, ("name",), "shepherd", ".claude-plugin/plugin.json", errors)
        _expect(plugin, ("version",), str(version), ".claude-plugin/plugin.json", errors)
        description = _at(plugin, ("description",), ".claude-plugin/plugin.json", errors)
        if isinstance(description, str) and description.count(contract) != 1:
            errors.append(
                ".claude-plugin/plugin.json: description must contain exactly one "
                f"{contract!r} contract"
            )

    codex_path = "plugins/shepherd/.codex-plugin/plugin.json"
    codex = _parse_json(codex_path, contents[codex_path], errors)
    if codex is not None:
        _expect(codex, ("name",), "shepherd", codex_path, errors)
        _expect(codex, ("version",), str(version), codex_path, errors)
        _expect(codex, ("skills",), "./codex/skills/", codex_path, errors)
        _expect(codex, ("hooks",), "./codex/hooks/hooks.json", codex_path, errors)

    pi_contract = _parse_json(
        "packages/harness-pi/shepherd.pi.json",
        contents["packages/harness-pi/shepherd.pi.json"],
        errors,
    )
    if pi_contract is not None:
        _expect(
            pi_contract,
            ("contract",),
            contract,
            "packages/harness-pi/shepherd.pi.json",
            errors,
        )


def _apply_rules(
    contents: Mapping[str, str], rules: Sequence[TextRule], errors: list[str]
) -> dict[str, str]:
    updated = dict(contents)
    for rule in rules:
        text = updated[rule.path]
        observed = text.count(rule.old)
        if observed != rule.expected_count:
            errors.append(
                f"{rule.path}: {rule.label} expected {rule.expected_count} occurrence(s), "
                f"found {observed}"
            )
            continue
        updated[rule.path] = text.replace(rule.old, rule.new)
    return updated


def _validate_rule_coverage(
    updated: Mapping[str, str],
    rules: Sequence[TextRule],
    current: SemVer,
    errors: list[str],
) -> None:
    for relative in sorted({rule.path for rule in rules}):
        residual = updated[relative]
        if relative == "README.md" and current == LAYOUT_V5_INTRODUCTION:
            historical = (
                f"pre-v{current} namespace",
                f"owned by the Rust CLI in v{current}:",
            )
            for marker in historical:
                observed = residual.count(marker)
                if observed != 1:
                    errors.append(
                        f"README.md: historical marker {marker!r} expected once, found {observed}"
                    )
                residual = residual.replace(marker, "")
        if str(current) in residual:
            errors.append(
                f"{relative}: contains an unclassified {current} version reference"
            )


def _is_historical(relative: str) -> bool:
    if relative in HISTORICAL_PATHS or relative.startswith(HISTORICAL_PREFIXES):
        return True
    parts = relative.split("/")
    return len(parts) >= 3 and parts[0] == "crates" and "tests" in parts[2:]


def _scan_unclassified_files(
    root: Path,
    contents: Mapping[str, str],
    version: SemVer,
    errors: list[str],
) -> None:
    authority = set(contents)
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in SCAN_EXCLUDED_DIRECTORIES
            and not (directory_path / name).is_symlink()
        )
        for file_name in sorted(file_names):
            path = directory_path / file_name
            if path.is_symlink() or path.suffix not in TEXT_SUFFIXES:
                continue
            relative = str(path.relative_to(root))
            if relative in authority or _is_historical(relative):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if str(version) in text:
                errors.append(f"{relative}: unclassified {version} version surface")


def _validate_and_render(
    root: Path,
    snapshots: Mapping[str, Snapshot],
    current: SemVer,
    next_version: SemVer,
) -> dict[str, str]:
    contents = {
        relative: snapshot.content.decode("utf-8") for relative, snapshot in snapshots.items()
    }
    errors: list[str] = []
    _validate_inventory(root, errors)
    _validate_cargo(contents, current, errors)
    _validate_npm(contents, current, errors)
    _validate_plugin(contents, current, errors)
    rules = version_rules(current, next_version)
    updated = _apply_rules(contents, rules, errors)
    _validate_rule_coverage(updated, rules, current, errors)
    _scan_unclassified_files(root, contents, current, errors)
    if errors:
        raise VersionAuthorityError("\n".join(errors))

    post_errors: list[str] = []
    _validate_cargo(updated, next_version, post_errors)
    _validate_npm(updated, next_version, post_errors)
    _validate_plugin(updated, next_version, post_errors)
    post_rules = version_rules(next_version, next_version.successor())
    post_updated = _apply_rules(updated, post_rules, post_errors)
    _validate_rule_coverage(post_updated, post_rules, next_version, post_errors)
    _scan_unclassified_files(root, updated, next_version, post_errors)
    if post_errors:
        raise VersionAuthorityError(
            "internal post-update validation failed:\n" + "\n".join(post_errors)
        )
    return updated


def _same_snapshot(snapshot: Snapshot) -> bool:
    try:
        details = snapshot.path.stat()
        content = snapshot.path.read_bytes()
    except OSError:
        return False
    return (
        details.st_dev == snapshot.device
        and details.st_ino == snapshot.inode
        and details.st_mtime_ns == snapshot.modified_ns
        and details.st_size == snapshot.size
        and content == snapshot.content
    )


def _write_temp(snapshot: Snapshot, content: bytes, suffix: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{snapshot.path.name}.",
        suffix=suffix,
        dir=snapshot.path.parent,
    )
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, snapshot.mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    return path


def _commit(snapshots: Mapping[str, Snapshot], rendered: Mapping[str, str]) -> tuple[str, ...]:
    changed = tuple(
        relative
        for relative in sorted(rendered)
        if rendered[relative].encode("utf-8") != snapshots[relative].content
    )
    if not changed:
        return ()

    replacements: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    try:
        for relative in changed:
            snapshot = snapshots[relative]
            replacements[relative] = _write_temp(
                snapshot,
                rendered[relative].encode("utf-8"),
                ".version-next",
            )
            backups[relative] = _write_temp(snapshot, snapshot.content, ".version-backup")

        raced = [relative for relative in changed if not _same_snapshot(snapshots[relative])]
        if raced:
            raise VersionAuthorityError(
                "version authorities changed after validation: " + ", ".join(raced)
            )

        replaced: list[str] = []
        try:
            for relative in changed:
                os.replace(replacements[relative], snapshots[relative].path)
                replaced.append(relative)
        except OSError as error:
            rollback_errors: list[str] = []
            for relative in reversed(replaced):
                try:
                    os.replace(backups[relative], snapshots[relative].path)
                except OSError as rollback_error:
                    rollback_errors.append(f"{relative}: {rollback_error}")
            detail = f"atomic publication failed: {error}"
            if rollback_errors:
                detail += "; rollback failures: " + "; ".join(rollback_errors)
            raise VersionAuthorityError(detail) from error
    finally:
        for path in (*replacements.values(), *backups.values()):
            path.unlink(missing_ok=True)
    return changed


def check(root: Path, version: SemVer) -> int:
    resolved = root.resolve(strict=True)
    snapshots = _read_snapshots(resolved, authority_paths(version))
    _validate_and_render(resolved, snapshots, version, version.successor())
    print(
        f"version-bump: OK version={version} authorities={len(snapshots)} mode=check"
    )
    return 0


def bump(root: Path, current: SemVer, next_version: SemVer) -> int:
    expected = current.successor()
    if next_version != expected:
        raise VersionAuthorityError(
            f"next must be the canonical successor of {current}: expected {expected}, "
            f"found {next_version}"
        )
    resolved = root.resolve(strict=True)
    snapshots = _read_snapshots(resolved, authority_paths(current))
    rendered = _validate_and_render(resolved, snapshots, current, next_version)
    changed = _commit(snapshots, rendered)
    print(
        f"version-bump: OK current={current} next={next_version} "
        f"updated={len(changed)}"
    )
    for relative in changed:
        print(relative)
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Fail-closed Shepherd release-version checker and bump tool."
    )
    subcommands = command.add_subparsers(dest="command", required=True)

    check_command = subcommands.add_parser("check", help="validate one exact current version")
    check_command.add_argument("--version", required=True)
    check_command.add_argument("--root", type=Path, default=Path.cwd())

    bump_command = subcommands.add_parser(
        "bump", help="validate current, then stage and atomically publish the next version"
    )
    bump_command.add_argument("--current", required=True)
    bump_command.add_argument("--next", dest="next_version", required=True)
    bump_command.add_argument("--root", type=Path, default=Path.cwd())
    return command


def main(arguments: Sequence[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    try:
        if options.command == "check":
            version = SemVer.parse(options.version, label="version")
            return check(options.root, version)
        current = SemVer.parse(options.current, label="current")
        next_version = SemVer.parse(options.next_version, label="next")
        return bump(options.root, current, next_version)
    except (OSError, VersionAuthorityError) as error:
        print(f"version-bump: ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
