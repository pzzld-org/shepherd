/*
    Appellation: loader <test>
    Created At: 2026.08.12:17:30:00
    Contrib: @FL03
*/
//! The configuration precedence contract.
//!
//! This is the layer most worth pinning. The bash implementation
//! (`src/hooks/scripts/_lib.sh:shctx_config_files`) is the incumbent and the
//! 32 guard scripts still read it, so any divergence between it and the engine
//! is a config file silently ignored — no error, no log line, just a value
//! that does not take effect.
#![cfg(all(feature = "config", feature = "std"))]

use std::path::{Path, PathBuf};

use shepherd_core::loader::{self, ConfigContext, ConfigTier};
use shepherd_core::types::Harness;

fn context(harness: Option<Harness>) -> ConfigContext {
    ConfigContext {
        namespace: PathBuf::from("/repo/.shepherd"),
        repo_root: PathBuf::from("/repo"),
        user_home: PathBuf::from("/home/jo3/.shepherd"),
        xdg_config_home: PathBuf::from("/home/jo3/.config"),
        harness,
    }
}

/// Transcribed from `_lib.sh:shctx_config_files()`. If the bash layer changes,
/// this fails and someone decides deliberately rather than discovering the
/// divergence months later through a config that does not apply.
#[test]
fn the_chain_matches_the_bash_implementation_with_a_harness() {
    let got: Vec<String> = loader::candidates(&context(Some(Harness::ClaudeCode)))
        .into_iter()
        .map(|c| c.path.display().to_string())
        .collect();

    assert_eq!(
        got,
        vec![
            // project layer (highest): local -> harness -> base
            "/repo/.shepherd/shepherd.local.toml",
            "/repo/.shepherd/shepherd.claude_code.toml",
            "/repo/.shepherd/shepherd.toml",
            // legacy project layer -- pre-v6.4.2, honoured indefinitely
            "/repo/.claude/shepherd.local.toml",
            "/repo/.claude/shepherd.toml",
            // user layer (defaults): local -> harness -> base
            "/home/jo3/.shepherd/shepherd.local.toml",
            "/home/jo3/.shepherd/shepherd.claude_code.toml",
            "/home/jo3/.shepherd/shepherd.toml",
            // legacy user global
            "/home/jo3/.config/shepherd.toml",
        ]
    );
}

/// Without a harness the two harness-specific slots disappear and nothing else
/// shifts. The bash version guards both with the same `[[ -n "$harness" ]]`.
#[test]
fn the_harness_slots_are_the_only_difference_when_there_is_no_harness() {
    let with: Vec<PathBuf> = loader::candidates(&context(Some(Harness::Pi)))
        .into_iter()
        .map(|c| c.path)
        .collect();
    let without: Vec<PathBuf> = loader::candidates(&context(None))
        .into_iter()
        .map(|c| c.path)
        .collect();

    assert_eq!(with.len(), 9);
    assert_eq!(without.len(), 7);

    let removed: Vec<&PathBuf> = with.iter().filter(|p| !without.contains(p)).collect();
    assert_eq!(
        removed,
        vec![
            &PathBuf::from("/repo/.shepherd/shepherd.pi.toml"),
            &PathBuf::from("/home/jo3/.shepherd/shepherd.pi.toml"),
        ]
    );
}

/// The harness reaches the filename through its serialised form, so the file a
/// user is told to create matches the value they put in their config.
#[test]
fn the_harness_filename_uses_the_wire_form() {
    let paths: Vec<String> = loader::candidates(&context(Some(Harness::PrimeAgent)))
        .into_iter()
        .map(|c| c.path.display().to_string())
        .collect();

    assert!(paths.contains(&"/repo/.shepherd/shepherd.prime_agent.toml".to_string()));
}

/// Tiers are ordered and carried, so a consumer can answer "why did this value
/// win" rather than just "what is the value".
#[test]
fn tiers_are_ordered_by_authority() {
    let tiers: Vec<ConfigTier> = loader::candidates(&context(Some(Harness::Codex)))
        .into_iter()
        .map(|c| c.tier)
        .collect();

    assert!(
        tiers.windows(2).all(|w| w[0] <= w[1]),
        "candidates must be emitted in non-decreasing tier order: {tiers:?}"
    );
    assert_eq!(tiers.first(), Some(&ConfigTier::Project));
    assert_eq!(tiers.last(), Some(&ConfigTier::LegacyUser));
}

/// THE INVERSION. `candidates` is highest-priority-first; `config` applies
/// later sources with higher priority. If `layer` ever stops reversing, this
/// test reads `/fallback` instead of `/winner` — configuration that loads
/// without error and is exactly backwards.
#[test]
fn the_highest_priority_layer_wins() {
    let project = Path::new("/repo/.shepherd/shepherd.toml");
    let user = Path::new("/home/jo3/.shepherd/shepherd.toml");

    let config = loader::layer([
        (project, "[workspace]\nworkdir = \"/winner\"\n"),
        (user, "[workspace]\nworkdir = \"/fallback\"\n"),
    ])
    .expect("both layers parse");

    assert_eq!(config.workspace.workdir, PathBuf::from("/winner"));
}

/// A lower-priority layer still supplies what a higher one omits; layering is
/// a merge, not a replacement.
#[test]
fn a_lower_layer_fills_what_a_higher_one_omits() {
    let project = Path::new("/repo/.shepherd/shepherd.local.toml");
    let user = Path::new("/home/jo3/.shepherd/shepherd.toml");

    // The higher-priority layer says nothing about `workdir`.
    let config = loader::layer([
        (project, "# deliberately empty\n"),
        (user, "[workspace]\nworkdir = \"/from-user\"\n"),
    ])
    .expect("layers merge");

    assert_eq!(config.workspace.workdir, PathBuf::from("/from-user"));
}

/// A malformed layer is named, because "invalid configuration" without a path
/// is a bug report nobody can act on.
#[test]
fn a_malformed_layer_names_its_file() {
    let path = Path::new("/repo/.shepherd/shepherd.local.toml");
    let error = loader::validate(path, "workspace = [ this is not toml").expect_err("must fail");

    let rendered = error.to_string();
    assert!(
        rendered.contains("shepherd.local.toml"),
        "the error must name the offending file, got: {rendered}"
    );
}
