"""Tests for ``shepherd guard serve`` -- the long-lived guard evaluator (S2-guard-serve).

``shepherd guard eval`` was measured (W10 auditor, five runs) at 0.67-0.84s per call, worse than
the coder's own 0.43-0.60s claim. Two consequences already landed by the time this step starts:
``packages/harness-codex``'s guard now shells out to ``eval`` on every single Write/Edit/Bash (a
real regression, commit ``1a0cf20``), and ``packages/harness-pi`` HALTED rather than collapse its
own 242-line interpreter onto the shared engine for exactly this reason, naming "a long-lived
``guard serve`` process" as the shape that would unblock it (``packages/harness-pi/src/guard.ts``'s
own header). ``shepherd_cli.commands.guard.run_serve`` is that shape: the engine loads ONCE, then
answers line-delimited JSON requests over stdio at a fraction of the per-call cost -- see that
module's own docstring for exactly where the measured 150-500ms/call went (poetry env
resolution, the interpreter/import-graph cost, and the predicate-corpus parse), of which
``serve`` amortizes every part across the life of one process instead of paying it per request.

Every test here drives the REAL ``shepherd guard serve`` CLI as a live subprocess (never
importing ``shepherd_cli`` into the pytest process), matching ``test_guard.py``'s own
module-wide convention. The live-corpus enumeration (:data:`test_guard._CORPUS`) is imported
directly from that sibling module rather than re-implemented here -- the same anti-drift
reasoning ``test_guard.py``'s own module docstring gives for never hand-copying a fixture list
applies doubly to two test files parametrizing over what is supposed to be the identical corpus.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator

import pytest
from conftest import CLI_ROOT, PY, clean_env_dict
from test_guard import _CORPUS, _CORPUS_IDS

# --------------------------------------------------------------------------
# A live `shepherd guard serve` subprocess, request/response helper.
# --------------------------------------------------------------------------

#: Generous headroom for a cold interpreter start under a loaded CI box --
#: not a tight bound (this is a "did the process ever come up" guard, not
#: the latency assertion; that one lives in
#: ``test_measured_latency_after_warmup_stays_under_threshold`` below with
#: its own, much tighter, MEASURED number).
_STARTUP_TIMEOUT_S = 15.0


class GuardServer:
    """A live ``shepherd guard serve`` subprocess, ready line already consumed."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc

    def request(self, payload: object) -> dict[str, object]:
        """Write one request line, read exactly one response line.

        Args:
            payload: A JSON-serializable request body.

        Returns:
            The parsed JSON response object.
        """
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line, (
            f"guard serve produced no response line -- process exited "
            f"(returncode={self.proc.poll()}); stderr={self._drain_stderr()!r}"
        )
        return json.loads(line)

    def send_raw_line(self, raw: str) -> str:
        """Write one raw (possibly malformed) line, return the raw response line.

        Args:
            raw: The exact line to send (a trailing newline is added).
        """
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(raw + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line, f"guard serve produced no response line for raw input {raw!r}"
        return line

    def _drain_stderr(self) -> str:
        if self.proc.stderr is None:
            return ""
        try:
            return self.proc.stderr.read()
        except Exception:  # noqa: BLE001 -- best-effort diagnostic only
            return ""


def _spawn_guard_serve() -> subprocess.Popen[str]:
    """Start a fresh ``shepherd guard serve`` subprocess (ready line not yet consumed)."""
    return subprocess.Popen(
        [PY, "-m", "shepherd_cli", "guard", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=clean_env_dict(),
        cwd=str(CLI_ROOT),
        text=True,
        bufsize=1,  # line-buffered: this protocol is one JSON object per line, both directions
    )


def _consume_ready_line(proc: subprocess.Popen[str]) -> None:
    """Block until the server's first stdout line, and assert it is the ready sentinel.

    Never sleeps a guessed duration (the whole point of the ready-line contract):
    ``readline()`` returns the instant the line is flushed, or returns an empty string the
    instant the process exits without ever printing one -- both are immediate, not a timeout
    race, so no ``_STARTUP_TIMEOUT_S``-based polling loop is needed here.
    """
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, f"guard serve exited before printing a ready line; stderr={proc.stderr.read() if proc.stderr else ''!r}"
    ready = json.loads(line)
    assert ready == {"ready": True}, f"first line was not the ready sentinel: {line!r}"


@pytest.fixture(scope="module")
def guard_server() -> Iterator[GuardServer]:
    """One ``shepherd guard serve`` process, shared across every test in this module.

    Module-scoped deliberately: the anti-divergence test's whole premise is N requests served
    by the SAME process, not a fresh process per request (that would just be ``eval`` again,
    restated). Every test below is read-only against the shared engine state (predicates loaded
    once, never mutated), so sharing one live process across cases is safe and is also what
    proves the "one process, many requests" contract actually holds under this test suite's own
    parametrization.
    """
    proc = _spawn_guard_serve()
    _consume_ready_line(proc)
    server = GuardServer(proc)
    try:
        yield server
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.wait(timeout=_STARTUP_TIMEOUT_S)


# --------------------------------------------------------------------------
# 1. N requests over ONE process reach the same verdicts `guard eval` reaches
#    one-by-one -- the anti-divergence test, parametrized over the live corpus.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("row", _CORPUS, ids=_CORPUS_IDS)
def test_serve_matches_eval_for_every_corpus_example(guard_server: GuardServer, row: dict[str, object]) -> None:
    """Every ``content/predicates/*.toml`` ``[[example]]``, sent to the SAME live ``serve``
    process, reaches exactly the ``result`` (and ``halt_code``, where declared) that
    ``test_guard.py``'s own ``test_every_corpus_example_passes_through_eval`` already proves
    ``guard eval`` reaches for the identical request -- ``serve`` shares
    :meth:`~shepherd_cli.predicates.Engine.evaluate` with ``eval``, so this is the check that
    sharing the code path actually holds in practice, not just in the module docstring's claim.
    """
    payload = {
        "harness": "claude",
        "role": row["role"],
        "predicate": row["predicate_id"],
        "action": row["action"],
        "context": row["context"],
    }
    verdict = guard_server.request(payload)
    assert verdict["decision"] == row["result"], f"{row['predicate_id']}/{row['name']}: {verdict!r}"
    if row["halt_code"]:
        assert verdict.get("halt_code") == row["halt_code"], f"{row['predicate_id']}/{row['name']}: {verdict!r}"


# --------------------------------------------------------------------------
# 2. A malformed line gets an error response, and the NEXT valid request
#    still succeeds -- the server must never die on one bad line.
# --------------------------------------------------------------------------
def test_malformed_line_gets_error_response_and_next_request_still_succeeds(guard_server: GuardServer) -> None:
    error_response = json.loads(guard_server.send_raw_line("not valid json{"))
    assert "error" in error_response, error_response
    assert "decision" not in error_response, "a parse failure must never be mistaken for a verdict"

    payload = {
        "harness": "claude",
        "role": "coder",
        "predicate": "git-custody",
        "action": "vcs.write",
        "context": {"role_tier": "implementer"},
    }
    verdict = guard_server.request(payload)
    assert verdict == {
        "decision": "deny",
        "predicate": "git-custody",
        "rule": "implementer-never-writes-git",
        "halt_code": "CODER-GIT-WRITE",
        "reason": verdict["reason"],
    }


def test_multiple_malformed_lines_in_a_row_never_kill_the_server(guard_server: GuardServer) -> None:
    """The server survives a RUN of bad lines, not just a single isolated one."""
    for bad in ["{", "[1, 2", "", "null null", "{\"unterminated"]:
        response = json.loads(guard_server.send_raw_line(bad))
        assert "error" in response, f"{bad!r}: {response!r}"

    payload = {"harness": "claude", "role": "coder", "tool_name": "Bash", "tool_input": {"command": "git status"}}
    assert guard_server.request(payload) == {"decision": "allow"}


# --------------------------------------------------------------------------
# 3. Per-request latency after warmup -- the entire reason this command
#    exists. Threshold set from a real measurement, stated in the message.
# --------------------------------------------------------------------------

#: Measured on this repo (2026-08-13), one process, 200 requests after a
#: 10-request warmup: 0.032-0.036 ms/request average (three repeated runs).
#: That is ~4,000-15,000x faster than ``guard eval``'s measured 150-830ms
#: subprocess-per-call cost (this module's own docstring). The assertion
#: below uses a MUCH looser bound than the measured value -- 5 ms/request,
#: still two to three orders of magnitude under the old per-call cost -- so
#: a slow/loaded CI box never flakes, while a real regression back toward
#: "pay the interpreter+import+parse cost every request" (which would land
#: in the tens-to-hundreds of ms) is still caught loudly.
_MEASURED_AVG_MS_PER_REQUEST = 0.036
_LATENCY_THRESHOLD_MS = 5.0
_WARMUP_REQUESTS = 10
_MEASURED_REQUESTS = 100


def test_measured_latency_after_warmup_stays_under_threshold(guard_server: GuardServer) -> None:
    payload = {
        "harness": "claude",
        "role": "coder",
        "predicate": "git-custody",
        "action": "vcs.write",
        "context": {"role_tier": "implementer"},
    }

    for _ in range(_WARMUP_REQUESTS):
        guard_server.request(payload)

    start = time.perf_counter()
    for _ in range(_MEASURED_REQUESTS):
        guard_server.request(payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / _MEASURED_REQUESTS

    assert avg_ms < _LATENCY_THRESHOLD_MS, (
        f"guard serve averaged {avg_ms:.4f} ms/request over {_MEASURED_REQUESTS} requests after "
        f"warmup -- expected well under the {_LATENCY_THRESHOLD_MS} ms/request threshold "
        f"(baseline measurement on this repo was {_MEASURED_AVG_MS_PER_REQUEST} ms/request; "
        f"`guard eval`'s own per-call cost was measured at 150-830 ms). A result anywhere near "
        f"the threshold means the per-request path regressed back toward paying import/parse "
        f"cost per call, not just per process."
    )


# --------------------------------------------------------------------------
# 4. The server exits cleanly on stdin close -- no orphan process.
# --------------------------------------------------------------------------
def test_server_exits_cleanly_on_stdin_close() -> None:
    proc = _spawn_guard_serve()
    _consume_ready_line(proc)
    assert proc.stdin is not None

    payload = {"harness": "claude", "role": "coder", "tool_name": "Bash", "tool_input": {"command": "git status"}}
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    assert proc.stdout is not None
    assert json.loads(proc.stdout.readline()) == {"decision": "allow"}

    proc.stdin.close()
    returncode = proc.wait(timeout=_STARTUP_TIMEOUT_S)
    assert returncode == 0, f"guard serve did not exit cleanly on stdin close: returncode={returncode}"
    assert proc.poll() is not None, "process must not be left running after stdin close + wait()"
