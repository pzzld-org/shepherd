# Extend existing structs; don't rewrite

When a struct is "almost what you need", add the missing method to its `impl` block in the SAME crate (5–15 min). Don't define a parallel `MyXyzRow`. Don't refactor surrounding code. Return to the original task.

## The 15-minute detour budget

If extending an existing type takes > 15 min, it's a sign the existing type wasn't actually a fit. Surface to the conductor; they decide whether to escalate.

## For external types (std, deps)

Use an extension trait in your crate. Orphan rule allows it because the trait is local even if the type is external:

```rust
// In your crate
pub trait OptionExt<T> {
    fn ok_or_log(self, msg: &str) -> Option<T>;
}

impl<T> OptionExt<T> for Option<T> {
    fn ok_or_log(self, msg: &str) -> Option<T> {
        if self.is_none() { tracing::warn!(msg = msg); }
        self
    }
}
```

## What this prevents

The dedup ledger pattern: every sprint adds `MyContextRow`, `BotInfoRow`, `DecisionRow`, `PositionRow` — each carrying the same fields with minor variations. None replaces the others; they just accumulate. The right design is one canonical row type extended via methods or sub-types as needed.

## The discipline

When you find yourself about to write `pub struct NewThing` for something that overlaps with an existing thing:

1. **Stop.** Open the existing thing.
2. **Read its full impl block.** Note every method.
3. **Identify the missing method or field.**
4. **Add it inline.** Test it.
5. **Check the call sites.** Anyone else using this struct? Their behavior unchanged?
6. **Return to the original task.**

If you can't do all six in 15 min, the existing thing wasn't a fit — escalate.

## Auditor-time check

The auditor `dependency-topology` concern grep at sprint close:

```bash
# Surface every NEW pub struct introduced this sprint
git diff v0.2.9..HEAD -- '**/*.rs' | rg '^\+pub struct ' | head -20
```

For each new struct, the auditor walks: was the closest-existing struct actually unfit, or was this an extend-instead-of-rewrite violation? Findings file as MEDIUM-severity unless the operator pre-authorized.

## See also

- `wrapper-must-earn-its-existence` (framework doctrine)
- `subtract-don't-add` (framework doctrine)
- `feedback_extend_existing_structs_stay_on_task` (in user memory)
