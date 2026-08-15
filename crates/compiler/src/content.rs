//! Canonical authored-content loading shared by the CLI and component.
//!
//! The parser lives beside the typed compiler input so every host reaches the
//! same frontmatter validation and source provenance. The component's embedded
//! path and the CLI's filesystem path both use these functions; neither host
//! owns a second Markdown/YAML parser.

use std::{
    fs,
    path::{Path, PathBuf},
};

use serde::Deserialize;

use crate::{CompileInput, Portability, RoleInput, SkillInput};

mod embedded {
    include!(concat!(env!("OUT_DIR"), "/embedded_content.rs"));
}

type EmbeddedSource = (&'static str, &'static str);
type EmbeddedSources = &'static [EmbeddedSource];

#[derive(Debug)]
pub enum ContentError {
    Io { path: PathBuf, message: String },
    InvalidFrontmatter { path: String },
    InvalidMetadata { path: String, message: String },
    InvalidSource { path: String, message: String },
}

impl std::fmt::Display for ContentError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io { path, message } => write!(formatter, "{}: {message}", path.display()),
            Self::InvalidFrontmatter { path } => {
                let kind = if path.contains("/roles/") {
                    "role"
                } else if path.contains("/skills/") {
                    "skill"
                } else {
                    "content"
                };
                write!(formatter, "{path}: invalid {kind} frontmatter")
            }
            Self::InvalidMetadata { path, message } => write!(formatter, "{path}: {message}"),
            Self::InvalidSource { path, message } => write!(formatter, "{path}: {message}"),
        }
    }
}

impl std::error::Error for ContentError {}

/// Parse the canonical content from an on-disk `content/` directory.
pub fn load_compile_input(content_dir: &Path) -> Result<CompileInput, ContentError> {
    let roles_dir = content_dir.join("roles");
    let skills_dir = content_dir.join("skills");
    let mut role_paths = regular_children(&roles_dir, ChildKind::MarkdownFile)?;
    let mut skill_paths = regular_children(&skills_dir, ChildKind::Directory)?;
    role_paths.sort();
    skill_paths.sort();

    if role_paths.is_empty() {
        return Err(ContentError::InvalidSource {
            path: roles_dir.display().to_string(),
            message: "zero role files".into(),
        });
    }
    if skill_paths.is_empty() {
        return Err(ContentError::InvalidSource {
            path: skills_dir.display().to_string(),
            message: "zero skill directories".into(),
        });
    }

    let roles = role_paths
        .into_iter()
        .map(|path| load_role(content_dir, &path))
        .collect::<Result<Vec<_>, _>>()?;
    let skills = skill_paths
        .into_iter()
        .map(|path| load_skill(content_dir, &path))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(CompileInput { roles, skills })
}

/// Parse the canonical corpus embedded at build time from the repository's
/// top-level `content/` tree.
pub fn embedded_compile_input() -> Result<CompileInput, ContentError> {
    if embedded::EMBEDDED_ROLES.is_empty() || embedded::EMBEDDED_SKILLS.is_empty() {
        return Err(ContentError::InvalidSource {
            path: "content".into(),
            message: "embedded canonical content must contain roles and skills".into(),
        });
    }
    let roles = embedded::EMBEDDED_ROLES
        .iter()
        .map(|(source, raw)| parse_role(source, raw))
        .collect::<Result<Vec<_>, _>>()?;
    let skills = embedded::EMBEDDED_SKILLS
        .iter()
        .map(|(source, raw)| parse_skill(source, raw))
        .collect::<Result<Vec<_>, _>>()?;
    Ok(CompileInput { roles, skills })
}

/// Return the raw canonical predicate and role sources for the guard engine.
/// The bytes are embedded by the same build script as compile inputs, so a
/// host cannot accidentally supply a second policy corpus.
pub fn embedded_guard_sources() -> (EmbeddedSources, EmbeddedSources) {
    (embedded::EMBEDDED_PREDICATES, embedded::EMBEDDED_ROLES)
}

/// Return the canonical handoff template embedded from generated package content.
#[must_use]
pub fn embedded_handoff_template() -> &'static str {
    embedded::EMBEDDED_TEMPLATES
        .iter()
        .find_map(|(path, raw)| (*path == "content/templates/handoff.md").then_some(*raw))
        .expect("generated package content must contain content/templates/handoff.md")
}

#[derive(Clone, Copy)]
enum ChildKind {
    MarkdownFile,
    Directory,
}

fn regular_children(directory: &Path, kind: ChildKind) -> Result<Vec<PathBuf>, ContentError> {
    let entries = fs::read_dir(directory).map_err(|error| ContentError::Io {
        path: directory.to_owned(),
        message: format!("cannot read directory: {error}"),
    })?;
    let mut paths = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|error| ContentError::Io {
            path: directory.to_owned(),
            message: format!("cannot read entry: {error}"),
        })?;
        let file_type = entry.file_type().map_err(|error| ContentError::Io {
            path: entry.path(),
            message: format!("cannot inspect entry: {error}"),
        })?;
        let path = entry.path();
        if file_type.is_symlink() {
            return Err(ContentError::InvalidSource {
                path: path.display().to_string(),
                message: "symlinks are not valid authored content".into(),
            });
        }
        match kind {
            ChildKind::MarkdownFile if file_type.is_file() => {
                if path.extension().and_then(|value| value.to_str()) != Some("md") {
                    return Err(ContentError::InvalidSource {
                        path: path.display().to_string(),
                        message: "expected a .md role file".into(),
                    });
                }
                paths.push(path);
            }
            ChildKind::Directory if file_type.is_dir() => paths.push(path),
            _ => {
                return Err(ContentError::InvalidSource {
                    path: path.display().to_string(),
                    message: "unexpected authored content entry".into(),
                });
            }
        }
    }
    Ok(paths)
}

fn load_role(content_dir: &Path, path: &Path) -> Result<RoleInput, ContentError> {
    let raw = read_regular_utf8(path)?;
    let source = relative_source(content_dir, path)?;
    parse_role(&source, &raw)
}

fn parse_role(source: &str, raw: &str) -> Result<RoleInput, ContentError> {
    let path = Path::new(source);
    let (frontmatter, body) = split_frontmatter(path, raw)?;
    let metadata: RoleFrontmatter =
        serde_saphyr::from_str(frontmatter).map_err(|_| ContentError::InvalidFrontmatter {
            path: path.display().to_string(),
        })?;
    let filename = path
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| ContentError::InvalidSource {
            path: path.display().to_string(),
            message: "role filename is not UTF-8".into(),
        })?;
    if metadata.role != filename {
        return Err(ContentError::InvalidMetadata {
            path: path.display().to_string(),
            message: format!(
                "role `{}` does not match filename `{filename}`",
                metadata.role
            ),
        });
    }
    if metadata.source.trim().is_empty() {
        return Err(ContentError::InvalidMetadata {
            path: path.display().to_string(),
            message: "source must not be empty".into(),
        });
    }
    Ok(RoleInput {
        role: metadata.role,
        description: metadata.description,
        model_hint: metadata.model_hint,
        write_eligible: metadata.write_eligible,
        dispatchable: metadata.dispatchable,
        capabilities: metadata.capabilities,
        write_scope: metadata.write_scope,
        body: body.into(),
        source_path: source.to_owned(),
        source_content: raw.to_owned(),
    })
}

fn load_skill(content_dir: &Path, directory: &Path) -> Result<SkillInput, ContentError> {
    let path = directory.join("SKILL.md");
    let raw = read_regular_utf8(&path)?;
    let source = relative_source(content_dir, &path)?;
    parse_skill(&source, &raw)
}

fn parse_skill(source: &str, raw: &str) -> Result<SkillInput, ContentError> {
    let path = Path::new(source);
    let directory = path.parent().ok_or_else(|| ContentError::InvalidSource {
        path: path.display().to_string(),
        message: "skill source has no directory".into(),
    })?;
    let (frontmatter, body) = split_frontmatter(path, raw)?;
    let metadata: SkillFrontmatter =
        serde_saphyr::from_str(frontmatter).map_err(|_| ContentError::InvalidFrontmatter {
            path: path.display().to_string(),
        })?;
    let directory_name = directory
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| ContentError::InvalidSource {
            path: path.display().to_string(),
            message: "skill directory is not UTF-8".into(),
        })?;
    if metadata.name != directory_name {
        return Err(ContentError::InvalidMetadata {
            path: path.display().to_string(),
            message: format!(
                "skill `{}` does not match directory `{directory_name}`",
                metadata.name
            ),
        });
    }
    if metadata.source.trim().is_empty() {
        return Err(ContentError::InvalidMetadata {
            path: path.display().to_string(),
            message: "source must not be empty".into(),
        });
    }
    let portability = match metadata.portability.as_str() {
        "cross-harness" => Portability::CrossHarness,
        "claude-only" => Portability::ClaudeOnly,
        "unverified" => Portability::Unverified,
        value => {
            return Err(ContentError::InvalidMetadata {
                path: path.display().to_string(),
                message: format!("unsupported portability `{value}`"),
            });
        }
    };
    Ok(SkillInput {
        name: metadata.name,
        description: metadata.description,
        portability,
        body: body.into(),
        source_path: source.to_owned(),
        source_content: raw.to_owned(),
    })
}

fn read_regular_utf8(path: &Path) -> Result<String, ContentError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| ContentError::Io {
        path: path.to_owned(),
        message: format!("cannot inspect file: {error}"),
    })?;
    if !metadata.file_type().is_file() {
        return Err(ContentError::InvalidSource {
            path: path.display().to_string(),
            message: "expected a regular file".into(),
        });
    }
    fs::read_to_string(path).map_err(|error| ContentError::Io {
        path: path.to_owned(),
        message: format!("cannot read UTF-8 content: {error}"),
    })
}

fn split_frontmatter<'a>(path: &Path, raw: &'a str) -> Result<(&'a str, &'a str), ContentError> {
    let raw = raw
        .strip_prefix("---\n")
        .or_else(|| raw.strip_prefix("---\r\n"))
        .ok_or_else(|| ContentError::InvalidFrontmatter {
            path: path.display().to_string(),
        })?;
    raw.split_once("\n---\n")
        .or_else(|| raw.split_once("\r\n---\r\n"))
        .ok_or_else(|| ContentError::InvalidFrontmatter {
            path: path.display().to_string(),
        })
}

fn relative_source(content_dir: &Path, path: &Path) -> Result<String, ContentError> {
    let parent = content_dir
        .parent()
        .ok_or_else(|| ContentError::InvalidSource {
            path: content_dir.display().to_string(),
            message: "content directory has no parent".into(),
        })?;
    path.strip_prefix(parent)
        .map_err(|_| ContentError::InvalidSource {
            path: path.display().to_string(),
            message: "source escaped content root".into(),
        })?
        .to_str()
        .map(|source| source.replace('\\', "/"))
        .ok_or_else(|| ContentError::InvalidSource {
            path: path.display().to_string(),
            message: "source path is not UTF-8".into(),
        })
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RoleFrontmatter {
    role: String,
    description: String,
    source: String,
    model_hint: String,
    write_eligible: bool,
    dispatchable: bool,
    capabilities: Vec<String>,
    write_scope: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SkillFrontmatter {
    name: String,
    description: String,
    source: String,
    portability: String,
}
