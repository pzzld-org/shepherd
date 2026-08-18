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
CODEX_MARKETPLACE = Path(".agents/plugins/marketplace.json")
CODEX_CARRIER = Path("plugins/shepherd/codex")

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


def rule_codex_carrier_is_regular_and_canonical(root: Path) -> list[str]:
    """Codex copies regular files only, so its projection must close without links."""
    bad = []
    marketplace_path = root / CODEX_MARKETPLACE
    carrier = root / "plugins" / "shepherd"
    manifest_path = carrier / ".codex-plugin" / "plugin.json"
    if not marketplace_path.is_file():
        return [f"{CODEX_MARKETPLACE} is missing"]
    marketplace = json.loads(marketplace_path.read_text())
    expected_source = {"source": "local", "path": "./plugins/shepherd"}
    plugins = marketplace.get("plugins", [])
    if len(plugins) != 1 or plugins[0].get("source") != expected_source:
        bad.append(f"{CODEX_MARKETPLACE} must expose one local ./plugins/shepherd source")
    if not manifest_path.is_file() or manifest_path.is_symlink():
        bad.append("plugins/shepherd/.codex-plugin/plugin.json must be a regular file")
        return bad
    manifest = json.loads(manifest_path.read_text())
    canonical = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    if manifest.get("version") != canonical.get("version"):
        bad.append("Claude and Codex plugin manifest versions must match")
    if manifest.get("skills") != "./codex/skills/":
        bad.append("Codex manifest skills must be ./codex/skills/")
    if manifest.get("hooks") != "./codex/hooks/hooks.json":
        bad.append("Codex manifest hooks must be ./codex/hooks/hooks.json")
    # RECONCILIATION.md is doctrine, and doctrine that miscounts its own corpus
    # is doctrine nobody can check against. It claimed "seven portable workflow
    # skills" while nine existed, and two content files cited "row N" of a
    # document that has no rows.
    reconciliation = root / "content" / "RECONCILIATION.md"
    if reconciliation.is_file():
        prose = reconciliation.read_text(encoding="utf-8")
        authored = sorted((root / "content" / "skills").glob("*/SKILL.md"))
        spelled = {
            1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
            6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
        }
        total = spelled.get(len(authored), str(len(authored)))
        if f"{total} workflow skills" not in prose:
            bad.append(
                f"content/RECONCILIATION.md must state `{total} workflow skills`; "
                f"{len(authored)} are authored"
            )
    for path in sorted((root / "content").rglob("*.md")):
        for citation in re.findall(r"RECONCILIATION\.md,? row \d+", path.read_text(encoding="utf-8")):
            bad.append(
                f"{path.relative_to(root)} cites `{citation}`, but that document "
                "has no numbered rows; cite a section heading instead"
            )

    codex_root = root / CODEX_CARRIER
    if not codex_root.is_dir():
        return [*bad, f"{CODEX_CARRIER} is missing"]
    for path in codex_root.rglob("*"):
        if path.is_symlink():
            bad.append(f"{path.relative_to(root)} must be a regular Codex carrier entry")
    # MINUS the claude-only skills. Requiring an exact match with the Claude
    # tree is what shipped `skills/harness/` -- Agent Teams, Dynamic Workflows,
    # `ToolSearch` -- to Codex users, on a platform that has none of them. The
    # compiler has always excluded it; this rule demanded it be there, which is
    # a gate encoding a defect as a requirement.
    claude_only = set()
    for authored in sorted((root / "content" / "skills").glob("*/SKILL.md")):
        text = authored.read_text(encoding="utf-8")
        end = text.find("\n---", 4) if text.startswith("---\n") else -1
        if end != -1 and re.search(r"^portability:\s*claude-only\s*$", text[4:end], re.M):
            claude_only.add(authored.parent.name)
    source_skills = [
        path
        for path in sorted((root / "skills").glob("*/SKILL.md"))
        if path.parent.name not in claude_only
    ]
    carrier_skills = sorted((codex_root / "skills").glob("*/SKILL.md"))
    source_names = [path.parent.name for path in source_skills]
    carrier_names = [path.parent.name for path in carrier_skills]
    if source_names != carrier_names:
        bad.append(
            "Codex skill inventory must match the canonical root skills minus "
            f"claude-only ones: expected {source_names}, found {carrier_names}"
        )
    else:
        for source, projected in zip(source_skills, carrier_skills, strict=True):
            if source.read_bytes() != projected.read_bytes():
                bad.append(f"{projected.relative_to(root)} differs from {source.relative_to(root)}")
    hooks_path = codex_root / "hooks" / "hooks.json"
    if not hooks_path.is_file() or hooks_path.is_symlink():
        bad.append("plugins/shepherd/codex/hooks/hooks.json must be a regular file")
    else:
        hooks = json.loads(hooks_path.read_text()).get("hooks", {})
        handlers = [
            hook
            for groups in hooks.values()
            for group in groups
            for hook in group.get("hooks", [])
        ]
        if not handlers or any(
            hook.get("command") != "shepherd codex-hook" or "args" in hook
            for hook in handlers
        ):
            bad.append("every Codex hook must invoke the native `shepherd codex-hook` command")
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
    rule_codex_carrier_is_regular_and_canonical,
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
        (tmp / ".agents" / "plugins").mkdir(parents=True)
        (tmp / CODEX_MARKETPLACE).write_text(
            '{"name":"shepherd","plugins":[{"name":"shepherd","source":{"source":"local","path":"./plugins/shepherd"}}]}'
        )
        (carrier / ".codex-plugin").mkdir()
        (carrier / ".codex-plugin" / "plugin.json").write_text(
            '{"name":"shepherd","skills":"./codex/skills/","hooks":"./codex/hooks/hooks.json"}'
        )
        codex = tmp / CODEX_CARRIER
        (codex / "skills" / "demo").mkdir(parents=True)
        (codex / "skills" / "demo" / "SKILL.md").write_text("# demo")
        (codex / "hooks").mkdir()
        (codex / "hooks" / "hooks.json").write_text(
            '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"shepherd codex-hook"}]}]}}'
        )
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

    def codex_carrier_drift(tmp: Path) -> None:
        (tmp / CODEX_CARRIER / "skills" / "demo" / "SKILL.md").write_text("drift")

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
        (rule_codex_carrier_is_regular_and_canonical, codex_carrier_drift),
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
