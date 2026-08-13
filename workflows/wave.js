export const meta = {
  name: 'wave',
  description: 'Execute one shepherd wave: fan out file-disjoint coder steps, verify ONCE centrally.',
  whenToUse:
    'When a shepherd run has an approved plan and a wave of file-disjoint steps to execute. Pass the wave spec as args. This is the sanctioned fan-out vehicle — do not hand-roll a batch of Agent() calls, and do not fan out the verify phase.',
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

// GH #270 applies to Agent() dispatch, where a return value routes to the
// task-tree owner. It does NOT apply to a Workflow agent() call: that value
// comes back to this script, and with `schema` it comes back validated. So a
// file is contracted only where the artifact IS a document.
//
// An @auditor writes a file — a verification report is a durable artifact and
// the role exists to author one. A @coder does NOT. A coder's deliverable is
// the DIFF, and `git diff` is a truer account of what it did than any prose it
// writes about itself. Measured on this run: 37 coder reports, 318 KB, ~46% of
// the whole reports directory — every one of them bypassed, because the central
// auditor re-verifies against live HEAD and explicitly distrusts self-reports.
// Report authorship belongs to @auditor / @discovery / @worker.
const deliverable = (path) => `
YOUR CONTRACTED DELIVERABLE IS A FILE ON DISK at exactly:
  ${path}
Write it with the Write tool before you finish. Your chat return value is NOT
collected — a report that exists only in your reply is a failed dispatch.
Absolute paths only. Repo root is ${REPO}.`

// The only thing a coder knows that the diff cannot show: what it could not
// verify because it was forbidden to build. That is the whole payload.
const CODER_RESULT = {
  type: 'object',
  properties: {
    step: { type: 'string' },
    files_touched: { type: 'array', items: { type: 'string' } },
    loc_delta: { type: 'string', description: 'e.g. "+41/-58"' },
    assumptions: {
      type: 'array',
      items: { type: 'string' },
      description: 'each assumption needing compile-time or runtime confirmation; [] if none',
    },
    halts: {
      type: 'array',
      items: { type: 'string' },
      description: 'halt codes raised, or [] — a halt is a valid outcome, not a failure to hide',
    },
    out_of_scope_writes: {
      type: 'array',
      items: { type: 'string' },
      description: 'any file written outside file_scope.exclusive; [] if none. Declare it, do not conceal it',
    },
  },
  required: ['step', 'files_touched', 'loc_delta', 'assumptions', 'halts', 'out_of_scope_writes'],
}

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

DO NOT WRITE A REPORT FILE. Your deliverable is the DIFF — the code itself, in
your scope, on disk. The central auditor reads \`git diff\`, not prose about it.
Return the structured result you are given a schema for and nothing else; the
only thing it carries that the diff cannot is your ASSUMPTIONS list, which is
the one input that makes verification fast.`,
      {
        agentType: s.agentType || 'shepherd:coder',
        model: s.model || 'sonnet',
        label: `coder:${s.id}`,
        phase: 'Implement',
        schema: CODER_RESULT,
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

You are the ONLY agent this wave permitted to build. The coders were forbidden to
compile, so each declared the ASSUMPTIONS it could not confirm — check every one.

VERIFY AGAINST THE DIFF, NOT AGAINST SELF-REPORTS. \`git diff\` and live HEAD are
the evidence; the structured results below are a coder's own account of its work
and carry no authority. Where they disagree, the tree wins and the step is REDO.

Steps to verify (${landed} of ${STEPS.length} returned):
${JSON.stringify(built.filter(Boolean), null, 1)}

Declared file scopes, for the out-of-scope check:
${STEPS.map((s) => `  ${s.id}: ${(s.scope || []).join(', ') || '(none declared)'}`).join('\n')}
${landed < STEPS.length ? '\nA step that returned NOTHING did not complete. Treat its scope as UNWRITTEN and fail it — absence is not a pass.\n' : ''}
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

// Coders return data, not documents. The ONE file this wave produces is the
// auditor's — the only artifact anyone reads twice.
return {
  run: RUN,
  wave: WAVE,
  steps_dispatched: STEPS.length,
  steps_returned: landed,
  steps: built.filter(Boolean),
  assumptions: built
    .filter(Boolean)
    .flatMap((r) => (r.assumptions || []).map((x) => `${r.step}: ${x}`)),
  out_of_scope: built
    .filter(Boolean)
    .flatMap((r) => (r.out_of_scope_writes || []).map((x) => `${r.step}: ${x}`)),
  halts: built.filter(Boolean).flatMap((r) => (r.halts || []).map((x) => `${r.step}: ${x}`)),
  verify: verdict ? 'returned' : 'FAILED to return',
  report: `${REPORTS}/auditor-${WAVE}-central-verify.md`,
}
