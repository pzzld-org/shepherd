# services/llm — the shepherd LLM service

One job: route a model call through the **local Claude Code** in headless print
mode (`claude -p`). Per the project rule, the software we build never calls a
hosted inference API — it shells out to the local Claude Code. Every other
service calls this contract; nothing else invokes `claude` directly.

## Contract

```bash
llm.sh complete [--prompt-file=F | --prompt=TXT | -] \
                [--system-file=F | --system=TXT]     \
                [--model=ALIAS] [--timeout=SEC]
```

- Prompt source precedence: `--prompt-file` > `--prompt` > stdin.
- Writes **only** the model's text response to stdout. Diagnostics go to stderr.
- `llm.sh ping` verifies the binary is reachable without spending a completion.

Exit codes: `0` ok · `2` usage · `3` timeout · `4` llm/runtime error.

## Why a service and not a one-liner

A single owner for the model call means a single place for the things that are
easy to get wrong eight different ways: the timeout (macOS ships no `timeout`
binary, so this service runs its own watchdog), the default model (`opus` — best
by default, never a silent downgrade for cost), and the **mock seam**.

## The mock seam

```bash
SHEPHERD_LLM_MOCK=<file>       # complete returns the file contents verbatim
SHEPHERD_LLM_MOCK_TEXT=<str>   # … or this inline string
```

Either short-circuits the claude call entirely. This is what lets downstream gate
tests (services/eval, `shctx eval`) assert the harness around the model —
prompt-building, score math, threshold verdict, DB recording — deterministically,
for free, in under two seconds. The latent part (the model's judgement) is mocked;
everything deterministic is tested for real.

## Config

This service reads only its own env (`SHEPHERD_LLM_BIN`, `SHEPHERD_LLM_MODEL`,
`SHEPHERD_LLM_TIMEOUT`, the two mock vars). It does not read `shepherd.toml` —
callers resolve config (which model, etc.) and pass it via flags, keeping the
service standalone and parallel-session-safe.

## Tests

```bash
bash services/llm/tests/run.sh   # gate lane — mock-only, no real claude call
```
