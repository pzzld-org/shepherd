#!/usr/bin/env python3
"""Deterministic integration tests for the release version authority tool."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


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


def _load_version_bump_module() -> ModuleType:
    """Import version-bump.py by path so fixtures can query its rule table
    directly, instead of re-declaring authority occurrence counts by hand.

    A hand-copied count drifts silently the next time the tool's rule table
    changes; asking the tool itself keeps this test's fixtures locked to
    whatever the tool actually enforces.
    """
    spec = importlib.util.spec_from_file_location("version_bump_tool", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the version-bump module from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    # Slotted dataclasses (TextRule, Snapshot, SemVer) look themselves up in
    # sys.modules during class creation, so the module must be registered
    # before exec_module runs it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VERSION_BUMP = _load_version_bump_module()
_CURRENT_SEMVER = VERSION_BUMP.SemVer.parse(CURRENT, label="current")
_NEXT_SEMVER = VERSION_BUMP.SemVer.parse(NEXT, label="next")
_VERSION_RULES = VERSION_BUMP.version_rules(_CURRENT_SEMVER, _NEXT_SEMVER)


def _rule_count(path: str, old: str, new: str, *, label_contains: str) -> int:
    """Return the expected occurrence count for the one rule in the tool's
    rule table that pins `path` from `old` to `new` under a label containing
    `label_contains`.

    Raises if the rule table no longer carries exactly one such rule, so a
    rule-table change that removes, splits, or duplicates an authority is
    caught here rather than producing a fixture that silently stops
    exercising what it claims to.
    """
    matches = [
        rule
        for rule in _VERSION_RULES
        if rule.path == path
        and rule.old == old
        and rule.new == new
        and label_contains in rule.label
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"{path}: expected exactly one version-bump rule matching "
            f"old={old!r} new={new!r} label*={label_contains!r}, found {len(matches)}"
        )
    return matches[0].expected_count


def whole_authority_count(path: str) -> int:
    """The occurrence count version-bump.py pins for the plain whole-file
    'release version' authority at `path`."""
    return _rule_count(path, CURRENT, NEXT, label_contains="release version")


def negative_control_count(path: str) -> int:
    """The occurrence count version-bump.py pins for the wrong-version
    negative control at `path`: text that already reads NEXT and must be
    left untouched by a CURRENT -> NEXT bump."""
    successor = str(_NEXT_SEMVER.successor())
    return _rule_count(path, NEXT, successor, label_contains="negative control")


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
        "shepherd = { default-features = false, package = \"shepherd-sdk\", path = \"crates/sdk\", version = \"6.4.5\" }\n"
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
            "shepherd-sdk",
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
        package_name = "shepherd-sdk" if crate == "sdk" else f"shepherd-{crate}"
        write(
            root,
            f"crates/{crate}/Cargo.toml",
            f'[package]\nname = "{package_name}"\nversion.workspace = true\n',
        )

    write_json(
        root,
        "package.json",
        {
            "name": "@pzzld/shepherd-workspace",
            "version": CURRENT,
            "private": True,
            "workspaces": ["packages/*"],
        },
    )
    package_manifests = {
        "component-runtime": {
            "name": "@pzzld/component-runtime",
            "version": CURRENT,
        },
        "harness-claude": {
            "name": "@pzzld/claude-shepherd",
            "version": CURRENT,
            "dependencies": {"@pzzld/component-runtime": CURRENT},
        },
        "harness-codex": {
            "name": "@pzzld/codex-shepherd",
            "version": CURRENT,
            "dependencies": {"@pzzld/component-runtime": CURRENT},
        },
        "harness-pi": {
            "name": "@pzzld/pi-shepherd",
            "version": CURRENT,
            "dependencies": {"@pzzld/component-runtime": CURRENT},
        },
    }
    for directory, manifest in package_manifests.items():
        write_json(root, f"packages/{directory}/package.json", manifest)

    write_json(
        root,
        "package-lock.json",
        {
            "name": "@pzzld/shepherd-workspace",
            "version": CURRENT,
            "lockfileVersion": 3,
            "packages": {
                "": {"name": "@pzzld/shepherd-workspace", "version": CURRENT},
                "packages/component-runtime": {
                    "name": "@pzzld/component-runtime",
                    "version": CURRENT,
                },
                "packages/harness-claude": {
                    "name": "@pzzld/claude-shepherd",
                    "version": CURRENT,
                    "dependencies": {"@pzzld/component-runtime": CURRENT},
                },
                "packages/harness-codex": {
                    "name": "@pzzld/codex-shepherd",
                    "version": CURRENT,
                    "dependencies": {"@pzzld/component-runtime": CURRENT},
                },
                "packages/harness-pi": {
                    "name": "@pzzld/pi-shepherd",
                    "version": CURRENT,
                    "dependencies": {"@pzzld/component-runtime": CURRENT},
                },
            },
        },
    )
    write(root, "bun.lock", repeated_version(whole_authority_count("bun.lock")))

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
        "plugins/shepherd/.claude-plugin/plugin.json",
        {
            "name": "shepherd",
            "version": CURRENT,
            "description": f"one fl03:shepherd@{CURRENT} component",
        },
    )
    write_json(
        root,
        "plugins/shepherd/.codex-plugin/plugin.json",
        {
            "name": "shepherd",
            "version": CURRENT,
            "skills": "./codex/skills/",
            "hooks": "./codex/hooks/hooks.json",
        },
    )
    write_json(
        root,
        ".claude-plugin/marketplace.json",
        {
            "name": "shepherd",
            "version": CURRENT,
            "description": f"one fl03:shepherd@{CURRENT} source plugin",
            "plugins": [
                {
                    "name": "shepherd",
                    "version": CURRENT,
                    "source": "./plugins/shepherd",
                }
            ],
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
Claude installs the thin marketplace carrier normally.
codex plugin marketplace add FL03/shepherd --ref v{CURRENT}

For an existing pre-v{CURRENT} namespace, preserve the migration threshold.
The command families are owned by the Rust CLI in v{CURRENT}:
""",
    )

    # QUICKSTART.md carries the same install surfaces as the README and so
    # drifts the same way; the bump owns it, therefore the fixture must too.
    write(
        root,
        "QUICKSTART.md",
        f"""# Shepherd Quickstart

https://raw.githubusercontent.com/FL03/shepherd/v{CURRENT}/scripts/install-shepherd.sh
SHEPHERD_VERSION={CURRENT} bash /tmp/install-shepherd.sh
codex plugin marketplace add FL03/shepherd --ref v{CURRENT}
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
        # A workflow file that DERIVES the version, mirroring the real
        # rust-wasm.yml. It must survive the bump untouched: a workflow that is
        # a version authority cannot be pushed by gitflow, because GITHUB_TOKEN
        # has no `workflows` scope to grant.
        ".github/workflows/rust-wasm.yml": (
            "run: grep -Fq \"export fl03:shepherd/engine@${component_version};\" out\n"
        ),
    }
    for relative, content in exact_text.items():
        write(root, relative, content)

    whole_file_paths = (
        "docs/configuration.md",
        "docs/customization.md",
        "docs/integration.md",
        "content/RECONCILIATION.md",
        "crates/compiler/README.md",
        "crates/component/README.md",
        "crates/sdk/README.md",
        "packages/component-runtime/README.md",
        "packages/harness-claude/README.md",
        "packages/harness-codex/README.md",
        "packages/harness-pi/README.md",
        "scripts/test-packed-plugin.sh",
        "scripts/tests/test-release-distribution-license.sh",
        "packages/scripts/check-package-boundary.mjs",
        "scripts/verify-release-assets.sh",
        "scripts/check-cargo-distribution.py",
        "scripts/tests/test-cargo-distribution.py",
    )
    for relative in whole_file_paths:
        write(root, relative, repeated_version(whole_authority_count(relative)))
    write(
        root,
        "scripts/tests/test-release-installers.sh",
        repeated_version(whole_authority_count("scripts/tests/test-release-installers.sh"))
        + "\n".join(
            f"negative-{index}={NEXT}"
            for index in range(negative_control_count("scripts/tests/test-release-installers.sh"))
        )
        + "\n",
    )
    write(
        root,
        "scripts/tests/test-release-assets.sh",
        repeated_version(whole_authority_count("scripts/tests/test-release-assets.sh"))
        + "\n".join(
            f"negative-{index}={NEXT}"
            for index in range(negative_control_count("scripts/tests/test-release-assets.sh"))
        )
        + "\n",
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

    def test_packed_plugin_release_archive_count_is_eleven(self) -> None:
        self.assertEqual(whole_authority_count("scripts/test-packed-plugin.sh"), 11)

    def test_pi_runtime_state_is_excluded_without_disabling_source_scan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shepherd-version-pi-state-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            write(root, ".pi/tasks/runtime.json", f'{{"version":"{CURRENT}"}}\n')
            write(root, "notes/current.mjs", f'export const version = "{CURRENT}";\n')

            result = self.run_tool(root, "check", "--version", CURRENT)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                f"notes/current.mjs: unclassified {CURRENT} version surface",
                result.stderr,
            )
            self.assertNotIn(".pi/tasks/runtime.json", result.stderr)

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

            # The bump must leave every workflow file byte-identical. A
            # workflow that is a version authority gets rewritten on release,
            # and gitflow then cannot push the bumped branch -- GITHUB_TOKEN
            # has no `workflows` scope to grant, so GitHub refuses the push.
            workflow = (root / ".github/workflows/rust-wasm.yml").read_text(encoding="utf-8")
            self.assertEqual(
                workflow,
                'run: grep -Fq "export fl03:shepherd/engine@${component_version};" out\n',
            )
            self.assertNotIn(NEXT, workflow)

            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertIn(f"# Shepherd v{NEXT}", readme)
            self.assertIn("thin marketplace carrier", readme)
            # The migration threshold is historical: it names when layout-v5
            # was introduced and does NOT move with the version.
            self.assertIn(f"pre-v{CURRENT} namespace", readme)
            # The command surface is NOT historical -- it describes what the
            # CURRENT binary owns, so the bump must rewrite it. Asserting the
            # opposite is what kept this line pinned at v6.4.5 across two
            # releases while the residual scan stayed quiet about it.
            self.assertIn(f"owned by the Rust CLI in v{NEXT}", readme)
            self.assertNotIn(f"owned by the Rust CLI in v{CURRENT}", readme)
            # QUICKSTART's install surfaces move with the version too.
            quickstart = (root / "QUICKSTART.md").read_text(encoding="utf-8")
            self.assertIn(f"FL03/shepherd/v{NEXT}/scripts/install-shepherd.sh", quickstart)
            self.assertIn(f"SHEPHERD_VERSION={NEXT} bash", quickstart)
            self.assertNotIn(CURRENT, quickstart)
            history = (root / "conformance/cases/history/case.json").read_text()
            self.assertNotIn(f"native-v{NEXT}", history)

            cargo_lock = (root / "Cargo.lock").read_text(encoding="utf-8")
            self.assertEqual(cargo_lock.count(f'version = "{NEXT}"'), 7)
            package_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
            self.assertEqual(package_lock["packages"]["packages/harness-pi"]["version"], NEXT)
            self.assertEqual(
                package_lock["packages"]["packages/harness-pi"]["dependencies"][
                    "@pzzld/component-runtime"
                ],
                NEXT,
            )
            self.assertEqual(
                (root / ".claude-plugin/plugin.json").read_bytes(),
                (root / "plugins/shepherd/.claude-plugin/plugin.json").read_bytes(),
            )
            codex = json.loads(
                (root / "plugins/shepherd/.codex-plugin/plugin.json").read_text()
            )
            self.assertEqual(codex["version"], NEXT)

    def test_carrier_manifest_drift_refuses_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shepherd-version-carrier-drift-") as temporary:
            root = Path(temporary)
            seed_fixture(root)
            carrier = root / "plugins/shepherd/.claude-plugin/plugin.json"
            carrier.write_text('{"name":"shepherd","version":"6.4.5"}\n', encoding="utf-8")
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
            self.assertIn("plugins/shepherd/.claude-plugin/plugin.json", result.stderr)
            self.assertIn("byte-identical", result.stderr)
            self.assertEqual(snapshot(root), before)

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
