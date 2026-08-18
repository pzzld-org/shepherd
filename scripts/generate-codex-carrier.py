#!/usr/bin/env python3
"""Generate or verify Codex's regular-file skill projection.

WHY THE PORTABILITY FILTER EXISTS.

The projection source is `skills/`, which is the CLAUDE carrier. Codex's plugin
manifest points at `./codex/skills/`, so whatever lands here is what a Codex
user installs -- and a straight copy shipped them `skills/harness/`, a skill
whose own frontmatter says `portability: claude-only` and whose entire content
is Agent Teams, Dynamic Workflows, and `ToolSearch`. None of those exist on
Codex. The compiler has always excluded it correctly; this projector did not,
and the drift check compared the Claude tree against a copy of the Claude tree,
so it was green the whole time.

This filter is a PROPERTY CHECK, not a second compiler: it reads the same
`portability` frontmatter the compiler keys on and refuses anything marked
claude-only. The authoritative comparison -- the committed carrier against a
real `compile --target codex` -- runs in the full gate.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "skills"
TARGET = ROOT / "plugins" / "shepherd" / "codex" / "skills"

AUTHORED = ROOT / "content" / "skills"
PORTABILITY = re.compile(r"^portability:\s*(\S+)\s*$", re.M)


def claude_only_skills() -> set[str]:
    """Skill directory names the compiler refuses to emit for a non-Claude target.

    Read from `content/skills/`, NOT from the compiled `skills/` tree: the
    compiler STRIPS `portability` out of the frontmatter it emits, so the
    projection source cannot answer this question about itself. The authored
    content is where the compiler reads it too, which is what keeps this a
    property check rather than a second opinion.
    """
    names = set()
    for authored in sorted(AUTHORED.glob("*/SKILL.md")):
        text = authored.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end == -1:
            continue
        found = PORTABILITY.search(text[4:end])
        if found and found.group(1) == "claude-only":
            names.add(authored.parent.name)
    return names


CLAUDE_ONLY = claude_only_skills()


def claude_only(relative: str) -> bool:
    return relative.split("/", 1)[0] in CLAUDE_ONLY


def inventory(root: Path, *, skip_claude_only: bool = False) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and not (skip_claude_only and claude_only(path.relative_to(root).as_posix()))
    }


def check() -> list[str]:
    source = inventory(SOURCE, skip_claude_only=True)
    projected = inventory(TARGET)
    failures = []
    for relative in sorted(inventory(TARGET)):
        if claude_only(relative):
            failures.append(
                f"plugins/shepherd/codex/skills/{relative} is `portability: claude-only`"
                " and must never ship in the Codex carrier"
            )
    if set(source) != set(projected):
        failures.append(
            f"skill inventory differs: source={sorted(source)} projected={sorted(projected)}"
        )
    for relative in sorted(set(source) & set(projected)):
        if source[relative].read_bytes() != projected[relative].read_bytes():
            failures.append(f"plugins/shepherd/codex/skills/{relative} has byte drift")
    for path in TARGET.rglob("*") if TARGET.is_dir() else ():
        if path.is_symlink():
            failures.append(f"{path.relative_to(ROOT)} must be a regular carrier entry")
    return failures


def generate() -> None:
    expected = inventory(SOURCE, skip_claude_only=True)
    existing = inventory(TARGET) if TARGET.is_dir() else {}
    extras = sorted(set(existing) - set(expected))
    if extras:
        raise SystemExit(f"refusing to overwrite a carrier with extra files: {extras}")
    for relative, source in expected.items():
        target = TARGET / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        generate()
    failures = check()
    if failures:
        for failure in failures:
            print(f"generate-codex-carrier: ERROR: {failure}")
        return 1
    print("ok: Codex skill carrier is a byte-exact regular-file projection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
