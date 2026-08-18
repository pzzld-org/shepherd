# S1 reference implementation - PROVEN, not a sketch

Prototyped and measured by the lane conductor while wave 1 was blocked on the stale-binary
defect. The S1 coder still owns the real change and must write its own tests; this exists so
the hardest step in the lane starts from a design that is already known to work rather than a
first draft.

## What was proven

Ran the detection against three tars: a stub modelling GNU tar, a stub modelling old
libarchive, and this machine's real bsdtar 3.5.3.

| tar | flags selected | archive built | byte-reproducible |
|---|---|---|---|
| GNU-like stub | `--owner 0 --group 0 --numeric-owner` | yes | yes |
| old-libarchive-like stub | `--uid 0 --gid 0 --uname "" --gname ""` | yes | yes |
| real bsdtar 3.5.3 | `--owner 0 --group 0 --numeric-owner` | yes | yes |

Both paths yield uid/gid `(0,0)` and mtime `315532800`.

## The finding that matters beyond "it works"

**The GNU path and the libarchive path produce BYTE-IDENTICAL archives.** Verified with
`cmp`. That is not incidental: release targets build on different runner images, so if the
two flag sets produced different ustar headers, the same version would ship non-comparable
artifacts depending on which runner packaged it. `--uname ""`/`--gname ""` on libarchive
yields the same headers as GNU's `--numeric-owner`. Preserve this property and assert it in
the test.

## Two design decisions the coder should keep

1. **Capability probe, not a version-string match.** The probe runs the candidate flags
   against a throwaway archive and selects the set that succeeds. A `tar --version` regex
   would work today and is exactly the class of assumption that produced this defect: the
   original comment asserted a shared flag set from inspection and was false on the runner.
   Test behaviour, not identity.
2. **An ARRAY for the flags, never a string.** `--uname ""` and `--gname ""` are
   empty-string arguments. Word-splitting a joined string silently drops them and the
   libarchive path breaks in a way the GNU path never shows. Bash 3.2 indexed arrays are
   fine here; associative arrays (`declare -A`) are not and are banned repo-wide.

## Files

- `s1-tar-detection.reference.sh` - the proven detection plus archive creation
- `stub-gnu-tar.sh` - rejects `--uid`/`--gid`/`--uname`/`--gname` as unrecognized
- `stub-old-libarchive-tar.sh` - rejects `--owner`/`--group` in BOTH spellings, emitting the
  runner's exact `tar: Option --owner=0 is not supported`

The stubs are the important artifact. The gate they replace stubbed a tar that accepts
`--owner 0` but rejects `--owner=0`, which no implementation does; it was a fingerprint of
the script rather than a model of portability. These two model real implementations, and the
script must pass under BOTH.
