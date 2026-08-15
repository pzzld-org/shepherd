/*
    Appellation: env <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! The canonical minijinja [`Environment`] for deterministic Markdown output.
//!
//! ## The trap this module exists to dodge
//!
//! minijinja applies `trim_blocks` / `lstrip_blocks` / `keep_trailing_newline`
//! / undefined behavior / autoescape to a template AT THE MOMENT it loads --
//! not retroactively. A setter called AFTER a caller's first template load
//! (`add_template`, `add_template_owned`, `template_from_str`) leaves that
//! ONE template under minijinja's own defaults instead (`false` for
//! `trim_blocks`/`lstrip_blocks`, matching Jinja2), the opposite of what
//! the canonical contract turns on -- silently, with no error anywhere.
//! [`build`] therefore never loads a template itself, so no setter here can
//! ever run after a load a caller made.
use minijinja::{AutoEscape, Environment, UndefinedBehavior};

/// Build the canonical, deterministic [`Environment`].
///
/// Every one of the five settings below MUST land on the returned
/// [`Environment`] before a caller's first template load (see the module
/// docs' trap above). Returns the [`Environment`] directly rather than a
/// newtype: `[USER-STYLE]` rules out a hollow wrapper around a type this
/// crate does not own.
#[must_use]
pub fn build() -> Environment<'static> {
    let mut env = Environment::new();

    // An undefined template variable is a hard render-time error, never a
    // silent blank. Exit-status mapping belongs to the CLI layer; this layer
    // guarantees that the error is preserved.
    env.set_undefined_behavior(UndefinedBehavior::Strict);

    // Whitespace determinism. Minijinja's defaults for all three are `false`;
    // Shepherd turns every one on so equal inputs produce equal bytes.
    env.set_trim_blocks(true);
    env.set_lstrip_blocks(true);
    env.set_keep_trailing_newline(true);

    // `autoescape=False`: every template this crate renders
    // is Markdown. minijinja's default autoescape callback infers escaping
    // from a template's name/extension; pinning the callback to always
    // return `AutoEscape::None` removes that guesswork instead of relying
    // on none of the 5 real template names ever matching an HTML/XML
    // extension by chance.
    env.set_auto_escape_callback(|_name| AutoEscape::None);

    // Override minijinja's builtin `tojson` with Shepherd's stable Markdown
    // serializer. Gated on `json` (this crate's optional
    // feature `sorted_tojson` needs for `serde_json` -- see
    // `crate::filters`), which ALSO now turns on minijinja's OWN `json`
    // feature (`Cargo.toml`'s `json = [..., "minijinja/json", ...]`):
    // minijinja's `builtins` feature (always on, see `Cargo.toml`) only
    // reserves the builtin-filter registration slot -- the `tojson` filter
    // BODY itself compiles only under minijinja's separate `json` feature
    // (minijinja `src/defaults.rs`). Without `minijinja/json` there is
    // nothing for `filters::tests::negative_control_builtin_tojson_diverges`
    // to diverge against; turning it on alongside our own `json` feature
    // restores it.
    //
    // Consequence for the MINIMAL build: under bare `default` (no `json`
    // feature), BOTH this override and minijinja's builtin compile out
    // together -- `minijinja/json` lives inside this crate's own optional
    // `json` feature, not `default`/`std`. The returned `Environment` then
    // has NO `tojson` filter at all; a template using `| tojson`
    // (`boot-prompt.md.j2`'s `peer_teammate_names`, `seed.md.j2`'s
    // `sprint_dependencies`/`parallel_with`) hard-fails with
    // `ErrorKind::UnknownFilter` rather than silently degrading to an
    // HTML-escaped, unsorted fallback -- there is no fallback. This is a
    // real, intentional gap for this step's scope: no default-feature
    // caller renders a `tojson` template today (`shepherd-sdk`'s own `json`
    // feature already forwards to `shepherd-render?/json`), but any future
    // default-feature caller of such a template (e.g. `crates/cli`) MUST
    // enable this crate's `json` feature or accept the hard render error.
    #[cfg(feature = "json")]
    env.add_filter("tojson", crate::filters::sorted_tojson);

    env
}

#[cfg(test)]
mod tests {
    use super::build;

    /// Pin every environment setting with a byte-level behavior test.
    #[test]
    fn matches_canonical_settings() {
        let env = build();

        // trim_blocks + lstrip_blocks: a block tag on
        // its own indented line leaves neither the indent nor a blank line
        // behind. Jinja2 on this exact source: `'A\nB\n'`.
        let trimmed = env
            .template_from_str("  {% if true %}\nA\n{% endif %}\nB\n")
            .expect("template compiles")
            .render(())
            .expect("template renders");
        assert_eq!(trimmed, "A\nB\n", "trim_blocks/lstrip_blocks must be on");

        // keep_trailing_newline: template engines trim a
        // template's FINAL newline by default; the setting restores it.
        // Jinja2 on this exact source: `'line\n'`.
        let trailing = env
            .template_from_str("line\n")
            .expect("template compiles")
            .render(())
            .expect("template renders");
        assert_eq!(trailing, "line\n", "keep_trailing_newline must be on");

        // autoescape=false: Markdown templates must never
        // see `&`/`<`/`>`/`'` HTML-escaped. Jinja2 on this exact source +
        // value: `"R&D <tag> 'quote'"` (unchanged).
        let unescaped = env
            .template_from_str("{{ value }}")
            .expect("template compiles")
            .render(minijinja::context! { value => "R&D <tag> 'quote'" })
            .expect("template renders");
        assert_eq!(unescaped, "R&D <tag> 'quote'", "autoescape must be off");

        // UndefinedBehavior::Strict: an undefined variable is a hard error,
        // never a blank. Exit-status mapping remains a CLI-layer concern.
        let error = env
            .template_from_str("{{ missing }}")
            .expect("template compiles")
            .render(())
            .expect_err("undefined variable must hard-fail, never render blank");
        assert_eq!(
            error.kind(),
            minijinja::ErrorKind::UndefinedError,
            "undefined variable must fail as UndefinedError: {error}"
        );
    }

    /// Render the canonical handoff template end-to-end against its frozen
    /// digest. The other historical templates belonged to the retired
    /// Python CLI and are deliberately not copied into the Rust content
    /// corpus. Whitespace, strict undefined values, escaping, and sorted
    /// JSON have dedicated unit coverage above and in `filters`.
    #[cfg(feature = "json")]
    #[test]
    fn end_to_end_matches_canonical_corpus() {
        use sha2::{Digest, Sha256};

        fn sha256_hex(bytes: &[u8]) -> String {
            Sha256::digest(bytes)
                .iter()
                .map(|byte| format!("{:02x}", *byte))
                .collect()
        }

        let env = build();
        let cases: [(&str, &str, &str, &str); 1] = [(
            "handoff.md",
            include_str!("../../../content/templates/handoff.md"),
            r#"{"ARTIFACTS_COUNT": "3", "BRANCH": "v6.4.1-dev.0", "CARRY_FORWARDS": "- none", "COMMITS": "abc1234 first\ndef5678 second", "DATE": "2026-08-02", "DRIFT_RISK_COUNT": "0", "FILES_OF_INTEREST": "- crates/cli/", "LOCK_COUNT": "1", "MEM_COUNT": "2", "NEXT_FOCUS": "- verify release", "NORTH_STAR": "one canonical CLI", "OPEN_ISSUES_COUNT": "27", "SESSION": "sess-0001"}"#,
            "51d55c5e3613860544124394b402166e91f5f98090db781273aebaafabfb2440",
        )];

        for (name, source, vars_json, expected_sha256) in cases {
            let vars: serde_json::Value = serde_json::from_str(vars_json)
                .unwrap_or_else(|e| panic!("{name}: vars parse: {e}"));
            let rendered = env
                .template_from_str(source)
                .unwrap_or_else(|e| panic!("{name}: compile: {e}"))
                .render(&vars)
                .unwrap_or_else(|e| panic!("{name}: render: {e}"));
            assert_eq!(
                sha256_hex(rendered.as_bytes()),
                expected_sha256,
                "{name}: output diverged from the canonical content corpus"
            );
        }
    }
}
