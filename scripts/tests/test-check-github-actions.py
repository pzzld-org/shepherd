#!/usr/bin/env python3
"""Falsification tests for the repository-wide GitHub Actions pin gate."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "check-github-actions.py"
NOW = "2026-08-15T18:00:00Z"
CHECKOUT_SHA = "a" * 40
CODEQL_SHA = "b" * 40


def action_record(tag: str, sha: str) -> dict[str, str]:
    return {
        "selector": "latest-release",
        "sha": sha,
        "tag": tag,
    }


def canonical_lock(
    actions: dict[str, dict[str, str]] | None = None,
    *,
    refresh_by: str = "2026-08-29T17:43:49Z",
) -> dict[str, object]:
    return {
        "actions": actions
        or {"actions/checkout": action_record("v7.0.1", CHECKOUT_SHA)},
        "refresh_by": refresh_by,
        "schema": 1,
        "verified_at": "2026-08-15T17:43:49Z",
    }


class CheckerFixture:
    def __init__(
        self,
        workflow: str,
        lock: dict[str, object] | None = None,
    ) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="shepherd-action-pins."
        )
        self.root = Path(self._temporary_directory.name)
        workflow_directory = self.root / ".github" / "workflows"
        workflow_directory.mkdir(parents=True)
        (workflow_directory / "test.yml").write_text(workflow, encoding="utf-8")
        (self.root / ".github" / "actions-lock.json").write_text(
            json.dumps(lock or canonical_lock(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def close(self) -> None:
        self._temporary_directory.cleanup()

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--root",
                str(self.root),
                "--now",
                NOW,
            ],
            check=False,
            capture_output=True,
            text=True,
        )


class GitHubActionsPinCheckerTests(unittest.TestCase):
    def run_fixture(
        self,
        workflow: str,
        lock: dict[str, object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        fixture = CheckerFixture(workflow, lock)
        self.addCleanup(fixture.close)
        return fixture.run()

    def assert_rejected(
        self,
        workflow: str,
        expected: str,
        lock: dict[str, object] | None = None,
    ) -> None:
        result = self.run_fixture(workflow, lock)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(expected, result.stderr)

    def test_canonical_lock_and_workflows_pass(self) -> None:
        result = self.run_fixture(
            f"jobs:\n  test:\n    uses: actions/checkout@{CHECKOUT_SHA} # v7.0.1\n"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 workflow file, 1 external use, 1 repository", result.stdout)

    def test_mutable_tag_is_rejected(self) -> None:
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.1\n",
            "reference must be a 40-character lowercase commit SHA",
        )

    def test_unknown_action_is_rejected(self) -> None:
        self.assert_rejected(
            f"jobs:\n  test:\n    uses: example/action@{CHECKOUT_SHA} # v1.0.0\n",
            "action repository is absent from .github/actions-lock.json: example/action",
        )

    def test_exact_tag_comment_drift_is_rejected(self) -> None:
        self.assert_rejected(
            f"jobs:\n  test:\n    uses: actions/checkout@{CHECKOUT_SHA} # v7\n",
            "tag comment must be exactly '# v7.0.1'",
        )

    def test_stale_sha_is_rejected(self) -> None:
        self.assert_rejected(
            f"jobs:\n  test:\n    uses: actions/checkout@{'c' * 40} # v7.0.1\n",
            f"commit SHA must equal locked SHA {CHECKOUT_SHA}",
        )

    def test_malformed_comment_without_yaml_whitespace_is_rejected(self) -> None:
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7# v7.0.1\n",
            "uses scalar must be an unquoted action followed by '# <exact-tag>'",
        )

    def test_noncanonical_sha_lengths_and_case_are_rejected(self) -> None:
        for reference in ("a" * 39, "a" * 41, "A" * 40):
            with self.subTest(reference=reference):
                self.assert_rejected(
                    f"jobs:\n  test:\n    uses: actions/checkout@{reference} # v7.0.1\n",
                    "reference must be a 40-character lowercase commit SHA",
                )

    def test_unused_lock_entry_is_rejected(self) -> None:
        lock = canonical_lock(
            {
                "actions/checkout": action_record("v7.0.1", CHECKOUT_SHA),
                "example/unused": action_record("v1.0.0", "d" * 40),
            }
        )
        self.assert_rejected(
            f"jobs:\n  test:\n    uses: actions/checkout@{CHECKOUT_SHA} # v7.0.1\n",
            "lock entry is not used by any workflow: example/unused",
            lock,
        )

    def test_subaction_uses_repository_lock(self) -> None:
        lock = canonical_lock(
            {
                "github/codeql-action": {
                    "channel": "v4",
                    "selector": "highest-stable-tag-in-supported-major",
                    "sha": CODEQL_SHA,
                    "tag": "v4.37.7",
                }
            }
        )
        result = self.run_fixture(
            f"jobs:\n  test:\n    uses: github/codeql-action/upload-sarif@{CODEQL_SHA} # v4.37.7\n",
            lock,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_expired_lock_is_rejected_offline(self) -> None:
        lock = canonical_lock(refresh_by="2026-08-15T17:59:59Z")
        self.assert_rejected(
            f"jobs:\n  test:\n    uses: actions/checkout@{CHECKOUT_SHA} # v7.0.1\n",
            "action lock expired at 2026-08-15T17:59:59Z",
            lock,
        )

    def test_local_and_docker_actions_do_not_require_lock_entries(self) -> None:
        result = self.run_fixture(
            f"""jobs:
  local:
    uses: ./actions/local
  docker:
    uses: docker://alpine:3.22
  external:
    uses: actions/checkout@{CHECKOUT_SHA} # v7.0.1
"""
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
