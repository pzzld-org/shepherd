#!/usr/bin/env python3
"""Deterministic tests for the resumable Cargo publisher."""

from __future__ import annotations

import json
import hashlib
import http.server
import importlib.util
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/cargo-publish.py"
VERSION = "6.4" + ".5"


def publisher_module():
    spec = importlib.util.spec_from_file_location("cargo_publish", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CargoPublishTests(unittest.TestCase):
    def test_prepared_state_has_no_remote_url_secret_sink(self) -> None:
        module = publisher_module()
        state = module.build_state(
            VERSION,
            "deadbeef",
            {"shepherd-core": {"status": "prepared"}},
        )
        self.assertNotIn("remote_url", state)

    def test_status_does_not_print_legacy_remote_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "version": VERSION,
                        "source_head": "deadbeef",
                        "remote_url": "https://TOKEN@example.invalid/repo.git",
                        "crates": {},
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "status",
                    "--version",
                    VERSION,
                    "--state",
                    str(state),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("remote_url", result.stdout)
            self.assertNotIn("TOKEN", result.stdout)

    def test_plan_is_the_exact_dependency_order(self) -> None:
        result = subprocess.run(
            ["python3", str(SCRIPT), "plan", "--version", "6.4.5", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["waves"],
            [
                ["shepherd-core", "shepherd-compiler"],
                ["shepherd-registry", "shepherd-render"],
                ["shepherd-sdk"],
                ["shepherd-cli"],
            ],
        )

    def test_status_rejects_state_from_another_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state.json"
            state.write_text(
                json.dumps({"schema_version": 1, "version": "6.4.4", "crates": {}}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "status",
                    "--version",
                    "6.4.5",
                    "--state",
                    str(state),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("version mismatch", result.stderr.lower())

    def test_publish_resumes_only_byte_identical_existing_crates(self) -> None:
        waves = [
            ["shepherd-core", "shepherd-compiler"],
            ["shepherd-registry", "shepherd-render"],
            ["shepherd-sdk"],
            ["shepherd-cli"],
        ]
        names = [name for wave in waves for name in wave]
        requests: list[str] = []

        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                name = self.path.split("/")[4]
                body = name.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            crates = {}
            for wave_index, wave in enumerate(waves, 1):
                for name in wave:
                    artifact = root / f"{name}-6.4.5.crate"
                    artifact.write_bytes(name.encode())
                    crates[name] = {
                        "artifact": str(artifact),
                        "local_sha256": hashlib.sha256(name.encode()).hexdigest(),
                        "published_sha256": None,
                        "status": "prepared",
                        "wave": wave_index,
                    }
            state = root / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "version": "6.4.5",
                        "source_head": subprocess.check_output(
                            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                        ).strip(),
                        "remote_url": "fixture",
                        "crates": crates,
                    }
                ),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run(
                    [
                        "python3",
                        str(SCRIPT),
                        "publish",
                        "--version",
                        "6.4.5",
                        "--state",
                        str(state),
                        "--registry-api",
                        f"http://127.0.0.1:{server.server_port}",
                        "--timeout",
                        "0",
                        "--confirm",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
            self.assertEqual(result.returncode, 0, result.stderr)
            saved_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertNotIn("remote_url", saved_state)
            receipts = saved_state["crates"]
            self.assertTrue(all(receipts[name]["status"] == "published" for name in names))
            expected = [
                f"/api/v1/crates/{name}/6.4.5/download"
                for name in names
                for _ in range(2)
            ]
            self.assertEqual(requests, expected)


if __name__ == "__main__":
    unittest.main()
