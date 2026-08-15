# shepherd-render

Template resolution, deterministic rendering, and artifact provenance.

## Why this is a crate and not a module

Rendering is the one place Shepherd emits bytes that another tool later diffs. The native manifest pins `template_sha256`, `vars_sha256`, and `output_sha256`, and the tests assert all three reproduce byte-identically.

Holding that here lets the property be tested without a database, a config loader, or a terminal — and keeps a template engine out of `shepherd-core`.

## The determinism contract

Rendering is a pure function of (template bytes, variables). Anything that varies per run is a defect, because it makes the manifest hashes unreproducible and the oracle unfalsifiable:

- no clock, no environment, no filesystem probe during render
- no iteration over a hash map in address order

`preserve_order` is deliberately **off** on `minijinja`. Without it, maps are backed by a `BTreeMap`, so iteration is sorted and reproducible. Turning it on swaps in insertion order, which makes `output_sha256` depend on the order the caller happened to build its context.

## Gate tests

`tests/default.rs` renders the same template 64 times and asserts byte-identical output, then pins SHA-256 against the NIST `"abc"` vector. Cross-implementation comparison is only meaningful if rendering is reproducible within one implementation first.

Note: `sha2` 0.11 returns a `hybrid_array::Array`, which does not implement `LowerHex` the way `generic_array` did on the 0.10 line, and it has no `std` feature — only `alloc` and `oid`. `{:x}` and `sha2/std` both compile under 0.10 and fail under 0.11.
