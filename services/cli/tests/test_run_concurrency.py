"""Regression tests for #294 — ``run.json``'s load-modify-save lost-update race.

Reproduces the close-swarm auditor's EXACT defect: two real, barrier-
synchronized OS processes each ``load_run()``, append a distinct
``LaneState``, then ``save_run()`` against the SAME ``run.json``. Measured
pre-fix (issue #294): both processes' in-memory view at save time proved
they read the same pre-write (empty-lanes) state concurrently —

    lane-alpha: saved, in-memory lanes at save time = ['lane-alpha']
    lane-beta:  saved, in-memory lanes at save time = ['lane-beta']
    === final run.json lanes ===
    ['lane-beta']

— ``lane-alpha``'s registration silently vanished: no exception, no
warning, exit 0 on both processes. ``atomic_write_json``'s tempfile +
``os.replace`` protects a single writer against a CRASH; it does nothing
for two writers racing the same read-modify-write cycle. A
``threading.Lock``-based "fix" would pass a threading-based version of
this test while leaving the real, cross-PROCESS defect completely open —
every worker below is therefore a genuine OS process (an independent
address space, an independent open file description on the lock file),
never a thread.

SUBPROCESS DISCIPLINE. ``conftest.py``'s own module docstring states this
suite's rule: "every test drives the real CLI ... never by importing
``shepherd_cli`` into the pytest process itself" — no test file in this
suite has an exception to that (see ``test_models_run.py``,
``test_verdicts.py``: even their pure-library-function tests round-trip
through a ``${PY} -c`` subprocess). This file keeps that rule intact by
never importing ``shepherd_cli`` at module scope: every scenario below is
driven through ONE orchestrator subprocess (``_run_orchestrator``) that
itself imports ``shepherd_cli.models_run`` and, INSIDE that subprocess,
spawns the actual racing workers via ``multiprocessing`` — real OS
processes distinct from both the pytest process and the orchestrator.
The orchestrator uses the ``fork`` start method (not the platform default
``spawn`` on macOS) specifically because a ``fork``ed child is a memory
copy of its parent at fork time: it needs no pickle-importable top-level
target, so a worker function defined inline in a ``${PY} -c`` snippet's
``__main__`` namespace (this file's only way to keep the import out of
the pytest process) works directly — ``spawn`` would require re-importing
that ``__main__`` module by name, which a ``-c`` snippet has no path to
satisfy. Synchronization uses a real ``multiprocessing.Barrier`` (an
OS-level semaphore), not a filesystem-polling convention — polling can't
guarantee every worker's ``load_run()`` fires before any worker's
``save_run()`` completes, which would make the race probabilistic rather
than the deterministic, always-fails-pre-fix / always-passes-post-fix
reproduction a regression test requires.

Scenarios:
  - the exact two-process race above (both lanes must survive).
  - N-process contention (8 processes, 8 lanes, zero lost).
  - a holder ``SIGKILL``ed mid read-modify-write: the next writer must
    recover near-instantly rather than hang — #294's stale-lock story is
    that ``flock`` is owned by the open file description, not the
    process, so the kernel releases it the instant every fd referencing
    it closes, SIGKILL included.
"""

from __future__ import annotations

import json
import signal
import subprocess
from pathlib import Path

from conftest import PY, clean_env_dict

#: Seeds a lane-less ``run.json``, then races ``len(lanes)`` fork-based OS
#: processes — released from a shared ``multiprocessing.Barrier`` as close
#: to simultaneously as the OS allows — each registering exactly one
#: distinct lane via the real ``load_run() -> mutate -> save_run()``
#: mutator shape every CLI lane command uses. Prints
#: ``{"exitcodes": [...]}`` on stdout; the caller re-reads ``run.json``
#: directly (plain JSON, no ``shepherd_cli`` import) to check which lanes
#: actually landed.
_RACE_SCRIPT = """\
import json
import multiprocessing
import sys

from shepherd_cli.models_run import LaneState, RunState, load_run, save_run

workdir, run, *lanes = sys.argv[1:]

save_run(RunState(run=run), workdir=workdir)


def _register(lane, barrier):
    barrier.wait()  # release every worker to load_run() as one simultaneous wave
    state = load_run(run, workdir=workdir)
    state.lanes.append(LaneState(id=lane))
    save_run(state, workdir=workdir)


ctx = multiprocessing.get_context("fork")
barrier = ctx.Barrier(len(lanes))
procs = [ctx.Process(target=_register, args=(lane, barrier)) for lane in lanes]
for p in procs:
    p.start()
for p in procs:
    p.join(timeout=30)

print(json.dumps({
    "alive": [p.is_alive() for p in procs],
    "exitcodes": [p.exitcode for p in procs],
}))
"""

#: Seeds a lane-less ``run.json``, forks a "holder" that ``load_run()``s
#: (acquiring #294's advisory lock) and then sleeps WITHOUT ever calling
#: ``save_run`` — the lock stays pending, exactly like a writer that
#: crashed mid read-modify-write. Once the holder signals it has the lock,
#: this SIGKILLs it, then times a fresh ``load_run -> mutate -> save_run``
#: in the orchestrator's own process. Prints
#: ``{"elapsed": ..., "holder_alive": ..., "holder_exitcode": ...}``.
_STALE_LOCK_SCRIPT = """\
import json
import multiprocessing
import os
import signal
import sys
import time

from shepherd_cli.models_run import LaneState, RunState, load_run, save_run

workdir, run = sys.argv[1], sys.argv[2]

save_run(RunState(run=run), workdir=workdir)


def _hold(ready):
    load_run(run, workdir=workdir)  # acquires the lock; deliberately never saves
    ready.set()
    time.sleep(60)  # killed well before this returns


ctx = multiprocessing.get_context("fork")
ready = ctx.Event()
holder = ctx.Process(target=_hold, args=(ready,))
holder.start()

if not ready.wait(timeout=10):
    print(json.dumps({"ok": False, "reason": "holder never signaled ready"}))
    sys.exit(1)
time.sleep(0.1)  # let the holder settle past its flock() call before killing it
os.kill(holder.pid, signal.SIGKILL)
holder.join(timeout=10)

start = time.monotonic()
state = load_run(run, workdir=workdir)
state.lanes.append(LaneState(id="lane-after-crash"))
save_run(state, workdir=workdir)
elapsed = time.monotonic() - start

print(json.dumps({
    "ok": True,
    "elapsed": elapsed,
    "holder_alive": holder.is_alive(),
    "holder_exitcode": holder.exitcode,
}))
"""


def _run_orchestrator(script: str, args: list[str], *, timeout: float) -> dict:
    """Run one of the scripts above as a fresh subprocess; parse its stdout JSON."""
    proc = subprocess.run(
        [PY, "-c", script, *args],
        env=clean_env_dict(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert proc.returncode == 0, f"orchestrator subprocess failed: {proc.stderr}"
    return json.loads(proc.stdout)


def _run_json(tmp_path: Path, run: str) -> dict:
    return json.loads((tmp_path / ".shepherd" / "runs" / run / "run.json").read_text())


def test_two_process_race_both_lanes_survive(tmp_path: Path) -> None:
    """#294's exact reproduction: two barrier-synced processes, both lanes land."""
    workdir = str(tmp_path / ".shepherd")
    lanes = ["lane-alpha", "lane-beta"]
    result = _run_orchestrator(_RACE_SCRIPT, [workdir, "v645", *lanes], timeout=30)
    assert result["exitcodes"] == [0, 0], result
    assert result["alive"] == [False, False], result

    doc = _run_json(tmp_path, "v645")
    lane_ids = sorted(lane["id"] for lane in doc["lanes"])
    assert lane_ids == sorted(lanes), (
        f"lost-update race: expected both lanes, got {lane_ids} -- the #294 fix must "
        "serialize load -> mutate -> save across processes"
    )


def test_n_process_contention_all_lanes_survive(tmp_path: Path) -> None:
    """Contention beyond the minimal 2-writer case: 8 processes, 8 lanes, zero lost."""
    workdir = str(tmp_path / ".shepherd")
    lanes = [f"lane-{i:02d}" for i in range(8)]
    result = _run_orchestrator(_RACE_SCRIPT, [workdir, "v645", *lanes], timeout=45)
    assert result["exitcodes"] == [0] * len(lanes), result
    assert not any(result["alive"]), result

    doc = _run_json(tmp_path, "v645")
    lane_ids = sorted(lane["id"] for lane in doc["lanes"])
    assert lane_ids == sorted(lanes), (
        f"lost-update race under contention: expected {sorted(lanes)}, got {lane_ids}"
    )


def test_killed_holder_does_not_hang_next_writer(tmp_path: Path) -> None:
    """A holder SIGKILLed mid read-modify-write must not deadlock the run forever.

    #294's stale-lock story: ``flock`` is owned by the open file
    description, not the process, so the kernel releases it the instant
    every fd referencing it closes — SIGKILL included. Recovery here must
    land in low single-digit seconds, nowhere near the lock's own 30s
    live-holder timeout, proving recovery comes from the kernel release,
    not from that timeout expiring.
    """
    workdir = str(tmp_path / ".shepherd")
    result = _run_orchestrator(_STALE_LOCK_SCRIPT, [workdir, "v645"], timeout=30)
    assert result["ok"], result
    assert result["holder_alive"] is False, result
    assert result["holder_exitcode"] == -signal.SIGKILL.value, result
    assert result["elapsed"] < 5.0, (
        f"recovery took {result['elapsed']:.2f}s -- a crashed holder's flock releases "
        "the moment the kernel reaps it; this should never approach the acquire timeout"
    )

    doc = _run_json(tmp_path, "v645")
    assert [lane["id"] for lane in doc["lanes"]] == ["lane-after-crash"]
