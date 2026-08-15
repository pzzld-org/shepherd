#!/usr/bin/env python3
"""Prove that the Rust binary is the repository's only CLI authority.

The former Python Typer package and Bash ``shctx`` dispatcher are deleted.
Their route names remain in ``conformance/legacy-command-disposition.json`` as
an immutable retirement inventory, not as executable compatibility code.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


MANIFEST_PATH = Path("conformance/legacy-command-disposition.json")
PUBLIC_LAUNCHER = Path("bin/shepherd")
RETIRED_ROOTS = (Path("services/cli"), Path("skills/context/scripts"))
FORBIDDEN_LAUNCHER_TOKENS = ("poetry", "python", "shepherd_cli", "node", "npm")


class AuthorityError(ValueError):
    """A CLI authority or route inventory contract is broken."""


def manifest_routes(manifest: dict[str, object], key: str, categories: tuple[str, ...]) -> set[str]:
    section = manifest.get(key)
    if not isinstance(section, dict):
        raise AuthorityError(f"manifest section {key!r} is missing")
    routes: list[str] = []
    for category in categories:
        values = section.get(category)
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise AuthorityError(f"manifest {key}.{category} must be a non-empty string array")
        routes.extend(values)
    if len(routes) != len(set(routes)):
        raise AuthorityError(f"manifest {key} has duplicate routes across dispositions")
    return set(routes)


def validate(repo_root: Path, manifest_path: Path) -> tuple[int, int, int]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2:
        raise AuthorityError("manifest schema_version must equal 2")

    for retired_root in RETIRED_ROOTS:
        path = repo_root / retired_root
        if path.exists():
            raise AuthorityError(f"retired CLI implementation root exists: {path}")

    python_section = manifest.get("python_typer")
    if not isinstance(python_section, dict) or "unsupported_pending_parity" in python_section:
        raise AuthorityError("python_typer must use explicit native/retired dispositions")
    python_routes = manifest_routes(manifest, "python_typer", ("native", "retired"))
    expected_python = python_section.get("expected_strict_leaf_count")
    if expected_python != len(python_routes):
        raise AuthorityError(f"Python route count is {len(python_routes)}, manifest expects {expected_python}")

    bash_section = manifest.get("bash_shctx")
    if not isinstance(bash_section, dict) or "unsupported_pending_parity" in bash_section:
        raise AuthorityError("bash_shctx must use explicit retired disposition")
    bash_routes = manifest_routes(manifest, "bash_shctx", ("retired",))
    expected_bash = bash_section.get("expected_dispatch_group_count")
    if expected_bash != len(bash_routes):
        raise AuthorityError(f"Bash route count is {len(bash_routes)}, manifest expects {expected_bash}")

    launcher = repo_root / PUBLIC_LAUNCHER
    if not launcher.is_file() or not launcher.stat().st_mode & 0o111:
        raise AuthorityError("bin/shepherd must be an executable file")
    launcher_text = launcher.read_text(encoding="utf-8").lower()
    forbidden = [token for token in FORBIDDEN_LAUNCHER_TOKENS if token in launcher_text]
    if forbidden:
        raise AuthorityError(f"bin/shepherd contains forbidden fallback token(s): {', '.join(forbidden)}")
    if 'exec "$candidate" "$@"' not in launcher_text:
        raise AuthorityError("bin/shepherd must exec the resolved native binary")
    return len(python_routes), len(bash_routes), len(python_section["native"])


def _write_fixture(root: Path) -> Path:
    (root / "conformance").mkdir(parents=True)
    (root / "bin").mkdir()
    launcher = root / PUBLIC_LAUNCHER
    launcher.write_text('#!/bin/sh\nexec "$candidate" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    manifest = {
        "schema_version": 2,
        "python_typer": {"native": ["known"], "retired": ["old"], "expected_strict_leaf_count": 2},
        "bash_shctx": {"retired": ["old"], "expected_dispatch_group_count": 1},
    }
    path = root / "conformance" / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="shepherd-cli-authority-") as temp:
        root = Path(temp)
        manifest = _write_fixture(root)
        validate(root, manifest)

        python_root = root / "services" / "cli"
        python_root.mkdir(parents=True)
        (python_root / "pyproject.toml").write_text("[project.scripts]\nshepherd = 'legacy:main'\n", encoding="utf-8")
        try:
            validate(root, manifest)
        except AuthorityError:
            pass
        else:
            raise AuthorityError("self-test failed: reintroduced Python console script was accepted")

        (python_root / "pyproject.toml").unlink()
        python_root.rmdir()
        shctx = root / "skills" / "context" / "scripts" / "shctx"
        shctx.parent.mkdir(parents=True)
        shctx.write_text("#!/bin/sh\n", encoding="utf-8")
        shctx.chmod(0o755)
        try:
            validate(root, manifest)
        except AuthorityError:
            pass
        else:
            raise AuthorityError("self-test failed: reintroduced executable shctx was accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="test both retired CLI resurrection paths")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
            print("check-cli-authority: self-test OK")
        else:
            python_count, bash_count, native_count = validate(Path.cwd(), MANIFEST_PATH)
            print(f"check-cli-authority: OK (python-routes={python_count}, bash-routes={bash_count}, native={native_count})")
    except (AuthorityError, OSError, json.JSONDecodeError) as error:
        print(f"check-cli-authority: {error}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
