//! Pure, segment-aware dispatch write-scope validation and matching.

#[cfg(feature = "alloc")]
use alloc::{string::String, vec::Vec};

use super::{DispatchError, DispatchResult};

/// Return whether one already repository-relative path is inside any declared
/// dispatch scope. Invalid paths and unsupported glob syntax are errors rather
/// than non-matches so callers can fail closed.
pub fn path_in_write_scope(path: &str, scopes: &[String]) -> DispatchResult<bool> {
    let path_parts = validate_write_path(path)?;
    for scope in scopes {
        let scope_parts = validate_write_scope_pattern(scope)?;
        if matches_scope(&path_parts, &scope_parts) {
            return Ok(true);
        }
    }
    Ok(false)
}

pub(crate) fn validate_write_scope_pattern(scope: &str) -> DispatchResult<Vec<&str>> {
    if scope.is_empty()
        || scope.len() > 512
        || scope.starts_with('/')
        || scope.contains(['\\', '\0'])
        || scope.chars().any(char::is_control)
    {
        return Err(DispatchError::InvalidWriteScope(scope.into()));
    }
    let parts: Vec<&str> = scope.split('/').collect();
    let valid = parts.iter().enumerate().all(|(index, part)| {
        !part.is_empty()
            && *part != "."
            && *part != ".."
            && (*part == "*"
                || (*part == "**" && index + 1 == parts.len())
                || (part.starts_with('*') && part.len() > 1 && part[1..].find('*').is_none())
                || !part.contains('*'))
    });
    if valid {
        Ok(parts)
    } else {
        Err(DispatchError::InvalidWriteScope(scope.into()))
    }
}

fn validate_write_path(path: &str) -> DispatchResult<Vec<&str>> {
    if path.is_empty()
        || path.len() > 4_096
        || path.starts_with('/')
        || path.contains(['\\', '\0', '*'])
        || path.chars().any(char::is_control)
    {
        return Err(DispatchError::InvalidWriteScope(path.into()));
    }
    let parts: Vec<&str> = path.split('/').collect();
    if parts
        .iter()
        .any(|part| part.is_empty() || *part == "." || *part == "..")
    {
        return Err(DispatchError::InvalidWriteScope(path.into()));
    }
    Ok(parts)
}

fn matches_scope(path: &[&str], scope: &[&str]) -> bool {
    let recursive = scope.last() == Some(&"**");
    let fixed = if recursive {
        &scope[..scope.len() - 1]
    } else {
        scope
    };
    if path.len() < fixed.len() || (!recursive && path.len() != fixed.len()) {
        return false;
    }
    fixed.iter().zip(path).all(|(expected, actual)| {
        *expected == "*"
            || expected == actual
            || expected
                .strip_prefix('*')
                .is_some_and(|suffix| !suffix.is_empty() && actual.ends_with(suffix))
    })
}
