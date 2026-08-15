#!/usr/bin/env python3
"""Verify every workflow action against the offline immutable-action lock."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


LOCK_RELATIVE_PATH = Path(".github/actions-lock.json")
WORKFLOWS_RELATIVE_PATH = Path(".github/workflows")
EXPECTED_TOP_LEVEL_KEYS = {"actions", "refresh_by", "schema", "verified_at"}
EXPECTED_RECORD_KEYS = {"selector", "sha", "tag"}
ALLOWED_RECORD_KEYS = EXPECTED_RECORD_KEYS | {"channel"}
ALLOWED_SELECTORS = {
    "latest-release",
    "highest-stable-tag-in-supported-major",
    "highest-stable-tag-plus-channel",
}
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SEMVER_TAG_PATTERN = re.compile(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
CHANNEL_PATTERN = re.compile(r"v(?:0|[1-9][0-9]*)")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
USES_LINE_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<scalar>.*?)\s*$")
USES_SCALAR_PATTERN = re.compile(
    r"(?P<action>\S+)(?:[ \t]+#[ \t]*(?P<tag>\S+)[ \t]*)?"
)
EXTERNAL_ACTION_PATTERN = re.compile(
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"(?P<subpath>/[^@\s]+)?@(?P<reference>\S+)"
)
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class DuplicateKeyError(ValueError):
    """Raised when JSON repeats an object key."""


def object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class ActionRecord:
    tag: str
    sha: str


@dataclass(frozen=True, order=True)
class Diagnostic:
    path: str
    line: int
    message: str

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: {self.message}"


def parse_timestamp(
    value: object,
    field: str,
    diagnostics: list[Diagnostic],
) -> datetime | None:
    if not isinstance(value, str):
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, f"{field} must be a UTC timestamp")
        )
        return None
    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        diagnostics.append(
            Diagnostic(
                str(LOCK_RELATIVE_PATH),
                0,
                f"{field} must use YYYY-MM-DDTHH:MM:SSZ: {value}",
            )
        )
        return None
    return parsed.replace(tzinfo=timezone.utc)


def read_lock(
    root: Path,
    now: datetime,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, ActionRecord], datetime | None]:
    lock_path = root / LOCK_RELATIVE_PATH
    try:
        raw = json.loads(
            lock_path.read_text(encoding="utf-8"),
            object_pairs_hook=object_without_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as error:
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, f"cannot read canonical lock: {error}")
        )
        return {}, None

    if not isinstance(raw, dict):
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, "lock root must be a JSON object")
        )
        return {}, None

    if list(raw) != sorted(raw):
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, "top-level keys must be sorted")
        )
    unexpected_keys = set(raw) - EXPECTED_TOP_LEVEL_KEYS
    missing_keys = EXPECTED_TOP_LEVEL_KEYS - set(raw)
    for key in sorted(unexpected_keys):
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, f"unknown top-level key: {key}")
        )
    for key in sorted(missing_keys):
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, f"missing top-level key: {key}")
        )
    if raw.get("schema") != 1:
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, "schema must equal 1")
        )

    verified_at = parse_timestamp(raw.get("verified_at"), "verified_at", diagnostics)
    refresh_by = parse_timestamp(raw.get("refresh_by"), "refresh_by", diagnostics)
    if verified_at is not None and refresh_by is not None:
        if verified_at > refresh_by:
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    "verified_at must not be later than refresh_by",
                )
            )
        if now < verified_at:
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"action lock is not valid before {raw['verified_at']}",
                )
            )
        if now > refresh_by:
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"action lock expired at {raw['refresh_by']}",
                )
            )

    raw_actions = raw.get("actions")
    if not isinstance(raw_actions, dict) or not raw_actions:
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, "actions must be a non-empty object")
        )
        return {}, verified_at
    if list(raw_actions) != sorted(raw_actions):
        diagnostics.append(
            Diagnostic(str(LOCK_RELATIVE_PATH), 0, "action repositories must be sorted")
        )

    records: dict[str, ActionRecord] = {}
    for repository, value in raw_actions.items():
        if not isinstance(repository, str) or not REPOSITORY_PATTERN.fullmatch(repository):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"invalid action repository key: {repository}",
                )
            )
            continue
        if not isinstance(value, dict):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"action record must be an object: {repository}",
                )
            )
            continue
        if list(value) != sorted(value):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"action record keys must be sorted: {repository}",
                )
            )
        for key in sorted(set(value) - ALLOWED_RECORD_KEYS):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"unknown key for {repository}: {key}",
                )
            )
        for key in sorted(EXPECTED_RECORD_KEYS - set(value)):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"missing key for {repository}: {key}",
                )
            )

        tag = value.get("tag")
        sha = value.get("sha")
        selector = value.get("selector")
        channel = value.get("channel")
        valid = True
        if not isinstance(tag, str) or not SEMVER_TAG_PATTERN.fullmatch(tag):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"tag must be an exact stable semver for {repository}: {tag}",
                )
            )
            valid = False
        if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"sha must be a 40-character lowercase commit for {repository}",
                )
            )
            valid = False
        if selector not in ALLOWED_SELECTORS:
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"unsupported selector for {repository}: {selector}",
                )
            )
            valid = False
        if channel is not None and (
            not isinstance(channel, str) or not CHANNEL_PATTERN.fullmatch(channel)
        ):
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"channel must be an exact major tag for {repository}: {channel}",
                )
            )
            valid = False
        if selector in {
            "highest-stable-tag-in-supported-major",
            "highest-stable-tag-plus-channel",
        } and channel is None:
            diagnostics.append(
                Diagnostic(
                    str(LOCK_RELATIVE_PATH),
                    0,
                    f"selector requires channel for {repository}: {selector}",
                )
            )
            valid = False
        if valid:
            records[repository] = ActionRecord(tag=tag, sha=sha)

    return records, verified_at


def workflow_paths(root: Path) -> list[Path]:
    directory = root / WORKFLOWS_RELATIVE_PATH
    return sorted((*directory.glob("*.yml"), *directory.glob("*.yaml")))


def check_workflows(
    root: Path,
    records: dict[str, ActionRecord],
    diagnostics: list[Diagnostic],
) -> tuple[int, set[str], int]:
    paths = workflow_paths(root)
    used_repositories: set[str] = set()
    external_uses = 0
    canonical_by_fold = {key.casefold(): key for key in records}

    for path in paths:
        relative_path = str(path.relative_to(root))
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            diagnostics.append(Diagnostic(relative_path, 0, f"cannot read workflow: {error}"))
            continue
        for line_number, line in enumerate(lines, 1):
            uses_line = USES_LINE_PATTERN.match(line)
            if uses_line is None:
                continue
            scalar = uses_line.group("scalar")
            scalar_match = USES_SCALAR_PATTERN.fullmatch(scalar)
            if scalar_match is None:
                external_uses += 1
                diagnostics.append(
                    Diagnostic(
                        relative_path,
                        line_number,
                        "uses scalar must be an unquoted action followed by '# <exact-tag>'",
                    )
                )
                continue

            action = scalar_match.group("action")
            tag_comment = scalar_match.group("tag")
            if action.startswith("./") or action.startswith("docker://"):
                continue
            external_uses += 1
            action_match = EXTERNAL_ACTION_PATTERN.fullmatch(action)
            if action_match is None:
                diagnostics.append(
                    Diagnostic(
                        relative_path,
                        line_number,
                        "external uses must be owner/repository[/subpath]@commit",
                    )
                )
                continue

            repository = action_match.group("repository")
            reference = action_match.group("reference")
            if not SHA_PATTERN.fullmatch(reference):
                diagnostics.append(
                    Diagnostic(
                        relative_path,
                        line_number,
                        "reference must be a 40-character lowercase commit SHA",
                    )
                )

            record = records.get(repository)
            if record is None:
                canonical = canonical_by_fold.get(repository.casefold())
                if canonical is not None:
                    message = f"action repository casing must be canonical: {canonical}"
                else:
                    message = (
                        "action repository is absent from "
                        f"{LOCK_RELATIVE_PATH}: {repository}"
                    )
                diagnostics.append(Diagnostic(relative_path, line_number, message))
                continue

            used_repositories.add(repository)
            if SHA_PATTERN.fullmatch(reference) and reference != record.sha:
                diagnostics.append(
                    Diagnostic(
                        relative_path,
                        line_number,
                        f"commit SHA must equal locked SHA {record.sha}",
                    )
                )
            if tag_comment != record.tag:
                diagnostics.append(
                    Diagnostic(
                        relative_path,
                        line_number,
                        f"tag comment must be exactly '# {record.tag}'",
                    )
                )

    for repository in sorted(set(records) - used_repositories):
        diagnostics.append(
            Diagnostic(
                str(LOCK_RELATIVE_PATH),
                0,
                f"lock entry is not used by any workflow: {repository}",
            )
        )
    return len(paths), used_repositories, external_uses


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    noun = singular if count == 1 else plural_form or f"{singular}s"
    return f"{count} {noun}"


def parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.strptime(value, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"--now must use YYYY-MM-DDTHH:MM:SSZ: {value}"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--now",
        help="UTC timestamp override for deterministic tests (YYYY-MM-DDTHH:MM:SSZ)",
    )
    arguments = parser.parse_args(argv)
    try:
        now = parse_now(arguments.now)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))

    root = arguments.root.resolve()
    diagnostics: list[Diagnostic] = []
    records, verified_at = read_lock(root, now, diagnostics)
    workflow_count, used_repositories, external_uses = check_workflows(
        root, records, diagnostics
    )

    if diagnostics:
        print("GitHub Actions pin contract failed:", file=sys.stderr)
        for diagnostic in sorted(diagnostics):
            print(diagnostic.render(), file=sys.stderr)
        return 1

    assert verified_at is not None
    lock_age_days = (now - verified_at).days
    print(
        "ok: "
        f"{plural(workflow_count, 'workflow file')}, "
        f"{plural(external_uses, 'external use')}, "
        f"{plural(len(used_repositories), 'repository', 'repositories')}; "
        f"lock age {lock_age_days}d"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
