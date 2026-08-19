#!/usr/bin/env python3
"""Prove every conversion is APPEND-ONLY: new line == old line + ' || { ... }'.

The lane's hardest safety property is "do not change what any assertion asserts"
(L7-S1 NON-GOALS). Reading 80 diffs by eye cannot establish that. This does it
deterministically: for each changed line, strip the appended guard and require
byte equality with the pre-image.
"""
import subprocess, sys, re

GUARD = re.compile(r'^(?P<orig>.*?)\s*\|\|\s*\{\s*(rc=\$\?;\s*)?printf .*?>&2;\s*exit 1;\s*\}$')

base = sys.argv[1] if len(sys.argv) > 1 else 'HEAD'
files = subprocess.run(['git', 'diff', '--name-only', base], capture_output=True,
                       text=True, check=True).stdout.split()
ok = bad = 0
problems = []
for f in files:
    old = subprocess.run(['git', 'show', f'{base}:{f}'], capture_output=True,
                         text=True, check=True).stdout.split('\n')
    new = open(f).read().split('\n')
    if len(old) != len(new):
        problems.append(f'{f}: LINE COUNT CHANGED {len(old)} -> {len(new)} '
                        f'(conversion must be one line per site)')
        bad += 1
        continue
    for i, (o, n) in enumerate(zip(old, new), 1):
        if o == n:
            continue
        m = GUARD.match(n)
        if not m:
            problems.append(f'{f}:{i}: changed line is not an append-only guard\n'
                            f'    old: {o}\n    new: {n}')
            bad += 1
        elif m.group('orig') != o:
            problems.append(f'{f}:{i}: ORIGINAL COMMAND TEXT MUTATED\n'
                            f'    old:      {o}\n    stripped: {m.group("orig")}')
            bad += 1
        else:
            ok += 1
print(f'append-only conversions verified: {ok}')
print(f'violations: {bad}')
for p in problems:
    print('  ' + p)
if ok == 0:
    print('EMPTY SCAN SET -- refusing to report success'); sys.exit(1)
sys.exit(1 if bad else 0)
