/*
    Appellation: default <module>
    Created At: 2026.04.19:15:24:41
    Contrib: @FL03
*/

/// Compile-time assertion to ensure the features are properly re-exported
#[test]
fn ff_resolve() {
    #[cfg(feature = "channels")]
    {
        let _: Option<axiom::channels::ChannelRegistry> = None;
        let _: Option<axiom::channels::ChannelSubscription> = None;
    }
    #[cfg(feature = "sim")]
    {
        let _: Option<axiom::sim::SimMode> = None;
    }
}
