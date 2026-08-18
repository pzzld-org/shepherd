/*
    Appellation: guard-tokenizer <module>
    Created At: 2026.08.14:00:00:00
    Contrib: @FL03
*/
//! Shell-token-compatible git subcommand extraction for the frozen guard wire.

use alloc::{string::String, vec::Vec};

const MAX_RECURSION_DEPTH: usize = 6;

const GIT_GLOBAL_OPTIONS_TAKING_ARGUMENTS: &[&str] = &[
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--config-env",
    "--super-prefix",
];

const SHELL_WRAPPERS: &[&str] = &["bash", "sh", "zsh", "dash", "ksh", "env", "xargs"];

/// Extract every git subcommand in encounter order.
///
/// This intentionally preserves the v6.4.7 token-level compatibility limits:
/// shell separators remain glued unless whitespace made them separate tokens.
/// Like `shlex`, the primary tokenizer recognizes only space, tab, carriage
/// return, and line feed as whitespace. Its malformed-quote fallback retains
/// the previously frozen broader Unicode-whitespace fallback behavior.
pub fn extract_git_subcommands(command: &str) -> Vec<String> {
    extract_at_depth(command, 0)
}

fn extract_at_depth(command: &str, depth: usize) -> Vec<String> {
    let mut output = Vec::new();
    if depth > MAX_RECURSION_DEPTH {
        return output;
    }
    let tokens = split_posix(command).unwrap_or_else(|()| {
        command
            .split_whitespace()
            .map(String::from)
            .collect::<Vec<_>>()
    });

    let mut index = 0;
    while index < tokens.len() {
        let base = tokens[index].rsplit('/').next().unwrap_or_default();
        if base == "git" {
            let mut candidate = index + 1;
            while candidate < tokens.len() {
                let option = &tokens[candidate];
                if GIT_GLOBAL_OPTIONS_TAKING_ARGUMENTS.contains(&option.as_str()) {
                    candidate += 2;
                    continue;
                }
                if option.starts_with("--") && option.contains('=') {
                    candidate += 1;
                    continue;
                }
                if option.starts_with('-') {
                    candidate += 1;
                    continue;
                }
                let end = option.find([';', '&', '|']).unwrap_or(option.len());
                let subcommand = option[..end].to_lowercase();
                if !subcommand.is_empty() {
                    output.push(subcommand);
                }
                break;
            }
            index = candidate.saturating_add(1);
        } else if base == "eval" {
            for token in &tokens[index + 1..] {
                output.extend(extract_at_depth(token, depth + 1));
            }
            index += 1;
        } else if SHELL_WRAPPERS.contains(&base) {
            let mut candidate = index + 1;
            while candidate < tokens.len() {
                if tokens[candidate] == "-c" && candidate + 1 < tokens.len() {
                    output.extend(extract_at_depth(&tokens[candidate + 1], depth + 1));
                    candidate += 2;
                    continue;
                }
                candidate += 1;
            }
            index += 1;
        } else {
            index += 1;
        }
    }
    output
}

#[derive(Clone, Copy)]
enum QuoteState {
    Unquoted,
    Single,
    Double,
}

fn split_posix(command: &str) -> Result<Vec<String>, ()> {
    let mut tokens = Vec::new();
    let mut token = String::new();
    let mut token_started = false;
    let mut state = QuoteState::Unquoted;
    let mut characters = command.chars();

    while let Some(character) = characters.next() {
        match state {
            QuoteState::Unquoted => match character {
                character if is_shlex_whitespace(character) => {
                    if token_started {
                        tokens.push(core::mem::take(&mut token));
                        token_started = false;
                    }
                }
                '\'' => {
                    state = QuoteState::Single;
                    token_started = true;
                }
                '"' => {
                    state = QuoteState::Double;
                    token_started = true;
                }
                '\\' => {
                    let escaped = characters.next().ok_or(())?;
                    token.push(escaped);
                    token_started = true;
                }
                _ => {
                    token.push(character);
                    token_started = true;
                }
            },
            QuoteState::Single => {
                if character == '\'' {
                    state = QuoteState::Unquoted;
                } else {
                    token.push(character);
                }
            }
            QuoteState::Double => match character {
                '"' => state = QuoteState::Unquoted,
                '\\' => {
                    let escaped = characters.next().ok_or(())?;
                    if matches!(escaped, '"' | '\\') {
                        token.push(escaped);
                    } else {
                        token.push('\\');
                        token.push(escaped);
                    }
                }
                _ => token.push(character),
            },
        }
    }

    if !matches!(state, QuoteState::Unquoted) {
        return Err(());
    }
    if token_started {
        tokens.push(token);
    }
    Ok(tokens)
}

const fn is_shlex_whitespace(character: char) -> bool {
    matches!(character, ' ' | '\t' | '\r' | '\n')
}
