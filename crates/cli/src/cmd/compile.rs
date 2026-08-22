//! Canonical content compilation and owned-tree materialization.

use std::{
    io::{self, Write},
    path::PathBuf,
};

use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Component, Path},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use shepherd::compiler::{
    EmittedFile, EmittedKind, EmittedRole, EmittedTree, HarnessProfile, compile,
};

use crate::{
    content_compiler::{embedded_compile_input, load_compile_input},
    interface::CliError,
};

const MANIFEST_SCHEMA: &str = "shepherd.compiled-tree/3";
const MANIFEST_NAME: &str = ".shepherd-generated.json";
const LEGACY_MANIFEST_SCHEMAS: [&str; 2] = ["shepherd.compiled-tree/1", "shepherd.compiled-tree/2"];
const MAX_MANIFEST_BYTES: usize = 4 * 1_048_576;

#[derive(
    Clone,
    Copy,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::ValueEnum,
    serde::Deserialize,
    serde::Serialize,
)]
enum CompileTarget {
    Claude,
    Codex,
    Pi,
}

impl CompileTarget {
    fn profile(self) -> HarnessProfile {
        match self {
            Self::Claude => HarnessProfile::claude(),
            Self::Codex => HarnessProfile::codex(),
            Self::Pi => HarnessProfile::pi(),
        }
    }
}

#[derive(
    Clone,
    Debug,
    Eq,
    Hash,
    Ord,
    PartialEq,
    PartialOrd,
    clap::Args,
    serde::Deserialize,
    serde::Serialize,
)]
pub struct CompileCmd {
    /// Harness carrier to emit.
    #[arg(long, value_enum)]
    target: CompileTarget,
    /// Managed output tree. Omit to print the manifest without writing.
    #[arg(long, value_name = "DIRECTORY")]
    out: Option<PathBuf>,
    /// Verify an existing managed tree without changing it.
    #[arg(long, requires = "out")]
    check: bool,
    /// Explicit authored-content override for development and tests.
    #[arg(long, value_name = "DIRECTORY")]
    content_dir: Option<PathBuf>,
}

impl CompileCmd {
    pub(crate) fn run(self) -> Result<(), CliError> {
        let input = match self.content_dir {
            Some(path) => load_compile_input(&path)?,
            None => embedded_compile_input()?,
        };
        let tree = compile(&input, &self.target.profile())
            .map_err(|error| CliError::message(error.to_string()))?;
        let manifest = GeneratedManifest::from_tree(&tree);

        match self.out {
            None => write_manifest_stdout(&manifest),
            Some(path) if self.check => managed::check(&path, &manifest),
            Some(path) => managed::materialize(&path, &tree, &manifest),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct GeneratedManifest {
    schema: String,
    target: String,
    tree_digest: String,
    tokenizer_version: String,
    #[serde(default)]
    roles: Vec<GeneratedRole>,
    files: Vec<GeneratedEntry>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct GeneratedRole {
    role: String,
    carrier_path: String,
    description: String,
    #[serde(default)]
    model_hint: String,
    model: Option<String>,
    profile: Option<String>,
    reasoning_effort: Option<String>,
    tools: Vec<String>,
    unsupported_capabilities: Vec<String>,
    capabilities: Vec<String>,
    write_eligible: bool,
    dispatchable: bool,
    write_scope: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct GeneratedEntry {
    path: String,
    kind: String,
    source_path: String,
    source_sha256: String,
    content_sha256: String,
    lines: usize,
    words: usize,
    utf8_bytes: usize,
    prompt_tokens: usize,
}

impl GeneratedManifest {
    fn from_tree(tree: &EmittedTree) -> Self {
        Self {
            schema: MANIFEST_SCHEMA.into(),
            target: tree.target.as_str().into(),
            tree_digest: tree.digest.clone(),
            tokenizer_version: tree.tokenizer_version.into(),
            roles: tree.roles.iter().map(GeneratedRole::from_role).collect(),
            files: tree.files.iter().map(GeneratedEntry::from_file).collect(),
        }
    }

    fn validate(&self) -> Result<(), CliError> {
        if self.schema != MANIFEST_SCHEMA
            && !LEGACY_MANIFEST_SCHEMAS.contains(&self.schema.as_str())
        {
            return Err(CliError::message(
                "generated manifest has an unsupported schema",
            ));
        }
        if !matches!(self.target.as_str(), "claude" | "codex" | "pi") {
            return Err(CliError::message(
                "generated manifest has an unsupported target",
            ));
        }
        if self.tree_digest.len() != 64 || self.tokenizer_version.is_empty() {
            return Err(CliError::message(
                "generated manifest provenance is invalid",
            ));
        }
        if self.schema == MANIFEST_SCHEMA {
            if self.roles.is_empty() {
                return Err(CliError::message(
                    "generated manifest has zero role contracts",
                ));
            }
            let mut roles = BTreeSet::new();
            for role in &self.roles {
                validate_manifest_token("role", &role.role, 64)?;
                validate_relative(&role.carrier_path)?;
                validate_manifest_text("role description", &role.description, 500)?;
                validate_manifest_token("model hint", &role.model_hint, 64)?;
                validate_optional_manifest_token("model", role.model.as_deref(), 128)?;
                validate_optional_manifest_token("profile", role.profile.as_deref(), 64)?;
                validate_optional_manifest_token(
                    "reasoning effort",
                    role.reasoning_effort.as_deref(),
                    64,
                )?;
                validate_manifest_text("write scope", &role.write_scope, 4_096)?;
                if !roles.insert(role.role.as_str()) {
                    return Err(CliError::message(format!(
                        "generated manifest repeats role `{}`",
                        role.role
                    )));
                }
                for token in role
                    .tools
                    .iter()
                    .chain(&role.unsupported_capabilities)
                    .chain(&role.capabilities)
                {
                    validate_manifest_token("role contract token", token, 128)?;
                }
            }
        }
        let mut paths = BTreeSet::new();
        for entry in &self.files {
            validate_relative(&entry.path)?;
            validate_relative(&entry.source_path)?;
            if !paths.insert(entry.path.as_str()) {
                return Err(CliError::message(format!(
                    "generated manifest repeats path `{}`",
                    entry.path
                )));
            }
            if entry.source_sha256.len() != 64 || entry.content_sha256.len() != 64 {
                return Err(CliError::message(format!(
                    "generated manifest has invalid digest for `{}`",
                    entry.path
                )));
            }
        }
        if self.files.is_empty() {
            return Err(CliError::message("generated manifest has zero files"));
        }
        Ok(())
    }
}

impl GeneratedRole {
    fn from_role(role: &EmittedRole) -> Self {
        Self {
            role: role.role.clone(),
            carrier_path: role.carrier_path.clone(),
            description: role.description.clone(),
            model_hint: role.model_hint.clone(),
            model: role.model.clone(),
            profile: role.profile.clone(),
            reasoning_effort: role.reasoning_effort.clone(),
            tools: role.tools.clone(),
            unsupported_capabilities: role.unsupported_capabilities.clone(),
            capabilities: role.capabilities.clone(),
            write_eligible: role.write_eligible,
            dispatchable: role.dispatchable,
            write_scope: role.write_scope.clone(),
        }
    }
}

impl GeneratedEntry {
    fn from_file(file: &EmittedFile) -> Self {
        let kind = match file.kind {
            EmittedKind::Role => "role",
            EmittedKind::Skill => "skill",
            EmittedKind::Config => "config",
        };
        Self {
            path: file.path.clone(),
            kind: kind.into(),
            source_path: file.source_path.clone(),
            source_sha256: file.source_sha256.clone(),
            content_sha256: file.content_sha256.clone(),
            lines: file.measurement.lines,
            words: file.measurement.words,
            utf8_bytes: file.measurement.utf8_bytes,
            prompt_tokens: file.measurement.prompt_tokens,
        }
    }
}

fn write_manifest_stdout(manifest: &GeneratedManifest) -> Result<(), CliError> {
    let mut bytes = serde_json::to_vec_pretty(manifest)
        .map_err(|error| CliError::message(format!("cannot encode compiler manifest: {error}")))?;
    bytes.push(b'\n');
    io::stdout()
        .write_all(&bytes)
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn validate_relative(value: &str) -> Result<(), CliError> {
    if value.is_empty()
        || value.len() > 4_096
        || value.contains(['\\', '\0'])
        || value.chars().any(char::is_control)
        || Path::new(value)
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(CliError::message(format!(
            "generated path is unsafe: `{value}`"
        )));
    }
    Ok(())
}

fn validate_optional_manifest_token(
    field: &str,
    value: Option<&str>,
    max: usize,
) -> Result<(), CliError> {
    match value {
        Some(value) => validate_manifest_token(field, value, max),
        None => Ok(()),
    }
}

fn validate_manifest_token(field: &str, value: &str, max: usize) -> Result<(), CliError> {
    if value.is_empty()
        || value.len() > max
        || value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(CliError::message(format!(
            "generated manifest {field} is invalid"
        )));
    }
    Ok(())
}

fn validate_manifest_text(field: &str, value: &str, max: usize) -> Result<(), CliError> {
    if value.trim().is_empty() || value.len() > max || value.contains(['\0', '\r']) {
        return Err(CliError::message(format!(
            "generated manifest {field} is invalid"
        )));
    }
    Ok(())
}

fn sha256(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        write!(output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}

#[cfg(unix)]
mod managed {
    use std::{
        ffi::OsStr,
        fs::File,
        io::{Read, Write},
        os::fd::OwnedFd,
        path::{Component, Path, PathBuf},
        sync::atomic::{AtomicU64, Ordering},
    };

    use rustix::fs::{AtFlags, FileType, Mode, OFlags, mkdirat, open, openat, renameat, unlinkat};

    use super::{
        BTreeMap, CliError, EmittedTree, GeneratedManifest, MANIFEST_NAME, MAX_MANIFEST_BYTES,
        sha256, validate_relative,
    };

    static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

    pub(super) fn check(root: &Path, expected: &GeneratedManifest) -> Result<(), CliError> {
        let directory = open_root(root, false)?;
        let current = read_manifest(&directory)?.ok_or_else(|| {
            CliError::message(format!(
                "{} is not owned by a Shepherd generated manifest",
                root.display()
            ))
        })?;
        current.validate()?;
        if &current != expected {
            return Err(CliError::message(format!(
                "generated manifest drift for {}",
                root.display()
            )));
        }
        verify_owned_files(&directory, &current)?;
        Ok(())
    }

    pub(super) fn materialize(
        root: &Path,
        tree: &EmittedTree,
        expected: &GeneratedManifest,
    ) -> Result<(), CliError> {
        let directory = open_root(root, true)?;
        let previous = read_manifest(&directory)?;
        if let Some(manifest) = &previous {
            manifest.validate()?;
            if manifest.target != expected.target {
                return Err(CliError::message(format!(
                    "generated root {} belongs to target `{}`, not `{}`",
                    root.display(),
                    manifest.target,
                    expected.target
                )));
            }
            verify_owned_files(&directory, manifest)?;
        }

        let previous_by_path = previous
            .as_ref()
            .map(|manifest| {
                manifest
                    .files
                    .iter()
                    .map(|entry| (entry.path.as_str(), entry.content_sha256.as_str()))
                    .collect::<BTreeMap<_, _>>()
            })
            .unwrap_or_default();
        for file in &tree.files {
            validate_relative(&file.path)?;
            if previous_by_path.contains_key(file.path.as_str()) {
                continue;
            }
            if read_optional(&directory, &file.path, file.content.len().max(1_048_576))?.is_some() {
                return Err(CliError::message(format!(
                    "generated target `{}` is not owned by the prior manifest",
                    file.path
                )));
            }
        }

        for file in &tree.files {
            write_atomic(&directory, &file.path, file.content.as_bytes())?;
        }

        if let Some(previous) = &previous {
            let next = tree
                .files
                .iter()
                .map(|file| file.path.as_str())
                .collect::<std::collections::BTreeSet<_>>();
            for stale in previous
                .files
                .iter()
                .filter(|entry| !next.contains(entry.path.as_str()))
            {
                unlink_file(&directory, &stale.path)?;
            }
        }

        let mut manifest_bytes = serde_json::to_vec_pretty(expected).map_err(|error| {
            CliError::message(format!("cannot encode generated manifest: {error}"))
        })?;
        manifest_bytes.push(b'\n');
        write_atomic(&directory, MANIFEST_NAME, &manifest_bytes)?;
        directory_sync(&directory)?;
        Ok(())
    }

    fn verify_owned_files(
        directory: &OwnedFd,
        manifest: &GeneratedManifest,
    ) -> Result<(), CliError> {
        for entry in &manifest.files {
            let bytes = read_optional(directory, &entry.path, entry.utf8_bytes.max(1_048_576))?
                .ok_or_else(|| {
                    CliError::message(format!("generated file drift: `{}` is missing", entry.path))
                })?;
            if sha256(&bytes) != entry.content_sha256 {
                return Err(CliError::message(format!(
                    "generated file drift: `{}` does not match its manifest",
                    entry.path
                )));
            }
        }
        Ok(())
    }

    fn read_manifest(directory: &OwnedFd) -> Result<Option<GeneratedManifest>, CliError> {
        let Some(bytes) = read_optional(directory, MANIFEST_NAME, MAX_MANIFEST_BYTES)? else {
            return Ok(None);
        };
        let manifest = serde_json::from_slice(&bytes)
            .map_err(|_| CliError::message("generated manifest is invalid JSON"))?;
        Ok(Some(manifest))
    }

    fn open_root(path: &Path, create: bool) -> Result<OwnedFd, CliError> {
        if path.as_os_str().is_empty() || path == Path::new(".") || path == Path::new("/") {
            return Err(CliError::message(
                "generated output root must name a child directory",
            ));
        }
        for component in path.components() {
            if matches!(component, Component::ParentDir | Component::Prefix(_)) {
                return Err(CliError::message(format!(
                    "output root is not normalized: {}",
                    path.display()
                )));
            }
        }
        let absolute = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map_err(|error| {
                    CliError::message(format!("cannot resolve current directory: {error}"))
                })?
                .join(path)
        };
        let mut ancestor = absolute.clone();
        let mut missing = Vec::new();
        loop {
            match std::fs::symlink_metadata(&ancestor) {
                Ok(metadata) => {
                    if missing.is_empty() && metadata.file_type().is_symlink() {
                        return Err(CliError::message(format!(
                            "generated output root must not be a symlink: {}",
                            path.display()
                        )));
                    }
                    if !metadata.file_type().is_dir() && !metadata.file_type().is_symlink() {
                        return Err(CliError::message(format!(
                            "generated output ancestor is not a directory: {}",
                            ancestor.display()
                        )));
                    }
                    break;
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound && create => {
                    let name = ancestor.file_name().ok_or_else(|| {
                        CliError::message(format!("cannot create output root: {}", path.display()))
                    })?;
                    missing.push(name.to_os_string());
                    ancestor = ancestor
                        .parent()
                        .map(PathBuf::from)
                        .ok_or_else(|| CliError::message("output root has no existing ancestor"))?;
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    return Err(CliError::message(format!(
                        "{} is not owned by a Shepherd generated manifest",
                        path.display()
                    )));
                }
                Err(error) => {
                    return Err(CliError::message(format!(
                        "cannot inspect output root {}: {error}",
                        path.display()
                    )));
                }
            }
        }
        let canonical = std::fs::canonicalize(&ancestor).map_err(|error| {
            CliError::message(format!(
                "cannot resolve output ancestor {}: {error}",
                ancestor.display()
            ))
        })?;
        let mut directory = open(
            &canonical,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| CliError::message(format!("cannot open output anchor: {error}")))?;
        for part in missing.iter().rev() {
            directory = open_directory(&directory, part, true)?;
        }
        Ok(directory)
    }

    fn open_directory(parent: &OwnedFd, name: &OsStr, create: bool) -> Result<OwnedFd, CliError> {
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW;
        match openat(parent, name, flags, Mode::empty()) {
            Ok(directory) => Ok(directory),
            Err(error) if create && error == rustix::io::Errno::NOENT => {
                mkdirat(parent, name, Mode::from_raw_mode(0o755)).map_err(|error| {
                    CliError::message(format!("cannot create generated directory: {error}"))
                })?;
                openat(parent, name, flags, Mode::empty()).map_err(|error| {
                    CliError::message(format!("cannot open generated directory: {error}"))
                })
            }
            Err(error) => Err(CliError::message(format!(
                "cannot open generated directory without following links: {error}"
            ))),
        }
    }

    fn parent_and_name<'a>(
        root: &OwnedFd,
        relative: &'a str,
        create: bool,
    ) -> Result<(OwnedFd, &'a str), CliError> {
        validate_relative(relative)?;
        let mut parts = relative.split('/').collect::<Vec<_>>();
        let name = parts.pop().expect("validated path has one component");
        let mut directory = openat(
            root,
            ".",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| CliError::message(format!("cannot duplicate output root: {error}")))?;
        for part in parts {
            directory = open_directory(&directory, OsStr::new(part), create)?;
        }
        Ok((directory, name))
    }

    fn read_optional(
        root: &OwnedFd,
        relative: &str,
        limit: usize,
    ) -> Result<Option<Vec<u8>>, CliError> {
        let (parent, name) = match parent_and_name(root, relative, false) {
            Ok(value) => value,
            Err(error)
                if error
                    .message_text()
                    .is_some_and(|message| message.contains("No such file")) =>
            {
                return Ok(None);
            }
            Err(error) => return Err(error),
        };
        let descriptor = match openat(
            &parent,
            name,
            OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(descriptor) => descriptor,
            Err(error) if error == rustix::io::Errno::NOENT => return Ok(None),
            Err(error) => {
                return Err(CliError::message(format!(
                    "cannot open generated file `{relative}` without following links: {error}"
                )));
            }
        };
        let stat = rustix::fs::fstat(&descriptor).map_err(|error| {
            CliError::message(format!(
                "cannot inspect generated file `{relative}`: {error}"
            ))
        })?;
        if !FileType::from_raw_mode(stat.st_mode).is_file() {
            return Err(CliError::message(format!(
                "generated path `{relative}` is not a regular file"
            )));
        }
        let mut bytes = Vec::new();
        File::from(descriptor)
            .take(u64::try_from(limit + 1).expect("file limit fits u64"))
            .read_to_end(&mut bytes)
            .map_err(|error| CliError::message(format!("cannot read `{relative}`: {error}")))?;
        if bytes.len() > limit {
            return Err(CliError::message(format!(
                "generated file `{relative}` exceeds its bounded size"
            )));
        }
        Ok(Some(bytes))
    }

    fn write_atomic(root: &OwnedFd, relative: &str, bytes: &[u8]) -> Result<(), CliError> {
        let (parent, name) = parent_and_name(root, relative, true)?;
        if let Some(existing) = read_optional(root, relative, bytes.len().max(1_048_576))?
            && existing == bytes
        {
            return Ok(());
        }
        let nonce = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
        let temporary = format!(".{name}.shepherd.tmp.{}.{nonce}", std::process::id());
        let descriptor = openat(
            &parent,
            temporary.as_str(),
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::from_raw_mode(0o644),
        )
        .map_err(|error| {
            CliError::message(format!("cannot create `{relative}` atomically: {error}"))
        })?;
        let mut file = File::from(descriptor);
        let result = (|| {
            file.write_all(bytes).map_err(|error| {
                CliError::message(format!("cannot write `{relative}`: {error}"))
            })?;
            file.sync_all()
                .map_err(|error| CliError::message(format!("cannot sync `{relative}`: {error}")))?;
            renameat(&parent, temporary.as_str(), &parent, name).map_err(|error| {
                CliError::message(format!("cannot publish `{relative}` atomically: {error}"))
            })?;
            directory_sync(&parent)
        })();
        if result.is_err() {
            let _ = unlinkat(&parent, temporary.as_str(), AtFlags::empty());
        }
        result
    }

    fn unlink_file(root: &OwnedFd, relative: &str) -> Result<(), CliError> {
        let (parent, name) = parent_and_name(root, relative, false)?;
        unlinkat(&parent, name, AtFlags::empty()).map_err(|error| {
            CliError::message(format!("cannot remove stale `{relative}`: {error}"))
        })?;
        directory_sync(&parent)?;
        let mut components = relative.split('/').collect::<Vec<_>>();
        components.pop();
        while !components.is_empty() {
            let directory_path = components.join("/");
            let (ancestor, directory_name) = parent_and_name(root, &directory_path, false)?;
            match unlinkat(&ancestor, directory_name, AtFlags::REMOVEDIR) {
                Ok(()) => directory_sync(&ancestor)?,
                Err(rustix::io::Errno::NOTEMPTY | rustix::io::Errno::NOENT) => {
                    break;
                }
                Err(error) => {
                    return Err(CliError::message(format!(
                        "cannot remove empty generated directory `{directory_path}`: {error}"
                    )));
                }
            }
            components.pop();
        }
        Ok(())
    }

    fn directory_sync(directory: &OwnedFd) -> Result<(), CliError> {
        File::from(
            openat(
                directory,
                ".",
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
                Mode::empty(),
            )
            .map_err(|error| CliError::message(format!("cannot duplicate directory: {error}")))?,
        )
        .sync_all()
        .map_err(|error| CliError::message(format!("cannot sync generated directory: {error}")))
    }
}

#[cfg(not(unix))]
mod managed {
    use std::path::Path;

    use std::path::PathBuf;

    use shepherd::compiler::EmittedTree;

    use super::{
        BTreeMap, BTreeSet, CliError, Component, GeneratedManifest, MANIFEST_NAME,
        MAX_MANIFEST_BYTES, sha256, validate_relative,
    };
    use crate::safe_fs;

    /// The non-unix twin of the descriptor-anchored materializer. The ALGORITHM
    /// is identical -- read the prior manifest, refuse a foreign target, verify
    /// every owned file still matches its digest, refuse to overwrite anything
    /// the prior manifest did not own, write, prune stale entries, then publish
    /// the manifest last. Only the primitives differ: a validated root path
    /// with per-component link rejection instead of a chain of directory
    /// descriptors. The manifest is written LAST on both platforms, so an
    /// interrupted run leaves a tree whose manifest still describes the state
    /// before it, which is the property `check` depends on.
    pub(super) fn check(root: &Path, expected: &GeneratedManifest) -> Result<(), CliError> {
        let directory = open_root(root, false)?;
        let current = read_manifest(&directory)?.ok_or_else(|| {
            CliError::message(format!(
                "{} is not owned by a Shepherd generated manifest",
                root.display()
            ))
        })?;
        current.validate()?;
        if &current != expected {
            return Err(CliError::message(format!(
                "generated manifest drift for {}",
                root.display()
            )));
        }
        verify_owned_files(&directory, &current)?;
        Ok(())
    }

    pub(super) fn materialize(
        root: &Path,
        tree: &EmittedTree,
        expected: &GeneratedManifest,
    ) -> Result<(), CliError> {
        let directory = open_root(root, true)?;
        let previous = read_manifest(&directory)?;
        if let Some(manifest) = &previous {
            manifest.validate()?;
            if manifest.target != expected.target {
                return Err(CliError::message(format!(
                    "generated root {} belongs to target `{}`, not `{}`",
                    root.display(),
                    manifest.target,
                    expected.target
                )));
            }
            verify_owned_files(&directory, manifest)?;
        }

        let previous_by_path = previous
            .as_ref()
            .map(|manifest| {
                manifest
                    .files
                    .iter()
                    .map(|entry| (entry.path.as_str(), entry.content_sha256.as_str()))
                    .collect::<BTreeMap<_, _>>()
            })
            .unwrap_or_default();
        for file in &tree.files {
            validate_relative(&file.path)?;
            if previous_by_path.contains_key(file.path.as_str()) {
                continue;
            }
            if read_optional(&directory, &file.path, file.content.len().max(1_048_576))?.is_some() {
                return Err(CliError::message(format!(
                    "generated target `{}` is not owned by the prior manifest",
                    file.path
                )));
            }
        }

        for file in &tree.files {
            write_atomic(&directory, &file.path, file.content.as_bytes())?;
        }

        if let Some(previous) = &previous {
            let next = tree
                .files
                .iter()
                .map(|file| file.path.as_str())
                .collect::<BTreeSet<_>>();
            for stale in previous
                .files
                .iter()
                .filter(|entry| !next.contains(entry.path.as_str()))
            {
                unlink_file(&directory, &stale.path)?;
            }
        }

        let mut manifest_bytes = serde_json::to_vec_pretty(expected).map_err(|error| {
            CliError::message(format!("cannot encode generated manifest: {error}"))
        })?;
        manifest_bytes.push(b'\n');
        write_atomic(&directory, MANIFEST_NAME, &manifest_bytes)?;
        Ok(())
    }

    fn verify_owned_files(directory: &Path, manifest: &GeneratedManifest) -> Result<(), CliError> {
        for entry in &manifest.files {
            let bytes = read_optional(directory, &entry.path, entry.utf8_bytes.max(1_048_576))?
                .ok_or_else(|| {
                    CliError::message(format!("generated file drift: `{}` is missing", entry.path))
                })?;
            if sha256(&bytes) != entry.content_sha256 {
                return Err(CliError::message(format!(
                    "generated file drift: `{}` does not match its manifest",
                    entry.path
                )));
            }
        }
        Ok(())
    }

    fn read_manifest(directory: &Path) -> Result<Option<GeneratedManifest>, CliError> {
        let Some(bytes) = read_optional(directory, MANIFEST_NAME, MAX_MANIFEST_BYTES)? else {
            return Ok(None);
        };
        let manifest = serde_json::from_slice(&bytes)
            .map_err(|_| CliError::message("generated manifest is invalid JSON"))?;
        Ok(Some(manifest))
    }

    /// Validate and resolve the output root, refusing the same shapes the unix
    /// twin refuses: an empty path, the current directory, the filesystem root,
    /// and anything carrying `..`. A generated tree is deleted and rewritten
    /// wholesale, so a root that escapes its intended parent is destructive.
    fn open_root(path: &Path, create: bool) -> Result<PathBuf, CliError> {
        if path.as_os_str().is_empty() || path == Path::new(".") || path == Path::new("/") {
            return Err(CliError::message(
                "generated output root must name a child directory",
            ));
        }
        for component in path.components() {
            if matches!(component, Component::ParentDir) {
                return Err(CliError::message(format!(
                    "output root is not normalized: {}",
                    path.display()
                )));
            }
        }
        let absolute = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir()
                .map_err(|error| {
                    CliError::message(format!("cannot resolve current directory: {error}"))
                })?
                .join(path)
        };
        if create {
            std::fs::create_dir_all(&absolute).map_err(|error| {
                CliError::message(format!(
                    "cannot create generated root {}: {error}",
                    absolute.display()
                ))
            })?;
        } else if !safe_fs::directory_exists(&absolute).map_err(|error| {
            CliError::message(format!(
                "cannot open generated root {} without following links: {error}",
                absolute.display()
            ))
        })? {
            return Err(CliError::message(format!(
                "{} is not owned by a Shepherd generated manifest",
                path.display()
            )));
        }
        safe_fs::reject_link_components(&absolute).map_err(|error| {
            CliError::message(format!(
                "cannot open generated root {} without following links: {error}",
                absolute.display()
            ))
        })?;
        Ok(absolute)
    }

    fn resolve(root: &Path, relative: &str) -> Result<PathBuf, CliError> {
        validate_relative(relative)?;
        Ok(root.join(relative))
    }

    /// Absence is `None`, not an error: both callers treat "not there" as a
    /// verdict (nothing to verify, nothing to refuse) rather than a failure.
    fn read_optional(
        root: &Path,
        relative: &str,
        limit: usize,
    ) -> Result<Option<Vec<u8>>, CliError> {
        let target = resolve(root, relative)?;
        match safe_fs::read_regular_nofollow(&target, limit as u64) {
            Ok(bytes) => Ok(Some(bytes)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(CliError::message(format!(
                "cannot read generated file `{relative}`: {error}"
            ))),
        }
    }

    fn write_atomic(root: &Path, relative: &str, bytes: &[u8]) -> Result<(), CliError> {
        let target = resolve(root, relative)?;
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent).map_err(|error| {
                CliError::message(format!(
                    "cannot create generated directory for `{relative}`: {error}"
                ))
            })?;
        }
        safe_fs::replace_atomic(&target, bytes).map_err(|error| {
            CliError::message(format!("cannot write generated file `{relative}`: {error}"))
        })
    }

    /// Removing the file is not enough: the unix twin also prunes the empty
    /// ancestor directories the file left behind, and `compile --check` asserts
    /// a pruned tree has no leftover `skills/adaptation/` directory. Stopping at
    /// the first non-empty ancestor is what keeps it from walking out of the
    /// generated root.
    fn unlink_file(root: &Path, relative: &str) -> Result<(), CliError> {
        let target = resolve(root, relative)?;
        safe_fs::remove_file_nofollow(&target).map_err(|error| {
            CliError::message(format!(
                "cannot remove stale generated file `{relative}`: {error}"
            ))
        })?;
        let mut components = relative.split('/').collect::<Vec<_>>();
        components.pop();
        while !components.is_empty() {
            let directory = resolve(root, &components.join("/"))?;
            match std::fs::remove_dir(&directory) {
                Ok(()) => {}
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::NotFound | std::io::ErrorKind::DirectoryNotEmpty
                    ) =>
                {
                    break;
                }
                Err(error) => {
                    return Err(CliError::message(format!(
                        "cannot remove empty generated directory `{}`: {error}",
                        components.join("/")
                    )));
                }
            }
            components.pop();
        }
        Ok(())
    }
}
