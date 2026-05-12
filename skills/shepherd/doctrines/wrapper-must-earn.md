# Wrapper types must earn their existence

A wrapper type that has no type-system-enforced invariant, no borrowed scope, no shared-allocation pattern, and no substantive trait/interface role IS A SMELL. Replace with a method on the inner type, a borrowed scope object, or just inline the call.

This rule is language-agnostic. Per-language detection greps and refactor patterns live in the relevant language skill (`rust`, `typescript`, `python`, `go`, ...). This doctrine owns the principle; language skills own the syntax.

## The four justifications (one MUST hold)

A wrapper type earns its existence ONLY if at least one of these is true:

1. **Type-system-enforced invariant** — the wrapper's only constructor enforces a property the inner can't (e.g., `NonZero`, `Sorted`, `Validated`). The compiler refuses bypass. Without this, any caller can manipulate the inner directly and the invariant is fiction.

2. **Borrowed scope over live state** — the wrapper holds short-lived references (Rust lifetime, JS closure-capture, Python context manager, Go pointer-with-doc-contract) that can't outlive the source. The borrow IS the value-add.

3. **Shared-allocation pattern** — `Arc<Inner>` (Rust), `Rc<Inner>` (Python proxy), shared pointer (C++ `shared_ptr`), interface with reference-counted backing. O(1) clone + method-forwarding for shareable runtime contexts. The shared allocator IS the value-add.

4. **Substantive trait / interface role** — implements ≥ 3 trait/interface methods that meaningfully differ from the inner's behavior, OR is a marker for a sealed-trait/interface family the inner can't be.

## What does NOT earn existence

The smell pattern, in any language, is:

> A wrapper holding a single field with no invariant, owned (not borrowed), with one or more methods whose bodies are thin redirects to free functions or methods on the inner.

When you see this:

- The wrapper carries no information beyond the inner.
- The wrapper's methods are pass-throughs.
- Removing the wrapper and putting the methods on the inner type (or inlining as a free function) makes the codebase smaller AND clearer.

→ **The wrapper is hollow. Delete it.**

## Per-language detection

Each language skill carries the detection grep + refactor pattern:

- **Rust** → see `rust` skill §wrappers (grep on `pub struct \w+ \{[\s\n]*pub params: \w+,?\s*\}`, refactor to method-on-params or `Step<'a>`)
- **TypeScript** → see `typescript` skill §wrappers (single-field class with all-delegating methods)
- **Python** → see `python` skill §wrappers (single-attribute class with `__getattr__` or pass-through methods)
- **Go** → see `go` skill §wrappers (single-field struct with one method per inner method)

If a project's primary language doesn't have a published detection pattern, the conductor's auditor falls back to the principle: "review every new wrapper introduced by a sprint and confirm at least one of the four justifications holds".

## Phase 0 wrapper-grep gate

Every sprint's Phase 0 mesh table includes a row that grep-checks for hollow wrappers per the project's primary language:

```markdown
| N | Code | **Wrapper-grep gate** — run the detection grep from the project-language skill against {sprint-touched-paths} BEFORE sprint close | Hits in lane-modified files: 0. Pre-existing hits outside sprint scope: documented in {paths.ctx}/wrapper-debt-ledger.md for a future canonicalization sprint. |
```

The auditor (`dependency-topology` concern) runs this grep at sprint close. **New lane-introduced hits ARE a sprint-fail.** Pre-existing hits are tracked in `{paths.ctx}/wrapper-debt-ledger.md` and slotted to a future canonicalization sprint.

## Why this matters

The proliferation pattern produces architectures with N parallel wrappers, each holding a single config struct, each with a single thin redirect method. Five wrappers. None earns its existence. Each adds a layer of indirection, a method-redirect, a clone semantic to track. The "right" design is methods on the params types directly (or borrowed scope objects when state mutation needs explicit lifetime). The wrappers added complexity with zero return.

This rule is the structural fix for "sessions reach for wrapper-around-named-method when they should reach for method-on-inner or borrowed-scope-context".

## Engineer-time prevention

The engineer's `[CONTEXT-INVENTORY]` for any new lane that introduces a type MUST cite the existing inner type the lane will operate on, AND the existing trait/interface it must implement. If the engineer can't cite both, the lane is under-specified — reject back to engineer for re-work.

## See also

- `subtract-dont-add.md` — wrappers compound the LOC accretion problem
- `chain-repair.md` — when canonicalization needs a SUBTRACT sprint of its own
- `README.md` — the language-agnostic stance and integration model
- per-language skills (`rust`, `typescript`, ...) — detection greps + refactor patterns
