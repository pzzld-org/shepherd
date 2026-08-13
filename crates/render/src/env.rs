/*
    Appellation: env <module>
    Created At: 2026.08.13:00:00:00
    Contrib: @FL03
*/
//! The canonical minijinja [`Environment`] -- the Rust twin of
//! `render.py:141-161`'s `build_env`, byte-for-byte.
//!
//! ## The trap this module exists to dodge
//!
//! minijinja applies `trim_blocks` / `lstrip_blocks` / `keep_trailing_newline`
//! / undefined behavior / autoescape to a template AT THE MOMENT it loads --
//! not retroactively. A setter called AFTER a caller's first template load
//! (`add_template`, `add_template_owned`, `template_from_str`) leaves that
//! ONE template under minijinja's own defaults instead (`false` for
//! `trim_blocks`/`lstrip_blocks`, matching Jinja2), the opposite of what
//! `render.py:155-156` turns on -- silently, with no error anywhere.
//! [`build`] therefore never loads a template itself, so no setter here can
//! ever run after a load a caller made.
use minijinja::{AutoEscape, Environment, UndefinedBehavior};

/// Build the canonical, deterministic [`Environment`] -- the Rust twin of
/// `render.py:141-161`'s `build_env`.
///
/// Every one of the five settings below MUST land on the returned
/// [`Environment`] before a caller's first template load (see the module
/// docs' trap above). Returns the [`Environment`] directly rather than a
/// newtype: `[USER-STYLE]` rules out a hollow wrapper around a type this
/// crate does not own.
#[must_use]
pub fn build() -> Environment<'static> {
    let mut env = Environment::new();

    // `undefined=StrictUndefined` (render.py:154): an undefined template
    // variable is a hard render-time error, never a silent blank. Mapping
    // that error to Python's exit code 4 is a CLI-layer concern, outside
    // this crate's `[FILE-SCOPE]`; what this layer owes is that the error
    // actually happens -- see `tests::matches_python_settings`.
    env.set_undefined_behavior(UndefinedBehavior::Strict);

    // Whitespace determinism (render.py:155-157). Jinja2's defaults for all
    // three are `false`; render.py turns every one on so renders are
    // byte-identical for byte-identical inputs.
    env.set_trim_blocks(true);
    env.set_lstrip_blocks(true);
    env.set_keep_trailing_newline(true);

    // `autoescape=False` (render.py:158): every template this crate renders
    // is Markdown. minijinja's default autoescape callback infers escaping
    // from a template's name/extension; pinning the callback to always
    // return `AutoEscape::None` removes that guesswork instead of relying
    // on none of the 5 real template names ever matching an HTML/XML
    // extension by chance.
    env.set_auto_escape_callback(|_name| AutoEscape::None);

    // `env.filters["tojson"] = _sorted_tojson` (render.py:160), overriding
    // minijinja's builtin `tojson`. Gated on `json` (this crate's optional
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

    /// `cargo test -p shepherd-render env::tests::matches_python_settings`
    /// (mandated by `[ACCEPTANCE]`). Every assertion's expected string was
    /// captured from the REAL `render.py::build_env` (Jinja2) rendering the
    /// identical source, 2026-08-13 -- this proves the Rust environment's
    /// five settings reproduce Jinja2's behavior, not just internal
    /// self-consistency.
    #[test]
    fn matches_python_settings() {
        let env = build();

        // trim_blocks + lstrip_blocks (render.py:155-156): a block tag on
        // its own indented line leaves neither the indent nor a blank line
        // behind. Jinja2 on this exact source: `'A\nB\n'`.
        let trimmed = env
            .template_from_str("  {% if true %}\nA\n{% endif %}\nB\n")
            .expect("template compiles")
            .render(())
            .expect("template renders");
        assert_eq!(trimmed, "A\nB\n", "trim_blocks/lstrip_blocks must be on");

        // keep_trailing_newline (render.py:157): both engines trim a
        // template's FINAL newline by default; the setting restores it.
        // Jinja2 on this exact source: `'line\n'`.
        let trailing = env
            .template_from_str("line\n")
            .expect("template compiles")
            .render(())
            .expect("template renders");
        assert_eq!(trailing, "line\n", "keep_trailing_newline must be on");

        // autoescape=false (render.py:158): Markdown templates must never
        // see `&`/`<`/`>`/`'` HTML-escaped. Jinja2 on this exact source +
        // value: `"R&D <tag> 'quote'"` (unchanged).
        let unescaped = env
            .template_from_str("{{ value }}")
            .expect("template compiles")
            .render(minijinja::context! { value => "R&D <tag> 'quote'" })
            .expect("template renders");
        assert_eq!(unescaped, "R&D <tag> 'quote'", "autoescape must be off");

        // UndefinedBehavior::Strict (render.py:154): an undefined variable
        // is a hard error, never a blank -- the render-layer half of
        // Python's exit-4 contract (exit(4) itself is a CLI-layer concern,
        // out of `[FILE-SCOPE]` for this step). Jinja2 on this exact
        // source raises `UndefinedError: 'missing' is undefined`.
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

    /// Action 5: table-test all 5 real templates end-to-end against a
    /// frozen corpus. `conformance/cases/render/**` does not exist in this
    /// checkout yet (its landing step is not this one), so the corpus here
    /// is self-produced: each `expected_sha256` is the sha256 of the REAL
    /// `render.py::build_env` + `Template.render` output for the exact
    /// same template source + vars, captured 2026-08-13. A byte-for-byte
    /// literal-string corpus was rejected in favor of digests to keep this
    /// file free of ~9KB of untypeable transcription risk (`sha2` is
    /// already an unconditional crate dependency); see the coder report for
    /// the exact capture command.
    ///
    /// Every case here compiles its template via `template_from_str` (the
    /// in-memory path), not a name+loader lookup -- this module has no
    /// loader. D2's UNVERIFIED note says do not assume `template_from_str`
    /// is byte-identical to the loader path that 4 of the 5 templates
    /// actually render through in production; this test proves parity for
    /// the `template_from_str` path only. See the coder report.
    #[cfg(feature = "json")]
    #[test]
    fn end_to_end_matches_python_corpus() {
        use sha2::{Digest, Sha256};

        fn sha256_hex(bytes: &[u8]) -> String {
            Sha256::digest(bytes)
                .iter()
                .map(|byte| format!("{:02x}", *byte))
                .collect()
        }

        let env = build();
        let cases: [(&str, &str, &str, &str); 5] = [
            (
                "handoff.md.j2",
                include_str!("../../../services/cli/shepherd_cli/templates/handoff.md.j2"),
                r#"{"ARTIFACTS_COUNT": "3", "BRANCH": "v6.4.1-dev.0", "CARRY_FORWARDS": "- none", "COMMITS": "abc1234 first\ndef5678 second", "DATE": "2026-08-02", "DRIFT_RISK_COUNT": "0", "FILES_OF_INTEREST": "- services/cli/", "LOCK_COUNT": "1", "MEM_COUNT": "2", "NEXT_FOCUS": "- retire bash", "NORTH_STAR": "one canonical CLI", "OPEN_ISSUES_COUNT": "27", "SESSION": "sess-0001"}"#,
                "8122bd9fffde6b07089f8fdf2b839381121a5f9b728e704943efbbc982f8b157",
            ),
            (
                "boot-prompt.md.j2",
                include_str!("../../../services/cli/shepherd_cli/templates/boot-prompt.md.j2"),
                r#"{"base_commit": "abc1234", "carry_forward_issues": "-", "claude_md_path": "/repo/CLAUDE.md", "fanout_mode": "lane", "git_custody": "lane", "lane_index": "1_of_2", "lane_plan_path": ".shepherd/runs/v641-dev0/lanes/a/plan.md", "lead_effort": "ultracode", "model_pin": "sonnet", "parallel_index": 2, "peer_teammate_names": ["lane-a & b", "lane <c>", "lane's-d"], "plan_path": ".shepherd/runs/v641-dev0/plan.md", "plugin_root": "/plug", "prior_handoff_path": "-", "root_session_name": "shepherd-root @ sess-1", "run_dir": ".shepherd/runs/v641-dev0", "scope": "sprint", "seed_path": ".shepherd/runs/v641-dev0/seed.md", "team_id": "team-1", "toml_snapshot": "[models]\nlead = \"opus\"", "wave_index": "1_of_2", "worktree_path": "/repo/.worktrees/v641-dev0-lane-1"}"#,
                "54d2fd3cc144c6c041a03ce88d9ffa468b2747acb70ce889c5dcad623d69064f",
            ),
            (
                "seed.md.j2",
                include_str!("../../../services/cli/shepherd_cli/templates/seed.md.j2"),
                r#"{"author": "@engineer", "date": "2026-08-12", "file_scope_additive": [], "file_scope_exclusive": ["crates/render/src/env.rs", "crates/render/src/filters.rs"], "kind": "sprint", "milestone": "v6.4.5", "parallel_with": [], "patch_branch": "v645", "patch_seed": ".shepherd/runs/v645/seed.md", "planter_mesh": ".shepherd/runs/v645/mesh.md", "prior_close_report": ".shepherd/runs/v644-dev0/close.md", "prior_handoff": ".shepherd/runs/v644-dev0/handoff.md", "prior_sprint": "v644-dev0", "sprint_branch": "v645-dev0", "sprint_dependencies": ["W1-GATE", "issue & 244", "path's/segment"], "sprint_size": "large", "theme": "render parity"}"#,
                "599676e84a39f04ef126c2ac10fd14bcb95e2b8f9246cd821041fb8bea27ce12",
            ),
            (
                "plan.md.j2",
                include_str!("../../../services/cli/shepherd_cli/templates/plan.md.j2"),
                r#"{"architecture": "minijinja Environment + hand-written tojson", "global_constraints": ["byte-identical output", "no new dependency"], "goal": "port render.py to shepherd-render", "seed_path": ".shepherd/runs/v645/seed.md", "sprint_branch": "v645-dev0"}"#,
                "2ad699c9f218efceccff98bc1b41666710b4027293689cb3393a65b0d6292cb3",
            ),
            (
                "lane-plan.md.j2",
                include_str!("../../../services/cli/shepherd_cli/templates/lane-plan.md.j2"),
                r#"{"acceptance": ["conformance/run.sh --impl=rust --suite=render"], "base_commit": "446d88e", "do_not_duplicate": [], "file_scope": {"exclusive": ["crates/render/src/env.rs", "crates/render/src/filters.rs"], "may_read": []}, "git_custody": "lane", "interfaces": {"consumes": ["conformance/run.sh --impl=rust --suite=render"], "produces": []}, "lane_id": "l2", "non_goals": [], "objective": "port render.py", "objective_title": "render parity", "parallel_with": [], "run": "v645-dev0", "steps": [{"acceptance": "cargo test -p shepherd-render env::tests::matches_python_settings", "actions": ["build the environment", "register tojson"], "file_scope": {"must_not_touch": ["crates/core/**"]}, "step_id": "W2-S1"}], "worktree_path": "/repo/.worktrees/v645-l2"}"#,
                "6878bc3854db3b5fd9dcc61d824f6450b58b4749dd77e73bee2483d9dbb80ee4",
            ),
        ];

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
                "{name}: output diverged from the frozen render.py oracle"
            );
        }
    }
}
