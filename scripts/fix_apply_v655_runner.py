#!/usr/bin/env python3
"""Correct the one stale comment anchor in the temporary v6.5.5 patch runner."""

from pathlib import Path

path = Path("scripts/apply_v655_harness_cleanup.py")
text = path.read_text()
needle = '# Section-aware companion to cfg_get:\n"""'
replacement = '# Section-aware companion to cfg_get: echo `key = value` under a specific\n"""'
count = text.count(needle)
if count != 2:
    raise SystemExit(f"expected two stale cfg_get anchors, found {count}")
path.write_text(text.replace(needle, replacement))
print("temporary patch runner anchor corrected")
