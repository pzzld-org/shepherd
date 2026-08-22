#!/usr/bin/env python3
"""Regression tests for generated pi-subagents role definitions."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate-pi-agents.py"
ROLES = ("auditor", "coder", "conductor", "critic", "discovery", "engineer", "planter", "shepherd", "worker")
NON_DISPATCHABLE = {"planter", "shepherd"}


def seed(root: Path) -> None:
    prompts = root / "prompts"
    prompts.mkdir(parents=True)
    roles = []
    for role in ROLES:
        (prompts / f"{role}.md").write_text(f"You are the Shepherd {role}.\n", encoding="utf-8")
        roles.append(
            {
                "role": role,
                "carrier_path": f"prompts/{role}.md",
                "description": f"Shepherd {role} role",
                "model_hint": "inherit-caller" if role == "shepherd" else "reasoning-high" if role in {"conductor", "engineer"} else "standard",
                "model": "inherit" if role == "shepherd" else None,
                "tools": ["read", "subagent"] if role in {"conductor", "engineer"} else ["read"],
                "capabilities": ["read", "dispatch"] if role in {"conductor", "engineer"} else ["read"],
                "write_eligible": role in {"coder", "conductor", "engineer", "worker"},
                "dispatchable": role not in NON_DISPATCHABLE,
            }
        )
    (root / ".shepherd-generated.json").write_text(
        json.dumps({"schema": "shepherd.compiled-tree/3", "target": "pi", "roles": roles}),
        encoding="utf-8",
    )


def run(package_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), str(package_root)],
        check=False,
        capture_output=True,
        text=True,
    )


class PiAgentGenerationTests(unittest.TestCase):
    def test_generates_exactly_the_seven_dispatchable_literal_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary)
            seed(package_root)
            generated = run(package_root)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            agents = package_root / "agents"
            self.assertEqual(
                sorted(path.stem for path in agents.glob("*.md")),
                sorted(set(ROLES) - NON_DISPATCHABLE),
            )
            engineer = (agents / "engineer.md").read_text(encoding="utf-8")
            self.assertIn('name: "shepherd:engineer"', engineer)
            self.assertIn("tools: read, subagent", engineer)
            self.assertIn("acceptanceRole: writer", engineer)
            self.assertIn("subagentOnlyExtensions: ../src/extension.mjs", engineer)
            self.assertIn("maxSubagentDepth: 2", engineer)
            self.assertIn("model: model-required/model-required", engineer)
            self.assertNotIn("sonnet", engineer)
            self.assertNotIn("haiku", engineer)
            self.assertTrue(engineer.endswith("You are the Shepherd engineer.\n"))
            manifest = json.loads((package_root / ".shepherd-generated.json").read_text(encoding="utf-8"))
            canonical_roles = {role["role"]: role for role in manifest["roles"]}
            for role in ("critic", "worker"):
                carrier = (agents / f"{role}.md").read_text(encoding="utf-8")
                carrier_tools = next(line for line in carrier.splitlines() if line.startswith("tools: "))
                if role == "critic":
                    self.assertIn("acceptanceRole: read-only", carrier)
                self.assertIn("subagent", carrier_tools)
                self.assertIn("maxSubagentDepth: 2", carrier)
                self.assertIn("model: model-required/model-required", carrier)
                self.assertNotIn("sonnet", carrier)
                self.assertNotIn("haiku", carrier)
                self.assertNotIn("dispatch", canonical_roles[role]["capabilities"])
            for role in ("conductor", "engineer"):
                self.assertIn("dispatch", canonical_roles[role]["capabilities"])
                carrier = (agents / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn("model: model-required/model-required", carrier)
                self.assertNotIn("model: inherit", carrier)

    def test_rejects_non_inherit_manifest_models_without_partial_output(self) -> None:
        for model in ("sonnet", "haiku", "provider/model:max"):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as temporary:
                package_root = Path(temporary)
                seed(package_root)
                manifest_path = package_root / ".shepherd-generated.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                worker = next(role for role in manifest["roles"] if role["role"] == "worker")
                worker["model"] = model
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                generated = run(package_root)

                self.assertNotEqual(generated.returncode, 0)
                self.assertEqual(
                    generated.stderr,
                    f"dispatchable role worker non-inherit hint standard must emit model null, got {model!r}\n",
                )
                self.assertFalse((package_root / "agents").exists())

    def test_inherit_caller_emits_only_the_compiler_inherit_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary)
            seed(package_root)
            manifest_path = package_root / ".shepherd-generated.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            engineer = next(role for role in manifest["roles"] if role["role"] == "engineer")
            engineer["model_hint"] = "inherit-caller"
            engineer["model"] = "inherit"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            generated = run(package_root)

            self.assertEqual(generated.returncode, 0, generated.stderr)
            carrier = (package_root / "agents/engineer.md").read_text(encoding="utf-8")
            self.assertIn("model: inherit\n", carrier)
            self.assertNotIn("model: model-required/model-required", carrier)

    def test_inherit_caller_requires_the_compiler_emitted_inherit_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary)
            seed(package_root)
            manifest_path = package_root / ".shepherd-generated.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            engineer = next(role for role in manifest["roles"] if role["role"] == "engineer")
            engineer["model_hint"] = "inherit-caller"
            engineer["model"] = None
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            generated = run(package_root)

            self.assertNotEqual(generated.returncode, 0)
            self.assertEqual(
                generated.stderr,
                "dispatchable role engineer inherit-caller hint must emit model inherit\n",
            )
            self.assertFalse((package_root / "agents").exists())

    def test_rejects_a_missing_prompt_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary)
            seed(package_root)
            (package_root / "prompts/engineer.md").unlink()
            generated = run(package_root)
            self.assertNotEqual(generated.returncode, 0)
            self.assertIn("missing role prompt", generated.stderr)
            self.assertFalse((package_root / "agents").exists())

    def test_rejects_zero_dispatchable_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package_root = Path(temporary)
            seed(package_root)
            manifest_path = package_root / ".shepherd-generated.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for role in manifest["roles"]:
                role["dispatchable"] = False
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            generated = run(package_root)
            self.assertNotEqual(generated.returncode, 0)
            self.assertIn("zero dispatchable roles", generated.stderr)
            self.assertFalse((package_root / "agents").exists())


if __name__ == "__main__":
    unittest.main()
