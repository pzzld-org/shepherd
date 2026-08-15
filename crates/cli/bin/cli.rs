/*
    Appellation: cli <module>
    Created At: 2026.08.12:14:49:29
    Contrib: @FL03
*/
use std::process::ExitCode;

use shepherd_cli::ShepherdCli;

fn main() -> ExitCode {
    let cli = ShepherdCli::parse();
    match cli.run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            if let Some(message) = error.message_text() {
                eprintln!("ERROR: {message}");
            }
            ExitCode::from(error.exit_code())
        }
    }
}
