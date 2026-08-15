/*
    Appellation: default <test>
    Created At: 2026.08.12:16:20:00
    Contrib: @FL03
*/
//! Compile-time assertions that the feature graph resolves to the surface each
//! flag advertises. These are cheap on purpose: the value is that they fail to
//! *compile* under a broken feature combination, which is the failure mode a
//! runtime assertion cannot catch.
extern crate shepherd_core as shepherd;

use shepherd::Harness;

/// Every flag exposes what it claims to.
#[test]
fn ff_resolve() {
    // always available, at the `alloc` floor
    let _: Option<shepherd::Error> = None;
    let _: Option<Harness> = None;

    #[cfg(feature = "std")]
    {
        let _: Option<shepherd::ShepherdConfig> = None;
        let _: Option<shepherd::settings::ProjectConfig> = None;
    }
}

/// `Harness` is a closed value set the engine carries. If a variant is added,
/// every adapter has a new case to answer for, so the count is pinned here
/// rather than discovered downstream at runtime.
#[test]
fn harness_is_a_closed_value_set() {
    use strum::{EnumCount, VariantNames};

    assert_eq!(Harness::COUNT, 4);
    assert_eq!(Harness::VARIANTS, ["claude", "codex", "pi", "prime_agent"]);
}

/// The wire form is snake_case in both directions, and parsing is
/// case-insensitive because harness names arrive from user-authored config.
#[test]
fn harness_round_trips_through_its_wire_form() {
    use core::str::FromStr;
    use strum::VariantNames;

    for variant in Harness::VARIANTS {
        let parsed = Harness::from_str(variant).expect("variant name must parse");
        assert_eq!(parsed.to_string(), *variant);
    }

    assert_eq!(Harness::from_str("CLAUDE").unwrap(), Harness::ClaudeCode);
    assert_eq!(
        Harness::from_str("CLAUDE_CODE").expect("the pre-v6.4.5 wire alias stays readable"),
        Harness::ClaudeCode,
    );
}

#[cfg(feature = "json")]
#[test]
fn harness_json_writes_the_canonical_name_and_reads_the_legacy_alias() {
    assert_eq!(
        serde_json::to_string(&Harness::ClaudeCode).expect("serialize harness"),
        r#""claude""#,
    );
    assert_eq!(
        serde_json::from_str::<Harness>(r#""claude_code""#).expect("read legacy alias"),
        Harness::ClaudeCode,
    );
}
