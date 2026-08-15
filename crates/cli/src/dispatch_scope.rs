//! Native extraction and race-safe containment of write-tool targets.

use std::path::{Component, Path};

use serde_json::Value;

use crate::DispatchServiceError;

const WRITE_TOOLS: &[&str] = &["Write", "Edit", "apply_patch"];

pub(crate) fn derive_write_paths(
    primary_root: &Path,
    tool_name: Option<&str>,
    tool_input: Option<&Value>,
) -> Result<Vec<String>, DispatchServiceError> {
    let Some(tool_name) = tool_name else {
        if tool_input.is_some() {
            return Err(invalid("tool_input requires tool_name"));
        }
        return Ok(Vec::new());
    };
    if !WRITE_TOOLS.contains(&tool_name) {
        return Ok(Vec::new());
    }
    let input = tool_input
        .and_then(Value::as_object)
        .ok_or_else(|| invalid("write tool input must be an object"))?;
    let mut raw = Vec::new();
    for key in ["file_path", "path"] {
        if let Some(value) = input.get(key) {
            raw.push(
                value
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| invalid(format!("tool_input.{key} must be a string")))?,
            );
        }
    }
    if tool_name == "apply_patch"
        && let Some(patch) = input.get("patch").or_else(|| input.get("input"))
    {
        let patch = patch
            .as_str()
            .ok_or_else(|| invalid("apply_patch input must be a string"))?;
        raw.extend(extract_patch_paths(patch)?);
    }
    raw.sort_unstable();
    raw.dedup();
    if raw.is_empty() {
        return Err(invalid(format!(
            "cannot derive native write path from `{tool_name}` input"
        )));
    }

    let mut paths = Vec::with_capacity(raw.len());
    for candidate in raw {
        let relative = normalize_relative(primary_root, candidate)?;
        verify_nofollow(primary_root, &relative)?;
        paths.push(relative);
    }
    paths.sort();
    paths.dedup();
    Ok(paths)
}

fn extract_patch_paths(patch: &str) -> Result<Vec<&str>, DispatchServiceError> {
    if patch.len() > 1_048_576 || patch.contains('\0') {
        return Err(invalid("apply_patch input is unsafe or too large"));
    }
    let mut paths = Vec::new();
    for line in patch.lines() {
        for prefix in [
            "*** Add File: ",
            "*** Update File: ",
            "*** Delete File: ",
            "*** Move to: ",
        ] {
            if let Some(path) = line.strip_prefix(prefix) {
                if path.is_empty() || path.trim() != path {
                    return Err(invalid("apply_patch contains an invalid path header"));
                }
                paths.push(path);
            }
        }
    }
    if paths.is_empty() {
        return Err(invalid("apply_patch contains no canonical file headers"));
    }
    Ok(paths)
}

fn normalize_relative(
    primary_root: &Path,
    candidate: &str,
) -> Result<String, DispatchServiceError> {
    if candidate.len() > 4_096
        || candidate.contains(['\\', '\0'])
        || candidate.chars().any(char::is_control)
    {
        return Err(invalid("write path is unsafe"));
    }
    let candidate = Path::new(candidate);
    let relative = if candidate.is_absolute() {
        candidate
            .strip_prefix(primary_root)
            .map_err(|_| invalid("absolute write path escapes the primary repository"))?
    } else {
        candidate
    };
    let mut parts = Vec::new();
    for component in relative.components() {
        match component {
            Component::Normal(part) => {
                let value = part
                    .to_str()
                    .ok_or_else(|| invalid("write path must be UTF-8"))?;
                if value.is_empty() || value == "." || value == ".." {
                    return Err(invalid("write path has an unsafe component"));
                }
                parts.push(value);
            }
            _ => {
                return Err(invalid(
                    "write path must be normalized and repository-relative",
                ));
            }
        }
    }
    if parts.is_empty() {
        return Err(invalid("write path cannot name the repository root"));
    }
    Ok(parts.join("/"))
}

#[cfg(unix)]
fn verify_nofollow(primary_root: &Path, relative: &str) -> Result<(), DispatchServiceError> {
    use rustix::fs::{FileType, Mode, OFlags, open, openat};

    let mut directory = open(
        primary_root,
        OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
        Mode::empty(),
    )
    .map_err(|error| {
        invalid(format!(
            "cannot open primary root without following links: {error}"
        ))
    })?;
    let parts: Vec<&str> = relative.split('/').collect();
    for (index, part) in parts.iter().enumerate() {
        let final_component = index + 1 == parts.len();
        let flags = if final_component {
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW
        } else {
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW
        };
        match openat(&directory, *part, flags, Mode::empty()) {
            Ok(next) if final_component => {
                let stat = rustix::fs::fstat(&next)
                    .map_err(|error| invalid(format!("cannot inspect write target: {error}")))?;
                if !FileType::from_raw_mode(stat.st_mode).is_file() {
                    return Err(invalid("existing write target is not a regular file"));
                }
            }
            Ok(next) => directory = next,
            Err(error) if final_component && error == rustix::io::Errno::NOENT => return Ok(()),
            Err(error) => {
                return Err(invalid(format!(
                    "write target is not safely contained without following links: {error}"
                )));
            }
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn verify_nofollow(_primary_root: &Path, _relative: &str) -> Result<(), DispatchServiceError> {
    Err(invalid(
        "race-safe write-path containment is unavailable on this platform",
    ))
}

fn invalid(reason: impl Into<String>) -> DispatchServiceError {
    DispatchServiceError::InvalidRequest(reason.into())
}
