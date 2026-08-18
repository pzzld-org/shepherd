#!/usr/bin/env python3
"""check-workspace — enforce the invariants that keep a five-crate workspace coherent.

WHY THIS EXISTS.

Every rule below is currently true because someone held it in their head while
writing the manifests. That is precisely the kind of knowledge a sprint loses:
six sprints, several agents, and one of them adds `crates/foo` that compiles
fine, passes clippy, and is quietly outside the umbrella, outside the feature
matrix, and linting looser than every other member. Nothing fails. The drift is
only visible months later when someone asks why `shepherd::foo` does not exist.

So the rules are checked, not documented. Adding a member is mechanical, and
this script is what tells you which step you skipped.

Usage:
    scripts/check-workspace.sh              # check the workspace
    scripts/check-workspace.sh --self-test  # prove the checks can fail

`--self-test` matters as much as the checks. A validator with a typo'd key
name passes everything forever; each rule below is exercised against a
deliberately broken fixture before it is trusted against the real manifests.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The umbrella and the binary are the two crates with special standing; every
# other member is a capability library reached through the umbrella.
UMBRELLA = "shepherd-sdk"
UMBRELLA_DEPENDENCY = "shepherd"
BINARY = "shepherd-cli"
COMPONENT = "shepherd-component"

RETIRED_NAMESPACE_IGNORE = re.compile(
    r"^(?:\*\*/)?(?:"
    r"(?:logs|tmp)(?:/|\*|$)|"
    r"\.artifacts(?:/|$)|"
    r"\.shepherd/(?:root\.db|tmp|temp|logs|cache|memory|dispatch|discoveries|insights|pauses|snapshots|uploads)(?:/|\*|$)"
    r")"
)


class Failure(Exception):
    """A violated workspace invariant."""


def load(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def members(root: Path) -> dict[str, dict]:
    """Map crate name -> parsed manifest for every `crates/*`."""
    found = {}
    for manifest in sorted(root.glob("crates/*/Cargo.toml")):
        data = load(manifest)
        data["__dir__"] = manifest.parent
        found[data["package"]["name"]] = data
    return found


# --------------------------------------------------------------------------
# The invariants.
#
# Each takes (root, crates) and returns a list of human-readable violations.
# --------------------------------------------------------------------------


def rule_lints_inherited(root: Path, crates: dict[str, dict]) -> list[str]:
    """Every member inherits the workspace lint table.

    A member that omits this lints looser than the rest of the workspace, and
    nothing anywhere reports it. It is the quietest possible divergence.
    """
    bad = []
    for name, data in crates.items():
        if data.get("lints", {}).get("workspace") is not True:
            bad.append(f"{name}: missing `[lints]\\nworkspace = true`")
    return bad


def rule_version_inherited(root: Path, crates: dict[str, dict]) -> list[str]:
    """Every member inherits the workspace version.

    Members are published together and the umbrella pins each path dependency
    with an exact `version`. A member that sets its own drifts out of that pin
    and breaks publication, not compilation -- so it is invisible until release.
    """
    bad = []
    for name, data in crates.items():
        version = data["package"].get("version")
        if not (isinstance(version, dict) and version.get("workspace") is True):
            bad.append(f"{name}: `version` must be `version.workspace = true`")
    return bad


def rule_has_readme_and_description(root: Path, crates: dict[str, dict]) -> list[str]:
    """Every member documents what it is and why it is separate.

    The crate split is the architecture. A member with no README is a member
    whose boundary exists only in whoever drew it.
    """
    bad = []
    for name, data in crates.items():
        if not (data["__dir__"] / "README.md").is_file():
            bad.append(f"{name}: no README.md")
        if not data["package"].get("description"):
            bad.append(f"{name}: no `description`")
    return bad


def rule_docsrs_metadata(root: Path, crates: dict[str, dict]) -> list[str]:
    """Every member builds its docs.rs page from `full`.

    Without this, docs.rs renders default features only and every capability
    behind a flag is invisible to anyone reading the published documentation --
    which, for a crate whose whole surface is feature-gated, is most of it.
    """
    bad = []
    for name, data in crates.items():
        meta = data.get("package", {}).get("metadata", {}).get("docs", {}).get("rs", {})
        if meta.get("features") != ["full"]:
            bad.append(f"{name}: `[package.metadata.docs.rs]` must set `features = [\"full\"]`")
    return bad


def rule_libraries_reachable_from_umbrella(root: Path, crates: dict[str, dict]) -> list[str]:
    """Every library member is reachable through the umbrella.

    Locked decision 9: consumers link `shepherd` and nothing else. A member the
    umbrella does not re-export is a member no consumer can reach, which makes
    it dead weight that still costs compile time.
    """
    umbrella = crates.get(UMBRELLA)
    if umbrella is None:
        return [f"the umbrella crate `{UMBRELLA}` is missing from crates/"]

    bad = []
    if umbrella.get("lib", {}).get("name") != UMBRELLA_DEPENDENCY:
        bad.append(f"{UMBRELLA}: `[lib].name` must be `{UMBRELLA_DEPENDENCY}`")
    alias = load(root / "Cargo.toml").get("workspace", {}).get("dependencies", {}).get(
        UMBRELLA_DEPENDENCY, {}
    )
    if alias.get("package") != UMBRELLA:
        bad.append(
            f"workspace dependency `{UMBRELLA_DEPENDENCY}` must alias package `{UMBRELLA}`"
        )
    declared = set(umbrella.get("dependencies", {}))
    for name in crates:
        if name in (UMBRELLA, BINARY, COMPONENT):
            continue
        if name not in declared:
            bad.append(f"{name}: not a dependency of the `{UMBRELLA}` umbrella")
    return bad


def rule_binary_routes_through_umbrella(root: Path, crates: dict[str, dict]) -> list[str]:
    """The binary names the umbrella, never a member.

    This is the indirection that makes splitting a new layer out of the engine
    an internal refactor. The moment an adapter names `shepherd-core` directly,
    that property is gone and nobody gets an error saying so.
    """
    binary = crates.get(BINARY)
    if binary is None:
        return [f"the binary crate `{BINARY}` is missing from crates/"]

    bad = []
    for dep in binary.get("dependencies", {}):
        if dep.startswith("shepherd-"):
            bad.append(
                f"{BINARY}: depends on `{dep}` directly; adapters must route through `{UMBRELLA_DEPENDENCY}`"
            )
    return bad


def rule_one_binary(root: Path, crates: dict[str, dict]) -> list[str]:
    """Only the CLI crate ships an executable.

    A library that grows a `[[bin]]` has grown a delivery layer, which is the
    boundary the `engine-boundary` workflow exists to hold.
    """
    bad = []
    for name, data in crates.items():
        if name != BINARY and data.get("bin"):
            bad.append(f"{name}: declares a `[[bin]]`; only `{BINARY}` may")
    return bad


def rule_workspace_deps_are_ungated(root: Path, crates: dict[str, dict]) -> list[str]:
    """No `[workspace.dependencies]` entry hard-codes a feature it cannot unset.

    A feature enabled here cannot be turned off downstream, so a `no_std` or
    wasm flag that silently resolves to `std` anyway is worse than no flag at
    all. `derive` is a proc-macro and universal; `std`/`alloc`/`clock`/`use_std`
    are runtime surfaces and belong to each member's own feature graph.
    """
    root_manifest = load(root / "Cargo.toml")
    forbidden = {"std", "alloc", "clock", "use_std", "use_alloc"}
    bad = []
    for name, spec in root_manifest.get("workspace", {}).get("dependencies", {}).items():
        if not isinstance(spec, dict):
            continue
        offending = forbidden.intersection(spec.get("features", []))
        if offending:
            bad.append(
                f"workspace.dependencies.{name}: pins {sorted(offending)}; "
                "move it into the consuming member's `[features]` graph"
            )
    return bad


def rule_members_in_feature_matrix(root: Path, crates: dict[str, dict]) -> list[str]:
    """Every member appears in the feature-matrix script.

    `cargo check --workspace` builds exactly one combination. A member absent
    from `check-features.sh` has every flag past its defaults unverified, which
    is the state the whole script exists to end.
    """
    script = root / "scripts" / "check-features.sh"
    if not script.is_file():
        return ["scripts/check-features.sh is missing"]

    body = script.read_text()
    bad = []
    for name in crates:
        short = name.removeprefix("shepherd-")
        if not re.search(rf"-p\s+{re.escape(name)}\b", body):
            bad.append(
                f"{name}: no `-p {name}` invocation in scripts/check-features.sh "
                f"(add a row for the `{short}` member)"
            )
    return bad


def rule_component_contract(root: Path, crates: dict[str, dict]) -> list[str]:
    """The WASI Preview 2 component has a checked WIT package boundary.

    A component crate that merely compiles a raw wasm module is not enough for
    hosts: the package metadata, WIT source, and contract tests must travel
    together so release tooling can validate and extract the interface.
    """
    component = crates.get(COMPONENT)
    if component is None:
        return [f"the component crate `{COMPONENT}` is missing"]
    bad = []
    if component.get("package", {}).get("publish") is not False:
        bad.append(f"{COMPONENT}: must set `publish = false`")
    metadata = component.get("package", {}).get("metadata", {}).get("component", {})
    if metadata.get("package") != "fl03:shepherd":
        bad.append(f"{COMPONENT}: package metadata must set component package to `fl03:shepherd`")
    directory = component["__dir__"]
    wit = directory / "wit" / "shepherd.wit"
    if not wit.is_file():
        bad.append(f"{COMPONENT}: missing wit/shepherd.wit")
    elif "package fl03:shepherd@6.4.7;" not in wit.read_text():
        bad.append(f"{COMPONENT}: WIT package/version does not match the workspace")
    tests = directory / "tests" / "component.rs"
    if not tests.is_file():
        bad.append(f"{COMPONENT}: missing component contract tests")
    return bad


def rule_retired_namespaces_are_visible(root: Path, crates: dict[str, dict]) -> list[str]:
    """Git must expose every reintroduced retired Shepherd namespace.

    Ignoring a retired root makes a duplicate authority invisible to both the
    operator and the layout migration. Canonical registry files and transient
    state below `.shepherd/runs/<run>` remain separately allowlisted.
    """
    ignore = root / ".gitignore"
    if not ignore.is_file():
        return [".gitignore is missing"]

    bad = []
    for line_number, raw in enumerate(ignore.read_text(encoding="utf-8").splitlines(), 1):
        pattern = raw.strip()
        if not pattern or pattern.startswith(("#", "!")):
            continue
        if RETIRED_NAMESPACE_IGNORE.match(pattern):
            bad.append(
                f".gitignore:{line_number}: retired namespace must stay visible: {pattern}"
            )
    return bad


def rule_msrv_is_consistent(root: Path, crates: dict[str, dict]) -> list[str]:
    """clippy.toml, the workspace `rust-version`, and the pinned toolchain agree.

    clippy consults `clippy.toml`'s `msrv` to suppress the `manual_*` and
    `incompatible_msrv` families, so a value below the real floor silently
    disables every modernization lint stabilized in between. Nothing else
    reads all three files, which is how `msrv` sat five minors behind the
    workspace without turning any build red.
    """
    manifest = load(root / "Cargo.toml")
    declared = manifest.get("workspace", {}).get("package", {}).get("rust-version")
    if not declared:
        return ["Cargo.toml: workspace.package.rust-version is missing"]

    bad = []
    clippy = root / "clippy.toml"
    if clippy.is_file():
        msrv = load(clippy).get("msrv")
        if msrv != declared:
            bad.append(f"clippy.toml: msrv `{msrv}` must match workspace rust-version `{declared}`")

    toolchain = root / "rust-toolchain.toml"
    if toolchain.is_file():
        channel = load(toolchain).get("toolchain", {}).get("channel")
        if channel != declared:
            bad.append(
                f"rust-toolchain.toml: channel `{channel}` must match "
                f"workspace rust-version `{declared}`"
            )
    return bad


RULES = [
    rule_lints_inherited,
    rule_version_inherited,
    rule_has_readme_and_description,
    rule_docsrs_metadata,
    rule_libraries_reachable_from_umbrella,
    rule_binary_routes_through_umbrella,
    rule_one_binary,
    rule_workspace_deps_are_ungated,
    rule_members_in_feature_matrix,
    rule_component_contract,
    rule_retired_namespaces_are_visible,
    rule_msrv_is_consistent,
]


def run(root: Path) -> int:
    crates = members(root)
    if not crates:
        print("::error::no members found under crates/")
        return 1

    print(f"checking {len(crates)} workspace members: {', '.join(sorted(crates))}\n")

    failures = 0
    for rule in RULES:
        label = rule.__name__.removeprefix("rule_").replace("_", " ")
        violations = rule(root, crates)
        if violations:
            failures += len(violations)
            print(f"  {label:<44} FAILED")
            for violation in violations:
                print(f"      {violation}")
        else:
            print(f"  {label:<44} ok")

    print()
    if failures:
        print(f"::error::{failures} workspace invariant(s) violated.")
        print("Adding a member is mechanical; see crates/sdk/README.md 'Adding a member'.")
        return 1
    print(f"ok: all {len(RULES)} workspace invariants hold.")
    return 0


# --------------------------------------------------------------------------
# Self-test.
#
# Each rule is run against a fixture that violates it. A rule that cannot fail
# is a rule that is not checking anything, and it would pass silently forever.
# --------------------------------------------------------------------------

FIXTURES = {
    rule_lints_inherited: {
        "shepherd-sdk": {"package": {"name": "shepherd-sdk"}, "__dir__": Path("/nonexistent")},
    },
    rule_version_inherited: {
        "shepherd-core": {
            "package": {"name": "shepherd-core", "version": "6.4.7"},
            "lints": {"workspace": True},
            "__dir__": Path("/nonexistent"),
        },
    },
    rule_has_readme_and_description: {
        "shepherd-core": {
            "package": {"name": "shepherd-core"},
            "__dir__": Path("/nonexistent"),
        },
    },
    rule_docsrs_metadata: {
        "shepherd-core": {
            "package": {"name": "shepherd-core", "metadata": {"docs": {"rs": {}}}},
            "__dir__": Path("/nonexistent"),
        },
    },
    rule_libraries_reachable_from_umbrella: {
        "shepherd-sdk": {
            "package": {"name": "shepherd-sdk"},
            "lib": {},
            "dependencies": {},
            "__dir__": Path("/x"),
        },
        "shepherd-orphan": {"package": {"name": "shepherd-orphan"}, "__dir__": Path("/x")},
    },
    rule_binary_routes_through_umbrella: {
        "shepherd-cli": {
            "package": {"name": "shepherd-cli"},
            "dependencies": {"shepherd-core": {}},
            "__dir__": Path("/x"),
        },
    },
    rule_one_binary: {
        "shepherd-core": {
            "package": {"name": "shepherd-core"},
            "bin": [{"name": "sneaky"}],
            "__dir__": Path("/x"),
        },
    },
    rule_members_in_feature_matrix: {
        "shepherd-nowhere": {"package": {"name": "shepherd-nowhere"}, "__dir__": Path("/x")},
    },
    rule_component_contract: {
        "shepherd-component": {
            "package": {"name": "shepherd-component", "metadata": {}},
            "__dir__": Path("/nonexistent"),
        },
    },
}


def self_test(root: Path) -> int:
    print("self-test: every rule must be able to fail\n")
    failures = 0

    for rule, fixture in FIXTURES.items():
        label = rule.__name__.removeprefix("rule_").replace("_", " ")
        violations = rule(root, fixture)
        if violations:
            print(f"  {label:<44} fails as designed")
        else:
            print(f"  {label:<44} DID NOT FAIL on a broken fixture")
            failures += 1

    # rule_workspace_deps_are_ungated reads the real root manifest rather than
    # the crate map, so it needs a fixture root of its own rather than a dict.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp)
        (broken / "Cargo.toml").write_text(
            '[workspace.dependencies]\nchrono = { version = "0.4", features = ["std"] }\n'
        )
        label = "workspace deps are ungated"
        if rule_workspace_deps_are_ungated(broken, {}):
            print(f"  {label:<44} fails as designed")
        else:
            print(f"  {label:<44} DID NOT FAIL on a broken fixture")
            failures += 1

    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp)
        (broken / ".gitignore").write_text(
            ".shepherd/cache/\n**/.artifacts/logs/\n**/logs/\n**/tmp/\n", encoding="utf-8"
        )
        label = "retired namespaces are visible"
        if len(rule_retired_namespaces_are_visible(broken, {})) == 4:
            print(f"  {label:<44} fails as designed")
        else:
            print(f"  {label:<44} DID NOT FAIL on a broken fixture")
            failures += 1

    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp)
        (broken / "Cargo.toml").write_text(
            '[workspace.package]\nrust-version = "1.97.0"\n', encoding="utf-8"
        )
        (broken / "clippy.toml").write_text('msrv = "1.91.0"\n', encoding="utf-8")
        label = "msrv is consistent"
        if rule_msrv_is_consistent(broken, {}):
            print(f"  {label:<44} fails as designed")
        else:
            print(f"  {label:<44} DID NOT FAIL on a broken fixture")
            failures += 1

    print()
    if failures:
        print(f"::error::{failures} rule(s) cannot detect their own violation.")
        return 1
    print("ok: every rule is falsifiable.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test(ROOT))
    raise SystemExit(run(ROOT))
