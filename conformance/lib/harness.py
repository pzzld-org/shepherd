"""conformance/lib/harness.py -- the byte-exact behavioral contract engine.

Every case freezes the canonical Rust CLI. The former Python and Bash
implementations were migration oracles only and are intentionally absent from
the release tree. Deterministic space, not latent space
(``conformance/NORMALIZATION.md``): every case is a script plus stored bytes.

The harness runs every case in a fresh ``tempfile.TemporaryDirectory`` rather
than a pytest ``tmp_path`` fixture, so it also runs standalone from
``conformance/run.sh`` outside pytest. It pins ``SHEPHERD_HOME`` to a separate
scratch user tier and strips every retired override. A case therefore cannot
read this checkout's project state or the operator's real ``~/.shepherd``.

PURE vs MUTATING (plan.md W0-S9, action 3): both kinds run in an isolated
scratch dir (always the safe default for a harness), but the label records
the SEMANTIC distinction the plan calls for -- a PURE case's captured bytes
depend only on its fixture, never on a prior invocation (idempotent
re-record); a MUTATING case's captured bytes are the record of ONE state
transition (e.g. ``run init`` scaffolding ``runs/<id>/run.json`` the first
time, then refusing the second) and its ``setup`` steps exist to walk that
transition up to the point being captured.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Fixed locations derived from this file's own position so the harness runs
# from any clone, worktree, or CI checkout.
# --------------------------------------------------------------------------
CONFORMANCE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONFORMANCE_ROOT.parent
SCHEMA_DIR = REPO_ROOT / "crates" / "registry" / "src" / "migrate" / "sql"
SCHEMA_BASE_SQL = SCHEMA_DIR / "0001_init.sql"
MIGRATIONS_DIR = SCHEMA_DIR / "migrations"

#: Every shepherd-specific override a case controls explicitly must never
#: leak in from whatever happens to be set in the host environment this
#: harness runs in (NORMALIZATION.md "env leakage").
_STRIP_ENV_KEYS = (
    "SHCTX_DB",
    "SHEPHERD_WORKDIR",
    "SHEPHERD_HOME",
    "SHCTX_ROOT_OVERRIDE",
    "SHEPHERD_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "CLAUDE_PLUGIN_ROOT",
    "SHCTX_SKILL_ROOT",
    "SHCTX_QUIET",
)

#: NORMALIZATION.md "timestamps": JSON keys this package's own models stamp
#: with epoch seconds/milliseconds -- matched by KEY NAME (an allow-list),
#: never by a bare digit-run regex, so an unrelated integer (a port number,
#: a row count) is never accidentally scrubbed.
_TS_FIELD_RE = re.compile(
    r'"(updated_at|spawned_at|last_seen_at|promised_at|created_at|refreshed_at|applied_at|ts)":\s*(-?\d+(?:\.\d+)?)'
)
#: NORMALIZATION.md "UUIDs": RFC-4122 textual form, case-insensitive.
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
#: The handoff template owns one local-calendar field. Match the complete
#: Markdown table row rather than every date-shaped string so branch names,
#: commit subjects, and authored prose remain byte-significant.
_HANDOFF_DATE_RE = re.compile(r"(?m)^\| Date \| \d{4}-\d{2}-\d{2} \|$")


@dataclass(frozen=True, slots=True)
class Case:
    """One conformance case: an invocation, its fixture, and what to capture.

    Attributes:
        case_id: The case's path relative to ``cases/``, POSIX-separated
            (e.g. ``guard-cli/dups-check/clean``) -- stable across machines,
            used as the case's display name and expected-output directory
            key.
        case_dir: The absolute directory holding ``case.json`` and its
            fixture files.
        suite: The ``--suite`` tag this case answers to (``"core"`` unless
            the case is one of the mandatory guard-cli five).
        kind: ``"pure"`` (deterministic stdout, no state transition) or
            ``"mutating"`` (captures one state transition; see the module
            docstring).
        description: One-line human summary, surfaced in ``run.sh`` output.
        setup: Argv lists run BEFORE the captured invocation, in order, in
            the same scratch cwd/env -- builds up state a MUTATING case
            needs to already exist (e.g. one ``run init`` before a second
            captures "already exists"). Never captured; asserted to exit 0.
        args: The captured invocation's argv tail, after ``shepherd`` (e.g.
            ``["dups", "check", "--stdin", "--as", "x.rs", "--json"]``).
        stdin: Bytes piped to the captured invocation's stdin, or ``None``.
        db_fixture: ``"none"`` (no DB file at all) or ``"full_schema"``
            (``0001_init.sql`` + every ``migrations/*.sql``, applied fresh).
        seed_sql: Raw SQL statements run against the fixture DB, after schema
            build and before the invocation -- mirrors ``conftest.py``'s own
            raw-``sqlite3`` fixture-row inserts.
        input_files: ``{relpath under scratch cwd: fixture file relative to
            case_dir}`` -- materialized before the invocation (e.g. a
            ``*.seed.md`` fixture ``seed verify`` reads by path).
        capture_files: Paths relative to the scratch ``SHEPHERD_WORKDIR``,
            captured (normalized) after the invocation -- e.g.
            ``runs/<id>/run.json``.
        capture_sqlite_master: When True, an order-normalized
            ``sqlite_master`` dump of the fixture DB is captured after the
            invocation (the registry parity surface: 45 tables, 14 views, 68
            indexes, 7 triggers, 19 tables carrying a ``json_valid`` CHECK,
            2 FTS5 external-content tables tokenized
            ``unicode61 remove_diacritics 2`` -- verified empirically against
            a freshly-built schema DB while authoring this corpus).
        authority: The frozen contract authority. It must be
            ``native-v6.4.5``. Legacy authority values are rejected so a
            deleted implementation cannot become a hidden recording path.
    """

    case_id: str
    case_dir: Path
    suite: str
    kind: str
    description: str
    setup: list[list[str]]
    args: list[str]
    stdin: str | None
    db_fixture: str
    seed_sql: list[str]
    input_files: dict[str, str]
    capture_files: list[str]
    capture_sqlite_master: bool
    requires_git: bool
    authority: str

    @property
    def expected_dir(self) -> Path:
        return self.case_dir / "expected"


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Everything captured from one real invocation of a :class:`Case`."""

    exit_code: int
    stdout: str
    stderr: str
    files: dict[str, str]
    sqlite_master: str | None


@dataclass(frozen=True, slots=True)
class Verdict:
    """The outcome of comparing a fresh :class:`CaseResult` to stored bytes."""

    case: Case
    passed: bool
    diffs: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Case discovery.
# --------------------------------------------------------------------------
def discover_cases(cases_dir: Path, suite: str | None) -> list[Case]:
    """Every ``case.json`` under ``cases_dir``, optionally filtered by suite.

    Args:
        cases_dir: The corpus root (``conformance/cases``).
        suite: When given, only cases whose ``"suite"`` field equals this
            value are returned; ``None`` returns the whole corpus.

    Returns:
        Cases sorted by ``case_id`` -- a stable, deterministic order so
        ``run.sh``'s own output is itself byte-reproducible run to run.
    """
    cases = [load_case(p, cases_dir) for p in sorted(cases_dir.rglob("case.json"))]
    if suite is not None:
        cases = [c for c in cases if c.suite == suite]
    return sorted(cases, key=lambda c: c.case_id)


def load_case(case_json_path: Path, cases_dir: Path) -> Case:
    """Parse one ``case.json`` plus its on-disk fixture files into a :class:`Case`.

    Args:
        case_json_path: The ``case.json`` file to load.
        cases_dir: The corpus root, for computing ``case_id``.

    Returns:
        The parsed case, with ``input_files``/``stdin`` fixture CONTENT
        already read off disk (case.json itself only names the fixture
        files, so authoring a case never means JSON-escaping source text).
    """
    case_dir = case_json_path.parent
    data = json.loads(case_json_path.read_text())
    input_files = {
        relpath: (case_dir / fname).read_text() for relpath, fname in data.get("input_files", {}).items()
    }
    stdin_file = data.get("stdin_file")
    stdin = (case_dir / stdin_file).read_text() if stdin_file else None
    authority = data.get("authority", "native-v6.4.5")
    if authority != "native-v6.4.5":
        raise ValueError(f"{case_json_path}: only native-v6.4.5 authority is supported")
    return Case(
        case_id=case_dir.relative_to(cases_dir).as_posix(),
        case_dir=case_dir,
        suite=data.get("suite", "core"),
        kind=data["kind"],
        description=data["description"],
        setup=data.get("setup", []),
        args=data["args"],
        stdin=stdin,
        db_fixture=data.get("db_fixture", "none"),
        seed_sql=data.get("seed_sql", []),
        input_files=input_files,
        capture_files=data.get("capture_files", []),
        capture_sqlite_master=data.get("capture_sqlite_master", False),
        requires_git=data.get("requires_git", False),
        authority=authority,
    )


# --------------------------------------------------------------------------
# Schema construction -- mirrors conftest.py's build_full_schema_db exactly
# (same files, same sorted order, same stdlib sqlite3 apply path).
# --------------------------------------------------------------------------
def build_schema_db(db_path: Path) -> None:
    """Apply ``0001_init.sql`` then every ``migrations/*.sql``, in sorted order.

    Applies the shipped schema and migration files exactly, INCLUDING its
    ``schema_versions`` bookkeeping: a migration file
    (unlike ``0001_init.sql``) never self-inserts its own ``schema_versions``
    row, so this function does it after each successful apply. Skipping
    that step leaves ``schema_versions`` short even though every table
    exists -- ``shepherd_cli.db.schema_is_current()`` then reports the DB as
    behind the shipped migrations, which is exactly the false "schema
    behind" failure this function exists to NOT produce.

    Args:
        db_path: Where to create the sqlite file; parent must already exist.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_BASE_SQL.read_text())
        conn.commit()
        for migration_sql in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            conn.executescript(migration_sql.read_text())
            version = int(migration_sql.name[:4])
            checksum = hashlib.sha256(migration_sql.read_bytes()).hexdigest()
            conn.execute(
                "INSERT OR IGNORE INTO schema_versions (version, applied_at, checksum) VALUES (?, ?, ?)",
                (version, int(time.time()), checksum),
            )
            conn.commit()
    finally:
        conn.close()


def dump_sqlite_master(db_path: Path) -> str:
    """An order-normalized ``sqlite_master`` dump -- the registry parity surface.

    Args:
        db_path: The fixture DB to dump.

    Returns:
        One ``type\\tname\\ttbl_name\\tsql\\n`` line per catalog entry,
        ``ORDER BY type, name`` (never physical/rowid order, which SQLite
        does not guarantee stable across writes) -- this ordering, not the
        capture step, is what makes the dump reproducible.
    """
    # No name filter: SQLite's own bookkeeping rows (sqlite_sequence for
    # AUTOINCREMENT, sqlite_autoindex_* for unnamed UNIQUE-constraint
    # indexes) are part of the real fingerprint -- a port that models a
    # column differently (e.g. drops AUTOINCREMENT, or names a UNIQUE
    # index explicitly) changes exactly these rows, which is precisely the
    # drift this dump exists to catch. This is also what makes the count
    # match the plan.md-cited surface verified while authoring this corpus:
    # 45 tables, 14 views, 68 indexes, 7 triggers.
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    finally:
        conn.close()
    # A multi-line CREATE TABLE's own sql text contains real newlines --
    # escaped here (literal "\n") so the dump is actually one line per
    # catalog entry, matching this function's own contract, rather than a
    # tab-separated prefix followed by however many DDL-formatting lines
    # the original author wrapped their columns across.
    return "".join(
        f"{kind}\t{name}\t{tbl_name}\t{(sql or '').replace(chr(10), chr(92) + 'n')}\n" for kind, name, tbl_name, sql in rows
    )


# --------------------------------------------------------------------------
# Normalization -- conformance/NORMALIZATION.md is the authoritative doc;
# this is its implementation. Every substitution is targeted (a key-name
# allow-list, a path we know, an RFC-4122 shape) -- never a blanket digit
# regex, which would silently scrub unrelated numbers.
# --------------------------------------------------------------------------
def normalize(text: str, *, scratch: Path) -> str:
    """Apply every documented non-determinism substitution to captured text.

    Args:
        text: Raw captured bytes (stdout, stderr, a captured file, or a
            sqlite_master dump).
        scratch: This case's own scratch root -- its absolute path is the
            first substitution (it is unique per invocation by construction,
            so it can never collide with real content).

    Returns:
        ``text`` with every NORMALIZATION.md rule applied.
    """
    out = text
    # macOS exposes `/var` through a `/private/var` canonical path. Native
    # ExecutionContext deliberately canonicalizes its primary root, while the
    # Python oracle preserves the tempfile spelling; both name one fixture.
    out = out.replace(f"/private{scratch}", "<SCRATCH>")
    out = out.replace(str(scratch), "<SCRATCH>")
    out = out.replace(str(REPO_ROOT), "<REPO_ROOT>")
    out = _UUID_RE.sub("<UUID>", out)
    out = _TS_FIELD_RE.sub(lambda m: f'"{m.group(1)}": <TS>', out)
    out = _HANDOFF_DATE_RE.sub("| Date | <DATE> |", out)
    hostname = socket.gethostname()
    if hostname and hostname in out:
        out = out.replace(hostname, "<HOSTNAME>")
    return out


# --------------------------------------------------------------------------
# Execution.
# --------------------------------------------------------------------------
def _build_env(cwd_dir: Path, workdir: Path, db_path: Path) -> dict[str, str]:
    """The isolated environment every case runs under.

    Strip every Shepherd override the host environment might carry, then pin
    the one supported user-tier override to a path inside the scratch fixture.
    ``workdir`` and ``db_path`` are accepted for call-site clarity; the native
    CLI derives those project paths from ``cwd_dir`` and does not honor the
    retired environment variables. Pins ``LC_ALL``/``TZ`` per NORMALIZATION.md
    "locale" rather than normalizing locale-dependent output after the
    fact -- pinning at the source is strictly more reliable than scrubbing
    downstream.
    """
    env = dict(os.environ)
    for key in _STRIP_ENV_KEYS:
        env.pop(key, None)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env["SHEPHERD_HOME"] = str(cwd_dir / ".shepherd-user")
    env["LC_ALL"] = "C"
    env["TZ"] = "UTC"
    return env


def _run_cli(
    args: list[str],
    *,
    impl: str,
    rust_bin: Path | None,
    stdin: str | None,
    env: dict[str, str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the canonical Rust CLI as a subprocess."""
    if impl != "rust":
        raise ValueError("the conformance harness is Rust-only")
    if rust_bin is None or not rust_bin.is_file():
        raise RuntimeError(f"Rust implementation binary is missing: {rust_bin}")
    command = [str(rust_bin), *args]

    return subprocess.run(
        command,
        input=stdin,
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )


def run_case(case: Case, *, impl: str = "rust", rust_bin: Path | None = None) -> CaseResult:
    """Execute one case end to end in a fresh, isolated scratch dir.

    Args:
        case: The case to run.

    Returns:
        The normalized :class:`CaseResult`.
    """
    with tempfile.TemporaryDirectory(prefix="shepherd-conformance-") as tmp:
        scratch = Path(tmp)
        cwd_dir = scratch / "cwd"
        workdir = cwd_dir / ".shepherd"
        cwd_dir.mkdir(parents=True)
        workdir.mkdir(parents=True)
        db_path = workdir / "shepherd.db"

        if case.requires_git:
            initialized = subprocess.run(
                ["git", "init", "--quiet"],
                cwd=str(cwd_dir),
                capture_output=True,
                text=True,
                check=False,
            )
            if initialized.returncode != 0:
                raise RuntimeError(
                    f"{case.case_id}: cannot initialize isolated git fixture: {initialized.stderr.strip()}"
                )

        for relpath, content in case.input_files.items():
            target = cwd_dir / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        if case.db_fixture == "full_schema":
            build_schema_db(db_path)
            if case.seed_sql:
                conn = sqlite3.connect(str(db_path))
                try:
                    for statement in case.seed_sql:
                        conn.execute(statement)
                    conn.commit()
                finally:
                    conn.close()
        elif case.db_fixture != "none":
            raise ValueError(f"{case.case_id}: unknown db_fixture {case.db_fixture!r}")

        env = _build_env(cwd_dir, workdir, db_path)

        for setup_args in case.setup:
            setup_proc = _run_cli(
                setup_args,
                impl=impl,
                rust_bin=rust_bin,
                stdin=None,
                env=env,
                cwd=cwd_dir,
            )
            if setup_proc.returncode != 0:
                raise RuntimeError(
                    f"{case.case_id}: setup step {setup_args!r} exited "
                    f"{setup_proc.returncode} (stderr: {setup_proc.stderr!r}) -- fixture is broken, not a case result"
                )

        proc = _run_cli(
            case.args,
            impl=impl,
            rust_bin=rust_bin,
            stdin=case.stdin,
            env=env,
            cwd=cwd_dir,
        )

        files: dict[str, str] = {}
        for relpath in case.capture_files:
            target = workdir / relpath
            content = target.read_text() if target.is_file() else "<MISSING>"
            files[relpath] = normalize(content, scratch=scratch)

        sqlite_master = None
        if case.capture_sqlite_master:
            sqlite_master = normalize(dump_sqlite_master(db_path), scratch=scratch)

        return CaseResult(
            exit_code=proc.returncode,
            stdout=normalize(proc.stdout, scratch=scratch),
            stderr=normalize(proc.stderr, scratch=scratch),
            files=files,
            sqlite_master=sqlite_master,
        )


# --------------------------------------------------------------------------
# Record (author-time: freeze live CLI output as the golden bytes) and
# verify (the oracle's actual job: does the CLI still match the freeze?).
# --------------------------------------------------------------------------
def _file_key(relpath: str) -> str:
    """A filesystem-safe filename for one ``capture_files`` entry."""
    return relpath.replace("/", "__")


def record_case(
    case: Case,
    *,
    impl: str = "rust",
    rust_bin: Path | None = None,
) -> CaseResult:
    """Run ``case`` live and (re)write its ``expected/`` directory from the result.

    Author-time only -- never called by ``run.sh``'s own acceptance paths
    (``--count``/plain run/``--verify-checksum``), only by
    ``runner.py --record`` when building or intentionally re-freezing a
    case. This is the ONE place that decides what "correct" means for a
    case; everything else compares against what it wrote.
    """
    if case.authority != "native-v6.4.5" or impl != "rust":
        raise ValueError(f"{case.case_id}: conformance recording is Rust-only")
    result = run_case(case, impl=impl, rust_bin=rust_bin)
    expected = case.expected_dir
    expected.mkdir(parents=True, exist_ok=True)
    (expected / "exit_code").write_text(f"{result.exit_code}\n")
    (expected / "stdout.txt").write_text(result.stdout)
    (expected / "stderr.txt").write_text(result.stderr)
    if result.files:
        files_dir = expected / "files"
        files_dir.mkdir(exist_ok=True)
        for relpath, content in result.files.items():
            (files_dir / f"{_file_key(relpath)}.txt").write_text(content)
    if result.sqlite_master is not None:
        (expected / "sqlite_master.txt").write_text(result.sqlite_master)
    return result


def verify_case(case: Case, *, impl: str = "rust", rust_bin: Path | None = None) -> Verdict:
    """Run ``case`` live and diff the result against its stored ``expected/`` bytes.

    Args:
        case: The case to verify.

    Returns:
        A :class:`Verdict` -- ``passed`` True only when exit code, stdout,
        stderr (when a golden ``stderr.txt`` was recorded), every captured
        file, and the sqlite_master dump (when applicable) all match
        exactly.
    """
    try:
        result = run_case(case, impl=impl, rust_bin=rust_bin)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        return Verdict(case=case, passed=False, diffs=[f"execution error: {error}"])
    expected = case.expected_dir
    diffs: list[str] = []

    exit_path = expected / "exit_code"
    if not exit_path.is_file():
        return Verdict(case=case, passed=False, diffs=[f"no recorded expected/ at {expected} -- run --record first"])
    expected_exit = int(exit_path.read_text().strip())
    if result.exit_code != expected_exit:
        diffs.append(f"exit_code: expected {expected_exit}, got {result.exit_code}")

    expected_stdout = (expected / "stdout.txt").read_text()
    if result.stdout != expected_stdout:
        diffs.append(f"stdout mismatch (expected {len(expected_stdout)} bytes, got {len(result.stdout)})")

    stderr_path = expected / "stderr.txt"
    if stderr_path.is_file():
        expected_stderr = stderr_path.read_text()
        if result.stderr != expected_stderr:
            diffs.append(f"stderr mismatch (expected {len(expected_stderr)} bytes, got {len(result.stderr)})")

    for relpath in case.capture_files:
        fp = expected / "files" / f"{_file_key(relpath)}.txt"
        expected_content = fp.read_text() if fp.is_file() else None
        actual_content = result.files.get(relpath)
        if actual_content != expected_content:
            diffs.append(f"file mismatch: {relpath}")

    if case.capture_sqlite_master:
        sm_path = expected / "sqlite_master.txt"
        expected_sm = sm_path.read_text() if sm_path.is_file() else None
        if result.sqlite_master != expected_sm:
            diffs.append("sqlite_master mismatch")

    return Verdict(case=case, passed=not diffs, diffs=diffs)
