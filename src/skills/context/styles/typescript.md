# TypeScript — project code style

Project-local at `.shepherd/styles/typescript.md` (`.artifacts/` legacy); injected as `[CODE-STYLE]` into coder briefs scoping TypeScript files. Edit freely — lives next to the project.

## Error handling
- Domain code does not throw — functions that can fail return `Result<T, E>` (`neverthrow`, or a custom `{ ok, value | error }` union). Exceptions are for truly unexpected conditions (programmer error, unrecoverable infra failure); library code wraps them at the boundary into `Result`.
- `try/catch` only at I/O / FFI / framework boundaries. Validate external input with `zod` (or equivalent) at the boundary; `Promise` rejections are `unknown` — type-narrow before re-raising.

## Ownership & state
- `unknown` for boundary inputs, never `any` (`any` requires an inline `// reason: <why>` comment); `readonly` on every non-mutating field, prefer `ReadonlyArray<T>`.
- `const` over `let`, `var` forbidden. Discriminated unions with a literal `kind`/`type` tag, exhaustiveness checked via `never` in the default branch; `boolean | undefined` forbidden — model the third state explicitly.

## Layout
- ES modules only, no `require`/`module.exports`; `"type": "module"` in `package.json`. Default exports only for React components/entry points, otherwise named exports.
- Files > ~300 LOC split; co-locate types with owning code. Barrel files (`index.ts`) curated by hand; path aliases (`@/...`) over deep `../../../` imports.

## Async
- `Promise.all`/`allSettled` over sequential `await` in loops for independent work (sequential needs a justifying comment); `for await ... of` for ordered streaming.
- `async` functions always return `Promise<T>`, never mixed with explicit `Promise` construction; `AbortSignal` cancellation passed through every async I/O function.

## Tooling
- `tsconfig.json`: `"strict": true`, `"noUncheckedIndexedAccess": true`, `"exactOptionalPropertyTypes": true`.
- `eslint` + `@typescript-eslint` MUST pass with no warnings; `tsc --noEmit` runs in CI as a distinct type-check pass. Test runner: `vitest`/`node:test`.

## Documentation
- TSDoc on every exported function/class/type (`@param`, `@returns`, `@throws`, `@example`); README per package states its responsibility in one paragraph.

## Common patterns to AVOID (operator-flagged)
- `as` casts without a runtime check (use a type guard/`zod` parse); `enum` over discriminated union literals (runtime cost, reverse-mapping surprises).
- `// @ts-ignore` (use `// @ts-expect-error <reason>` so the fix surfaces); mutating function arguments (return a new value); `Date` arithmetic without a date library at boundaries.
