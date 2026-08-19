#!/usr/bin/env python3
"""Publish the four npm adapter tarballs, idempotently, in dependency order.

WHY THIS EXISTS.

There has never been an `npm publish` anywhere in this repository's CI. The
release pipeline runs `npm pack`, attaches the four tarballs to the GitHub
release, and stops. `@pzzld/pi-shepherd` and `@pzzld/component-runtime` were
published by hand once at 6.4.5 and never again; `@pzzld/claude-shepherd` and
`@pzzld/codex-shepherd` have never been published at all. Seven releases
(6.4.6 through 6.5.1) shipped crates to crates.io and nothing to npm.

The visible cost: `pi install npm:@pzzld/pi-shepherd` installs 6.4.5, which
predates the `pi` key in package.json and is inert on Pi.

WHAT THIS PUBLISHES.

The EXACT tarballs `cargo-build.yml` already produced and verified -- never a
rebuild. A rebuild here would be a second construction path for bytes that were
already checksummed and attached to the release, and the two would drift.
`npm publish <file>.tgz` takes the archive directly, so the published bytes are
the release bytes.

IDEMPOTENCE.

An npm version is immutable and not reissuable, exactly like a crates.io
version. Publishing an already-published version must be a no-op, not a failure,
so a partial run can be resumed: the registry is consulted per package first and
already-present versions are skipped. That makes this safe to re-run after a
network failure halfway through.

DEPENDENCY ORDER.

`component-runtime` first: the three harness adapters each depend on it at an
exact pinned version, and publishing an adapter whose dependency is not yet
resolvable leaves a broken package installable.

Run with --self-test to prove the checks can fail.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

# The one package every adapter depends on. It must publish first, or an
# adapter lands whose exact-pinned dependency is not yet resolvable.
#
# Everything else is DISCOVERED from the tarballs, never listed here. The
# directory names and the published names differ -- packages/harness-claude
# publishes as @pzzld/claude-shepherd -- so a hardcoded list is a second source of
# truth that is wrong the moment either side is renamed. It already was: the
# first version of this file assumed the directory names and resolved zero of
# the three adapters.
ROOT_PACKAGE = "@pzzld/component-runtime"

class RegistryUnavailable(RuntimeError):
    """The registry could not be consulted, so idempotence cannot be established."""


# A new scoped package can take minutes to surface on the public endpoint.
VERIFY_ATTEMPTS = 10
VERIFY_INTERVAL_SECONDS = 20

REGISTRY = "https://registry.npmjs.org"
USER_AGENT = "shepherd-npm-publish (+https://github.com/pzzld-org/shepherd)"


def discover(directory: pathlib.Path, version: str) -> list[tuple[str, pathlib.Path]]:
    """Find every @pzzld tarball in `directory`, ordered for publication.

    Identity comes from the manifest inside each archive, never the filename.
    """
    found: list[tuple[str, pathlib.Path]] = []
    for tarball in sorted(directory.glob("*.tgz")):
        try:
            name, packed = version_in_tarball(tarball)
        except (KeyError, ValueError, tarfile.TarError):
            continue
        if not name.startswith("@pzzld/"):
            continue
        if packed != version:
            raise ValueError(
                f"{tarball.name} contains {name}@{packed}, expected version {version}"
            )
        found.append((name, tarball))
    # Root first, the rest in a stable order.
    found.sort(key=lambda entry: (entry[0] != ROOT_PACKAGE, entry[0]))
    return found


def version_in_tarball(tarball: pathlib.Path) -> tuple[str, str]:
    """Read name and version from the archive itself, not from the filename.

    The filename is a convention; the manifest inside is the authority. A
    tarball whose name says one version and whose manifest says another would
    otherwise publish silently under the wrong number.
    """
    with tarfile.open(tarball, "r:gz") as archive:
        member = archive.extractfile("package/package.json")
        if member is None:
            raise ValueError(f"{tarball.name}: no package/package.json inside")
        manifest = json.loads(member.read().decode("utf-8"))
    return manifest["name"], manifest["version"]


def already_published(name: str, version: str) -> bool:
    """True when the registry already serves this exact version."""
    request = urllib.request.Request(
        f"{REGISTRY}/{name.replace('/', '%2f')}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            document = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False  # never published at all
        raise RegistryUnavailable(f"{name}: registry returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        # FAIL CLOSED, and say why. Without a registry answer this run cannot
        # tell "already published" from "not yet", and a traceback here reads
        # as a code defect when it is almost always a network or CA-trust
        # problem on the host.
        raise RegistryUnavailable(f"{name}: cannot reach {REGISTRY}: {error}") from error
    return version in (document.get("versions") or {})


def publish(tarball: pathlib.Path, dry_run: bool) -> None:
    command = ["npm", "publish", str(tarball), "--access", "public"]
    if dry_run:
        command.append("--dry-run")
    subprocess.run(command, check=True)


def run(directory: pathlib.Path, version: str, confirm: bool, dry_run: bool) -> int:
    if not directory.is_dir():
        print(f"FAIL: asset directory does not exist: {directory}", file=sys.stderr)
        return 1

    try:
        planned = discover(directory, version)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    if not any(name == ROOT_PACKAGE for name, _ in planned):
        print(
            f"FAIL: {ROOT_PACKAGE} is not among the tarballs in {directory}; every adapter\n"
            f"      pins it exactly, so publishing without it lands broken packages.",
            file=sys.stderr,
        )
        return 1

    # STATE THE COUNT AND FAIL ON ZERO. A publisher that finds nothing and exits
    # 0 is indistinguishable from one that published everything.
    if not planned:
        print("FAIL: resolved zero packages to publish", file=sys.stderr)
        return 1
    print(f"resolved {len(planned)} tarball(s) for version {version}")

    published, skipped = 0, 0
    for name, tarball in planned:
        try:
            present = already_published(name, version)
        except RegistryUnavailable as error:
            print(
                f"FAIL: {error}\n"
                f"      Publication is not attempted when the registry cannot be consulted:\n"
                f"      an npm version is immutable, so this run must know what already\n"
                f"      exists before it uploads anything.",
                file=sys.stderr,
            )
            return 1
        if present:
            print(f"  skip     {name}@{version} (already on the registry)")
            skipped += 1
            continue
        if not confirm:
            print(f"  would publish {name}@{version} from {tarball.name}")
            continue
        print(f"  publish  {name}@{version} from {tarball.name}")
        publish(tarball, dry_run)
        published += 1

    if not confirm:
        print(f"plan only: {len(planned) - skipped} to publish, {skipped} already present")
        return 0

    # VERIFY, DO NOT TRUST THE EXIT CODE.
    #
    # `npm publish` returned 0 for two brand-new package names that were never
    # created, and this script duly reported "4 published". Exit status is a
    # claim about the command; the registry is the fact. A publisher that
    # believes the claim reports a green release over an empty registry, which
    # is precisely how the adapter rename appeared to ship and did not.
    # POLL, do not check once. A brand-new scoped package does not appear on the
    # public registry endpoint immediately -- claude-shepherd and codex-shepherd
    # both read 404 for several minutes after a successful publish, which a
    # single check would report as a failed release. Retry with a bounded
    # ceiling so lag is tolerated and a genuine no-op still fails.
    missing = []
    for name, _ in planned:
        for attempt in range(VERIFY_ATTEMPTS):
            try:
                if already_published(name, version):
                    break
            except RegistryUnavailable as error:
                print(f"FAIL: cannot verify publication: {error}", file=sys.stderr)
                return 1
            if attempt + 1 < VERIFY_ATTEMPTS:
                print(f"  waiting for {name}@{version} to appear "
                      f"({attempt + 1}/{VERIFY_ATTEMPTS})")
                time.sleep(VERIFY_INTERVAL_SECONDS)
        else:
            missing.append(name)
    if missing:
        print(
            f"FAIL: npm reported success but {len(missing)} package(s) are absent "
            f"from the registry:\n"
            + "".join(f"  {name}@{version}\n" for name in missing)
            + "      This is checked with a bounded retry, so it is not registry lag.\n"
            "      A brand-new package name needs a token permitted to CREATE\n"
            "      packages in the scope; a token scoped to existing packages can\n"
            "      exit 0 without publishing.",
            file=sys.stderr,
        )
        return 1

    print(
        f"npm-publish: {published} published, {skipped} already present, "
        f"{len(planned)} total, all verified present on the registry"
    )
    return 0


def self_test() -> int:
    """The checks must be able to fail."""
    cases = 0
    with tempfile.TemporaryDirectory() as tmp:
        directory = pathlib.Path(tmp)

        # An empty directory must fail, not silently publish nothing.
        cases += 1
        if run(directory, "9.9.9", confirm=False, dry_run=True) == 0:
            print("FAIL self-test: an empty asset directory was accepted", file=sys.stderr)
            return 1

        # Build a tarball whose INNER manifest disagrees with its filename.
        cases += 1
        staging = directory / "package"
        staging.mkdir()
        (staging / "package.json").write_text(
            json.dumps({"name": "@pzzld/component-runtime", "version": "0.0.1"})
        )
        mismatched = directory / "pzzld-component-runtime-9.9.9.tgz"
        with tarfile.open(mismatched, "w:gz") as archive:
            archive.add(staging / "package.json", arcname="package/package.json")
        if run(directory, "9.9.9", confirm=False, dry_run=True) == 0:
            print(
                "FAIL self-test: a tarball whose manifest version disagrees with its "
                "filename was accepted",
                file=sys.stderr,
            )
            return 1

        # A set of adapters with no component-runtime must fail: they all pin it.
        cases += 1
        mismatched.unlink()
        (staging / "package.json").write_text(
            json.dumps({"name": "@pzzld/pi-shepherd", "version": "9.9.9"})
        )
        orphan = directory / "pzzld-pi-shepherd-9.9.9.tgz"
        with tarfile.open(orphan, "w:gz") as archive:
            archive.add(staging / "package.json", arcname="package/package.json")
        if run(directory, "9.9.9", confirm=False, dry_run=True) == 0:
            print(
                "FAIL self-test: adapters without @pzzld/component-runtime were accepted",
                file=sys.stderr,
            )
            return 1
        orphan.unlink()

        # A nonexistent directory must fail.
        cases += 1
        if run(directory / "absent", "9.9.9", confirm=False, dry_run=True) == 0:
            print("FAIL self-test: a missing asset directory was accepted", file=sys.stderr)
            return 1

    print(f"npm-publish: self-test OK ({cases} cases passed)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=pathlib.Path, help="directory holding the packed tarballs")
    parser.add_argument("--version", help="exact MAJOR.MINOR.PATCH being released")
    parser.add_argument("--confirm", action="store_true", help="actually publish")
    parser.add_argument("--dry-run", action="store_true", help="pass --dry-run to npm publish")
    parser.add_argument("--self-test", action="store_true", help="prove the checks can fail")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.assets or not args.version:
        parser.error("--assets and --version are required unless --self-test is given")
    return run(args.assets, args.version, args.confirm, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
