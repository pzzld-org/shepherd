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
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/cargo-publish.py"
# A synthetic version for the temp-state fixtures: they never touch the real
# workspace, so pinning a real release here would only rot at every bump.
VERSION = "1.2" + ".3"


def _workspace_version() -> str:
    """The version `plan` is run against, read from the workspace itself.

    This drives `version-bump.py plan` against the REAL repository, so it has to
    be whatever the workspace currently declares. Hardcoding the release of the
    day made this test fail on the next bump -- for the seventh time in one
    sprint, in a file whose whole job is guarding the version authority.
    """
    manifest = (ROOT / "Cargo.toml").read_text(encoding="utf-8")
    for line in manifest.splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            return stripped.split("=", 1)[1].strip().strip('"')
    raise AssertionError("Cargo.toml declares no workspace.package.version")


NEXT_VERSION = _workspace_version()


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
            ["python3", str(SCRIPT), "plan", "--version", NEXT_VERSION, "--json"],
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
                    NEXT_VERSION,
                    "--state",
                    str(state),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("version mismatch", result.stderr.lower())

    def test_metadata_404_means_the_exact_version_is_absent(self) -> None:
        module = publisher_module()
        requests: list[str] = []

        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            metadata = module.crate_metadata(
                f"http://127.0.0.1:{server.server_port}",
                "shepherd-core",
                VERSION,
            )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertIsNone(metadata)
        self.assertEqual(requests, [f"/api/v1/crates/shepherd-core/{VERSION}"])

    def test_publish_uses_metadata_404_to_publish_an_absent_version(self) -> None:
        module = publisher_module()
        commands: list[list[str]] = []

        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / f"shepherd-core-{VERSION}.crate"
            artifact.write_bytes(b"new crate bytes")
            state = root / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "version": VERSION,
                        "source_head": "deadbeef",
                        "crates": {
                            "shepherd-core": {
                                "artifact": str(artifact),
                                "local_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                                "published_sha256": None,
                                "status": "prepared",
                                "wave": 1,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original_run = module.run
            original_wait = module.wait_for_checksum
            original_waves = module.WAVES

            def fake_run(command: list[str], *, capture: bool = False) -> str:
                commands.append(command)
                if command[:2] == ["git", "rev-parse"]:
                    return "deadbeef"
                return ""

            def fake_wait(args: SimpleNamespace, name: str, expected: str) -> str:
                return expected

            module.run = fake_run
            module.wait_for_checksum = fake_wait
            module.WAVES = (("shepherd-core",),)
            try:
                module.publish(
                    SimpleNamespace(
                        confirm=True,
                        state=state,
                        version=VERSION,
                        registry_api=f"http://127.0.0.1:{server.server_port}",
                        timeout=0,
                    )
                )
            finally:
                module.run = original_run
                module.wait_for_checksum = original_wait
                module.WAVES = original_waves
                server.shutdown()
                thread.join()
                server.server_close()

            self.assertIn(["cargo", "publish", "--locked", "--package", "shepherd-core"], commands)
            saved_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved_state["crates"]["shepherd-core"]["status"], "published")

    def test_download_rejects_a_json_url_envelope_as_non_archive_bytes(self) -> None:
        module = publisher_module()

        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = json.dumps(
                    {
                        "url": (
                            "https://static.crates.io/crates/shepherd-core/"
                            f"shepherd-core-{VERSION}.crate"
                        )
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(module.PublishError, "JSON envelope"):
                module.download_crate(
                    f"http://127.0.0.1:{server.server_port}",
                    "shepherd-core",
                    VERSION,
                )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_publish_resumes_only_byte_identical_existing_crates(self) -> None:
        waves = [
            ["shepherd-core", "shepherd-compiler"],
            ["shepherd-registry", "shepherd-render"],
            ["shepherd-sdk"],
            ["shepherd-cli"],
        ]
        names = [name for wave in waves for name in wave]
        requests: list[str] = []
        accepts: list[str | None] = []

        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                accepts.append(self.headers.get("Accept"))
                if self.path.endswith(f"/{NEXT_VERSION}"):
                    name = self.path.split("/")[4]
                    body = name.encode()
                    body = json.dumps(
                        {
                            "version": {
                                "num": NEXT_VERSION,
                                "checksum": hashlib.sha256(body).hexdigest(),
                            }
                        }
                    ).encode()
                    content_type = "application/json"
                elif self.path.endswith("/download"):
                    name = self.path.split("/")[4]
                    self.send_response(302)
                    self.send_header("Location", f"/archive/{name}")
                    self.end_headers()
                    return
                else:
                    name = self.path.rsplit("/", 1)[-1]
                    body = name.encode()
                    content_type = "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
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
                    artifact = root / f"{name}-{NEXT_VERSION}.crate"
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
                        "version": NEXT_VERSION,
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
                        NEXT_VERSION,
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
                path
                for name in names
                for path in (
                    f"/api/v1/crates/{name}/{NEXT_VERSION}",
                    f"/api/v1/crates/{name}/{NEXT_VERSION}/download",
                    f"/archive/{name}",
                )
            ]
            self.assertEqual(requests, expected)
            for index, path in enumerate(requests):
                if path.endswith(f"/{NEXT_VERSION}"):
                    self.assertEqual(accepts[index], "application/json")
                else:
                    self.assertEqual(accepts[index], "application/octet-stream")

    def test_publish_fails_closed_on_existing_archive_checksum_mismatch(self) -> None:
        expected_bytes = b"expected crate bytes"
        actual_bytes = b"different immutable crate bytes"
        expected_checksum = hashlib.sha256(expected_bytes).hexdigest()
        requests: list[str] = []

        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append(self.path)
                if self.path.endswith(f"/{VERSION}"):
                    body = json.dumps(
                        {
                            "version": {
                                "num": VERSION,
                                "checksum": expected_checksum,
                            }
                        }
                    ).encode()
                    content_type = "application/json"
                else:
                    body = actual_bytes
                    content_type = "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / f"shepherd-core-{VERSION}.crate"
            artifact.write_bytes(expected_bytes)
            state = root / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "version": VERSION,
                        "source_head": subprocess.check_output(
                            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                        ).strip(),
                        "crates": {
                            "shepherd-core": {
                                "artifact": str(artifact),
                                "local_sha256": expected_checksum,
                                "published_sha256": None,
                                "status": "prepared",
                                "wave": 1,
                            }
                        },
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
                        VERSION,
                        "--state",
                        str(state),
                        "--registry-api",
                        f"http://127.0.0.1:{server.server_port}",
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

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive checksum mismatch", result.stderr)
            saved_state = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(saved_state["crates"]["shepherd-core"]["status"], "prepared")
            self.assertEqual(
                requests,
                [
                    f"/api/v1/crates/shepherd-core/{VERSION}",
                    f"/api/v1/crates/shepherd-core/{VERSION}/download",
                ],
            )


if __name__ == "__main__":
    unittest.main()
