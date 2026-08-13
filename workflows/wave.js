export const meta = {
  name: 'wave',
  description: 'Execute one shepherd wave: fan out file-disjoint coder steps, verify ONCE centrally.',
  whenToUse:
    'When a shepherd run has an approved plan and a wave of file-disjoint steps to execute. ' +
    'Pass the wave spec as args. This is the sanctioned fan-out vehicle — do not hand-roll a ' +
    'batch of Agent() calls, and do not fan out the verify phase.',
  phases: [
    { title: 'Implement', detail: 'one coder per file-disjoint step, concurrently' },
    { title: 'Verify', detail: 'ONE central auditor — the only agent permitted to build' },
  ],
}

// ---------------------------------------------------------------------------
// args contract (pass as a real JSON object, never a JSON-encoded string —
// a stringified value arrives as one string and every .map/.filter below throws)
//
// {
//   repo:      "/abs/path/to/checkout",       // where coders work
//   run:       "v645",                        // run id
//   wave:      "W2",                          // wave label, used in report names
//   plan:      "/abs/path/to/plan.md",         // steps carry their full spec here
//   reports:   "/abs/path/to/reports",         // durable deliverable directory
//   steps: [                                   // file-disjoint; see the guard below
//     { id: "W2-S1", model: "sonnet", brief: "...", scope: ["crates/render/src/env.rs"] }
//   ],
//   verify: { brief: "...", model: "sonnet", commands: ["cargo test -p foo"] }
// }
// ---------------------------------------------------------------------------

const a = args || {}
const REPO = a.repo
const RUN = a.run
const WAVE = a.wave || 'W'
const REPORTS = a.reports
const STEPS = Array.isArray(a.steps) ? a.steps : []

if (!REPO || !REPORTS || STEPS.length === 0)
  throw new Error(
    'WAVE-ARGS-INCOMPLETE: args must carry repo, reports and a non-empty steps[]. ' +
      'Pass args as a JSON object, not a JSON-encoded string.'
  )

// Dispatch law (#255). Agent() and Workflow agent() are the same law under two
// spellings; omitting either option is the SAME violation. The Workflow runtime
// never reads shepherd.toml [models], so `model` MUST be pinned literally here —
// an unpinned call silently inherits the host session's model.
function flockAgent(prompt, opts = {}) {
  if (!opts.agentType || !opts.agentType.startsWith('shepherd:'))
    throw new Error('DISPATCH-MISSING-SUBAGENT-TYPE: agentType must be shepherd:<role>')
  if (!opts.model) throw new Error('DISPATCH-MODEL-UNPINNED: Workflow agent() bypasses [models]')
  return agent(prompt, opts)
}

// Fan-out counterweight (#256) rule 1: file-disjointness authorizes concurrent
// WRITES. Two steps claiming the same path is a plan defect, not a race to
// discover at runtime — fail before spawning anything.
const claimed = new Map()
for (const s of STEPS)
  for (const p of s.scope || []) {
    if (claimed.has(p))
      throw new Error(`WAVE-SCOPE-OVERLAP: ${s.id} and ${claimed.get(p)} both claim ${p}`)
    claimed.set(p, s.id)
  }

// GH #270: a dispatched agent's return value routes to the task-tree owner, not
// to this script. The contracted deliverable is a file on disk, always.
const deliverable = (path) => `
YOUR CONTRACTED DELIVERABLE IS A FILE ON DISK at exactly:
  ${path}
Write it with the Write tool before you finish. Your chat return value is NOT
collected — a report that exists only in your reply is a failed dispatch.
Absolute paths only. Repo root is ${REPO}.`

// #256 rule 2: fan out fixes, verify ONCE centrally. N agents each running the
// project's build is the documented way this box gets taken down — measured at
// 12 concurrent cargo invocations driving free memory to 16 MB and swap to
// 8.6 GB, with the kernel SIGKILLing a lane doing useful work.
const noBuild = `
RESOURCE DISCIPLINE (#256, binding): do NOT run the project's build or test
command. Other agents are running concurrently. Verification is centralized and
happens ONCE, after this phase. Write code and reason about correctness; the
central verifier compiles. State every assumption that needs compile-time
confirmation in your report so that verification is fast.`

phase('Implement')

const built = await parallel(
  STEPS.map((s) => () =>
    flockAgent(
      `Implement step \`${s.id}\`.

WORK IN: ${REPO}
Read the full step spec first — it is the contract, and this brief is only a pointer:
  ${a.plan || '(no plan path supplied)'}  §${s.id}
It carries [SKILLS], [CONTEXT-INVENTORY], [DO-NOT-DUPLICATE], [USER-STYLE],
[FILE-SCOPE], [NON-GOALS] and [ACCEPTANCE]. Honor every one.

file_scope.exclusive (yours alone this wave; siblings hold the rest):
${(s.scope || []).map((p) => `  ${p}`).join('\n') || '  (see the plan)'}
Writing outside that scope collides with a concurrent sibling.

${s.brief || ''}
${noBuild}
${deliverable(`${REPORTS}/coder-${s.id}.md`)}`,
      {
        agentType: s.agentType || 'shepherd:coder',
        model: s.model || 'sonnet',
        label: `coder:${s.id}`,
        phase: 'Implement',
      }
    )
  )
)

const landed = built.filter(Boolean).length
log(`${WAVE}: ${landed}/${STEPS.length} steps returned`)
if (landed < STEPS.length)
  log(`WARNING: ${STEPS.length - landed} step(s) died or were skipped — the verifier is told to treat their scope as unwritten, NOT as passing.`)

phase('Verify')

const verify = a.verify || {}
const verdict = await flockAgent(
  `You are the CENTRAL verification auditor for ${RUN} ${WAVE}. READ-ONLY: no edits, no git writes.

You are the ONLY agent this wave permitted to build. Everything below was written by
agents that were forbidden to compile, so their reports list ASSUMPTIONS needing
compile-time confirmation — check every one.

Steps to verify (${landed} of ${STEPS.length} returned):
${STEPS.map((s) => `  ${s.id} — report: ${REPORTS}/coder-${s.id}.md`).join('\n')}
${landed < STEPS.length ? '\nA step whose report is ABSENT did not complete. Treat its scope as UNWRITTEN and fail it — absence is not a pass.\n' : ''}
${verify.commands && verify.commands.length ? `Run these SERIALLY, one at a time, never a workspace-wide parallel build:
${verify.commands.map((c) => `  ${c}`).join('\n')}
Read each command's OWN exit code — redirect to a file and echo it. Do NOT pipe
through tail/head and read $? from the pipe; that reads the pipe's status and has
produced false findings before.` : ''}

${verify.brief || ''}

A GREEN SUITE IS NOT A GATE. Before returning PASS, prove the check can FAIL:
mutate the implementation at a load-bearing line, confirm the relevant assertion
fails, then restore it and confirm the tree is byte-identical. Report what you
mutated and what failed. A PASS on a check you did not prove falsifiable is not a
PASS — say so instead.

VERDICT per step: PASS or REDO, blocking items enumerated, every claim grounded in
a command you ran and its verbatim output.
${deliverable(`${REPORTS}/auditor-${WAVE}-central-verify.md`)}`,
  {
    agentType: 'shepherd:auditor',
    model: verify.model || 'sonnet',
    label: `verify:${WAVE}-central`,
    phase: 'Verify',
  }
)

return {
  run: RUN,
  wave: WAVE,
  steps_dispatched: STEPS.length,
  steps_returned: landed,
  verify: verdict ? 'returned' : 'FAILED to return',
  reports: [
    ...STEPS.map((s) => `${REPORTS}/coder-${s.id}.md`),
    `${REPORTS}/auditor-${WAVE}-central-verify.md`,
  ],
}
