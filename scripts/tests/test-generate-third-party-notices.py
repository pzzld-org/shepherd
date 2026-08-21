#!/usr/bin/env python3
"""Focused tests for legal generation and repository source-authority hygiene."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "generate_third_party_notices", ROOT / "scripts" / "generate-third-party-notices.py"
)
assert SPEC and SPEC.loader
NOTICES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOTICES)


class LicenseTextTests(unittest.TestCase):
    def test_missing_upstream_mit_text_fails_closed(self) -> None:
        """A license identifier is metadata, never authority to invent text."""
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "no bundled license"):
                NOTICES.license_texts(Path(temp), "MIT")

    def test_locked_node_package_without_upstream_text_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package-lock.json").write_text(json.dumps({
                "packages": {
                    "packages/adapter": {"name": "@pzzld/adapter", "dependencies": {"shipped": "1.0.0"}},
                    "node_modules/shipped": {"name": "shipped", "version": "1.0.0"},
                }
            }))
            original_root = NOTICES.ROOT
            try:
                NOTICES.ROOT = root
                with self.assertRaisesRegex(RuntimeError, "dependency source is unavailable"):
                    NOTICES.node_rows(["@pzzld/adapter"], root)
            finally:
                NOTICES.ROOT = original_root


class ClosureTests(unittest.TestCase):
    def test_cargo_closure_excludes_component_only_crate_from_native(self) -> None:
        metadata = {
            "packages": [
                {"id": "cli", "name": "shepherd-cli", "source": None},
                {"id": "core", "name": "shepherd-core", "source": None},
                {"id": "native", "name": "native-dependency", "source": "registry+https://example.test"},
                {"id": "component", "name": "component-only", "source": "registry+https://example.test"},
            ],
            "resolve": {
                "nodes": [
                    {"id": "cli", "dependencies": ["core", "native"]},
                    {"id": "core", "dependencies": []},
                    {"id": "native", "dependencies": []},
                    {"id": "component", "dependencies": []},
                ]
            },
        }
        selected = NOTICES.cargo_closure(metadata, "shepherd-cli")
        self.assertEqual([package["id"] for package in selected], ["cli", "core", "native"])

    def test_node_closure_excludes_build_tools_and_platform_optional_packages(self) -> None:
        lock = {
            "packages": {
                "": {"devDependencies": {"build-tool": "1.0.0"}},
                "packages/component-runtime": {
                    "name": "@pzzld/component-runtime",
                    "dependencies": {"runtime-dependency": "1.0.0"},
                },
                "node_modules/runtime-dependency": {
                    "name": "runtime-dependency",
                    "version": "1.0.0",
                    "dependencies": {"platform-binary": "1.0.0"},
                },
                "node_modules/platform-binary": {
                    "name": "platform-binary",
                    "version": "1.0.0",
                    "optional": True,
                    "os": ["darwin"],
                    "dependencies": {"platform-transitive": "1.0.0"},
                },
                "node_modules/platform-transitive": {"name": "platform-transitive", "version": "1.0.0"},
                "node_modules/build-tool": {"name": "build-tool", "version": "1.0.0"},
            }
        }
        selected = NOTICES.node_closure(lock, ["@pzzld/component-runtime"])
        self.assertEqual(selected, ["node_modules/runtime-dependency"])


class BuildTests(unittest.TestCase):
    def test_full_scope_renders_each_dependency_identity_once(self) -> None:
        shared = {
            "kind": "Rust crate", "name": "shared", "version": "1.0.0",
            "origin": "registry+https://example.test", "integrity": "a", "license": "MIT",
            "texts": [("LICENSE", b"shared license\n")],
        }
        component_only = {
            "kind": "Rust crate", "name": "component-only", "version": "1.0.0",
            "origin": "registry+https://example.test", "integrity": "b", "license": "MIT",
            "texts": [("LICENSE", b"component license\n")],
        }

        def fake_cargo_rows(_target: str, package_name: str) -> list[dict[str, object]]:
            return [shared] if package_name == "shepherd-cli" else [shared, component_only]

        with patch.object(NOTICES, "cargo_rows", fake_cargo_rows), patch.object(NOTICES, "node_rows", return_value=[]):
            notices, _ = NOTICES.build("full", "wasm32-wasip2")
        self.assertEqual(notices.count("| Rust crate | `shared` |"), 1)
        self.assertEqual(notices.count("| Rust crate | `component-only` |"), 1)


class SourceAuthorityTests(unittest.TestCase):
    def test_default_legal_output_is_build_owned(self) -> None:
        output_root = ROOT / "target" / "legal" / "full"
        self.assertEqual(
            NOTICES.DEFAULT_OUTPUT,
            output_root / "THIRD_PARTY_NOTICES.md",
        )
        self.assertEqual(
            NOTICES.DEFAULT_LICENSES_DIR,
            output_root / "THIRD_PARTY_LICENSES",
        )

    def test_repository_root_has_no_generated_or_provider_runtime_authority(self) -> None:
        self.assertEqual(NOTICES.repository_source_authority_violations(ROOT), [])

    def test_guard_rejects_every_retired_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "THIRD_PARTY_NOTICES.md").write_text("generated\n", encoding="utf-8")
            (root / "THIRD_PARTY_LICENSES").mkdir()
            (root / "workflows").mkdir()

            violations = NOTICES.repository_source_authority_violations(root)

        self.assertEqual(len(violations), 3)
        self.assertTrue(any("THIRD_PARTY_NOTICES.md" in item for item in violations))
        self.assertTrue(any("THIRD_PARTY_LICENSES" in item for item in violations))
        self.assertTrue(any("workflows" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
