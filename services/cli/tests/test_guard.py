"""Tests for ``shepherd guard`` — the DF-76 guard-predicate evaluator CLI.

``services/cli/shepherd_cli/predicates.py`` is the ONE guard-predicate
engine every harness adapter (``packages/harness-claude``,
``packages/harness-codex``, ``packages/harness-pi``) was already relaying
to before it existed (DF-76's own finding); ``services/cli/shepherd_cli/commands/guard.py``
is the thin CLI surface over it. Every assertion below drives the REAL
``shepherd guard ...`` CLI as a subprocess (``${PY} -m shepherd_cli guard
...``) — exactly like every other suite in this package
(``test_audit.py``'s ``run_insert``, ``test_dups.py``'s ``_run_cli``) — and
never imports ``shepherd_cli`` into the pytest process itself, matching
``conftest.py``'s own module-wide convention.

The one exception, ``_load_live_corpus`` below, still honors that
convention: it reads ``content/predicates/*.toml`` via a FRESH ``${PY} -c``
subprocess that imports ``shepherd_cli.predicates`` on the SUBPROCESS side
only, using the engine's own loader/flatten helpers — so the parametrized
corpus in :data:`_CORPUS` can never drift from how ``shepherd guard eval``
itself reads the spec, without ever hand-copying a fixture list (the
dispatch brief's own "a copied list is how a spec silently drifts").
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import CLI_ROOT, PY, REPO_ROOT, clean_env_dict


def _guard_env() -> dict[str, str]:
    """A stripped env for driving ``shepherd guard ...`` — no DB, no workdir needed."""
    return clean_env_dict()


def _run_guard(args: list[str], *, stdin: str = "", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke ``shepherd guard <args>``, feeding ``stdin`` verbatim.

    ``conftest.run_cli`` has no ``input=`` passthrough (matching
    ``test_audit.py``'s ``run_insert``/``test_dups.py``'s own local helper,
    for the same reason: no other ported command needed stdin when
    ``run_cli`` was written), so this calls ``subprocess.run`` directly with
    the same ``${PY} -m shepherd_cli`` invocation shape.

    Args:
        args: Arguments after ``guard``, e.g. ``["eval"]``.
        stdin: The raw text piped to the subprocess's stdin.
        env: The subprocess environment; defaults to :func:`_guard_env`.

    Returns:
        The completed subprocess, stdout/stderr captured as text.
    """
    return subprocess.run(
        [PY, "-m", "shepherd_cli", "guard", *args],
        input=stdin,
        env=env if env is not None else _guard_env(),
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


# --------------------------------------------------------------------------
# Live corpus enumeration — never a hand-copied fixture list.
# --------------------------------------------------------------------------

#: Runs on the SUBPROCESS side only (see module docstring): reads the live
#: ``content/predicates/*.toml`` corpus via the engine's own
#: ``load_predicates``/``flatten_example_context``, and prints one JSON row
#: per ``[[example]]`` — the exact shape a real ``guard eval`` normalized
#: (shape (a)) request needs.
_CORPUS_SNIPPET = """\
import json

from shepherd_cli.predicates import flatten_example_context, load_predicates, resolve_content_dir

predicates = load_predicates(resolve_content_dir())
rows = []
for predicate_id, doc in predicates.items():
    for example in doc.examples:
        rows.append(
            {
                "predicate_id": predicate_id,
                "name": example.get("name"),
                "role": example.get("role"),
                "action": example.get("action"),
                "context": flatten_example_context(example),
                "result": example.get("result"),
                "halt_code": example.get("halt_code"),
            }
        )
print(json.dumps(rows))
"""


def _load_live_corpus() -> list[dict[str, object]]:
    """Every ``content/predicates/*.toml`` ``[[example]]``, read fresh.

    Returns:
        One dict per example, in file-then-declaration order.
    """
    proc = subprocess.run(
        [PY, "-c", _CORPUS_SNIPPET],
        env=clean_env_dict(),
        cwd=str(CLI_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"failed to enumerate the live predicate corpus: {proc.stderr}"
    return json.loads(proc.stdout)


#: Computed once at import time, exactly like ``test_migrate.py``'s
#: ``_SHIPPED_MIGRATIONS`` — every node below automatically tracks whatever
#: ``content/predicates/*.toml`` declares today, no manual upkeep.
_CORPUS: list[dict[str, object]] = _load_live_corpus()
_CORPUS_IDS = [f"{row['predicate_id']}/{row['name']}" for row in _CORPUS]

assert len(_CORPUS) > 0, "expected at least one content/predicates/*.toml [[example]]"
assert {row["predicate_id"] for row in _CORPUS} == {"dedup-gate", "dispatch-scope", "git-custody", "write-boundary"}


# --------------------------------------------------------------------------
# 1. Every predicate example passes through `guard eval` (live corpus).
# --------------------------------------------------------------------------
@pytest.mark.parametrize("row", _CORPUS, ids=_CORPUS_IDS)
def test_every_corpus_example_passes_through_eval(row: dict[str, object]) -> None:
    """A shape-(a) request built from one real ``[[example]]`` reaches
    exactly that example's declared ``result`` (and ``halt_code``, where
    the example declares one) through the real CLI."""
    payload = {
        "harness": "claude",
        "role": row["role"],
        "predicate": row["predicate_id"],
        "action": row["action"],
        "context": row["context"],
    }
    proc = _run_guard(["eval"], stdin=json.dumps(payload))
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict["decision"] == row["result"], f"{row['predicate_id']}/{row['name']}: {verdict!r}"
    if row["halt_code"]:
        assert verdict.get("halt_code") == row["halt_code"], f"{row['predicate_id']}/{row['name']}: {verdict!r}"


# --------------------------------------------------------------------------
# 2. A deliberately WRONG effect mapping makes `guard test` fail.
# --------------------------------------------------------------------------
@pytest.fixture
def content_copy(tmp_path: Path) -> Path:
    """A throwaway, mutable copy of the real ``content/`` tree."""
    dest = tmp_path / "content"
    shutil.copytree(REPO_ROOT / "content", dest)
    return dest


def test_wrong_effect_mapping_makes_guard_test_fail(content_copy: Path) -> None:
    """Rewiring one rule's ``effect`` to an always-allow no-op must turn a
    known ``deny``-kind example into a mismatch — ``guard test`` is the
    falsifiability harness the dispatch brief requires, and a harness that
    cannot go red against a broken engine cannot be trusted when it is
    green (DF-59's own lesson, restated for this predicate corpus)."""
    dedup_toml = content_copy / "predicates" / "dedup-gate.toml"
    original = dedup_toml.read_text(encoding="utf-8")
    mutated = original.replace(
        'effect = "deny_if_hit_without_justification"',
        'effect = "allow_if_no_hit"',
    )
    assert mutated != original, "fixture assumption broke: nothing was replaced"
    dedup_toml.write_text(mutated, encoding="utf-8")

    proc = _run_guard(["test", "--content-dir", str(content_copy)])
    assert proc.returncode != 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "FAIL" in proc.stdout or "FAIL" in proc.stderr


# --------------------------------------------------------------------------
# 3. `guard test` exits non-zero when pointed at an empty predicates dir.
# --------------------------------------------------------------------------
def test_empty_predicates_dir_exits_nonzero(tmp_path: Path) -> None:
    """DF-59: a conformance runner that reports a green ``0/0`` made a wave
    gate pass before any implementation existed. Zero examples loaded must
    fail loudly, never report success by omission."""
    empty_content = tmp_path / "content"
    empty_content.mkdir()

    proc = _run_guard(["test", "--content-dir", str(empty_content)])
    assert proc.returncode != 0
    assert "0/0" in proc.stdout


# --------------------------------------------------------------------------
# 4. Shape (a) and shape (b) reach the same verdict for the same situation.
# --------------------------------------------------------------------------
def test_normalized_and_raw_tool_call_reach_the_same_verdict() -> None:
    """A coder's ``git commit`` denies identically whether the caller
    already resolved ``(predicate, action, context)`` itself (shape a), or
    handed the engine a raw ``Bash`` tool call to map on its own (shape b)
    — the whole reason shape (b) lives in the engine (three adapters each
    hand-rolling their own git-subcommand tokenizer, per the dispatch
    brief)."""
    normalized = {
        "harness": "claude",
        "role": "coder",
        "predicate": "git-custody",
        "action": "vcs.write",
        "context": {"role_tier": "implementer"},
    }
    raw_tool_call = {
        "harness": "claude",
        "role": "coder",
        "tool_name": "Bash",
        "tool_input": {"command": "git -C /repo commit -am wip"},
    }

    verdict_a = json.loads(_run_guard(["eval"], stdin=json.dumps(normalized)).stdout)
    verdict_b = json.loads(_run_guard(["eval"], stdin=json.dumps(raw_tool_call)).stdout)

    assert verdict_a == verdict_b
    assert verdict_a == {
        "decision": "deny",
        "predicate": "git-custody",
        "rule": "implementer-never-writes-git",
        "halt_code": "CODER-GIT-WRITE",
        "reason": verdict_a["reason"],
    }


def test_read_only_git_and_non_git_bash_both_allow_via_raw_tool_call() -> None:
    """A read-only git command and a bash command with no git in it at all
    both short-circuit to allow (shape b) without ever reaching a
    predicate — matching ``hooks/scripts/coder_git_guard.sh``'s own
    ``pass_silent`` for exactly those two cases."""
    for command in ["git status", "ls -la", "git -C /repo log --oneline"]:
        payload = {"harness": "claude", "role": "coder", "tool_name": "Bash", "tool_input": {"command": command}}
        verdict = json.loads(_run_guard(["eval"], stdin=json.dumps(payload)).stdout)
        assert verdict == {"decision": "allow"}, f"{command!r}: {verdict!r}"


# --------------------------------------------------------------------------
# 5. A request with no resolvable role returns `unresolved`, not `allow`.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {
            "harness": "claude",
            "role": None,
            "predicate": "write-boundary",
            "action": "fs.write",
            "context": {"write_eligible": True, "path_in_dispatch_write_scope": True},
        },
        {"harness": "claude", "role": None, "tool_name": "Write", "tool_input": {"file_path": "/tmp/x"}},
        {"harness": "claude", "tool_name": "Bash", "tool_input": {"command": "git commit -am wip"}},
    ],
    ids=["normalized-null-role", "raw-write-tool-null-role", "raw-bash-tool-missing-role"],
)
def test_no_resolvable_role_returns_unresolved_not_allow(payload: dict[str, object]) -> None:
    """DF-75: a guard that cannot identify the acting role must not
    silently allow (the permanent no-op this wave exists to kill) and must
    not blanket-deny either — it returns ``unresolved`` and lets the
    adapter decide its own harness's posture, loudly. Even a context that
    WOULD allow if role could be ignored (case 1: fully in-scope,
    write-eligible) must still come back unresolved, never allow."""
    proc = _run_guard(["eval"], stdin=json.dumps(payload))
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict["decision"] == "unresolved", verdict
    assert verdict["decision"] != "allow"
    assert "role" in verdict.get("missing", [])


# --------------------------------------------------------------------------
# 6. Malformed stdin exits non-zero WITHOUT printing an allow verdict.
# --------------------------------------------------------------------------
def test_malformed_stdin_exits_nonzero_without_printing_allow_verdict() -> None:
    proc = _run_guard(["eval"], stdin="not valid json{")
    assert proc.returncode != 0
    assert proc.stdout.strip() == "", proc.stdout
    assert '"decision": "allow"' not in proc.stdout
    assert '"decision":"allow"' not in proc.stdout


def test_content_dir_pointed_at_a_nonexistent_path_is_zero_predicates_not_a_crash(tmp_path: Path) -> None:
    """An explicit ``--content-dir`` is trusted as given (never silently
    substituted): a nonexistent directory loads zero predicates — same
    degraded-but-valid state as an empty one — so `eval` still reaches a
    real verdict (``unresolved``, since the named predicate cannot be
    found), exit 0. The engine only exits non-zero when it cannot decide
    a request AT ALL (malformed stdin) — never for a request it can
    correctly explain it has no data for."""
    nonexistent = tmp_path / "does-not-exist"
    payload = {"harness": "claude", "role": "coder", "predicate": "git-custody", "action": "vcs.write", "context": {}}
    proc = _run_guard(["eval", "--content-dir", str(nonexistent)], stdin=json.dumps(payload))
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict["decision"] == "unresolved", verdict


# --------------------------------------------------------------------------
# `guard explain` — small, but part of the three-subcommand contract.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("predicate_id", ["dedup-gate", "dispatch-scope", "git-custody", "write-boundary"])
def test_explain_prints_rules_and_examples_for_every_predicate(predicate_id: str) -> None:
    proc = _run_guard(["explain", predicate_id])
    assert proc.returncode == 0, proc.stderr
    assert predicate_id in proc.stdout
    assert "Rules:" in proc.stdout
    assert "Examples:" in proc.stdout


def test_explain_unknown_predicate_exits_nonzero() -> None:
    proc = _run_guard(["explain", "no-such-predicate"])
    assert proc.returncode != 0
    assert "no-such-predicate" in proc.stderr
