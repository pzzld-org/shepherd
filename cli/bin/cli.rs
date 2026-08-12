/*
    Appellation: cli <module>
    Created At: 2026.08.12:14:49:29
    Contrib: @FL03
*/
use shepherd_cli::ShepherdCli;

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::TRACE)
        .init();

    tracing::debug!("Parsing cli arguments...");
    let cli = ShepherdCli::parse();
    tracing::debug!(
        config = %cli.config,
        release = cli.release,
        update = cli.update,
        verbose = cli.verbose,
        "parsed cli arguments"
    );

    Ok(())
}
