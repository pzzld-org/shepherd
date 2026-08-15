//! CLI adapters for the shared canonical-content loader.
//!
//! Parsing and embedding belong to `shepherd_compiler::content`; this module
//! only maps its typed errors onto the CLI's exit/reporting boundary.

use std::path::Path;

use shepherd::compiler::{CompileInput, content};

use crate::CliError;

/// Load authored content from a filesystem `content/` directory.
pub fn load_compile_input(content_dir: &Path) -> Result<CompileInput, CliError> {
    content::load_compile_input(content_dir).map_err(|error| CliError::message(error.to_string()))
}

/// Parse the one canonical corpus embedded by `shepherd-compiler` at build
/// time. The CLI and WASM component therefore receive identical typed inputs.
pub fn embedded_compile_input() -> Result<CompileInput, CliError> {
    content::embedded_compile_input().map_err(|error| CliError::message(error.to_string()))
}
