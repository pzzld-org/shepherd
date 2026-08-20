#!/usr/bin/env python3
"""Correct stale assertions in the temporary v6.5.5 patch runner."""

from pathlib import Path

path = Path("scripts/apply_v655_harness_cleanup.py")
text = path.read_text()

needle = '# Section-aware companion to cfg_get:\n"""'
replacement = '# Section-aware companion to cfg_get: echo `key = value` under a specific\n"""'
count = text.count(needle)
if count != 2:
    raise SystemExit(f"expected two stale cfg_get anchors, found {count}")
text = text.replace(needle, replacement)

single_launcher_assertion = '''replace_once(
    "hooks/hooks.json",
    '\"command\": \"shepherd\"',
    '\"command\": \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/shepherd_native.sh\"',
)
# Replace all remaining native hook launchers after the first assertion-backed replacement.
'''
if text.count(single_launcher_assertion) != 1:
    raise SystemExit("expected one contradictory hooks.json launcher assertion")
text = text.replace(
    single_launcher_assertion,
    "# Replace every native hook launcher through the shared resolver.\n",
)

path.write_text(text)
print("temporary patch runner assertions corrected")
