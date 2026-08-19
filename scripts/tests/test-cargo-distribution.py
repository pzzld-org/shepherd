#!/usr/bin/env python3
"""Deterministic contracts for Shepherd's Cargo-native distribution."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_toml(relative: str) -> dict:
    with (ROOT / relative).open("rb") as handle:
        return tomllib.load(handle)


class CargoIdentityTests(unittest.TestCase):
    def test_core_uses_the_standard_config_builder_for_layer_merge(self) -> None:
        root = load_toml("Cargo.toml")
        core = load_toml("crates/core/Cargo.toml")
        loader = (ROOT / "crates/core/src/loader.rs").read_text(encoding="utf-8")

        config_dependency = root["workspace"]["dependencies"]["config"]
        self.assertEqual(config_dependency["version"], "0.15")
        self.assertEqual(config_dependency["features"], ["toml"])
        self.assertFalse(config_dependency["default-features"])

        self.assertTrue(core["dependencies"]["config"]["optional"])
        self.assertTrue(core["dependencies"]["config"]["workspace"])
        self.assertIn("dep:config", core["features"]["config"])
        self.assertIn("SourceConfig::builder()", loader)
        self.assertNotIn("fn merge_value", loader)

    def test_sdk_package_preserves_the_shepherd_rust_import(self) -> None:
        root = load_toml("Cargo.toml")
        sdk = load_toml("crates/sdk/Cargo.toml")
        component = load_toml("crates/component/Cargo.toml")

        self.assertEqual(sdk["package"]["name"], "shepherd-sdk")
        self.assertEqual(sdk["lib"]["name"], "shepherd")

        alias = root["workspace"]["dependencies"]["shepherd"]
        self.assertEqual(alias["package"], "shepherd-sdk")
        self.assertEqual(alias["path"], "crates/sdk")
        self.assertEqual(alias["version"], "6.5.3")

        self.assertIs(component["package"]["publish"], False)

    def test_binstall_uses_only_immutable_shepherd_archives(self) -> None:
        cli = load_toml("crates/cli/Cargo.toml")
        metadata = cli["package"]["metadata"]["binstall"]
        self.assertEqual(
            metadata["pkg-url"],
            "{ repo }/releases/download/v{ version }/shepherd-{ version }-{ target }.tar.gz",
        )
        self.assertEqual(metadata["bin-dir"], "{ bin }{ binary-ext }")
        self.assertEqual(metadata["pkg-fmt"], "tgz")
        self.assertEqual(metadata["disabled-strategies"], ["quick-install", "compile"])
        windows = metadata["overrides"]["x86_64-pc-windows-msvc"]
        self.assertEqual(
            windows["pkg-url"],
            "{ repo }/releases/download/v{ version }/shepherd-{ version }-{ target }.zip",
        )
        self.assertEqual(windows["pkg-fmt"], "zip")


if __name__ == "__main__":
    unittest.main()
