//! Deterministic native `seed verify` gate.

use std::{
    fs::File,
    io::{self, Read, Write},
    path::{Path, PathBuf},
    process::Command,
};

use crate::interface::CliError;

const MIN_MESH_ROWS: usize = 8;
const SPRINT_FOOTPRINT_CAP: usize = 400;
const PATCH_FOOTPRINT_CAP: usize = 200;
const MAX_SEED_BYTES: u64 = 1_048_576;
const USAGE: &str = "shepherd seed verify <path> [--quiet]\n  Deterministic pre-flight gate for a *.seed.md.\n  Exit 1 on >=1 HARD failure (blocks the SEED-GATE); 0 otherwise (warnings allowed).";
const NEW_MARKERS: [&str; 7] = ["(NEW", "(new", "(New", "#NEW", "#new", "# NEW", "# new"];

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
#[command(disable_help_flag = true)]
pub struct WaveB2SeedCmd {
    #[arg(
        value_name = "ARGS",
        num_args = 0..,
        allow_hyphen_values = true,
        trailing_var_arg = true
    )]
    args: Vec<String>,
}

impl WaveB2SeedCmd {
    pub(crate) fn run(self) -> Result<(), CliError> {
        let Some(subcommand) = self.args.first().map(String::as_str) else {
            return write_stdout(USAGE);
        };
        if matches!(subcommand, "help" | "--help" | "-h") {
            return write_stdout(USAGE);
        }
        if subcommand != "verify" {
            write_stderr(&format!("unknown subcommand: {subcommand}\n{USAGE}"))?;
            return Err(CliError::reported_with_code(2));
        }

        let mut quiet = false;
        let mut path = None;
        for argument in self.args.iter().skip(1) {
            if argument == "--quiet" {
                quiet = true;
            } else if argument.starts_with('-') {
                write_stderr(&format!("unknown flag: {argument}"))?;
                return Err(CliError::reported_with_code(2));
            } else {
                path = Some(PathBuf::from(argument));
            }
        }
        let Some(path) = path else {
            write_stderr("ERR: seed verify needs a <path>")?;
            return Err(CliError::reported_with_code(2));
        };
        if !path.is_file() {
            write_stderr(&format!("ERR: no such file: {}", path.display()))?;
            return Err(CliError::reported_with_code(2));
        }

        let report = verify(&path, quiet)?;
        if !report.lines.is_empty() {
            write_stdout(&report.lines.join("\n"))?;
        }
        if report.hard == 0 {
            Ok(())
        } else {
            Err(CliError::reported())
        }
    }
}

#[derive(Debug)]
struct Report {
    hard: usize,
    warnings: usize,
    quiet: bool,
    lines: Vec<String>,
}

impl Report {
    fn new(quiet: bool) -> Self {
        Self {
            hard: 0,
            warnings: 0,
            quiet,
            lines: Vec::new(),
        }
    }

    fn hard(&mut self, message: impl Into<String>) {
        self.hard += 1;
        if !self.quiet {
            self.lines.push(format!("  HARD  {}", message.into()));
        }
    }

    fn warn(&mut self, message: impl Into<String>) {
        self.warnings += 1;
        if !self.quiet {
            self.lines.push(format!("  warn  {}", message.into()));
        }
    }

    fn finish(&mut self) {
        if self.quiet {
            return;
        }
        if self.hard == 0 {
            self.lines
                .push(format!("OK: 0 hard failures, {} warning(s)", self.warnings));
        } else {
            self.lines.push(format!(
                "FAIL: {} hard failure(s), {} warning(s)",
                self.hard, self.warnings
            ));
        }
    }
}

fn verify(path: &Path, quiet: bool) -> Result<Report, CliError> {
    let file = File::open(path)
        .map_err(|error| CliError::message(format!("cannot read {}: {error}", path.display())))?;
    let mut bytes = Vec::new();
    file.take(MAX_SEED_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| CliError::message(format!("cannot read {}: {error}", path.display())))?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_SEED_BYTES {
        return Err(CliError::message(format!(
            "seed input exceeds {MAX_SEED_BYTES} bytes: {}",
            path.display()
        )));
    }
    let raw = String::from_utf8_lossy(&bytes);
    let content = raw.trim_end_matches('\n');
    let lines = content.split('\n').collect::<Vec<_>>();
    let kind = extract_kind(&lines);
    // Declared-kind's threshold for the WARN-only signals below (smell warn,
    // patch mislabel warn) — never for the HARD ceiling. `kind` is an
    // unvalidated author label (measured, not assumed): v645 declares
    // `patch-seed` at `sprint_size: XL`; v646's 393-line patch-seed and
    // v651's 388-line sprint-seed carry near-identical deliverable/scope
    // counts (10/14 vs 13/27 entries). No measured signal in the corpus
    // separates a "real" patch from a mislabeled sprint, so a one-word
    // relabel must never buy HARD-cap slack.
    let declared_cap = if kind == "patch-seed" {
        PATCH_FOOTPRINT_CAP
    } else {
        SPRINT_FOOTPRINT_CAP
    };
    let mut report = Report::new(quiet);

    // Footprint severity, evaluated in this order, at most one finding:
    //   1. lines > SPRINT_FOOTPRINT_CAP (400) -> HARD, every kind. The one
    //      ceiling nothing can relabel its way past.
    //   2. else kind == "patch-seed" && lines > PATCH_FOOTPRINT_CAP (200)
    //      -> warn, naming the mislabel. The v6.4.6 carry-forward said "do
    //      not resolve it by moving the number" — this fixes which
    //      severity the label may select, not the number itself.
    //   3. else the pre-existing smell warn at 3/4 of the declared-kind's
    //      threshold, byte-identical to prior behaviour.
    if lines.len() > SPRINT_FOOTPRINT_CAP {
        report.hard(format!(
            "footprint {} lines > cap {SPRINT_FOOTPRINT_CAP} (kind={})",
            lines.len(),
            if kind.is_empty() { "sprint" } else { &kind }
        ));
    } else if kind == "patch-seed" && lines.len() > PATCH_FOOTPRINT_CAP {
        report.warn(format!(
            "footprint {} lines > patch cap {PATCH_FOOTPRINT_CAP} (kind=patch-seed) — sprint-shaped; relabel or move evidence to mesh.md",
            lines.len()
        ));
    } else if lines.len() > declared_cap * 3 / 4 {
        report.warn(format!(
            "footprint {} lines > smell threshold {}",
            lines.len(),
            declared_cap * 3 / 4
        ));
    }

    if contains_word_marker(content, "TODO:") || contains_word_marker(content, "FIXME:") {
        report.hard("TODO:/FIXME: marker(s) present — resolve before commit");
    }
    if contains_lane_number(content) {
        report.hard(
            "prescriptive 'Lane N' numbering present — lane decomposition is engineer territory (#67)",
        );
    }
    if lines.iter().any(|line| sequencing_directive(line)) {
        report.warn("'Sequencing:' directive present — sequencing is engineer territory (#67)");
    }
    if contains_semver_judgment(content) {
        report.warn("semver-content judgment present — version tier is the operator's call");
    }

    let scope = extract_scope_block(&lines);
    if !scope.is_empty() {
        let repo = repo_root();
        let entries = parse_scope_entries(&scope);
        // `file_scope` proposes paths that will exist once the seed's sprint
        // runs — resolving them against the LIVE tree is a pre-flight check,
        // exactly what USAGE promises ("Deterministic pre-flight gate for a
        // *.seed.md ... blocks the SEED-GATE"). Once a run has closed, its
        // seed is a historical record, not a proposal: paths it named can
        // legitimately be gone (deleted, renamed, moved by a *later* sprint)
        // without the seed itself being wrong. So a closed run's unresolved
        // path is a warn, never a HARD block — every other seed keeps
        // today's HARD failure byte-identical.
        //
        // "Closed" requires BOTH, deliberately narrow so a stray close.md
        // can never accidentally relax a live gate:
        //   1. path shape: basename is exactly `seed.md` and its parent's
        //      parent is named `runs` (i.e. `.../runs/<run-id>/seed.md`) —
        //      this mirrors the shape `hooks/scripts/seed_preflight_check.sh`
        //      already gates its own input on. It also means the hook's own
        //      write-time check is structurally immune to this rule: it
        //      verifies a copy at `mktemp -t shep-seed.XXXXXX`, a bare file
        //      directly under $TMPDIR that is never named `seed.md` and is
        //      never inside a `runs/<id>/` directory, so it can never be
        //      mistaken for a closed run's record no matter what else sits
        //      beside it in $TMPDIR.
        //   2. a sibling `close.md` exists next to the seed — the artifact
        //      a run emits when it closes (`.shepherd/runs/v646/close.md`
        //      exists; `.shepherd/runs/v651/close.md` does not until
        //      CLOSE-S2 writes it at the end of this sprint).
        // Deliberately NOT: frontmatter `date:` (verdict would then flip
        // with the calendar — a time-bomb) and NOT git archaeology against
        // the seed's named commit (`base: main` is a moving ref, and the
        // hook's temp-dir copy has no commit at all).
        let run_closed = is_run_scoped_seed_path(path)
            && path
                .parent()
                .is_some_and(|dir| dir.join("close.md").is_file());
        for entry in &entries {
            if !resolves(entry, repo.as_deref()) {
                if run_closed {
                    report.warn(format!(
                        "file_scope path does not resolve: {} (run closed — close.md present; a closed run's seed is a record, not a proposal)",
                        first_token(entry)
                    ));
                } else {
                    report.hard(format!(
                        "file_scope path does not resolve and is not marked (NEW): {}",
                        first_token(entry)
                    ));
                }
            }
        }
        if entries.is_empty() {
            report.warn(
                "file_scope present but no entries parsed — verify paths manually (unrecognized YAML shape)",
            );
        }
    }

    let deliverables = deliverable_blocks(&lines);
    let missing = deliverables
        .iter()
        .filter(|(is_deliverable, has_gh)| *is_deliverable && !*has_gh)
        .count();
    if missing > 0 {
        report.hard(format!(
            "{missing} deliverable block(s) carry a priority but no **GH:** anchor (seed-anchored-by-issues.md)"
        ));
    }

    if is_canonical(content, &lines) {
        let mesh_rows = lines.iter().filter(|line| is_mesh_row(line)).count();
        if mesh_rows > 0 && mesh_rows < MIN_MESH_ROWS {
            report.warn(format!(
                "Phase 0 mesh has {mesh_rows} row(s) (< {MIN_MESH_ROWS} recommended)"
            ));
        }
        if has_any_priority(content) && !has_high_priority(content) {
            report
                .warn("no deliverable ranked CRITICAL or HIGH — confirm this sprint earns a slot");
        }
        if !lines.iter().any(|line| line.starts_with("milestone:")) {
            report.warn("frontmatter missing 'milestone:' (engineer + critic parse it)");
        }
        if !lines.iter().any(|line| line.starts_with("kind:")) {
            report.warn("frontmatter missing 'kind:' (sprint-seed | patch-seed)");
        }
    }

    report.finish();
    Ok(report)
}

fn extract_kind(lines: &[&str]) -> String {
    for line in lines {
        let Some(value) = line.strip_prefix("kind:") else {
            continue;
        };
        let value = value.trim_start();
        let value = value
            .find('#')
            .filter(|index| {
                value[..*index]
                    .chars()
                    .next_back()
                    .is_some_and(char::is_whitespace)
            })
            .map(|index| &value[..index])
            .unwrap_or(value);
        return value.trim_end().to_owned();
    }
    String::new()
}

fn contains_word_marker(content: &str, marker: &str) -> bool {
    content.match_indices(marker).any(|(index, _)| {
        index == 0
            || content[..index]
                .chars()
                .next_back()
                .is_none_or(|value| !(value.is_alphanumeric() || value == '_'))
    })
}

fn contains_lane_number(content: &str) -> bool {
    content.match_indices("Lane").any(|(index, _)| {
        let boundary = index == 0
            || content[..index]
                .chars()
                .next_back()
                .is_none_or(|value| !(value.is_alphanumeric() || value == '_'));
        if !boundary {
            return false;
        }
        let suffix = &content[index + "Lane".len()..];
        let spaces = suffix
            .bytes()
            .take_while(|byte| matches!(byte, b' ' | b'\t'))
            .count();
        spaces > 0
            && suffix
                .as_bytes()
                .get(spaces)
                .is_some_and(u8::is_ascii_digit)
    })
}

fn sequencing_directive(line: &str) -> bool {
    line.trim_start()
        .trim_start_matches('*')
        .starts_with("Sequencing:")
        && line
            .trim_start()
            .chars()
            .take_while(|value| *value == '*')
            .count()
            <= 2
}

fn contains_semver_judgment(content: &str) -> bool {
    let lower = content.to_ascii_lowercase();
    [
        "too small for a patch",
        "too big for a patch",
        "too large for a patch",
        "too small for a minor",
        "too big for a minor",
        "too large for a minor",
        "too small for a sprint",
        "too big for a sprint",
        "too large for a sprint",
        "should be a patch",
        "should be a minor",
        "should be a major",
        "really a minor",
        "really a major",
    ]
    .iter()
    .any(|needle| lower.contains(needle))
}

fn extract_scope_block<'a>(lines: &'a [&'a str]) -> Vec<&'a str> {
    let mut scope = Vec::new();
    let mut inside = false;
    for line in lines {
        if line.starts_with("file_scope:") {
            inside = true;
            continue;
        }
        if inside
            && (line.trim() == "---" || line.chars().next().is_some_and(|c| !c.is_whitespace()))
        {
            inside = false;
        }
        if inside {
            scope.push(*line);
        }
    }
    while scope.last().is_some_and(|line| line.is_empty()) {
        scope.pop();
    }
    scope
}

fn parse_scope_entries(lines: &[&str]) -> Vec<String> {
    let mut entries = Vec::new();
    for line in lines {
        let flow = (line.contains("exclusive:") || line.contains("additive:"))
            && line.contains('[')
            && line.contains(']');
        if flow {
            if let (Some(start), Some(end)) = (line.find('['), line.rfind(']')) {
                entries.extend(
                    line[start + 1..end]
                        .split(',')
                        .map(str::trim)
                        .filter(|value| !value.is_empty())
                        .map(str::to_owned),
                );
            }
            continue;
        }
        if !line.contains("- ") {
            continue;
        }
        let entry = line
            .trim_start()
            .strip_prefix('-')
            .unwrap_or(line)
            .trim_start();
        if entry.is_empty() || entry.starts_with("exclusive:") || entry.starts_with("additive:") {
            continue;
        }
        entries.push(entry.to_owned());
    }
    entries
}

fn first_token(value: &str) -> &str {
    value
        .find(char::is_whitespace)
        .map(|index| &value[..index])
        .unwrap_or(value)
}

fn resolves(raw: &str, repo_root: Option<&Path>) -> bool {
    if NEW_MARKERS.iter().any(|marker| raw.contains(marker)) {
        return true;
    }
    let token = first_token(raw);
    if token.is_empty() || (token.starts_with('<') && token.ends_with('>')) {
        return true;
    }
    let path = PathBuf::from(token);
    let candidate = if path.is_absolute() {
        path
    } else if let Some(root) = repo_root {
        root.join(path)
    } else {
        path
    };
    if token.contains(['*', '?', '[']) {
        glob_exists(&candidate)
    } else {
        candidate.exists()
    }
}

/// True when `path`'s basename is exactly `seed.md` and its grandparent
/// directory is named `runs` — i.e. it has the shape `.../runs/<run-id>/seed.md`.
/// This is one of the two required conditions for treating a seed as
/// belonging to a closed run (see the comment above its call site). A
/// non-UTF8 component defaults to `false` (stays strict) rather than guessing.
fn is_run_scoped_seed_path(path: &Path) -> bool {
    path.file_name().and_then(|name| name.to_str()) == Some("seed.md")
        && path
            .parent()
            .and_then(Path::parent)
            .and_then(Path::file_name)
            .and_then(|name| name.to_str())
            == Some("runs")
}

fn repo_root() -> Option<PathBuf> {
    let output = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8(output.stdout).ok()?;
    let value = value.trim();
    (!value.is_empty()).then(|| PathBuf::from(value))
}

fn glob_exists(pattern: &Path) -> bool {
    let Some(pattern) = pattern.to_str() else {
        return false;
    };
    let options = glob::MatchOptions {
        case_sensitive: true,
        require_literal_separator: true,
        require_literal_leading_dot: true,
    };
    glob::glob_with(pattern, options).is_ok_and(|mut matches| matches.any(|entry| entry.is_ok()))
}

fn deliverable_blocks(lines: &[&str]) -> Vec<(bool, bool)> {
    let mut blocks = Vec::new();
    let mut started = false;
    let mut deliverable = false;
    let mut has_gh = false;
    let flush = |blocks: &mut Vec<(bool, bool)>, started: bool, deliverable: bool, has_gh: bool| {
        if started {
            blocks.push((deliverable, has_gh));
        }
    };
    for line in lines {
        if line.starts_with("### ") || line.starts_with("###\t") {
            flush(&mut blocks, started, deliverable, has_gh);
            started = true;
            deliverable = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
                .iter()
                .any(|priority| line.contains(&format!("[{priority}]")));
            has_gh = false;
            continue;
        }
        if line.starts_with("## ") || line.starts_with("##\t") {
            flush(&mut blocks, started, deliverable, has_gh);
            started = false;
            deliverable = false;
            has_gh = false;
        }
        if line.contains("**Priority:**") {
            deliverable = true;
        }
        if line.contains("**GH:**") {
            has_gh = true;
        }
    }
    flush(&mut blocks, started, deliverable, has_gh);
    blocks
}

fn is_canonical(content: &str, lines: &[&str]) -> bool {
    content.contains("**Priority:**")
        || lines.iter().any(|line| line.starts_with("file_scope:"))
        || content.contains("Phase 0 mesh")
        || content.contains("**GH:**")
}

fn is_mesh_row(line: &str) -> bool {
    let Some(rest) = line.strip_prefix('|') else {
        return false;
    };
    let rest = rest.trim_start();
    let digits = rest.bytes().take_while(u8::is_ascii_digit).count();
    digits > 0 && rest[digits..].trim_start().starts_with('|')
}

fn has_any_priority(content: &str) -> bool {
    content.contains("**Priority:**")
        || ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
            .iter()
            .any(|priority| content.contains(&format!("[{priority}]")))
}

fn has_high_priority(content: &str) -> bool {
    content.contains("[CRITICAL]")
        || content.contains("[HIGH]")
        || content
            .lines()
            .filter_map(|line| line.split_once("**Priority:**"))
            .map(|(_, value)| value.trim_start())
            .any(|value| value.starts_with("CRITICAL") || value.starts_with("HIGH"))
}

fn write_stdout(message: &str) -> Result<(), CliError> {
    let mut output = io::stdout().lock();
    output
        .write_all(message.as_bytes())
        .and_then(|()| output.write_all(b"\n"))
        .and_then(|()| output.flush())
        .map_err(|error| CliError::message(format!("cannot write stdout: {error}")))
}

fn write_stderr(message: &str) -> Result<(), CliError> {
    let mut output = io::stderr().lock();
    output
        .write_all(message.as_bytes())
        .and_then(|()| output.write_all(b"\n"))
        .and_then(|()| output.flush())
        .map_err(|error| CliError::message(format!("cannot write stderr: {error}")))
}
