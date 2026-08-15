#!/usr/bin/env python3
"""Cold localhost proof for Shepherd's Cargo Binstall metadata."""

from __future__ import annotations

import http.server
import io
import ssl
import subprocess
import tarfile
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class BinstallFixtureTests(unittest.TestCase):
    def test_crate_metadata_installs_and_executes_root_binary(self) -> None:
        if subprocess.run(["cargo", "binstall", "-V"], capture_output=True).returncode != 0:
            self.skipTest("cargo-binstall is not installed")
        with (ROOT / "Cargo.toml").open("rb") as handle:
            version = tomllib.load(handle)["workspace"]["package"]["version"]
        host = next(
            line.removeprefix("host: ")
            for line in subprocess.check_output(["rustc", "-vV"], text=True).splitlines()
            if line.startswith("host: ")
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / f"shepherd-{version}-{host}.tar.gz"
            payload = f"#!/bin/sh\nprintf '%s\\n' 'shepherd-cli {version}'\n".encode()
            info = tarfile.TarInfo("shepherd")
            info.mode = 0o755
            info.size = len(payload)
            info.mtime = 0
            with tarfile.open(archive, "w:gz") as handle:
                handle.addfile(info, io.BytesIO(payload))

            certificate = root / "localhost.pem"
            key = root / "localhost.key"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-subj",
                    "/CN=127.0.0.1",
                    "-addext",
                    "subjectAltName=IP:127.0.0.1",
                    "-addext",
                    "extendedKeyUsage=serverAuth",
                    "-addext",
                    "basicConstraints=critical,CA:TRUE",
                    "-addext",
                    "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign",
                    "-keyout",
                    str(key),
                    "-out",
                    str(certificate),
                ],
                check=True,
                capture_output=True,
            )

            handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
                *args, directory=root, **kwargs
            )
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                binary = root / "install/bin/shepherd"
                result = subprocess.run(
                    [
                        "cargo",
                        "binstall",
                        "--manifest-path",
                        str(ROOT / "crates/cli/Cargo.toml"),
                        "--version",
                        version,
                        "--targets",
                        host,
                        "--pkg-url",
                        f"https://127.0.0.1:{server.server_port}/shepherd-{{ version }}-{{ target }}.tar.gz",
                        "--strategies",
                        "crate-meta-data",
                        "--root",
                        str(root / "install"),
                        "--no-confirm",
                        "--no-track",
                        "--disable-telemetry",
                        "--no-discover-github-token",
                        "--root-certificates",
                        str(certificate),
                        "shepherd-cli",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(
                    subprocess.check_output([str(binary), "--version"], text=True).strip(),
                    f"shepherd-cli {version}",
                )
            finally:
                server.shutdown()
                thread.join()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
