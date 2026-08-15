# services/eval — the shepherd eval harness

Scores a **latent agent output** (a conductor reflection, a discovery report, a
seed, …) against a rubric, using the local-Claude-Code judge in
[`../llm`](../llm/README.md). This is the standing follow-up from v6.2.0: the
plugin's latent instructions finally have a behavioral eval, not just gate-tested
storage.

## The split, applied to the plugin itself

The plugin preaches a latent/deterministic split. The harness lives it:

| Part | Owner | Where |
|------|-------|-------|
| Per-dimension 1..scale scores + rationale | the model (latent) | the judge call |
| Rubric, judge-prompt build, weighted overall, threshold verdict, exit code | code (deterministic) | `eval.sh` |

Same scores in ⇒ same verdict out. The only non-reproducible step is the model's
judgement, and that is exactly the part a rubric + threshold is meant to bound.

## Use

```bash
# score text directly
echo "next sprint, front-load the dups gate before the coder wave" \
  | services/eval/eval.sh run --kind=reflection -

# score a file, machine-readable verdict
services/eval/eval.sh run --kind=discovery --input-file=report.md --json

services/eval/eval.sh rubrics        # list rubric kinds
services/eval/eval.sh show seed      # print a rubric
```

Exit codes: `0` pass · `1` fail (below threshold) · `2` usage · `4` judge/parse error.
`--json` prints **only** the verdict object. A caller may persist that object
through the native registry boundary, but this service never opens project
state itself.

## Rubrics

One file per subject kind in [`rubrics/`](rubrics/), e.g.
[`reflection.rubric.json`](rubrics/reflection.rubric.json). Shape:

```json
{
  "kind": "reflection",
  "subject": "what is being judged, in one sentence",
  "scale": 5,
  "threshold": 60,
  "dimensions": [
    { "key": "specificity", "weight": 2, "desc": "…" }
  ],
  "guidance": "what to reward / penalize"
}
```

Overall score = `round( 100 * Σ(score·weight) / (scale · Σweight) )`. Adding a new
subject is one JSON file — no code change. `test_eval_rubrics.sh` enforces the
shape so a malformed rubric fails loudly instead of scoring garbage.

## Two lanes (per the project's test/eval discipline)

- **Gate lane** — `bash services/eval/tests/run.sh`. Deterministic, free, <2s.
  The judge is mocked (`SHEPHERD_LLM_MOCK`), so the eval→llm boundary, the score
  math, the threshold verdict, and every error path are tested for real while the
  model returns a canned response.
- **Live lane** — `SHEPHERD_EVAL_LIVE=1 bash services/eval/evals/run_eval.sh`.
  Paid, real judge. Proves the harness generalizes: the real judge must pass the
  golden-good cases, fail the golden-bad cases, and separate them by a margin.
  The `content` pair specifically exercises minimum context selection, budget
  invariants, canonical roles/layout, native capability degradation, and bounded
  cross-harness resume. The `plugin-distribution` pair exercises self-contained
  Component runtime packaging, one-authority carrier selection, truthful Claude
  ZIP loading semantics, and release evidence.
  Run before ship and nightly, not on every commit.

## Boundary

The native `shepherd eval` command inspects already-recorded evaluation rows.
It does not invoke a model. This service is the only scoring runner and remains
pure and stateless: explicit text enters, one verdict leaves. Any future
persistence integration must call a typed registry API rather than importing
this service's internals or adding another model invocation path.
