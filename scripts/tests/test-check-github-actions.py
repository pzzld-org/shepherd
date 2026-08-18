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
        workspace_version: str | None = None,
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
        if workspace_version is not None:
            (self.root / "Cargo.toml").write_text(
                f'[workspace.package]\nversion = "{workspace_version}"\n', encoding="utf-8"
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
        workspace_version: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        fixture = CheckerFixture(workflow, lock, workspace_version)
        self.addCleanup(fixture.close)
        return fixture.run()

    def assert_rejected(
        self,
        workflow: str,
        expected: str,
        lock: dict[str, object] | None = None,
        workspace_version: str | None = None,
    ) -> None:
        result = self.run_fixture(workflow, lock, workspace_version)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(expected, result.stderr)

    def test_canonical_lock_and_workflows_pass(self) -> None:
        result = self.run_fixture("jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.1\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 workflow file, 1 external use, 1 repository", result.stdout)

    def test_sha_pin_is_rejected(self) -> None:
        """A SHA cannot inherit the action's own minor and patch fixes."""
        self.assert_rejected(
            f"jobs:\n  test:\n    uses: actions/checkout@{CHECKOUT_SHA} # v7.0.1\n",
            "reference must be the major version tag 'v7'",
        )

    def test_wrong_major_is_rejected(self) -> None:
        """Floating is not unconstrained: the major must match the lock."""
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v6 # v7.0.1\n",
            "reference must be the major version tag 'v7'",
        )

    def test_upstream_patch_release_keeps_the_gate_green(self) -> None:
        """The whole point of floating: v7.0.2 ships and we are not red."""
        result = self.run_fixture("jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.2\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_comment_is_optional(self) -> None:
        result = self.run_fixture("jobs:\n  test:\n    uses: actions/checkout@v7\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflow_pinning_the_workspace_version_is_rejected(self) -> None:
        """A version literal in a workflow makes the file a release authority.

        `version-bump.py` then rewrites it every release, and the gitflow
        handoff cannot push the bumped branch: GITHUB_TOKEN has no `workflows`
        scope to grant, so GitHub refuses any push that updates a workflow. The
        release automation ran correctly all the way to `git push` and died
        there. Derive the version from Cargo.toml in the step instead.
        """
        # 9.9.9 is synthetic on purpose. A fixture pinned to the real release
        # would make this file a version authority, which is the exact coupling
        # the rule under test exists to prevent.
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.1\n"
            "    env:\n      PINNED: 'engine@9.9.9'\n",
            "workflow hard-codes the workspace version `9.9.9`",
            workspace_version="9.9.9",
        )

    def test_workflow_deriving_the_version_is_accepted(self) -> None:
        """The rule must not reject a workflow that reads Cargo.toml."""
        result = self.run_fixture(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.1\n"
            "    env:\n      PINNED: 'engine@${VERSION}'\n",
            workspace_version="9.9.9",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_comment_from_another_major_is_rejected(self) -> None:
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v6.1.0\n",
            "tag comment must be an exact semver in v7.x, or omitted",
        )

    def test_inexact_comment_is_rejected(self) -> None:
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v7\n",
            "tag comment must be an exact semver in v7.x, or omitted",
        )

    def test_pre_release_action_must_pin_the_exact_tag(self) -> None:
        """`v0` is not a compatibility channel -- a 0.x minor may break."""
        lock = canonical_lock(
            {"mozilla-actions/sccache-action": action_record("v0.0.11", CHECKOUT_SHA)}
        )
        self.assert_rejected(
            "jobs:\n  test:\n    uses: mozilla-actions/sccache-action@v0\n",
            "pre-1.0 action must pin the exact tag 'v0.0.11'",
            lock,
        )

        result = self.run_fixture(
            "jobs:\n  test:\n    uses: mozilla-actions/sccache-action@v0.0.11\n", lock
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_action_is_rejected(self) -> None:
        self.assert_rejected(
            "jobs:\n  test:\n    uses: example/action@v1 # v1.0.0\n",
            "action repository is absent from .github/actions-lock.json: example/action",
        )

    def test_malformed_comment_without_yaml_whitespace_is_rejected(self) -> None:
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7# v7.0.1\n",
            "uses scalar must be an unquoted action, optionally followed by '# <exact-tag>'",
        )

    def test_unused_lock_entry_is_rejected(self) -> None:
        lock = canonical_lock(
            {
                "actions/checkout": action_record("v7.0.1", CHECKOUT_SHA),
                "example/unused": action_record("v1.0.0", "d" * 40),
            }
        )
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.1\n",
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
            "jobs:\n  test:\n    uses: github/codeql-action/upload-sarif@v4 # v4.37.7\n",
            lock,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_expired_lock_is_rejected_offline(self) -> None:
        lock = canonical_lock(refresh_by="2026-08-15T17:59:59Z")
        self.assert_rejected(
            "jobs:\n  test:\n    uses: actions/checkout@v7 # v7.0.1\n",
            "action lock expired at 2026-08-15T17:59:59Z",
            lock,
        )

    def test_local_and_docker_actions_do_not_require_lock_entries(self) -> None:
        result = self.run_fixture(
            """jobs:
  local:
    uses: ./actions/local
  docker:
    uses: docker://alpine:3.22
  external:
    uses: actions/checkout@v7 # v7.0.1
"""
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
