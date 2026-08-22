#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "gate-artifact.py"
FIELDS = ["--run", "r1", "--wave", "w1", "--lane", "l1", "--gate", "fast"]
PASS = [sys.executable, "-c", "raise SystemExit(0)"]
FAIL = [sys.executable, "-c", "raise SystemExit(7)"]


class GateArtifactTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts/gate-artifact.py"
        shutil.copy2(SOURCE, self.script)
        self.artifact = self.root / ".shepherd/runs/r1/lanes/l1/evidence/gates/w1-fast.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, action: str, *command: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *FIELDS, action, *command],
            cwd=cwd or self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def state(self, expected: list[str]) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        completed = self.invoke("status", "--", *expected)
        return completed, json.loads(completed.stdout) if completed.stdout else {}

    def invocation(self, attempt: str, invoked: list[str]) -> dict[str, object]:
        return {
            "schema": "shepherd.gate-attempt/1",
            "kind": "invocation",
            "run": "r1",
            "wave": "w1",
            "lane": "l1",
            "gate": "fast",
            "attempt_id": attempt,
            "command": invoked,
        }

    def result(self, attempt: str, exit_code: int = 0) -> dict[str, object]:
        return {
            "schema": "shepherd.gate-attempt/1",
            "kind": "result",
            "run": "r1",
            "wave": "w1",
            "lane": "l1",
            "gate": "fast",
            "attempt_id": attempt,
            "status": "passed" if exit_code == 0 else "failed",
            "exit_code": exit_code,
        }

    def test_missing_artifact_is_unverified_for_expected_command(self) -> None:
        completed, state = self.state(PASS)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(state["state"], "unverified")

    def test_pass_records_correlated_invocation_before_execution_and_result(self) -> None:
        probe = [
            sys.executable,
            "-c",
            "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); r=json.loads(p.read_text().splitlines()[-1]); raise SystemExit(0 if r['kind']=='invocation' else 9)",
            str(self.artifact),
        ]
        completed = self.invoke("run", "--", *probe)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        records = [json.loads(line) for line in self.artifact.read_text().splitlines()]
        self.assertEqual([record["kind"] for record in records], ["invocation", "result"])
        self.assertEqual(records[0]["attempt_id"], records[1]["attempt_id"])
        status, state = self.state(probe)
        self.assertEqual(status.returncode, 0)
        self.assertEqual((state["state"], state["exit_code"]), ("passed", 0))

    def test_failure_preserves_original_exit_code(self) -> None:
        self.assertEqual(self.invoke("run", "--", *FAIL).returncode, 7)
        status, state = self.state(FAIL)
        self.assertEqual((status.returncode, state["state"], state["exit_code"]), (1, "failed", 7))

    def test_declared_gate_rejects_a_different_command(self) -> None:
        self.assertEqual(self.invoke("run", "--", *PASS).returncode, 0)
        completed, _ = self.state(["true"])
        self.assertEqual(completed.returncode, 2)
        self.assertIn("does not match the expected command", completed.stderr)

    def test_latest_incomplete_attempt_overrides_an_older_pass(self) -> None:
        self.assertEqual(self.invoke("run", "--", *PASS).returncode, 0)
        self.artifact.write_text(self.artifact.read_text() + json.dumps(self.invocation("a" * 32, ["pending"])) + "\n")
        status, state = self.state(["pending"])
        self.assertEqual((status.returncode, state["state"], state["attempt_id"]), (4, "invoked", "a" * 32))

    def test_status_is_linearized_with_a_concurrent_retry(self) -> None:
        self.assertEqual(self.invoke("run", "--", *PASS).returncode, 0)
        with self.artifact.open("ab", buffering=0) as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            process = subprocess.Popen(
                [sys.executable, str(self.script), *FIELDS, "status", "--", "pending"],
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.05)
            self.assertIsNone(process.poll(), "status must wait for the artifact lock")
            stream.write((json.dumps(self.invocation("b" * 32, ["pending"])) + "\n").encode())
            os.fsync(stream.fileno())
            fcntl.flock(stream, fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 4, stderr)
        self.assertEqual(json.loads(stdout)["attempt_id"], "b" * 32)

    def test_unknown_contradictory_and_impossible_results_fail_closed(self) -> None:
        self.artifact.parent.mkdir(parents=True)
        invocation = self.invocation("a" * 32, ["gate"])
        for result in (self.result("b" * 32), {**self.result("a" * 32), "status": "failed"}, self.result("a" * 32, 999)):
            self.artifact.write_text(json.dumps(invocation) + "\n" + json.dumps(result) + "\n")
            completed = self.invoke("status", "--", "gate")
            self.assertEqual(completed.returncode, 2, completed.stdout)

    def test_malformed_partial_and_empty_commands_fail_closed(self) -> None:
        self.artifact.parent.mkdir(parents=True)
        self.artifact.write_text("not-json\n")
        self.assertEqual(self.invoke("status", "--", *PASS).returncode, 2)
        self.artifact.write_text(json.dumps(self.invocation("a" * 32, PASS)))
        partial = self.invoke("status", "--", *PASS)
        self.assertEqual(partial.returncode, 2)
        self.assertIn("not newline-terminated", partial.stderr)
        self.artifact.unlink()
        self.assertEqual(self.invoke("run", "--").returncode, 2)
        self.assertEqual(self.invoke("status", "--").returncode, 2)

    def test_short_writes_are_completed(self) -> None:
        spec = importlib.util.spec_from_file_location("gate_artifact", self.script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        record = self.invocation("a" * 32, PASS)
        real_write = module.os.write
        with mock.patch.object(module.os, "write", side_effect=lambda fd, data: real_write(fd, bytes(data[:1]))):
            module.append_record(self.root, self.artifact, record)
        self.assertTrue(self.artifact.read_bytes().endswith(b"\n"))
        self.assertEqual(json.loads(self.artifact.read_text()), record)

    @unittest.skipIf(os.name == "nt", "no-follow descriptor contract is POSIX")
    def test_symlinked_parent_is_rejected_for_run_and_status(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        outside_artifact = outside / "lanes/l1/evidence/gates/w1-fast.jsonl"
        outside_artifact.parent.mkdir(parents=True)
        outside_artifact.write_text(json.dumps(self.invocation("a" * 32, PASS)) + "\n" + json.dumps(self.result("a" * 32)) + "\n")
        (self.root / ".shepherd/runs").mkdir(parents=True)
        (self.root / ".shepherd/runs/r1").symlink_to(outside, target_is_directory=True)
        for completed in (self.invoke("run", "--", *PASS), self.invoke("status", "--", *PASS)):
            self.assertEqual(completed.returncode, 2)
            self.assertIn("unsafe or not a directory", completed.stderr)

    def test_script_location_owns_artifact_root_not_caller_cwd(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        self.assertEqual(self.invoke("run", "--", *PASS, cwd=nested).returncode, 0)
        self.assertTrue(self.artifact.is_file())
        self.assertFalse((nested / ".shepherd").exists())


if __name__ == "__main__":
    unittest.main()
