#!/usr/bin/env python3
"""Deterministic integration tests for the release version authority tool."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


CURRENT = "6.4.5"
NEXT = "6.4.6"
SCRIPT = Path(__file__).resolve().parents[1] / "version-bump.py"

CRATES = (
    "cli",
    "compiler",
    "component",
    "core",
    "registry",
    "render",
    "sdk",
)


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(root: Path, relative: str, value: object) -> None:
    write(root, relative, json.dumps(value, indent=2) + "\n")


def repeated_version(count: int) -> str:
    return "\n".join(f"authority-{index}={CURRENT}" for index in range(count)) + "\n"


def seed_fixture(root: Path) -> None:
    internal = (
        "shepherd = { default-features = false, path = \"crates/sdk\", version = \"6.4.5\" }\n"
        "shepherd-core = { default-features = false, path = \"crates/core\", "
        "version = \"6.4.5\" }\n"
        "shepherd-compiler = { default-features = false, path = \"crates/compiler\", "
        "version = \"6.4.5\" }\n"
        "shepherd-registry = { default-features = false, path = \"crates/registry\", "
        "version = \"6.4.5\" }\n"
        "shepherd-render = { default-features = false, path = \"crates/render\", "
        "version = \"6.4.5\" }\n"
        "shepherd-cli = { default-features = false, path = \"crates/cli\", version = \"6.4.5\" }\n"
    )
    write(
        root,
        "Cargo.toml",
        "[workspace]\n"
        'members = ["crates/*"]\n'
        "\n[workspace.package]\n"
        'version = "6.4.5"\n'
        "\n[workspace.dependencies]\n"
        f"{internal}",
    )
    lock_packages = "\n".join(
        f'[[package]]\nname = "{name}"\nversion = "{CURRENT}"\n'
        for name in (
            "shepherd",
            "shepherd-cli",
            "shepherd-compiler",
            "shepherd-component",
            "shepherd-core",
            "shepherd-registry",
            "shepherd-render",
        )
    )
    write(root, "Cargo.lock", f"version = 4\n\n{lock_packages}")
    for crate in CRATES:
        package_name = "shepherd" if crate == "sdk" else f"shepherd-{crate}"
        write(
            root,
            f"crates/{crate}/Cargo.toml",
            f'[package]\nname = "{package_name}"\nversion.workspace = true\n',
        )

    write_json(
        root,
        "package.json",
        {
            "name": "shepherd-workspace",
            "version": CURRENT,
            "private": True,
            "workspaces": ["packages/*"],
        },
    )
    package_manifests = {
        "component-runtime": {
            "name": "@fl03/component-runtime",
            "version": CURRENT,
        },
        "harness-claude": {
            "name": "@fl03/harness-claude",
            "version": CURRENT,
            "dependencies": {"@fl03/component-runtime": CURRENT},
        },
        "harness-codex": {
            "name": "@fl03/harness-codex",
            "version": CURRENT,
            "dependencies": {"@fl03/component-runtime": CURRENT},
        },
        "harness-pi": {
            "name": "@fl03/harness-pi",
            "version": CURRENT,
            "dependencies": {"@fl03/component-runtime": CURRENT},
        },
    }
    for directory, manifest in package_manifests.items():
        write_json(root, f"packages/{directory}/package.json", manifest)

    write_json(
        root,
        "package-lock.json",
        {
            "name": "shepherd-workspace",
            "version": CURRENT,
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "shepherd-workspace", "version": CURRENT},
                "packages/component-runtime": {
                    "name": "@fl03/component-runtime",
                    "version": CURRENT,
                },
                "packages/harness-claude": {
                    "name": "@fl03/harness-claude",
                    "version": CURRENT,
                    "dependencies": {"@fl03/component-runtime": CURRENT},
                },
                "packages/harness-codex": {
                    "name": "@fl03/harness-codex",
                    "version": CURRENT,
                    "dependencies": {"@fl03/component-runtime": CURRENT},
                },
                "packages/harness-pi": {
                    "name": "@fl03/harness-pi",
                    "version": CURRENT,
                    "dependencies": {"@fl03/component-runtime": CURRENT},
                },
            },
        },
    )
    write_json(
        root,
        ".claude-plugin/plugin.json",
        {
            "name": "shepherd",
            "version": CURRENT,
            "description": f"one fl03:shepherd@{CURRENT} component",
        },
    )
    write_json(
        root,
        "packages/harness-pi/shepherd.pi.json",
        {"schema": "shepherd.pi-adapter/1", "contract": f"fl03:shepherd@{CURRENT}"},
    )

    write(
        root,
        "README.md",
        f"""# Shepherd v{CURRENT}

The v{CURRENT} component is published as `fl03:shepherd@{CURRENT}`.
https://raw.githubusercontent.com/FL03/shepherd/v{CURRENT}/scripts/install-shepherd.sh
SHEPHERD_VERSION={CURRENT} bash /tmp/install-shepherd.sh
https://raw.githubusercontent.com/FL03/shepherd/v{CURRENT}/scripts/install-shepherd.ps1
$env:SHEPHERD_VERSION = '{CURRENT}'
`shepherd-claude-plugin-{CURRENT}.zip` is the release archive.
https://github.com/FL03/shepherd/releases/download/v{CURRENT}/shepherd-claude-plugin-{CURRENT}.zip

For an existing pre-v{CURRENT} namespace, preserve the migration threshold.
The command families are owned by the Rust CLI in v{CURRENT}:
""",
    )

    exact_text = {
        "crates/component/src/lib.rs": (
            f'pub const COMPONENT_CONTRACT_VERSION: &str = "fl03:shepherd@{CURRENT}";\n'
        ),
        "crates/core/src/guard/json.rs": (
            f"//! Byte-exact verdict serialization for the v{CURRENT} guard wire.\n"
        ),
        "crates/core/src/guard/tokenizer.rs": (
            f"/// This intentionally preserves the v{CURRENT} token-level compatibility limits:\n"
        ),
        "crates/component/tests/component.rs": (
            f'assert!(wit.contains("package fl03:shepherd@{CURRENT};"));\n'
        ),
        "crates/component/wit/shepherd.wit": f"package fl03:shepherd@{CURRENT};\n",
        "packages/component-runtime/src/index.mjs": (
            f'export const COMPONENT_CONTRACT_VERSION = "fl03:shepherd@{CURRENT}";\n'
        ),
        "packages/harness-pi/test/subagent-provider.test.mjs": (
            f'assert.equal(contract.contract, "fl03:shepherd@{CURRENT}");\n'
        ),
        "packages/harness-pi/src/extension.mjs": (
            f"// generated by the fl03:shepherd@{CURRENT} component\n"
        ),
        "scripts/check-features.sh": f"grep -Fq 'package fl03:shepherd@{CURRENT};' out\n",
        "scripts/gate.sh": f"grep -Fq 'export fl03:shepherd/engine@{CURRENT};' out\n",
        ".github/workflows/rust-wasm.yml": (
            f"run: grep -Fq 'export fl03:shepherd/engine@{CURRENT};' out\n"
        ),
    }
    for relative, content in exact_text.items():
        write(root, relative, content)

    whole_file_counts = {
        "docs/configuration.md": 1,
        "docs/customization.md": 1,
        "docs/integration.md": 6,
        "content/RECONCILIATION.md": 1,
        "crates/compiler/README.md": 1,
        "crates/component/README.md": 1,
        "crates/sdk/README.md": 1,
        "packages/component-runtime/README.md": 1,
        "packages/harness-claude/README.md": 5,
        "packages/harness-codex/README.md": 1,
        "packages/harness-pi/README.md": 1,
        "scripts/test-packed-plugin.sh": 13,
        "scripts/tests/test-release-distribution-license.sh": 8,
        "packages/scripts/check-package-boundary.mjs": 3,
        "scripts/verify-release-assets.sh": 1,
    }
    for relative, count in whole_file_counts.items():
        write(root, relative, repeated_version(count))
    write(
        root,
        "scripts/tests/test-release-installers.sh",
        repeated_version(24) + "\n".join(f"negative-{index}={NEXT}" for index in range(3)) + "\n",
    )
    write(
        root,
        "scripts/tests/test-release-assets.sh",
        repeated_version(16) + "\n".join(f"negative-{index}={NEXT}" for index in range(2)) + "\n",
    )

    write(
        root,
        "scripts/check-workspace.sh",
        f"""grep -Fq 'package fl03:shepherd@{CURRENT};' out
fixture = {{"package": {{"name": "shepherd-core", "version": "{CURRENT}"}}}}
""",
    )
    write(
        root,
        "conformance/cases/history/case.json",
        json.dumps({"authority": f"native-v{CURRENT}"}) + "\n",
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class VersionBumpTests(unittest.TestCase):
    def run_tool(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), *arguments, "--root", str(root)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_bump_updates_every_authority_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shepherd-version-bump-") as temporary:
            root = Path(temporary)
            seed_fixture(root)

            result = self.run_tool(
                root,
                "bump",
                "--current",
                CURRENT,
                "--next",
                NEXT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            checked = self.run_tool(root, "check", "--version", NEXT)
            self.assertEqual(checked.returncode, 0, checked.stderr)

            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertIn(f"# Shepherd v{NEXT}", readme)
            self.assertIn(f"shepherd-claude-plugin-{NEXT}.zip", readme)
            self.assertIn(f"releases/download/v{NEXT}/", readme)
            self.assertIn(f"pre-v{CURRENT} namespace", readme)
            self.assertIn(f"owned by the Rust CLI in v{CURRENT}", readme)
            history = (root / "conformance/cases/history/case.json").read_text()
            self.assertNotIn(f"native-v{NEXT}", history)

            cargo_lock = (root / "Cargo.lock").read_text(encoding="utf-8")
            self.assertEqual(cargo_lock.count(f'version = "{NEXT}"'), 7)
            package_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
            self.assertEqual(package_lock["packages"]["packages/harness-pi"]["version"], NEXT)
            self.assertEqual(
                package_lock["packages"]["packages/harness-pi"]["dependencies"][
                    "@fl03/component-runtime"
                ],
                NEXT,
            )

    def test_stale_surface_refuses_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shepherd-version-stale-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            wit = root / "crates/component/wit/shepherd.wit"
            wit.write_text("package fl03:shepherd@6.4.4;\n", encoding="utf-8")
            before = snapshot(root)

            result = self.run_tool(
                root,
                "bump",
                "--current",
                CURRENT,
                "--next",
                NEXT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crates/component/wit/shepherd.wit", result.stderr)
            self.assertEqual(snapshot(root), before)

    def test_missing_surface_refuses_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shepherd-version-missing-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            missing = root / "packages/component-runtime/src/index.mjs"
            missing.unlink()
            before = snapshot(root)

            result = self.run_tool(
                root,
                "bump",
                "--current",
                CURRENT,
                "--next",
                NEXT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("packages/component-runtime/src/index.mjs", result.stderr)
            self.assertEqual(snapshot(root), before)

    def test_rejects_noncanonical_successor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shepherd-version-next-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            before = snapshot(root)

            result = self.run_tool(
                root,
                "bump",
                "--current",
                CURRENT,
                "--next",
                "6.4.7",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical successor", result.stderr)
            self.assertEqual(snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
