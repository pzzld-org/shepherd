#!/usr/bin/env python3
"""check-plugin — the plugin layout is an interface contract, so check it.

WHY THIS EXISTS.

On 2026-08-12 the `hooks/`, `skills/` and `docs/` trees were moved under
`src/`. Nothing complained. `claude plugin validate` reported "Validation
passed" on the broken tree, because it checks manifest *shape* and never looks
inside `hooks/hooks.json` at the `command` strings. The live session kept
working too, because the running plugin is the cached install of the previous
release, not the working tree.

So the breakage was total and completely silent: 43 hook registrations pointing
at scripts that no longer existed, 7 skills nothing would discover, 17 gate
tests red, and the release pipeline quietly skipping its SKILL.md version bump
forever. It surfaces at publish time, on users, with no CI signal in between.

The plugin root layout is an interface contract with the harness, not a
repository-organisation preference. This checks it.

Usage:
    scripts/check-plugin.sh              # check the contract
    scripts/check-plugin.sh --self-test  # prove the checks can fail
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Discovery is by convention at the plugin ROOT. `plugin.json` may override
# `skills`/`hooks`/`agents` with explicit paths, but note the trap
# that makes an override a poor substitute for the convention: per the plugin
# reference, `${CLAUDE_PLUGIN_ROOT}` is "the plugin's installation directory",
# i.e. the ROOT -- relocating hooks.json does NOT re-base the paths inside it.
COMPONENT_DIRS = ("agents", "skills", "hooks")
CARRIER_LINKS = {
    "hooks/hooks.json": "../../../hooks/hooks.json",
    "agents": "../../agents",
    "skills": "../../skills",
}

PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s)\\]+)")


def rule_component_dirs_are_at_the_root(root: Path) -> list[str]:
    """`agents/`, `skills/` and `hooks/` live at the plugin root.

    A component directory elsewhere is not discovered, and nothing says so.
    """
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    bad = []
    for name in COMPONENT_DIRS:
        if (root / name).is_dir():
            continue
        # An explicit manifest override is the only other legal home.
        if name in manifest:
            continue
        bad.append(
            f"{name}/ is not at the plugin root and plugin.json declares no "
            f'"{name}" override — it will not be discovered'
        )
    return bad


def rule_retired_command_surface_is_absent(root: Path) -> list[str]:
    """Slash-command wrappers may not recreate a second workflow authority."""
    commands = root / "commands"
    if not commands.is_dir():
        return []
    files = sorted(path.relative_to(root).as_posix() for path in commands.rglob("*") if path.is_file())
    return [f"{path} recreates the retired slash-command authority" for path in files]


def rule_hooks_json_is_discoverable(root: Path) -> list[str]:
    """`hooks/hooks.json` exists at the default location, or is declared."""
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    if (root / "hooks" / "hooks.json").is_file():
        return []
    if "hooks" in manifest:
        return []
    return [
        "hooks/hooks.json is missing and plugin.json declares no \"hooks\" "
        "override — every hook registration is inert"
    ]


def _hook_files(root: Path) -> list[Path]:
    found = [root / "hooks" / "hooks.json"]
    return [p for p in found if p.is_file()]


def rule_hook_commands_resolve(root: Path) -> list[str]:
    """Every `${CLAUDE_PLUGIN_ROOT}/...` in hooks.json points at a real file.

    This is the check that was missing. `claude plugin validate` parses
    hooks.json as JSON and stops; it never opens the `command` strings, so a
    hook wired to a deleted script validates clean and fails at runtime.
    """
    bad = []
    for path in _hook_files(root):
        for ref in sorted(set(PLUGIN_ROOT_REF.findall(path.read_text()))):
            target = root / ref
            if not target.exists():
                bad.append(f"{path.relative_to(root)} -> {ref} does not exist")
            elif target.is_file() and not target.stat().st_mode & 0o111:
                bad.append(f"{path.relative_to(root)} -> {ref} is not executable")
    return bad


def rule_plugin_root_refs_resolve(root: Path) -> list[str]:
    """`${CLAUDE_PLUGIN_ROOT}/...` resolves everywhere it appears, not just hooks.

    Agent and skill bodies reference scripts by the same variable. A stale one
    sends an agent to a path that does not exist, mid-sprint.
    """
    bad = []
    scan = ["agents", "commands", "skills", "hooks", "scripts", "bin", "docs"]
    for directory in scan:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix in {".png", ".jpg", ".db"}:
                continue
            # This file carries deliberately-broken paths in its own self-test
            # fixtures. Scanning it finds them and reports the checker as the
            # violation, which is true and useless.
            if path.resolve() == Path(__file__).resolve():
                continue
            try:
                body = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for ref in sorted(set(PLUGIN_ROOT_REF.findall(body))):
                # Trailing punctuation from prose is not part of the path.
                cleaned = ref.rstrip(".,;:`")
                # Globs and `{placeholder}` templates are patterns, not paths.
                # `skills/context/styles/{profile}.md` is documentation of a
                # naming convention, not a file anyone expects to exist.
                if any(ch in cleaned for ch in "*?<>{}"):
                    continue
                if not (root / cleaned).exists():
                    bad.append(f"{path.relative_to(root)} -> {cleaned} does not exist")
    return bad


def rule_skills_are_shaped_correctly(root: Path) -> list[str]:
    """Every skill is `skills/<name>/SKILL.md`."""
    skills = root / "skills"
    if not skills.is_dir():
        return ["skills/ is missing"]
    bad = []
    found = 0
    for child in sorted(skills.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").is_file():
            found += 1
        else:
            bad.append(f"skills/{child.name}/ has no SKILL.md")
    if found == 0:
        bad.append("skills/ contains no <name>/SKILL.md — nothing to discover")
    return bad


def rule_generated_skills_are_thin(root: Path) -> list[str]:
    """Root skill carriers contain one generated entrypoint and no doctrine copy.

    Authored skill content lives under ``content/`` and the Rust compiler emits
    the harness carrier. Extra references, schemas, scripts, or examples here
    silently create a second authority and expand every installed plugin.
    """
    skills = root / "skills"
    if not skills.is_dir():
        return ["skills/ is missing"]
    bad = []
    for child in sorted(skills.iterdir()):
        if not child.is_dir():
            continue
        extras = sorted(
            path.relative_to(child).as_posix()
            for path in child.rglob("*")
            if path.is_file() and path.name != "SKILL.md"
        )
        for extra in extras:
            bad.append(
                f"skills/{child.name}/{extra} is a second carrier authority; "
                "root skills may contain only SKILL.md"
            )
    return bad


def rule_thin_carrier_projects_canonical_content(root: Path) -> list[str]:
    """The marketplace carrier keeps one manifest projection and three links.

    Claude's strict marketplace validator requires a regular manifest, while
    the loader dereferences within-marketplace links for the remaining plugin
    content. The manifest must therefore stay byte-identical to the canonical
    root manifest and the carrier must not acquire a Node/npm bootstrap.
    """
    carrier = root / "plugins" / "shepherd"
    canonical_manifest = root / ".claude-plugin" / "plugin.json"
    carrier_manifest = carrier / ".claude-plugin" / "plugin.json"
    bad = []
    if not carrier_manifest.is_file() or carrier_manifest.is_symlink():
        bad.append("plugins/shepherd/.claude-plugin/plugin.json must be a regular file")
    elif not canonical_manifest.is_file():
        bad.append(".claude-plugin/plugin.json is missing")
    elif carrier_manifest.read_bytes() != canonical_manifest.read_bytes():
        bad.append(
            "plugins/shepherd/.claude-plugin/plugin.json must be byte-identical to "
            ".claude-plugin/plugin.json"
        )

    for relative, target in CARRIER_LINKS.items():
        path = carrier / relative
        if not path.is_symlink():
            bad.append(f"plugins/shepherd/{relative} must be a canonical symlink")
            continue
        if path.readlink().as_posix() != target:
            bad.append(f"plugins/shepherd/{relative} must link to {target}")
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            bad.append(f"plugins/shepherd/{relative} escapes the repository")

    for forbidden in ("package.json", "package-lock.json", "node_modules"):
        if (carrier / forbidden).exists():
            bad.append(f"plugins/shepherd/{forbidden} is forbidden in the thin carrier")
    return bad


def rule_configured_gates_resolve(root: Path) -> list[str]:
    """Paths named by `.shepherd/shepherd.toml` gate commands exist.

    The sprint gate is configuration, so a moved directory turns it into a
    command that fails on every run rather than a check that reports.
    """
    config = root / ".shepherd" / "shepherd.toml"
    if not config.is_file():
        return []
    with config.open("rb") as handle:
        data = tomllib.load(handle)

    bad = []
    # Gate commands live under [gates] / [checks]; scan every string value.
    def walk(node, trail):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{trail}.{key}" if trail else key)
        elif isinstance(node, str):
            for token in node.split():
                token = token.strip("\"'")
                if "/" not in token or token.startswith("-"):
                    continue
                head = token.split("/")[0]
                if head not in (*COMPONENT_DIRS, "scripts", "services", "bin", "docs"):
                    continue
                if not (root / token).exists():
                    bad.append(f".shepherd/shepherd.toml [{trail}] -> {token} does not exist")

    walk(data, "")
    return bad


RULES = [
    rule_component_dirs_are_at_the_root,
    rule_retired_command_surface_is_absent,
    rule_hooks_json_is_discoverable,
    rule_hook_commands_resolve,
    rule_plugin_root_refs_resolve,
    rule_skills_are_shaped_correctly,
    rule_generated_skills_are_thin,
    rule_thin_carrier_projects_canonical_content,
    rule_configured_gates_resolve,
]


def run(root: Path) -> int:
    print("checking the plugin layout contract\n")
    failures = 0
    for rule in RULES:
        label = rule.__name__.removeprefix("rule_").replace("_", " ")
        violations = rule(root)
        if violations:
            failures += len(violations)
            print(f"  {label:<44} FAILED")
            for violation in violations[:20]:
                print(f"      {violation}")
            if len(violations) > 20:
                print(f"      ... and {len(violations) - 20} more")
        else:
            print(f"  {label:<44} ok")

    print()
    if failures:
        print(f"::error::{failures} plugin contract violation(s).")
        print("Component directories are discovered by convention at the plugin")
        print("ROOT. Note that ${CLAUDE_PLUGIN_ROOT} is the plugin root itself,")
        print("so relocating hooks.json does NOT re-base the paths inside it.")
        return 1
    print(f"ok: all {len(RULES)} plugin contract rules hold.")
    return 0


def self_test(root: Path) -> int:
    """Every rule must fail on a tree that violates it.

    Built by copying the real layout into a temp dir and breaking one thing at
    a time — the same move that broke the plugin for real.
    """
    import shutil
    import tempfile

    print("self-test: every rule must be able to fail\n")
    failures = 0

    def fixture(mutate) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".claude-plugin").mkdir()
        (tmp / ".claude-plugin" / "plugin.json").write_text('{"name":"shepherd"}')
        for name in COMPONENT_DIRS:
            (tmp / name).mkdir()
        (tmp / "hooks" / "hooks.json").write_text('{"hooks":{}}')
        (tmp / "skills" / "demo").mkdir()
        (tmp / "skills" / "demo" / "SKILL.md").write_text("# demo")
        carrier = tmp / "plugins" / "shepherd"
        (carrier / ".claude-plugin").mkdir(parents=True)
        (carrier / ".claude-plugin" / "plugin.json").write_bytes(
            (tmp / ".claude-plugin" / "plugin.json").read_bytes()
        )
        (carrier / "hooks").mkdir()
        (carrier / "hooks" / "hooks.json").symlink_to("../../../hooks/hooks.json")
        (carrier / "agents").symlink_to("../../agents")
        (carrier / "skills").symlink_to("../../skills")
        mutate(tmp)
        return tmp

    def broken_move(tmp: Path) -> None:
        # Exactly the real failure: components relocated under src/.
        (tmp / "src").mkdir()
        for name in ("hooks", "skills"):
            shutil.move(str(tmp / name), str(tmp / "src" / name))

    def dangling_hook(tmp: Path) -> None:
        (tmp / "hooks" / "hooks.json").write_text(
            '{"PreToolUse":[{"command":"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/gone.sh"}]}'
        )

    def duplicate_command_authority(tmp: Path) -> None:
        (tmp / "commands").mkdir()
        (tmp / "commands" / "start.md").write_text("duplicate workflow")

    def skill_without_body(tmp: Path) -> None:
        (tmp / "skills" / "empty").mkdir()

    def stale_plugin_root_ref(tmp: Path) -> None:
        (tmp / "agents").mkdir(exist_ok=True)
        (tmp / "agents" / "a.md").write_text("run ${CLAUDE_PLUGIN_ROOT}/skills/gone/SKILL.md")

    def duplicate_skill_authority(tmp: Path) -> None:
        (tmp / "skills" / "demo" / "references").mkdir()
        (tmp / "skills" / "demo" / "references" / "doctrine.md").write_text("duplicate")

    def carrier_manifest_drift(tmp: Path) -> None:
        (tmp / "plugins" / "shepherd" / ".claude-plugin" / "plugin.json").write_text(
            '{"name":"drifted"}'
        )

    def broken_gate(tmp: Path) -> None:
        (tmp / ".shepherd").mkdir()
        (tmp / ".shepherd" / "shepherd.toml").write_text(
            '[gates]\ncheck = "jq empty hooks/gone.json"\n'
        )

    cases = [
        (rule_component_dirs_are_at_the_root, broken_move),
        (rule_retired_command_surface_is_absent, duplicate_command_authority),
        (rule_hooks_json_is_discoverable, broken_move),
        (rule_hook_commands_resolve, dangling_hook),
        (rule_plugin_root_refs_resolve, stale_plugin_root_ref),
        (rule_skills_are_shaped_correctly, skill_without_body),
        (rule_generated_skills_are_thin, duplicate_skill_authority),
        (rule_thin_carrier_projects_canonical_content, carrier_manifest_drift),
        (rule_configured_gates_resolve, broken_gate),
    ]

    for rule, mutate in cases:
        label = rule.__name__.removeprefix("rule_").replace("_", " ")
        tmp = fixture(mutate)
        try:
            if rule(tmp):
                print(f"  {label:<44} fails as designed")
            else:
                print(f"  {label:<44} DID NOT FAIL on a broken fixture")
                failures += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

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
