# Security Policy

## Supported versions

Security fixes are made for the latest published Shepherd release. Older
releases are unsupported. Upgrade to the latest release before reporting unless
the version difference is part of the vulnerability.

| Version | Supported |
| --- | --- |
| Latest published release | Yes |
| Earlier releases | No |

## Private reporting

Do not open a public issue for a suspected vulnerability. Use
[GitHub private vulnerability reporting](https://github.com/pzzld-org/shepherd/security/advisories/new).
If that channel is unavailable, email `security@pzzld.org` with the affected
version, impact, reproduction, and any proposed mitigation. Do not include
secrets or personal data that are not needed to reproduce the report.

Use the public issue tracker for ordinary correctness and compatibility defects
that do not cross a security boundary.

## Response process

The maintainers will:

1. acknowledge a report within three business days;
2. validate scope and severity, then provide a status update within seven
   business days;
3. coordinate a fix, regression test, advisory, and release when confirmed;
4. credit the reporter unless anonymity is requested; and
5. publish material changes after affected users have a reasonable upgrade
   window.

These are response targets, not a guarantee that every investigation or fix
will complete within those periods. Reporters will receive updates when the
assessment or schedule changes.

## Coordinated disclosure

Keep vulnerability details private until maintainers and the reporter agree on
a disclosure date or 90 days have passed without a mutually agreed extension.
The project will coordinate a GitHub security advisory, patched release, and
release notes. If a report is not accepted, the maintainers will explain the
scope decision so the reporter can disclose it accurately.

## Scope

Security reports include defects that can cross a trust boundary in:

- tool-call, session, run, lane, role, or agent identity;
- guard decisions and least-authority write scope;
- native CLI, Component Model, or harness adapter input handling;
- release artifacts, installers, checksums, or package provenance;
- dependency compromise that is reachable from a shipped artifact; and
- descriptor-safe filesystem publication or migration.

Unsupported host behavior, documentation errors, feature requests, and
ordinary correctness and compatibility defects belong in the public issue
tracker unless they demonstrate security impact.

## Safe harbor

The project will not pursue legal action against good-faith research that:

- stays within accounts and systems the researcher owns or has permission to
  test;
- avoids privacy violations, data destruction, persistence, social engineering,
  and service disruption;
- uses only the access needed to demonstrate the issue;
- reports the issue promptly through the private channel; and
- follows coordinated disclosure.

This safe harbor applies only to claims controlled by this project and does not
bind third parties. If uncertainty about scope could put users or systems at
risk, ask through the private reporting channel before continuing.
