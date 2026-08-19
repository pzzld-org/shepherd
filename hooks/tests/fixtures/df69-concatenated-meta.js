// hooks/tests/fixtures/df69-concatenated-meta.js — the NEGATIVE control corpus
// for `scripts/check-workflow-meta.sh --self-test` (DF-69).
//
// THIS FILE IS DELIBERATELY WRONG. Do not "fix" it, do not reformat it, and do
// not collapse the three `+`-joined fragments below into one string. Its only
// job is to be REJECTED. The self-test asserts both that the gate rejects it
// AND that the stated reason is `BinaryExpression` — a `+` operator surviving
// outside every string literal — because a fixture rejected for some unrelated
// reason (unparseable, no block found, a different construct) would keep
// printing PASS long after the concatenation check itself had broken.
//
// WHY A TRACKED FILE AND NOT A COMMIT. This corpus used to be recovered at
// self-test time with `git show <sha>:workflows/wave.js` against the commit
// that first shipped the defect. That is archaeology, and it is fragile twice
// over. The object is already absent from this clone — history was truncated
// in an org transfer — and `actions/checkout` defaults to `fetch-depth: 1`, so
// `git show <old-sha>` cannot resolve in CI even in a repository that still
// holds the object. A control that depends on git history is a control that
// stops controlling without anyone noticing, which is the exact failure class
// this gate exists to prevent. A file in the tree cannot rot that way, and it
// works identically in a shallow checkout, a fresh clone, and a tarball.
//
// FIDELITY. The three fragments below concatenate to precisely the text that
// `workflows/wave.js` carries today: the v6.4.5 hotfix collapsed the
// concatenation without changing a byte of the resulting string. So the ONLY
// difference between this file and the shipped one is the defect under test,
// which is what makes the control specific rather than incidental.
//
// NOT A WORKFLOW. It lives outside `workflows/`, so the normal-mode scan never
// sees it and it can never be dispatched; the self-test reads it by path.

export const meta = {
  name: 'wave',
  description: 'Execute one shepherd wave: fan out file-disjoint coder steps, verify ONCE centrally.',
  whenToUse:
    'When a shepherd run has an approved plan and a wave of file-disjoint steps to execute. ' +
    'Pass the wave spec as args. This is the sanctioned fan-out vehicle — do not hand-roll ' +
    'a batch of Agent() calls, and do not fan out the verify phase.',
  phases: [
    { title: 'Implement', detail: 'one coder per file-disjoint step, concurrently' },
    { title: 'Verify', detail: 'ONE central auditor — the only agent permitted to build' },
  ],
}
