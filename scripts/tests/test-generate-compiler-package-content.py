#!/usr/bin/env python3
"""Regression tests for the compiler's generated package content."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate-compiler-package-content.py"


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def seed(root: Path) -> Path:
    write(root / "content/roles/a.md", "role\n")
    write(root / "content/skills/s/SKILL.md", "skill\n")
    write(root / "content/predicates/p.toml", "value = true\n")
    write(root / "content/templates/handoff.md", "handoff\n")
    return root / "projection"


def run(root: Path, output: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), mode, "--root", str(root), "--output", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )


class ProjectionTests(unittest.TestCase):
    def test_write_then_check_is_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = seed(root)
            written = run(root, output, "--write")
            self.assertEqual(written.returncode, 0, written.stderr)
            checked = run(root, output, "--check")
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(
                sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()),
                [
                    "SHA256SUMS",
                    "content/predicates/p.toml",
                    "content/roles/a.md",
                    "content/skills/s/SKILL.md",
                    "content/templates/handoff.md",
                ],
            )

    def test_check_rejects_missing_extra_drift_and_symlink_entries(self) -> None:
        mutations = ("missing", "extra", "drift", "symlink")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = seed(root)
                self.assertEqual(run(root, output, "--write").returncode, 0)
                role = output / "content/roles/a.md"
                if mutation == "missing":
                    role.unlink()
                elif mutation == "extra":
                    write(output / "content/roles/extra.md", "extra\n")
                elif mutation == "drift":
                    write(role, "changed\n")
                else:
                    role.unlink()
                    role.symlink_to(root / "content/roles/a.md")
                checked = run(root, output, "--check")
                self.assertNotEqual(checked.returncode, 0)
                self.assertIn(mutation, checked.stderr.lower())

    def test_first_run_spawn_sequence_survives_every_committed_projection(self) -> None:
        marker = "`shepherd run init <run>` → invoke `plant` → invoke `spawn` again"
        paths = [
            ROOT / "content/skills/spawn/SKILL.md",
            ROOT / "skills/spawn/SKILL.md",
            ROOT / "plugins/shepherd/codex/skills/spawn/SKILL.md",
            ROOT / "crates/compiler/package-content/content/skills/spawn/SKILL.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                text = " ".join(path.read_text().split())
                self.assertIn(marker, text)
                self.assertIn("Never run `shepherd init --confirm` as a spawn side effect", text)

    def test_projection_check_rejects_removed_first_run_action(self) -> None:
        marker = "`shepherd run init <run>` → invoke `plant` → invoke `spawn` again"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = seed(root)
            spawn = root / "content/skills/spawn/SKILL.md"
            write(spawn, f"before\n{marker}\nafter\n")
            self.assertEqual(run(root, output, "--write").returncode, 0)
            write(spawn, "before\nafter\n")
            checked = run(root, output, "--check")
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("byte drift: content/skills/spawn/SKILL.md", checked.stderr)

    def test_repository_projection_has_exactly_twenty_four_sources(self) -> None:
        checked = run(ROOT, ROOT / "crates/compiler/package-content", "--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        sources = [
            path
            for path in (ROOT / "crates/compiler/package-content/content").rglob("*")
            if path.is_file() and not path.is_symlink()
        ]
        # 24, not 23: authoring content/skills/plant/SKILL.md added one source.
        self.assertEqual(len(sources), 24)


if __name__ == "__main__":
    unittest.main()
