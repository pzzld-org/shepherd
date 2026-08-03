# TypeScript — project code style

This file is project-local at `.artifacts/styles/typescript.md`. The conductor injects its content into every coder brief whose `[FILE-SCOPE]` includes TypeScript files. Edit freely; lives next to the project, not the user.

## Error handling
- Domain code does not throw. Functions that can fail return `Result<T, E>` (or a project-specific equivalent — `neverthrow`, custom `{ ok, value | error }` discriminated union).
- Exceptions are reserved for truly unexpected conditions (programmer error, unrecoverable infra failure). Library code wraps them at the boundary into `Result`.
- `try/catch` only at I/O / FFI / framework boundaries. Internal layers propagate `Result` and chain with `.map`/`.andThen`.
- Validate every external input with `zod` (or equivalent) at the boundary. Internal types assume validated inputs.
- `Promise` rejections are `unknown` — type-narrow before re-raising or wrapping.

## Ownership & state
- `unknown` for boundary inputs; never `any`. `any` requires an inline `// reason: <why>` comment and reviewer acknowledgement.
- `readonly` on every field that does not need to mutate. Prefer `ReadonlyArray<T>`/`readonly T[]` in signatures.
- `const` over `let`. `let` requires reassignment; `var` is forbidden.
- Discriminated unions with a literal `kind` / `type` tag for sum types — exhaustiveness checked via `never` in the default branch.
- No nullable booleans. `boolean | undefined` is a smell; model the third state explicitly.

## Layout
- ES modules only — no `require`, no `module.exports`. `"type": "module"` in `package.json`.
- One default export per file is allowed only for React components / framework-required entry points; otherwise named exports.
- Files > ~300 LOC are split. Co-locate types with the code that owns them; cross-module types live in `types.ts` or a `types/` directory.
- Barrel files (`index.ts` re-exports) are curated by hand — no auto-export-everything.
- Path aliases (`@/...`) over deep `../../../` relative imports.

## Async
- `Promise.all` (or `Promise.allSettled`) over sequential `await` in loops when the work is independent. Sequential `await` requires a comment justifying the dependency.
- `for await ... of` for ordered streaming; `Promise.all(arr.map(...))` for fan-out.
- Cancellation via `AbortSignal`; pass through every async function that does I/O.
- `async` functions always return `Promise<T>` — never mix `async` and explicit `Promise` construction.

## Tooling
- `tsconfig.json` has `"strict": true`, `"noUncheckedIndexedAccess": true`, `"exactOptionalPropertyTypes": true`.
- `eslint` + `@typescript-eslint` MUST pass with no warnings. `prettier` formats; no manual whitespace bikeshedding.
- `tsc --noEmit` runs in CI as a type-check pass distinct from build.
- Test runner: `vitest` (or `node:test` for low-dep packages). Snapshot tests are reviewed at every change.

## Documentation
- TSDoc on every exported function/class/type. `@param`, `@returns`, `@throws`, `@example` where applicable.
- Public types are documented at the type definition, not at every usage site.
- README in every package explains its single responsibility in one paragraph.

## Common patterns to AVOID (operator-flagged)
- `any` without a `// reason:` comment — silent type holes.
- `as` casts without a runtime check — use a type guard or `zod` parse.
- Sequential `await` over an array when items are independent — use `Promise.all`.
- Throwing inside domain logic — return `Result<T, E>` instead.
- `enum` over discriminated union literals — enums have runtime cost and reverse-mapping surprises.
- `// @ts-ignore` — use `// @ts-expect-error <reason>` so it surfaces when the underlying issue is fixed.
- Mutating function arguments — return a new value or use an explicit out-parameter pattern.
- Using `Date` arithmetic without a date library at boundaries — timezone bugs are cheap to introduce, expensive to find.
