# services/ — self-contained services

Independent, single-concern services with their own code, contract, tests, and
evals. Each is parallel-session-safe: a session working in one never collides
with one working in another, because they talk only through documented contracts,
never by reaching into each other's internals.

| Service | Concern | Contract |
|---------|---------|----------|
| [`llm/`](llm/README.md) | Route a model call through the **local Claude Code** (`claude -p`). The single owner of the model invocation. | `llm.sh complete` — prompt in, text out |
| [`eval/`](eval/README.md) | Quality-score a latent agent output against a rubric, using the llm service as judge. | `eval.sh run --kind=K` — item in, verdict out |
| [`cli/`](cli/README.md) | The packaged `shepherd` CLI (Python + Poetry: Tortoise ORM / Pydantic / Typer) — a typed, session/pid-scoped data-access layer over the registry. Natively-ported groups (v6.3.7): `teammate`, `signal`, `mem`, `deliverable`, `status`, `lock`, `sprint`, `models`, `query`, `style`, `report`, `search`, `export`, `lint`, `seed`, `config`, `sync`, `dash`, `insights`, `dups`, `handoff`, `ready`, `discovery`, `audit`, `eval`, `doctor`. Un-ported subcommands shim to bash `shctx`. | `shepherd teammate liveness` — scoped read, table/JSON out |

## How they compose

```
shctx eval run          (registry-side glue: resolves subjects, records eval_runs)
      │  calls
      ▼
services/eval/eval.sh    (pure judge: rubric → prompt → parse → weighted verdict)
      │  calls
      ▼
services/llm/llm.sh      (the only place that shells out to `claude -p`)
      │  shells out to
      ▼
local Claude Code
```

The rule the whole chain enforces: **no hosted inference API.** Model calls go
through the local Claude Code via `services/llm`, and every other piece calls that
contract instead of invoking `claude` itself.

## The split, embodied

`services/eval` is the plugin scoring its own latent instructions, so it is the
clearest place the latent/deterministic discipline is made literal: the model's
per-dimension scores are latent; the rubric, the weighted overall, the threshold
verdict, the exit code, and the recorded row are deterministic. Same scores in ⇒
same verdict out.

## Tests

```bash
bash services/llm/tests/run.sh      # gate — mock-only, no real claude call
bash services/eval/tests/run.sh     # gate — judge mocked, deterministic, <2s
SHEPHERD_EVAL_LIVE=1 bash services/eval/evals/run_eval.sh   # live lane (paid)
```
