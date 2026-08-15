/*
    Appellation: default <test>
    Created At: 2026.04.19:15:24:41
    Contrib: @FL03
*/
//! Compile-time assertions that the umbrella re-exports what each feature
//! advertises.
//!
//! A feature graph rots silently: a capability flag keeps resolving long after
//! the re-export behind it was renamed or dropped, because nothing referenced
//! it. These assertions are what make the flag surface falsifiable.

/// The engine is flattened into the umbrella, so `shepherd::Harness` resolves
/// without the consumer ever naming `shepherd-core`. That indirection is the
/// point of the crate.
#[test]
fn ff_resolve() {
    let _: Option<shepherd::Harness> = None;
    let _: Option<shepherd::Error> = None;

    #[cfg(feature = "std")]
    {
        let _: Option<shepherd::ShepherdConfig> = None;
    }
    #[cfg(feature = "registry")]
    {
        let _: Option<shepherd::registry::Error> = None;
    }
    #[cfg(feature = "render")]
    {
        let _: Option<shepherd::render::Error> = None;
    }
    #[cfg(feature = "compiler")]
    {
        let _: Option<shepherd::compiler::CompileInput> = None;
    }
}

/// The umbrella's prelude must stay unambiguous with every capability enabled.
/// Each member defines its own `Error` and `Result`; if the member preludes are
/// ever globbed in alongside the engine's, this fails to compile with E0659.
#[test]
fn prelude_is_unambiguous_under_every_capability() {
    use shepherd::prelude::*;

    let _: Option<Error> = None;
    let _: Result<()> = Ok(());
}
