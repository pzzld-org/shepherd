#!/usr/bin/env python3
"""Mutation controls for live release-trust dependency measurements."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from collections.abc import Callable
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check-deps.mjs"
AS_OF = "2026-08-22"
FIXTURE_DIR = ".release-trust-fixtures"
CARGO_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"
CARGO_DEV_ID = f"{CARGO_SOURCE}#cargo-dev@1.0.0"
CARGO_RUNTIME_ID = f"{CARGO_SOURCE}#cargo-runtime@1.0.0"
ROOT_IDS = {
    name: f"path+file:///fixture/crates/{directory}#{name}@1.0.0"
    for name, directory in (
        ("shepherd-cli", "cli"),
        ("shepherd-compiler", "compiler"),
        ("shepherd-component", "component"),
        ("shepherd-core", "core"),
        ("shepherd-registry", "registry"),
        ("shepherd-render", "render"),
        ("shepherd-sdk", "sdk"),
    )
}
NPM_DEV_FINDING = "npm:critical-dev:node_modules/build-tool/node_modules/critical-dev"
NPM_OPTIONAL_FINDING = "npm:optional-vuln:node_modules/optional-vuln"
CARGO_DEV_FINDING = f"cargo:RUSTSEC-dev-only:{CARGO_DEV_ID}"
CARGO_RUNTIME_FINDING = f"cargo:RUSTSEC-runtime:{CARGO_RUNTIME_ID}"


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(root: Path, relative: str, value: object) -> None:
    write(root, relative, json.dumps(value, indent=2, sort_keys=False) + "\n")


def npm_audit_report() -> dict[str, Any]:
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "critical-dev": {
                "name": "critical-dev",
                "severity": "critical",
                "isDirect": False,
                "via": [
                    {
                        "source": 1001,
                        "name": "critical-dev",
                        "dependency": "critical-dev",
                        "title": "development-only fixture advisory",
                        "url": "https://github.com/advisories/GHSA-dev-only",
                        "severity": "critical",
                        "range": "<=1.0.0",
                    }
                ],
                "effects": ["build-tool"],
                "range": "<=1.0.0",
                "nodes": ["node_modules/build-tool/node_modules/critical-dev"],
                "fixAvailable": False,
            },
            "optional-vuln": {
                "name": "optional-vuln",
                "severity": "moderate",
                "isDirect": False,
                "via": ["runtime-parent"],
                "effects": [],
                "range": "<2.0.0",
                "nodes": ["node_modules/optional-vuln"],
                "fixAvailable": {
                    "name": "optional-vuln",
                    "version": "2.0.0",
                    "isSemVerMajor": True,
                },
            },
        },
        "metadata": {
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 1,
                "high": 0,
                "critical": 1,
                "total": 2,
            },
            "dependencies": {"prod": 3, "dev": 2, "optional": 1, "peer": 0, "total": 5},
        },
    }


def cargo_advisories_report() -> dict[str, Any]:
    def vulnerability(
        advisory_id: str,
        package: str,
        cvss: str,
        patched: list[str],
    ) -> dict[str, Any]:
        return {
            "advisory": {
                "id": advisory_id,
                "package": package,
                "title": f"{package} fixture advisory",
                "description": "fixture",
                "date": "2026-08-01",
                "aliases": [],
                "related": [],
                "collection": "crates",
                "categories": [],
                "keywords": [],
                "cvss": cvss,
                "informational": None,
                "references": [],
                "source": None,
                "url": f"https://rustsec.org/advisories/{advisory_id}.html",
                "withdrawn": None,
                "license": "CC0-1.0",
                "expect-deleted": False,
            },
            "versions": {"patched": patched, "unaffected": []},
            "affected": None,
            "package": {
                "name": package,
                "version": "1.0.0",
                "source": CARGO_SOURCE,
                "checksum": None,
                "dependencies": [],
                "replace": None,
            },
        }

    return {
        "lockfile": {"dependency-count": 9},
        "settings": {
            "ignore": [],
            "informational_warnings": ["notice", "unmaintained", "unsound"],
            "severity": None,
            "target_arch": [],
            "target_os": [],
        },
        "vulnerabilities": [
            vulnerability(
                "RUSTSEC-dev-only",
                "cargo-dev",
                "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                [">=2.0.0"],
            ),
            vulnerability(
                "RUSTSEC-runtime",
                "cargo-runtime",
                "CVSS:3.1/AV:L/AC:H/PR:L/UI:R/S:U/C:L/I:L/A:N",
                [],
            ),
        ],
        "warnings": {},
    }


def cargo_metadata_report() -> dict[str, Any]:
    packages: list[dict[str, Any]] = []
    for name, package_id in ROOT_IDS.items():
        packages.append(
            {
                "name": name,
                "version": "1.0.0",
                "id": package_id,
                "license": "Apache-2.0",
                "source": None,
                "dependencies": [],
                "targets": [{"name": name, "kind": ["lib"], "crate_types": ["lib"]}],
                "features": {},
                "manifest_path": f"/fixture/crates/{name}/Cargo.toml",
                "publish": [] if name == "shepherd-component" else None,
            }
        )
    for name, package_id in (("cargo-dev", CARGO_DEV_ID), ("cargo-runtime", CARGO_RUNTIME_ID)):
        packages.append(
            {
                "name": name,
                "version": "1.0.0",
                "id": package_id,
                "license": "MIT",
                "source": CARGO_SOURCE,
                "dependencies": [],
                "targets": [{"name": name, "kind": ["lib"], "crate_types": ["lib"]}],
                "features": {},
                "manifest_path": f"/registry/{name}/Cargo.toml",
            }
        )

    nodes = [{"id": package_id, "dependencies": [], "deps": [], "features": []} for package_id in ROOT_IDS.values()]
    by_id = {node["id"]: node for node in nodes}
    by_id[ROOT_IDS["shepherd-cli"]]["dependencies"] = [CARGO_RUNTIME_ID]
    by_id[ROOT_IDS["shepherd-cli"]]["deps"] = [
        {
            "name": "cargo_runtime",
            "pkg": CARGO_RUNTIME_ID,
            "dep_kinds": [{"kind": None, "target": None}],
        }
    ]
    by_id[ROOT_IDS["shepherd-component"]]["dependencies"] = [CARGO_DEV_ID]
    by_id[ROOT_IDS["shepherd-component"]]["deps"] = [
        {
            "name": "cargo_dev",
            "pkg": CARGO_DEV_ID,
            "dep_kinds": [{"kind": "dev", "target": None}],
        }
    ]
    nodes.extend(
        [
            {"id": CARGO_DEV_ID, "dependencies": [], "deps": [], "features": []},
            {"id": CARGO_RUNTIME_ID, "dependencies": [], "deps": [], "features": []},
        ]
    )
    return {
        "packages": packages,
        "workspace_members": list(ROOT_IDS.values()),
        "workspace_default_members": [ROOT_IDS["shepherd-cli"]],
        "resolve": {"root": None, "nodes": nodes},
        "target_directory": "/fixture/target",
        "version": 1,
        "workspace_root": "/fixture",
        "metadata": None,
    }


def base_policy() -> dict[str, Any]:
    all_npm_artifacts = [
        "@pzzld/claude-shepherd",
        "@pzzld/codex-shepherd",
        "@pzzld/component-runtime",
        "@pzzld/pi-shepherd",
    ]
    observed = [
        {
            "id": CARGO_DEV_FINDING,
            "ecosystem": "cargo",
            "package": "cargo-dev",
            "version": "1.0.0",
            "packageId": CARGO_DEV_ID,
            "advisory": "RUSTSEC-dev-only",
            "advisoryKind": "vulnerability",
            "cvss": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "affected": {"patched": [">=2.0.0"], "unaffected": []},
            "fix": {"status": "available", "versions": [">=2.0.0"]},
        },
        {
            "id": CARGO_RUNTIME_FINDING,
            "ecosystem": "cargo",
            "package": "cargo-runtime",
            "version": "1.0.0",
            "packageId": CARGO_RUNTIME_ID,
            "advisory": "RUSTSEC-runtime",
            "advisoryKind": "vulnerability",
            "cvss": "CVSS:3.1/AV:L/AC:H/PR:L/UI:R/S:U/C:L/I:L/A:N",
            "affected": {"patched": [], "unaffected": []},
            "fix": {"status": "none"},
        },
        {
            "id": NPM_DEV_FINDING,
            "ecosystem": "npm",
            "package": "critical-dev",
            "version": "1.0.0",
            "node": "node_modules/build-tool/node_modules/critical-dev",
            "severity": "critical",
            "affected": "<=1.0.0",
            "advisories": ["GHSA-dev-only"],
            "fix": {"status": "none"},
        },
        {
            "id": NPM_OPTIONAL_FINDING,
            "ecosystem": "npm",
            "package": "optional-vuln",
            "version": "1.0.0",
            "node": "node_modules/optional-vuln",
            "severity": "moderate",
            "affected": "<2.0.0",
            "advisories": ["package:runtime-parent"],
            "fix": {
                "status": "semver-major",
                "package": "optional-vuln",
                "version": "2.0.0",
            },
        },
    ]
    classifications = [
        {
            "id": CARGO_DEV_FINDING,
            "productionClosure": False,
            "reachable": False,
            "dependencyPath": [],
            "shippedArtifacts": [],
            "rationale": "The only metadata edge is dev-only and is excluded from every shipped Cargo artifact.",
            "disposition": "not-shipped",
        },
        {
            "id": CARGO_RUNTIME_FINDING,
            "productionClosure": True,
            "reachable": False,
            "dependencyPath": [ROOT_IDS["shepherd-cli"], CARGO_RUNTIME_ID],
            "shippedArtifacts": ["crates.io:shepherd-cli", "github-release:shepherd"],
            "rationale": "The exact package ID is in the native CLI normal-dependency closure but the affected API is not called.",
            "disposition": "not-reachable",
        },
        {
            "id": NPM_DEV_FINDING,
            "productionClosure": False,
            "reachable": False,
            "dependencyPath": [],
            "shippedArtifacts": [],
            "rationale": "The vulnerable duplicate path is nested below root development tooling, not a shipped workspace package.",
            "disposition": "not-shipped",
        },
        {
            "id": NPM_OPTIONAL_FINDING,
            "productionClosure": True,
            "reachable": False,
            "dependencyPath": ["packages/component-runtime", "node_modules/optional-vuln"],
            "shippedArtifacts": all_npm_artifacts,
            "rationale": "Every shipped adapter resolves the component runtime, whose optional dependency resolves to this exact lock path.",
            "disposition": "not-reachable",
        },
    ]
    return {
        "schema": 2,
        "measuredOn": AS_OF,
        "sources": {
            "npm": "npm audit --json",
            "cargoDeny": "cargo deny --workspace --all-features check",
            "cargoAdvisories": "cargo deny --format json --workspace --all-features check advisories --audit-compatible-output",
            "cargoMetadata": "cargo metadata --format-version 1 --locked --all-features",
        },
        "observedFindings": observed,
        "classifications": classifications,
    }


def workflow_text() -> str:
    return textwrap.dedent(
        """\
        name: release
        jobs:
          release-metadata:
            name: Resolve release metadata
            runs-on: ubuntu-latest
            steps:
              - name: Detect exact release version
                id: detect
                shell: bash
                run: |
                  set -euo pipefail
                  current=1.0.0
                  printf 'current=%s\\n' "$current" >> "$GITHUB_OUTPUT"
                  printf 'proceed=true\\n' >> "$GITHUB_OUTPUT"
              - name: Verify version authority
                if: steps.detect.outputs.proceed == 'true'
                run: python3 scripts/version-bump.py check --root . --version "${{ steps.detect.outputs.current }}"
              - name: Verify dependency policy mutations
                if: steps.detect.outputs.proceed == 'true'
                run: python3 scripts/tests/test-dependency-policy.py
              - name: Setup cargo-deny
                if: steps.detect.outputs.proceed == 'true'
                uses: taiki-e/install-action@v2
                with:
                  tool: cargo-deny
              - name: Verify live dependency trust
                if: steps.detect.outputs.proceed == 'true'
                run: node scripts/check-deps.mjs
          unrelated:
            runs-on: ubuntu-latest
            steps:
              - run: echo done
        """
    )


def active_inventory() -> dict[str, Any]:
    return {
        "schema": 1,
        "activeSurfaces": [
            {"path": ".claude/settings.json", "kind": "marketplace-discovery"},
            {"path": "README.md", "kind": "installation-documentation"},
        ],
        "historicalPaths": ["CHANGELOG.md"],
        "historicalPrefixes": [".shepherd/runs/", "conformance/"],
        "preservedContributorIdentity": [
            {"path": ".github/FUNDING.yml", "requiredText": "FL03"},
            {"path": "CODEOWNERS", "requiredText": "@FL03"},
        ],
    }


def seed_fixture(root: Path) -> None:
    write_json(
        root,
        "package.json",
        {
            "name": "fixture",
            "private": True,
            "workspaces": ["packages/*"],
            "devDependencies": {"build-tool": "1.0.0"},
            "shepherdReleaseTrust": base_policy(),
        },
    )
    write_json(
        root,
        "packages/component-runtime/package.json",
        {
            "name": "@pzzld/component-runtime",
            "version": "1.0.0",
            "dependencies": {"critical-dev": "2.0.0"},
            "optionalDependencies": {"optional-vuln": "1.0.0"},
            "devDependencies": {"dev-root": "1.0.0"},
        },
    )
    for directory, name in (
        ("harness-claude", "@pzzld/claude-shepherd"),
        ("harness-codex", "@pzzld/codex-shepherd"),
        ("harness-pi", "@pzzld/pi-shepherd"),
    ):
        write_json(
            root,
            f"packages/{directory}/package.json",
            {"name": name, "version": "1.0.0", "dependencies": {"@pzzld/component-runtime": "1.0.0"}},
        )
    write_json(
        root,
        "package-lock.json",
        {
            "name": "fixture",
            "lockfileVersion": 3,
            "packages": {
                "": {"devDependencies": {"build-tool": "1.0.0"}},
                "packages/component-runtime": {
                    "name": "@pzzld/component-runtime",
                    "version": "1.0.0",
                    "dependencies": {"critical-dev": "2.0.0"},
                    "optionalDependencies": {"optional-vuln": "1.0.0"},
                    "devDependencies": {"dev-root": "1.0.0"},
                },
                "packages/harness-claude": {
                    "name": "@pzzld/claude-shepherd",
                    "version": "1.0.0",
                    "dependencies": {"@pzzld/component-runtime": "1.0.0"},
                },
                "packages/harness-codex": {
                    "name": "@pzzld/codex-shepherd",
                    "version": "1.0.0",
                    "dependencies": {"@pzzld/component-runtime": "1.0.0"},
                },
                "packages/harness-pi": {
                    "name": "@pzzld/pi-shepherd",
                    "version": "1.0.0",
                    "dependencies": {"@pzzld/component-runtime": "1.0.0"},
                },
                "node_modules/@pzzld/component-runtime": {"resolved": "packages/component-runtime", "link": True},
                "node_modules/build-tool": {
                    "version": "1.0.0",
                    "dev": True,
                    "dependencies": {"critical-dev": "1.0.0"},
                },
                "node_modules/build-tool/node_modules/critical-dev": {"version": "1.0.0", "dev": True},
                "node_modules/critical-dev": {"version": "2.0.0"},
                "node_modules/dev-root": {"version": "1.0.0", "dev": True},
                "node_modules/optional-vuln": {"version": "1.0.0", "optional": True},
            },
        },
    )
    fixture = root / FIXTURE_DIR
    write_json(fixture, "npm-audit.json", npm_audit_report())
    write_json(fixture, "cargo-advisories.json", cargo_advisories_report())
    write_json(fixture, "cargo-metadata.json", cargo_metadata_report())
    write(
        root,
        ".github/dependabot.yml",
        """version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: monthly
  - package-ecosystem: npm
    directory: /
    schedule:
      interval: monthly
  - package-ecosystem: cargo
    directory: /
    schedule:
      interval: monthly
""",
    )
    write_json(
        root,
        ".claude/settings.json",
        {
            "enabledPlugins": {"shepherd@shepherd": True},
            "extraKnownMarketplaces": {
                "shepherd": {"source": {"source": "github", "repo": "pzzld-org/shepherd"}}
            },
        },
    )
    write(
        root,
        "SECURITY.md",
        """# Security Policy

## Supported versions
Only the latest release receives security fixes.

## Private reporting
Report vulnerabilities through GitHub private vulnerability reporting.

## Response process
We acknowledge, triage, remediate, and coordinate disclosure.

## Coordinated disclosure
Do not publish details before a fix and disclosure date are agreed.

## Scope
Dependency compromise is in scope. Ordinary correctness and compatibility defects use the public tracker.

## Safe harbor
Good-faith research that avoids privacy violations, data destruction, and service disruption is protected.
""",
    )
    write(root, ".github/workflows/release.yml", workflow_text())
    write(root, "README.md", "https://github.com/pzzld-org/shepherd\n")
    write(root, "CHANGELOG.md", "Historical attribution: https://github.com/FL03/shepherd.\n")
    write(root, "CODEOWNERS", "* @FL03 @Scattered-Systems\n")
    write(root, ".github/FUNDING.yml", "github: [ FL03 ]\n")
    write_json(root, "scripts/release-trust-surfaces.json", active_inventory())


class DependencyPolicyTests(unittest.TestCase):
    maxDiff = None

    def run_checker(
        self,
        root: Path,
        *,
        fixture: bool = True,
        env: dict[str, str] | None = None,
        evidence_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["node", str(SCRIPT), "--root", str(root), "--as-of", AS_OF]
        if fixture:
            command.extend(["--fixture-dir", str(root / FIXTURE_DIR)])
        if evidence_dir is not None:
            command.extend(["--evidence-dir", str(evidence_dir)])
        return subprocess.run(command, check=False, capture_output=True, text=True, env=env)

    def mutate_policy(self, root: Path, mutation: Callable[[dict[str, Any]], None]) -> None:
        manifest_path = root / "package.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutation(manifest["shepherdReleaseTrust"])
        write_json(root, "package.json", manifest)

    def test_fixture_reports_bind_exact_findings_and_exact_closures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-baseline-") as temporary:
            root = Path(temporary)
            seed_fixture(root)

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("findings=4", result.stdout)
            self.assertIn("npm-production-findings=1", result.stdout)
            self.assertIn("cargo-production-findings=1", result.stdout)

    def test_omitted_and_fabricated_npm_findings_fail_exact_measurement(self) -> None:
        mutations = {
            "omitted": lambda policy: policy["observedFindings"].pop(2),
            "fabricated": lambda policy: policy["observedFindings"].append(
                {
                    "id": "npm:fabricated:node_modules/fabricated",
                    "ecosystem": "npm",
                    "package": "fabricated",
                    "version": "9.9.9",
                    "node": "node_modules/fabricated",
                    "severity": "critical",
                    "affected": "*",
                    "advisories": ["GHSA-fabricated"],
                    "fix": {"status": "none"},
                }
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"release-trust-npm-{name}-") as temporary:
                root = Path(temporary)
                seed_fixture(root)
                self.mutate_policy(root, mutation)

                result = self.run_checker(root)

                self.assertEqual(result.returncode, 1)
                self.assertIn("observedFindings", result.stderr)
                self.assertIn("exact measured findings", result.stderr)

    def test_omitted_cargo_finding_fails_exact_measurement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-cargo-omitted-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            self.mutate_policy(
                root,
                lambda policy: policy["observedFindings"].pop(0),
            )

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn(CARGO_DEV_FINDING, result.stderr)
            self.assertIn("exact measured findings", result.stderr)

    def test_duplicate_npm_versions_use_exact_audit_node_path_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-npm-duplicates-") as temporary:
            root = Path(temporary)
            seed_fixture(root)

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("npm-production-findings=1", result.stdout)
            manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
            dev_finding = next(
                finding
                for finding in manifest["shepherdReleaseTrust"]["observedFindings"]
                if finding["id"] == NPM_DEV_FINDING
            )
            self.assertEqual(dev_finding["version"], "1.0.0")
            self.assertEqual(dev_finding["node"], "node_modules/build-tool/node_modules/critical-dev")

    def test_npm_follows_optional_dependencies_but_never_dev_dependencies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-npm-edge-kinds-") as temporary:
            root = Path(temporary)
            seed_fixture(root)

            def reverse_claims(policy: dict[str, Any]) -> None:
                by_id = {value["id"]: value for value in policy["classifications"]}
                by_id[NPM_DEV_FINDING]["productionClosure"] = True
                by_id[NPM_OPTIONAL_FINDING]["productionClosure"] = False

            self.mutate_policy(root, reverse_claims)
            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn(NPM_DEV_FINDING, result.stderr)
            self.assertIn(NPM_OPTIONAL_FINDING, result.stderr)
            self.assertIn("derived productionClosure", result.stderr)

    def test_cargo_closure_uses_exact_package_ids_and_excludes_dev_only_edges(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-cargo-closure-") as temporary:
            root = Path(temporary)
            seed_fixture(root)

            def reverse_claims(policy: dict[str, Any]) -> None:
                by_id = {value["id"]: value for value in policy["classifications"]}
                by_id[CARGO_DEV_FINDING]["productionClosure"] = True
                by_id[CARGO_RUNTIME_FINDING]["productionClosure"] = False

            self.mutate_policy(root, reverse_claims)
            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn(CARGO_DEV_FINDING, result.stderr)
            self.assertIn(CARGO_RUNTIME_FINDING, result.stderr)
            self.assertIn("derived productionClosure", result.stderr)

    def test_cargo_finding_name_and_version_must_match_metadata_package_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-cargo-membership-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            report_path = root / FIXTURE_DIR / "cargo-advisories.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["vulnerabilities"][0]["package"]["version"] = "9.9.9"
            write_json(root / FIXTURE_DIR, "cargo-advisories.json", report)

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn("cargo-dev@9.9.9", result.stderr)
            self.assertIn("cargo metadata", result.stderr)

    def test_fixed_version_integrity_is_derived_for_npm_and_cargo(self) -> None:
        for finding_id in (NPM_OPTIONAL_FINDING, CARGO_DEV_FINDING):
            with self.subTest(finding_id=finding_id), tempfile.TemporaryDirectory(prefix="release-trust-fixed-") as temporary:
                root = Path(temporary)
                seed_fixture(root)

                def corrupt_fix(policy: dict[str, Any]) -> None:
                    finding = next(item for item in policy["observedFindings"] if item["id"] == finding_id)
                    finding["fix"] = {"status": "none"}

                self.mutate_policy(root, corrupt_fix)
                result = self.run_checker(root)

                self.assertEqual(result.returncode, 1)
                self.assertIn("exact measured findings", result.stderr)
                self.assertIn(finding_id, result.stderr)

    def test_classification_path_and_shipped_artifacts_must_equal_derived_values(self) -> None:
        mutations = {
            "path": lambda classification: classification.update({"dependencyPath": ["fabricated"]}),
            "artifacts": lambda classification: classification.update({"shippedArtifacts": ["fabricated"]}),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="release-trust-artifact-") as temporary:
                root = Path(temporary)
                seed_fixture(root)

                def mutate(policy: dict[str, Any]) -> None:
                    classification = next(
                        item for item in policy["classifications"] if item["id"] == CARGO_RUNTIME_FINDING
                    )
                    mutation(classification)

                self.mutate_policy(root, mutate)
                result = self.run_checker(root)

                self.assertEqual(result.returncode, 1)
                self.assertIn(CARGO_RUNTIME_FINDING, result.stderr)
                self.assertIn("derived", result.stderr)

    def test_reachable_production_high_requires_complete_unexpired_waiver(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-waiver-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            audit_path = root / FIXTURE_DIR / "npm-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["vulnerabilities"]["optional-vuln"]["severity"] = "high"
            write_json(root / FIXTURE_DIR, "npm-audit.json", audit)

            def make_high_reachable(policy: dict[str, Any]) -> None:
                finding = next(item for item in policy["observedFindings"] if item["id"] == NPM_OPTIONAL_FINDING)
                finding["severity"] = "high"
                classification = next(item for item in policy["classifications"] if item["id"] == NPM_OPTIONAL_FINDING)
                classification["reachable"] = True
                classification["disposition"] = "waived"

            self.mutate_policy(root, make_high_reachable)
            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn("complete unexpired waiver", result.stderr)

    def test_complete_future_waiver_passes_and_expired_waiver_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-waiver-expiry-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            audit_path = root / FIXTURE_DIR / "npm-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["vulnerabilities"]["optional-vuln"]["severity"] = "high"
            write_json(root / FIXTURE_DIR, "npm-audit.json", audit)

            def add_waiver(policy: dict[str, Any]) -> None:
                finding = next(item for item in policy["observedFindings"] if item["id"] == NPM_OPTIONAL_FINDING)
                finding["severity"] = "high"
                classification = next(item for item in policy["classifications"] if item["id"] == NPM_OPTIONAL_FINDING)
                classification.update(
                    {
                        "reachable": True,
                        "disposition": "waived",
                        "waiver": {
                            "owner": "@pzzld-org/security",
                            "reason": "The affected input is disabled while the major-version upgrade is validated.",
                            "expires": "2026-09-01",
                            "tracking": "https://github.com/pzzld-org/shepherd/issues/999",
                        },
                    }
                )

            self.mutate_policy(root, add_waiver)
            passing = self.run_checker(root)
            self.assertEqual(passing.returncode, 0, passing.stderr)

            def expire(policy: dict[str, Any]) -> None:
                classification = next(item for item in policy["classifications"] if item["id"] == NPM_OPTIONAL_FINDING)
                classification["waiver"]["expires"] = AS_OF

            self.mutate_policy(root, expire)
            failing = self.run_checker(root)
            self.assertEqual(failing.returncode, 1)
            self.assertIn("expired on", failing.stderr)

    def test_default_mode_executes_all_live_commands_and_accepts_npm_findings_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-live-commands-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            log = root / "commands.log"
            npm_report = root / FIXTURE_DIR / "npm-audit.json"
            cargo_report = root / FIXTURE_DIR / "cargo-advisories.json"
            metadata_report = root / FIXTURE_DIR / "cargo-metadata.json"
            write(
                root,
                "fake-bin/npm",
                f"#!/bin/sh\nprintf 'npm %s\\n' \"$*\" >> \"$COMMAND_LOG\"\ncat {npm_report!s}\nexit 1\n",
            )
            write(
                root,
                "fake-bin/cargo",
                f"""#!/bin/sh
printf 'cargo %s\\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  'deny --workspace --all-features check') echo 'deny ok' >&2; exit 0 ;;
  'deny --format json --workspace --all-features check advisories --audit-compatible-output') cat {cargo_report!s}; exit 1 ;;
  'metadata --format-version 1 --locked --all-features') cat {metadata_report!s}; exit 0 ;;
  *) echo unexpected cargo command >&2; exit 9 ;;
esac
""",
            )
            os.chmod(fake_bin / "npm", 0o755)
            os.chmod(fake_bin / "cargo", 0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            env["COMMAND_LOG"] = str(log)
            evidence = root / "evidence"

            result = self.run_checker(root, fixture=False, env=env, evidence_dir=evidence)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                [
                    "npm audit --json",
                    "cargo deny --workspace --all-features check",
                    "cargo deny --format json --workspace --all-features check advisories --audit-compatible-output",
                    "cargo metadata --format-version 1 --locked --all-features",
                ],
            )
            self.assertTrue((evidence / "npm-audit.json").is_file())
            self.assertTrue((evidence / "cargo-advisories.json").is_file())
            self.assertTrue((evidence / "cargo-deny-check.txt").is_file())
            summary = json.loads((evidence / "cargo-metadata-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["packageCount"], 9)
            self.assertIn("sha256", summary)
            self.assertFalse((evidence / "cargo-metadata.json").exists())

    def test_npm_tool_failure_is_exit_two_not_a_finding_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-npm-failure-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            write(root, "fake-bin/npm", "#!/bin/sh\nprintf '%s\\n' '{\"error\":{\"code\":\"ENETDOWN\"}}'\nexit 1\n")
            os.chmod(fake_bin / "npm", 0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

            result = self.run_checker(root, fixture=False, env=env)

            self.assertEqual(result.returncode, 2)
            self.assertIn("npm audit tool failure", result.stderr)
            self.assertNotIn("exact measured findings", result.stderr)

    def test_heredoc_other_job_and_if_false_workflow_commands_fail(self) -> None:
        mutations = {
            "heredoc": lambda text: text.replace(
                "        run: node scripts/check-deps.mjs\n",
                "        run: |\n"
                "          cat <<'COMMANDS' >/dev/null\n"
                "          node scripts/check-deps.mjs\n"
                "          COMMANDS\n"
                "          node scripts/check-deps.mjs --fixture-dir .release-trust-fixtures\n",
            ),
            "other-job": lambda text: text.replace(
                "      - name: Verify live dependency trust\n"
                "        if: steps.detect.outputs.proceed == 'true'\n"
                "        run: node scripts/check-deps.mjs\n",
                "",
            ).replace("      - run: echo done\n", "      - run: node scripts/check-deps.mjs\n"),
            "if-false": lambda text: text.replace(
                "      - name: Verify live dependency trust\n"
                "        if: steps.detect.outputs.proceed == 'true'\n",
                "      - name: Verify live dependency trust\n                if: false\n",
            ),
            "missing-cargo-deny": lambda text: text.replace(
                "      - name: Setup cargo-deny\n"
                "        if: steps.detect.outputs.proceed == 'true'\n"
                "        uses: taiki-e/install-action@v2\n"
                "        with:\n"
                "          tool: cargo-deny\n",
                "",
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"release-trust-workflow-{name}-") as temporary:
                root = Path(temporary)
                seed_fixture(root)
                workflow = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
                write(root, ".github/workflows/release.yml", mutation(workflow))

                result = self.run_checker(root)

                self.assertEqual(result.returncode, 1)
                self.assertIn("release-metadata", result.stderr)
                self.assertIn("live dependency trust", result.stderr.lower())

    def test_duplicate_dev_copy_of_shipped_name_is_not_a_production_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-npm-root-identity-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            lock_path = root / "package-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            node = "node_modules/build-tool/node_modules/@pzzld/component-runtime"
            lock["packages"]["node_modules/build-tool"]["dependencies"]["@pzzld/component-runtime"] = "0.0.1"
            lock["packages"][node] = {"name": "@pzzld/component-runtime", "version": "0.0.1", "dev": True}
            write_json(root, "package-lock.json", lock)
            audit_path = root / FIXTURE_DIR / "npm-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["vulnerabilities"]["@pzzld/component-runtime"] = {
                "name": "@pzzld/component-runtime", "severity": "high", "isDirect": False,
                "via": ["build-tool"], "effects": [], "range": "<1.0.0", "nodes": [node], "fixAvailable": False,
            }
            write_json(root / FIXTURE_DIR, "npm-audit.json", audit)
            manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
            finding_id = f"npm:@pzzld/component-runtime:{node}"
            manifest["shepherdReleaseTrust"]["observedFindings"].append({
                "id": finding_id, "ecosystem": "npm", "package": "@pzzld/component-runtime",
                "version": "0.0.1", "node": node, "severity": "high", "affected": "<1.0.0",
                "advisories": ["package:build-tool"], "fix": {"status": "none"},
            })
            manifest["shepherdReleaseTrust"]["classifications"].append({
                "id": finding_id, "productionClosure": False, "reachable": False,
                "dependencyPath": [], "shippedArtifacts": [],
                "rationale": "This duplicate name is nested only below root development tooling.",
                "disposition": "not-shipped",
            })
            write_json(root, "package.json", manifest)

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_duplicate_classification_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-duplicate-classification-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            self.mutate_policy(root, lambda policy: policy["classifications"].append(copy.deepcopy(policy["classifications"][0])))

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn("duplicate classification", result.stderr)

    def test_current_fl03_urls_are_case_and_scheme_insensitive_but_history_is_preserved(self) -> None:
        bad_urls = (
            "http://github.com/fl03/shepherd/releases",
            "HTTP://RAW.GITHUBUSERCONTENT.COM/fL03/Shepherd/main/install.sh",
        )
        for url in bad_urls:
            with self.subTest(url=url), tempfile.TemporaryDirectory(prefix="release-trust-url-") as temporary:
                root = Path(temporary)
                seed_fixture(root)
                write(root, "README.md", f"{url}\n")

                result = self.run_checker(root)

                self.assertEqual(result.returncode, 1)
                self.assertIn("README.md", result.stderr)
                self.assertIn("current FL03 URL", result.stderr)
                self.assertNotIn("CHANGELOG.md:", result.stderr)

    def test_active_surface_inventory_preserves_historical_runs_and_contributor_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-inventory-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            baseline = self.run_checker(root)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)

            write(root, "CODEOWNERS", "* @replacement\n")
            changed = self.run_checker(root)
            self.assertEqual(changed.returncode, 1)
            self.assertIn("preserved contributor identity", changed.stderr)

            write(root, "CODEOWNERS", "* @FL03 @Scattered-Systems\n")
            write(root, ".shepherd/runs/v1/history.md", "http://github.com/fl03/shepherd\n")
            historical = self.run_checker(root)
            self.assertEqual(historical.returncode, 0, historical.stderr)

    def test_dependabot_security_and_shared_settings_contracts_remain_enforced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="release-trust-posture-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            dependabot = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
            write(root, ".github/dependabot.yml", dependabot.replace("package-ecosystem: cargo", "package-ecosystem: pip"))
            settings = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
            settings["permissions"] = {"defaultMode": "bypassPermissions", "allow": ["Bash(*)"]}
            write_json(root, ".claude/settings.json", settings)
            security = (root / "SECURITY.md").read_text(encoding="utf-8")
            write(root, "SECURITY.md", security.replace("## Safe harbor", "## Research"))

            result = self.run_checker(root)

            self.assertEqual(result.returncode, 1)
            self.assertIn("dependabot", result.stderr.lower())
            self.assertIn("shared project settings", result.stderr)
            self.assertIn("Safe harbor", result.stderr)

    def test_repository_active_surface_inventory_covers_every_extended_scope_path(self) -> None:
        inventory = json.loads((REPO / "scripts/release-trust-surfaces.json").read_text(encoding="utf-8"))
        paths = {item["path"] for item in inventory["activeSurfaces"]}
        self.assertTrue(
            {
                ".claude-plugin/marketplace.json",
                ".claude-plugin/plugin.json",
                ".claude/settings.json",
                ".github/workflows/release.yml",
                "Cargo.toml",
                "QUICKSTART.md",
                "README.md",
                "docs/integration.md",
                "package.json",
                "packages/harness-claude/README.md",
                "plugins/shepherd/.claude-plugin/plugin.json",
                "plugins/shepherd/.codex-plugin/plugin.json",
                "scripts/install-shepherd.ps1",
                "scripts/install-shepherd.sh",
            }.issubset(paths)
        )
        self.assertIn(".shepherd/runs/", inventory["historicalPrefixes"])
        identity = {item["path"]: item["requiredText"] for item in inventory["preservedContributorIdentity"]}
        self.assertEqual(identity["CODEOWNERS"], "@FL03")
        self.assertEqual(identity[".github/FUNDING.yml"], "FL03")


if __name__ == "__main__":
    unittest.main()
