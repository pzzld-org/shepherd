#!/usr/bin/env python3
"""Prove that the Rust binary is the repository's only CLI authority.

The former Python Typer package and Bash ``shctx`` dispatcher are deleted.
Their route names remain in ``conformance/legacy-command-disposition.json`` as
an immutable retirement inventory, not as executable compatibility code.

The repo also carried a Bash compatibility launcher at ``bin/shepherd`` that
resolved and ``exec``'d the native binary. D4 retired it outright rather than
patch its resolution bug: it derived its search root from the unresolved
``BASH_SOURCE[0]``, so a symlinked install (e.g. ``~/.local/bin/shepherd``)
silently exited 127 instead of falling through PATH. The launcher's
PRESENCE is now the defect this gate checks for: the native binary reached
via PATH (or ``SHEPHERD_NATIVE_BIN``) is the sole CLI authority, and a
repo-tracked launcher can only reintroduce the same class of resolution bug.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path


MANIFEST_PATH = Path("conformance/legacy-command-disposition.json")

# `conformance/legacy-command-disposition.json`'s `retirement_contract.public_launcher`
# field names this exact same path as a historical retirement record -- the launcher
# that used to be the repo's public CLI entrypoint. `conformance/` belongs to a
# different lane and is read-only from here, so this gate deliberately does NOT parse
# that field back out of the manifest; it never did (the prior revision of this module
# hardcoded the identical literal without reading it either). This constant remains
# that independently-maintained literal -- both it and the manifest field are
# retirement records of the same deleted file, not a live contract between the two
# documents -- and the rule below inverts to assert the path's ABSENCE rather than
# requiring its presence.
PUBLIC_LAUNCHER = Path("bin/shepherd")
RETIRED_ROOTS = (Path("services/cli"), Path("skills/context/scripts"))


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
    if launcher.exists() or launcher.is_symlink():
        raise AuthorityError(
            f"{PUBLIC_LAUNCHER} must not exist: the compatibility launcher is retired (D4) "
            "and the native binary resolved from PATH/SHEPHERD_NATIVE_BIN is the sole CLI authority"
        )
    return len(python_routes), len(bash_routes), len(python_section["native"])


def _write_fixture(root: Path) -> Path:
    (root / "conformance").mkdir(parents=True)
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

        shctx.unlink()
        shctx.parent.rmdir()
        launcher = root / PUBLIC_LAUNCHER
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text('#!/bin/sh\nexec "$candidate" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
        try:
            validate(root, manifest)
        except AuthorityError:
            pass
        else:
            raise AuthorityError("self-test failed: reintroduced bin/shepherd launcher was accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="test all three retired-artifact resurrection paths")
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
