#!/usr/bin/env python3
"""Generate pi-subagents definitions from one compiled Pi carrier."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn, cast


ROLE_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
TOOL_PATTERN = re.compile(r"[A-Za-z0-9_.:-]+")
MODEL_REQUIRED_SENTINEL = "model-required/model-required"


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def load_outputs(package_root: Path) -> dict[str, str]:
    manifest_path = package_root / ".shepherd-generated.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read compiled Pi manifest {manifest_path}: {error}")
    if not isinstance(manifest, dict):
        fail("compiled Pi manifest must be an object")
    document = cast(dict[str, Any], manifest)
    if document.get("schema") != "shepherd.compiled-tree/3" or document.get("target") != "pi":
        fail("compiled carrier must use shepherd.compiled-tree/3 for target pi")
    roles = document.get("roles")
    if not isinstance(roles, list):
        fail("compiled Pi manifest roles must be an array")

    outputs: dict[str, str] = {}
    for value in roles:
        if not isinstance(value, dict):
            continue
        raw = cast(dict[str, Any], value)
        if raw.get("dispatchable") is not True:
            continue
        role = raw.get("role")
        if not isinstance(role, str) or ROLE_PATTERN.fullmatch(role) is None:
            fail(f"invalid dispatchable role: {role!r}")
        if role in outputs:
            fail(f"duplicate dispatchable role: {role}")
        description = raw.get("description")
        tools = raw.get("tools")
        if not isinstance(description, str) or not description.strip():
            fail(f"dispatchable role {role} has no description")
        if not isinstance(tools, list) or not tools or any(
            not isinstance(tool, str) or TOOL_PATTERN.fullmatch(tool) is None for tool in tools
        ):
            fail(f"dispatchable role {role} has invalid tools")
        role_name = cast(str, role)
        role_description = cast(str, description)
        role_tools = cast(list[str], tools)
        transport_tools = list(dict.fromkeys([*role_tools, "subagent"]))
        carrier_path = raw.get("carrier_path")
        if carrier_path != f"prompts/{role_name}.md":
            fail(f"dispatchable role {role} has unexpected carrier path: {carrier_path!r}")
        prompt_path = package_root / cast(str, carrier_path)
        if not prompt_path.is_file() or prompt_path.is_symlink():
            fail(f"missing role prompt: {carrier_path}")
        model_hint = raw.get("model_hint")
        if not isinstance(model_hint, str) or ROLE_PATTERN.fullmatch(model_hint) is None:
            fail(f"dispatchable role {role} has invalid model hint")
        model = raw.get("model")
        if model is not None and (
            not isinstance(model, str)
            or not model.strip()
            or any(character.isspace() or character in {'"', "\\"} for character in model)
        ):
            fail(f"dispatchable role {role} has invalid model")
        if model_hint == "inherit-caller":
            if model != "inherit":
                fail(f"dispatchable role {role} inherit-caller hint must emit model inherit")
        else:
            if model is not None:
                fail(
                    f"dispatchable role {role} non-inherit hint {model_hint} "
                    f"must emit model null, got {model!r}"
                )
            model = MODEL_REQUIRED_SENTINEL

        frontmatter = [
            "---",
            f"name: {json.dumps(f'shepherd:{role_name}')}",
            f"description: {json.dumps(role_description)}",
            f"tools: {', '.join(transport_tools)}",
        ]
        frontmatter.append(f"model: {model}")
        frontmatter.extend(
            [
                "systemPromptMode: replace",
                "inheritProjectContext: true",
                "inheritSkills: false",
                "subagentOnlyExtensions: ../src/extension.mjs",
                f"acceptanceRole: {'writer' if raw.get('write_eligible') is True else 'read-only'}",
            ]
        )
        frontmatter.append("maxSubagentDepth: 2")
        if raw.get("write_eligible") is not True:
            frontmatter.append("completionGuard: false")
        prompt = prompt_path.read_text(encoding="utf-8")
        outputs[role_name] = "\n".join([*frontmatter, "---", "", prompt])

    if not outputs:
        fail("compiled Pi manifest contains zero dispatchable roles")
    return outputs


def main() -> None:
    if len(sys.argv) != 2:
        fail(f"usage: {Path(sys.argv[0]).name} <staged-package-root>")
    package_root = Path(sys.argv[1]).resolve()
    outputs = load_outputs(package_root)
    agents = package_root / "agents"
    if agents.exists() or agents.is_symlink():
        fail(f"refusing to replace existing generated agent carrier: {agents}")
    agents.mkdir()
    for role, content in sorted(outputs.items()):
        (agents / f"{role}.md").write_text(content, encoding="utf-8")
    print(f"generated {len(outputs)} Pi subagent definitions under {agents}")


if __name__ == "__main__":
    main()
