/*
    Appellation: manifest <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! The render provenance manifest: the digest triad that proves a render
//! reproduced byte-for-byte.
//!
//! ## Why `vars_sha256` needs canonicalization and the other two do not
//!
//! `template_sha256` and `output_sha256` hash raw bytes with no
//! normalization at all (pinned against a NIST vector in
//! `tests/default.rs`). `vars_sha256` cannot work that way: the SAME
//! variables, built in a different insertion order (a `HashMap` iterated
//! in address order, say), would hash to different bytes even though the
//! rendered TEXT is identical -- an unreproducible digest hiding behind a
//! perfectly reproducible render. Shepherd serializes variables with sorted
//! keys, compact separators, and unescaped Unicode before hashing.
//!
//! This module reproduces those exact bytes with no hand-written
//! serializer. Per `crate::filters`' module docs (W2-S1), a
//! `serde_json::Map` without this workspace's (always-off)
//! `preserve_order` feature is a `BTreeMap`, so key order is already
//! sorted at every nesting level before serialization ever runs; and
//! `serde_json`'s own compact `Serializer` already writes `,`/`:` with no
//! surrounding space and passes non-ASCII text through as UTF-8
//! untouched. `serde_json::to_vec` alone reproduces the canonical bytes -- no
//! recursive writer is needed (contrast `crate::filters`, whose
//! `tojson` filter needs one because ITS separators/HTML-escaping rules
//! differ from `serde_json`'s own defaults).
use crate::error::{Error, Result};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::Path;

/// The provenance digest triad for one render. Every field is a lowercase-hex
/// SHA-256 digest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderManifest {
    /// sha256 of the template source's raw bytes, exactly as read from
    /// disk -- no whitespace or line-ending normalization.
    pub template_sha256: String,
    /// sha256 of `vars`, canonicalized: sorted keys, compact separators,
    /// non-ASCII preserved -- see the module docs.
    pub vars_sha256: String,
    /// sha256 of the rendered output's UTF-8 bytes.
    pub output_sha256: String,
}

/// Render the template at `template_path` with `vars`, returning the
/// rendered text and its [`RenderManifest`].
///
/// Applies no name resolution or search-path precedence: the caller
/// supplies the exact file to render (a loader is a later step, outside
/// this crate's `[FILE-SCOPE]` here). Compiles through
/// [`crate::env::build`] (W2-S1) unconditionally, so every
/// render-layer setting this crate owns -- including
/// `UndefinedBehavior::Strict` -- applies to this render too.
///
/// # Errors
///
/// - [`Error::Unknown`] if `template_path` cannot be read (missing, a
///   directory, permission denied) or is not valid UTF-8, or if `vars`
///   is somehow not JSON-serializable.
/// - [`Error::Template`] (wrapping [`minijinja::Error`]) if the template
///   fails to compile, or -- preserved here, never softened to a warning
///   or a blank render -- if `vars` leaves any referenced variable
///   undefined. Exit-status mapping is a CLI-layer concern.
pub fn render_with_manifest(
    template_path: &Path,
    vars: &Value,
) -> Result<(String, RenderManifest)> {
    let template_source = std::fs::read_to_string(template_path)
        .map_err(|error| Error::unknown(format!("{}: {error}", template_path.display())))?;

    let output = crate::env::build()
        .template_from_str(&template_source)?
        .render(vars)?;

    // See the module docs: `to_vec` alone reproduces the canonical
    // sorted-key, compact-separator, unescaped-Unicode
    // vars serialization, with no hand-written writer.
    let vars_bytes = serde_json::to_vec(vars)
        .map_err(|error| Error::unknown(format!("vars not JSON-serializable: {error}")))?;

    let manifest = RenderManifest {
        template_sha256: sha256_hex(template_source.as_bytes()),
        vars_sha256: sha256_hex(&vars_bytes),
        output_sha256: sha256_hex(output.as_bytes()),
    };

    Ok((output, manifest))
}

/// Lowercase-hex sha256. Hand-rolled per-byte: `sha2` 0.11's digest
/// `Array` type does not implement `LowerHex` the way `generic_array`
/// did on the 0.10 line (`tests/default.rs`'s note), so `{:x}` on the
/// whole digest fails to compile.
fn sha256_hex(bytes: &[u8]) -> String {
    use core::fmt::Write;

    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut acc, byte| {
            write!(&mut acc, "{byte:02x}").expect("writing to a String cannot fail");
            acc
        })
}

#[cfg(test)]
mod tests {
    use super::render_with_manifest;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    static SCRATCH_TEMPLATE_COUNTER: AtomicU64 = AtomicU64::new(0);

    /// One collision-resistant scratch template path per fixture label, so
    /// parallel `cargo test` threads do not collide on the same file. Each
    /// test removes its own path once done with it.
    fn scratch_template_path(label: &str) -> std::path::PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0);
        let nonce = SCRATCH_TEMPLATE_COUNTER.fetch_add(1, Ordering::Relaxed);
        std::env::temp_dir().join(format!(
            "shepherd-render-manifest-{label}-{stamp:x}-{nonce}.md.j2"
        ))
    }

    #[test]
    fn scratch_template_paths_are_distinct() {
        assert_ne!(
            scratch_template_path("same-label"),
            scratch_template_path("same-label"),
            "each fixture reservation must receive its own path"
        );
    }

    /// `cargo test -p shepherd-render manifest::tests::digests_reproduce`
    /// -- the step's mandated test: render the SAME template with the
    /// SAME vars twice and assert the output bytes AND all three digests
    /// are byte-identical both times. Requires `--features json` (this
    /// whole module is gated on `std` + `json` in `lib.rs`); bare
    /// `cargo test` finds 0 matching tests here, mirroring W2-S1's
    /// identical `filters`-module caveat -- see the coder report.
    #[test]
    fn digests_reproduce() {
        let path = scratch_template_path("reproduce");
        std::fs::write(&path, "{{ greeting }}, {{ name }}!\n").expect("write fixture template");

        let vars = serde_json::json!({ "name": "World", "greeting": "Hello" });

        let (first_text, first_manifest) =
            render_with_manifest(&path, &vars).expect("first render must succeed");
        let (second_text, second_manifest) =
            render_with_manifest(&path, &vars).expect("second render must succeed");

        // Cleanup only; a leftover scratch file in the OS temp dir is
        // not a test-outcome signal, so its removal result is discarded
        // deliberately.
        let _ = std::fs::remove_file(&path);

        assert_eq!(first_text, "Hello, World!\n");
        assert_eq!(first_text, second_text, "output bytes must reproduce");
        assert_eq!(
            first_manifest, second_manifest,
            "the full digest triad must reproduce byte-for-byte across renders"
        );
        assert_eq!(
            first_manifest.template_sha256, second_manifest.template_sha256,
            "template_sha256 must reproduce"
        );
        assert_eq!(
            first_manifest.vars_sha256, second_manifest.vars_sha256,
            "vars_sha256 must reproduce"
        );
        assert_eq!(
            first_manifest.output_sha256, second_manifest.output_sha256,
            "output_sha256 must reproduce"
        );
    }

    /// `vars_sha256` must depend on the CANONICALIZED variables, not
    /// their construction order -- the whole reason this digest cannot
    /// just hash raw bytes like the other two (see the module docs).
    /// Two `Value`s parsed from JSON text with reversed key order must
    /// still produce the identical `vars_sha256`.
    #[test]
    fn vars_digest_is_order_independent() {
        let path = scratch_template_path("order-independent");
        std::fs::write(&path, "{{ a }}-{{ b }}\n").expect("write fixture template");

        let forward: serde_json::Value =
            serde_json::from_str(r#"{"a": 1, "b": 2}"#).expect("parse forward-order vars");
        let reversed: serde_json::Value =
            serde_json::from_str(r#"{"b": 2, "a": 1}"#).expect("parse reversed-order vars");

        let (_, forward_manifest) =
            render_with_manifest(&path, &forward).expect("forward-order render must succeed");
        let (_, reversed_manifest) =
            render_with_manifest(&path, &reversed).expect("reversed-order render must succeed");

        let _ = std::fs::remove_file(&path);

        assert_eq!(
            forward_manifest.vars_sha256, reversed_manifest.vars_sha256,
            "vars_sha256 must not depend on JSON key insertion order"
        );
    }

    /// `[USER-STYLE]`: `StrictUndefined` (`crate::env::build`) means a
    /// missing template variable is a hard error, never a warning or a
    /// blank render. This step must not soften that -- assert the
    /// failure surfaces as `Error::Template` wrapping minijinja's own
    /// `ErrorKind::UndefinedError`, distinguishable enough for a CLI
    /// layer to map to its documented render failure status.
    #[test]
    fn undefined_variable_is_hard_error() {
        let path = scratch_template_path("undefined-var");
        std::fs::write(&path, "{{ missing }}").expect("write fixture template");

        let result = render_with_manifest(&path, &serde_json::json!({}));

        let _ = std::fs::remove_file(&path);

        match result {
            Err(crate::error::Error::Template(error)) => {
                assert_eq!(error.kind(), minijinja::ErrorKind::UndefinedError);
            }
            other => panic!("expected Err(Error::Template(UndefinedError)), got {other:?}"),
        }
    }
}
