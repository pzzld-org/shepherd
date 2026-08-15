from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conformance.lib import harness


class AuthorityContractTests(unittest.TestCase):
    def write_case(self, root: Path, authority: str | None) -> harness.Case:
        case_dir = root / "case"
        case_dir.mkdir()
        document: dict[str, object] = {
            "kind": "pure",
            "description": "authority fixture",
            "args": ["seed"],
        }
        if authority is not None:
            document["authority"] = authority
        (case_dir / "case.json").write_text(json.dumps(document))
        return harness.load_case(case_dir / "case.json", root)

    def test_cases_default_to_native_recording_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_case(Path(temporary), None)
            self.assertEqual(case.authority, "native-v6.4.5")

    def test_legacy_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "only native-v6.4.5 authority"):
                self.write_case(Path(temporary), "python-legacy")

    def test_unknown_recording_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "only native-v6.4.5 authority"):
                self.write_case(Path(temporary), "latest-wins")

    def test_case_environment_uses_an_isolated_user_home_and_no_legacy_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary)
            cwd = scratch / "cwd"
            workdir = cwd / ".shepherd"
            database = workdir / "shepherd.db"
            leaked = {
                "SHEPHERD_HOME": "/real/home/.shepherd",
                "SHEPHERD_WORKDIR": "/real/project/.shepherd",
                "SHCTX_DB": "/real/project/.shepherd/shepherd.db",
            }

            with mock.patch.dict("os.environ", leaked, clear=False):
                environment = harness._build_env(cwd, workdir, database)

            self.assertEqual(environment["SHEPHERD_HOME"], str(cwd / ".shepherd-user"))
            self.assertNotIn("SHEPHERD_WORKDIR", environment)
            self.assertNotIn("SHCTX_DB", environment)


if __name__ == "__main__":
    unittest.main()
