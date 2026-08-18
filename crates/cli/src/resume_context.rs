//! Bounded, canonical resume context from the primary run and registry.

use std::path::Path;

#[cfg(unix)]
use std::io::Read;

use shepherd::{
    dispatch::{
        AgentId, ContextBundle, ContextEntry, ContextQuery, DispatchRecord,
        MAX_RESUME_CONTEXT_ENTRIES, MAX_RESUME_CONTEXT_TOKENS, MAX_RESUME_CONTEXT_WORDS, ProjectId,
        RunId, materialize_context,
    },
    registry::{OpenMode, Registry},
};

use crate::DispatchStore;

const RUN_BYTES: usize = 2_048;
const LANE_PLAN_BYTES: usize = 6_144;
const CHECKPOINT_BYTES: usize = 2_048;
const RESULT_BYTES: usize = 2_048;
const MEMORY_BYTES: usize = 1_024;
const MAX_LINEAGE: usize = 32;
const MAX_MEMORIES: usize = 16;

pub(crate) fn build_resume_context(
    store: &DispatchStore,
    registry_path: &Path,
    record: &DispatchRecord,
) -> Result<ContextBundle, String> {
    let mut source = Source::open(store.runs_root(), &record.run)?;
    let mut entries = Vec::new();
    push_file(
        &mut entries,
        &source,
        record,
        None,
        "run.json",
        RUN_BYTES,
        1_000,
    )?;
    if let Some(lane) = &record.lane {
        let plan = format!("lanes/{}/plan.md", lane.as_str());
        push_file(
            &mut entries,
            &source,
            record,
            record.lane.clone(),
            &plan,
            LANE_PLAN_BYTES,
            950,
        )?;
    }
    if let Some(checkpoint) = source.latest_checkpoint()? {
        push_file(
            &mut entries,
            &source,
            record,
            record.lane.clone(),
            &checkpoint,
            CHECKPOINT_BYTES,
            900,
        )?;
    }

    let mut cursor = Some(record.clone());
    for ordinal in 0..MAX_LINEAGE {
        let Some(current) = cursor else { break };
        if let Some(reference) = &current.result_artifact {
            push_file(
                &mut entries,
                &source,
                record,
                current.lane.clone(),
                reference,
                RESULT_BYTES,
                800 - i32::try_from(ordinal).unwrap_or(100),
            )?;
        }
        cursor = current
            .resumes_agent_id
            .as_ref()
            .map(|agent_id| store.load_active(agent_id))
            .transpose()
            .map_err(|error| format!("cannot load resume lineage: {error}"))?;
    }
    if cursor.is_some() {
        return Err(format!("resume lineage exceeds {MAX_LINEAGE} records"));
    }

    append_memories(&mut entries, registry_path, record)?;
    Ok(materialize_context(
        &entries,
        &ContextQuery {
            project_id: record.project_id.clone(),
            run: record.run.clone(),
            lane: record.lane.clone(),
            min_freshness: 0,
            max_entries: MAX_RESUME_CONTEXT_ENTRIES,
            max_words: MAX_RESUME_CONTEXT_WORDS,
            max_tokens: MAX_RESUME_CONTEXT_TOKENS,
        },
    ))
}

fn push_file(
    entries: &mut Vec<ContextEntry>,
    source: &Source,
    record: &DispatchRecord,
    lane: Option<shepherd::dispatch::LaneId>,
    relative: &str,
    limit: usize,
    priority: i32,
) -> Result<(), String> {
    let content = source.read_text(relative, limit)?;
    push_entry(
        entries,
        EntrySeed {
            project_id: record.project_id.clone(),
            run: record.run.clone(),
            lane,
            provenance: relative,
            freshness: record.started_at.max(0),
            priority,
            content,
        },
    )
}

struct EntrySeed<'a> {
    project_id: ProjectId,
    run: RunId,
    lane: Option<shepherd::dispatch::LaneId>,
    provenance: &'a str,
    freshness: i64,
    priority: i32,
    content: String,
}

fn push_entry(entries: &mut Vec<ContextEntry>, seed: EntrySeed<'_>) -> Result<(), String> {
    let ordinal = entries.len();
    let words = seed.content.split_whitespace().count().max(1);
    let tokens = seed.content.len().max(1);
    let id = AgentId::new(format!("resume-entry-{ordinal:03}"))
        .map_err(|error| format!("cannot identify resume entry: {error}"))?;
    let entry = ContextEntry::new(
        id.to_string(),
        seed.project_id,
        seed.run,
        seed.lane,
        seed.provenance,
        seed.freshness,
        words,
        tokens,
        seed.priority,
        seed.content,
    )
    .map_err(|error| format!("cannot build resume entry: {error}"))?;
    entries.push(entry);
    Ok(())
}

fn append_memories(
    entries: &mut Vec<ContextEntry>,
    registry_path: &Path,
    record: &DispatchRecord,
) -> Result<(), String> {
    if !registry_path.exists() {
        return Ok(());
    }
    #[derive(Debug)]
    struct Memory {
        id: String,
        kind: String,
        title: String,
        body: String,
        tags: String,
        pinned: bool,
        updated_at: i64,
    }
    let registry = Registry::open(registry_path, OpenMode::ReadOnly)
        .map_err(|error| format!("cannot open resume registry: {error}"))?;
    let memories = registry
        .query(
            "SELECT id, kind, title, body, tags, pinned, updated_at FROM mem_entries WHERE project_id = ?1 ORDER BY pinned DESC, updated_at DESC, id ASC LIMIT 256",
            [record.project_id.as_str()],
            |row| {
                Ok(Memory {
                    id: row.get(0)?,
                    kind: row.get(1)?,
                    title: row.get(2)?,
                    body: row.get(3)?,
                    tags: row.get(4)?,
                    pinned: row.get::<_, i64>(5)? != 0,
                    updated_at: row.get(6)?,
                })
            },
        )
        .map_err(|error| format!("cannot query resume memories: {error}"))?;
    let run_tag = format!("run:{}", record.run.as_str());
    let lane_tag = record
        .lane
        .as_ref()
        .map(|lane| format!("lane:{}", lane.as_str()));
    let mut accepted = 0usize;
    for memory in memories {
        let tags: Vec<String> = serde_json::from_str(&memory.tags)
            .map_err(|error| format!("memory `{}` has invalid tags: {error}", memory.id))?;
        let run_scopes: Vec<&str> = tags
            .iter()
            .filter_map(|tag| tag.strip_prefix("run:"))
            .collect();
        let lane_scopes: Vec<&str> = tags
            .iter()
            .filter_map(|tag| tag.strip_prefix("lane:"))
            .collect();
        if (!run_scopes.is_empty() && !tags.iter().any(|tag| tag == &run_tag))
            || (!lane_scopes.is_empty()
                && !lane_tag
                    .as_ref()
                    .is_some_and(|expected| tags.iter().any(|tag| tag == expected)))
        {
            continue;
        }
        let mut content = format!("# {}\n\n{}", memory.title, memory.body);
        content = truncate_utf8(content, MEMORY_BYTES);
        let provenance = format!("registry:{}:{}", memory.id, memory.kind);
        push_entry(
            entries,
            EntrySeed {
                project_id: record.project_id.clone(),
                run: record.run.clone(),
                lane: if lane_scopes.is_empty() {
                    None
                } else {
                    record.lane.clone()
                },
                provenance: &provenance,
                freshness: memory.updated_at.max(0),
                priority: if memory.pinned { 750 } else { 700 },
                content,
            },
        )?;
        accepted += 1;
        if accepted >= MAX_MEMORIES {
            break;
        }
    }
    Ok(())
}

fn truncate_utf8(mut content: String, limit: usize) -> String {
    if content.len() <= limit {
        return content;
    }
    let marker = "\n[truncated by Shepherd resume budget]\n";
    let target = limit.saturating_sub(marker.len());
    let mut boundary = target.min(content.len());
    while !content.is_char_boundary(boundary) {
        boundary -= 1;
    }
    content.truncate(boundary);
    content.push_str(marker);
    content
}

#[cfg(unix)]
struct Source {
    run: std::os::fd::OwnedFd,
    run_path: std::path::PathBuf,
}

#[cfg(unix)]
impl Source {
    fn open(runs_root: &Path, run: &RunId) -> Result<Self, String> {
        use rustix::fs::{Mode, OFlags, open, openat};

        let root = open(
            runs_root,
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| format!("cannot open runs root without following links: {error}"))?;
        let run_path = runs_root.join(run.as_str());
        let run = openat(
            &root,
            run.as_str(),
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        )
        .map_err(|error| format!("cannot open active run without following links: {error}"))?;
        Ok(Self { run, run_path })
    }

    fn read_text(&self, relative: &str, limit: usize) -> Result<String, String> {
        use rustix::fs::{FileType, Mode, OFlags, openat};
        use std::fs::File;

        let parts = safe_parts(relative)?;
        let mut directory = rustix::io::dup(&self.run)
            .map_err(|error| format!("cannot duplicate run descriptor: {error}"))?;
        for (index, part) in parts.iter().enumerate() {
            let final_component = index + 1 == parts.len();
            let flags = if final_component {
                OFlags::RDONLY | OFlags::CLOEXEC | OFlags::NOFOLLOW
            } else {
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW
            };
            let next = openat(&directory, *part, flags, Mode::empty()).map_err(|error| {
                format!("cannot open resume artifact `{relative}` safely: {error}")
            })?;
            if final_component {
                let stat = rustix::fs::fstat(&next).map_err(|error| {
                    format!("cannot inspect resume artifact `{relative}`: {error}")
                })?;
                if !FileType::from_raw_mode(stat.st_mode).is_file() {
                    return Err(format!(
                        "resume artifact `{relative}` is not a regular file"
                    ));
                }
                let mut bytes = Vec::new();
                File::from(next)
                    .take(u64::try_from(limit + 1).expect("resume limit fits u64"))
                    .read_to_end(&mut bytes)
                    .map_err(|error| {
                        format!("cannot read resume artifact `{relative}`: {error}")
                    })?;
                let truncated = bytes.len() > limit;
                bytes.truncate(limit);
                let mut content = loop {
                    match String::from_utf8(bytes) {
                        Ok(content) => break content,
                        Err(error)
                            if error.utf8_error().error_len().is_none()
                                && error.utf8_error().valid_up_to() > 0 =>
                        {
                            let valid_up_to = error.utf8_error().valid_up_to();
                            bytes = error.into_bytes();
                            bytes.truncate(valid_up_to);
                        }
                        Err(_) => {
                            return Err(format!("resume artifact `{relative}` is not valid UTF-8"));
                        }
                    }
                };
                if truncated {
                    content = truncate_utf8(content, limit);
                }
                return Ok(content);
            }
            directory = next;
        }
        Err(format!("resume artifact `{relative}` is empty"))
    }

    fn latest_checkpoint(&mut self) -> Result<Option<String>, String> {
        use rustix::fs::{Mode, OFlags, openat};

        let _snapshots = match openat(
            &self.run,
            "snapshots",
            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC | OFlags::NOFOLLOW,
            Mode::empty(),
        ) {
            Ok(directory) => directory,
            Err(error) if error == rustix::io::Errno::NOENT => return Ok(None),
            Err(error) => return Err(format!("cannot open snapshots safely: {error}")),
        };
        let mut candidates = Vec::new();
        let directory = std::fs::read_dir(self.run_path.join("snapshots"))
            .map_err(|error| format!("cannot enumerate snapshot descriptor: {error}"))?;
        for entry in directory {
            let entry = entry.map_err(|error| format!("cannot enumerate snapshots: {error}"))?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| "snapshot name must be UTF-8".to_owned())?;
            if is_checkpoint_name(&name) {
                candidates.push(name);
            }
        }
        candidates.sort();
        Ok(candidates.pop().map(|name| format!("snapshots/{name}")))
    }
}

/// The non-unix twin. Same three operations, same messages, same truncation
/// behaviour -- including the part that is easy to lose: an over-limit artifact
/// is truncated at a char boundary and marked, not rejected, because a resume
/// context is a summary and a partial one is still useful.
#[cfg(not(unix))]
struct Source {
    run_path: std::path::PathBuf,
}

#[cfg(not(unix))]
impl Source {
    fn open(runs_root: &Path, run: &RunId) -> Result<Self, String> {
        use crate::safe_fs;

        if !safe_fs::directory_exists(runs_root)
            .map_err(|error| format!("cannot open runs root without following links: {error}"))?
        {
            return Err("cannot open runs root without following links: it is absent".into());
        }
        let run_path = runs_root.join(run.as_str());
        if !safe_fs::directory_exists(&run_path)
            .map_err(|error| format!("cannot open active run without following links: {error}"))?
        {
            return Err("cannot open active run without following links: it is absent".into());
        }
        Ok(Self { run_path })
    }

    fn read_text(&self, relative: &str, limit: usize) -> Result<String, String> {
        use crate::safe_fs;

        let parts = safe_parts(relative)?;
        let mut target = self.run_path.clone();
        for part in &parts {
            target.push(part);
        }
        let bytes = safe_fs::read_regular_nofollow(&target, limit as u64 + 1)
            .map_err(|error| format!("cannot read resume artifact `{relative}`: {error}"))?;
        if bytes.is_empty() {
            return Err(format!("resume artifact `{relative}` is empty"));
        }
        let truncated = bytes.len() > limit;
        let mut bytes = bytes;
        bytes.truncate(limit);
        let mut content = loop {
            match String::from_utf8(bytes) {
                Ok(content) => break content,
                Err(error)
                    if error.utf8_error().error_len().is_none()
                        && error.utf8_error().valid_up_to() > 0 =>
                {
                    let valid_up_to = error.utf8_error().valid_up_to();
                    bytes = error.into_bytes();
                    bytes.truncate(valid_up_to);
                }
                Err(_) => {
                    return Err(format!("resume artifact `{relative}` is not valid UTF-8"));
                }
            }
        };
        if truncated {
            content = truncate_utf8(content, limit);
        }
        Ok(content)
    }

    /// An absent `snapshots/` directory is `None`, not an error: a run that has
    /// not checkpointed yet still resumes, it just resumes without one.
    fn latest_checkpoint(&mut self) -> Result<Option<String>, String> {
        use crate::safe_fs;

        let snapshots = self.run_path.join("snapshots");
        let names = match safe_fs::regular_children(&snapshots) {
            Ok(names) => names,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(format!("cannot open snapshots safely: {error}")),
        };
        let mut candidates: Vec<String> = names
            .into_iter()
            .filter(|name| is_checkpoint_name(name))
            .collect();
        candidates.sort();
        Ok(candidates.pop().map(|name| format!("snapshots/{name}")))
    }
}

fn safe_parts(relative: &str) -> Result<Vec<&str>, String> {
    if relative.is_empty()
        || relative.len() > 4_096
        || relative.starts_with('/')
        || relative.contains(['\\', '\0'])
        || relative.chars().any(char::is_control)
    {
        return Err(format!("unsafe resume artifact `{relative}`"));
    }
    let parts: Vec<&str> = relative.split('/').collect();
    if parts
        .iter()
        .any(|part| part.is_empty() || *part == "." || *part == "..")
    {
        return Err(format!("unsafe resume artifact `{relative}`"));
    }
    Ok(parts)
}

fn is_checkpoint_name(name: &str) -> bool {
    name.starts_with("precompact-")
        && name.ends_with(".json")
        && name.len() <= 256
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}
