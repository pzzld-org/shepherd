#!/usr/bin/env python3
"""Verify that registered Claude hooks are adapters, never a second engine.

The v6.4.5 source registry permits only thin component/native adapters and
non-blocking telemetry that writes run-scoped evidence. Shell policy, direct
registry mutation, and agent-policy hooks are retired. The native component
and Rust core are the only policy authority.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


THIN = "thin component/native adapter"
TELEMETRY = "telemetry-only"
ALLOWED = {THIN, TELEMETRY}

METADATA: dict[str, dict[str, Any]] = {
    "packages/harness-claude/hooks/dispatch-lifecycle.mjs": {
        "classification": THIN,
        "native_coverage": "full",
        "native_surface": ["Component lifecycle provider", "shepherd dispatch"],
    },
    "packages/harness-claude/hooks/guard-eval.mjs": {
        "classification": THIN,
        "native_coverage": "full",
        "native_surface": ["Component guard provider", "shepherd guard eval"],
    },
    "hooks/scripts/seed_preflight_check.sh": {
        "classification": THIN,
        "native_coverage": "full",
        "native_surface": ["shepherd seed verify <path>"],
    },
    "hooks/scripts/agent_insight_capture.sh": {
        "classification": TELEMETRY,
        "native_coverage": "partial",
        "native_surface": ["shepherd insights"],
    },
    "hooks/scripts/bash_post.sh": {
        "classification": TELEMETRY,
        "native_coverage": "partial",
        "native_surface": ["shepherd doctor"],
    },
    "hooks/scripts/cwd_changed.sh": {
        "classification": TELEMETRY,
        "native_coverage": "none",
        "native_surface": [],
    },
    "hooks/scripts/discovery_capture.sh": {
        "classification": TELEMETRY,
        "native_coverage": "partial",
        "native_surface": ["shepherd discovery"],
    },
    "hooks/scripts/precompact_snapshot.sh": {
        "classification": TELEMETRY,
        "native_coverage": "partial",
        "native_surface": ["shepherd run", "shepherd status"],
    },
    "hooks/scripts/subagent_telemetry.sh": {
        "classification": TELEMETRY,
        "native_coverage": "partial",
        "native_surface": ["shepherd status", "shepherd doctor"],
    },
}

TARGET_RE = re.compile(
    r"(?P<target>(?:hooks/scripts|packages/harness-claude/hooks)/\S+)"
)
FORBIDDEN = {
    "retired_cli": re.compile(r"\bshctx\b"),
    "retired_python_cli": re.compile(r"services/cli"),
    "plugin_local_launcher": re.compile(r"(?:^|/)bin/shepherd\b"),
    "retired_doctrine": re.compile(
        r"skills/(?:shepherd|harness|context)/references|commands/[A-Za-z0-9_.-]+\.md"
    ),
}
DIRECT_RUNTIME = re.compile(r"\b(?:sqlite3|python3)\b")
TELEMETRY_POLICY = (
    re.compile(r"\b(?:emit_deny|permissionDecision)\b"),
    re.compile(r"\bemit_json_obj\b.*\bdecision\b"),
    re.compile(r"\bsqlite3\b.*\b(?:INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE)\b", re.I),
)


def executable_lines(path: Path) -> list[tuple[int, str]]:
    """Return non-comment source lines for a registered adapter."""
    lines: list[tuple[int, str]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.lstrip().startswith("#"):
            continue
        lines.append((number, raw))
    return lines


def registrations(root: Path) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """Read the Claude registry and return command targets plus illegal agents."""
    data = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))
    commands: dict[str, list[dict[str, str]]] = {}
    agents: list[str] = []
    for event, groups in data["hooks"].items():
        for group in groups:
            matcher = group.get("matcher", "*")
            for hook in group.get("hooks", []):
                hook_type = hook.get("type")
                if hook_type == "command":
                    command = hook["command"]
                    match = TARGET_RE.search(command)
                    if match is None:
                        raise ValueError(
                            f"registered command has no audited hook target: {command}"
                        )
                    target = match.group("target")
                    commands.setdefault(target, []).append(
                        {"event": event, "matcher": matcher, "command": command}
                    )
                elif hook_type == "agent":
                    agents.append(f"{event}:matcher={matcher}:if={hook.get('if', '<none>')}")
                else:
                    raise ValueError(
                        f"registered hook has unsupported type: {hook_type!r}"
                    )
    return commands, agents


def audit(root: Path) -> tuple[dict[str, Any], list[str]]:
    """Return machine-readable inventory and deterministic gate failures."""
    registered, agents = registrations(root)
    failures: list[str] = []
    entries: list[dict[str, Any]] = []

    for agent in agents:
        failures.append(f"nondeterministic-policy agent registration is retired: {agent}")

    for target in sorted(set(registered) - set(METADATA)):
        failures.append(f"missing inventory metadata: {target}")
    for target in sorted(set(METADATA) - set(registered)):
        failures.append(f"stale inventory metadata for unregistered hook: {target}")

    for target in sorted(registered):
        metadata = METADATA.get(target)
        if metadata is None:
            continue
        classification = metadata["classification"]
        if classification not in ALLOWED:
            failures.append(f"unsupported hook authority classification: {target}: {classification}")
            continue

        path = root / target
        if not path.is_file():
            failures.append(f"registered hook target missing: {target}")
            continue

        direct_runtime_lines: list[int] = []
        source_findings: list[dict[str, Any]] = []
        policy_lines: list[int] = []
        for line_number, line in executable_lines(path):
            for name, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    source_findings.append(
                        {"kind": name, "line": line_number, "source": line}
                    )
                    failures.append(f"{target}:{line_number}: forbidden {name}")
            if DIRECT_RUNTIME.search(line):
                direct_runtime_lines.append(line_number)
            if classification == TELEMETRY:
                for pattern in TELEMETRY_POLICY:
                    if pattern.search(line):
                        policy_lines.append(line_number)
                        failures.append(
                            f"{target}:{line_number}: telemetry_policy_authority"
                        )
                        break

        if classification == THIN and direct_runtime_lines:
            failures.append(
                f"{target}: thin component/native adapter directly invokes "
                f"sqlite3/python3 at {','.join(map(str, direct_runtime_lines))}"
            )

        entries.append(
            {
                "target": target,
                "registration_kind": "command",
                "classification": classification,
                "registrations": registered[target],
                "native_coverage": metadata["native_coverage"],
                "native_surface": metadata["native_surface"],
                "direct_runtime_lines": direct_runtime_lines,
                "policy_authority_lines": policy_lines,
                "forbidden_source_findings": source_findings,
            }
        )

    return {
        "schema": "shepherd.hook-authority-inventory/1",
        "entries": entries,
        "strict": True,
        "counts": {
            THIN: sum(item["classification"] == THIN for item in entries),
            TELEMETRY: sum(item["classification"] == TELEMETRY for item in entries),
            "independent deterministic policy/state authority": 0,
            "nondeterministic-policy": 0,
        },
    }, failures


def self_test() -> int:
    """Prove the gate rejects retired CLIs, direct runtimes, and agent policy."""
    with TemporaryDirectory(prefix="shepherd-hook-audit-") as temporary:
        root = Path(temporary)
        (root / "hooks/scripts").mkdir(parents=True)
        plugin_root = "$" + "{CLAUDE_PLUGIN_ROOT}"
        (root / "hooks/hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{plugin_root}/hooks/scripts/thin.sh",
                                    },
                                    {
                                        "type": "command",
                                        "command": f"{plugin_root}/hooks/scripts/telemetry.sh",
                                    },
                                    {"type": "agent", "prompt": "legacy policy"},
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        (root / "hooks/scripts/thin.sh").write_text(
            "shctx status\nservices/cli/shepherd_cli\n/bin/shepherd\nsqlite3 db\npython3 -c pass\n",
            encoding="utf-8",
        )
        (root / "hooks/scripts/telemetry.sh").write_text(
            "emit_deny nope\nsqlite3 db 'UPDATE state SET x=1'\n",
            encoding="utf-8",
        )
        previous = dict(METADATA)
        METADATA.update(
            {
                "hooks/scripts/thin.sh": {
                    "classification": THIN,
                    "native_coverage": "full",
                    "native_surface": ["fixture"],
                },
                "hooks/scripts/telemetry.sh": {
                    "classification": TELEMETRY,
                    "native_coverage": "none",
                    "native_surface": [],
                },
            }
        )
        try:
            _, failures = audit(root)
        finally:
            METADATA.clear()
            METADATA.update(previous)

    required = {
        "retired_cli",
        "retired_python_cli",
        "plugin_local_launcher",
        "sqlite3/python3",
        "telemetry_policy_authority",
        "nondeterministic-policy agent registration is retired",
    }
    found = "\n".join(failures)
    missing = [item for item in required if item not in found]
    if missing:
        print(f"self-test failed to detect: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("hook_authority_inventory: self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--check", action="store_true", help="run the fast authority gate")
    parser.add_argument("--strict", action="store_true", help="alias for release closure")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    inventory, failures = audit(args.root.resolve())
    if args.json:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    else:
        counts = inventory["counts"]
        print(
            "hook_authority_inventory: "
            f"{counts[THIN]} thin, {counts[TELEMETRY]} telemetry, "
            f"{counts['independent deterministic policy/state authority']} independent, "
            f"{counts['nondeterministic-policy']} nondeterministic"
        )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
