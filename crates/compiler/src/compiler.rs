//! Harness-specific emission over pure typed content.

use alloc::{
    collections::BTreeSet,
    format,
    string::{String, ToString},
    vec,
    vec::Vec,
};
use core::fmt::Write;

use sha2::{Digest, Sha256};

use crate::{
    BudgetClass, CompileError, CompileInput, EmittedFile, EmittedKind, EmittedRole, EmittedTree,
    HarnessProfile, ModelResolution, Portability, RoleInput, SkillInput, TOKENIZER_VERSION, Target,
    validate_budget,
};

pub fn compile(
    input: &CompileInput,
    profile: &HarnessProfile,
) -> Result<EmittedTree, CompileError> {
    validate_input(input)?;

    let mut roles = input.roles.iter().collect::<Vec<_>>();
    roles.sort_by(|left, right| left.role.cmp(&right.role));
    let mut skills = input.skills.iter().collect::<Vec<_>>();
    skills.sort_by(|left, right| left.name.cmp(&right.name));
    let emitted_roles = resolve_roles(&roles, profile)?;

    let mut files = match profile.target {
        Target::Claude => emit_claude(&roles, &emitted_roles, &skills)?,
        Target::Codex => emit_codex(&roles, &emitted_roles, &skills, profile)?,
        Target::Pi => emit_pi(&roles, &emitted_roles, &skills)?,
    };
    files.sort_by(|left, right| left.path.cmp(&right.path));
    for pair in files.windows(2) {
        if pair[0].path == pair[1].path {
            return Err(CompileError::Invalid(format!(
                "duplicate emitted path `{}` for target `{}`",
                pair[0].path,
                profile.target.as_str()
            )));
        }
    }

    let skill_bundle = files
        .iter()
        .filter(|file| file.kind == EmittedKind::Skill)
        .map(|file| file.content.as_str())
        .collect::<String>();
    validate_budget(
        &format!("{} skill entry set", profile.target.as_str()),
        BudgetClass::HarnessSkillSet,
        &skill_bundle,
    )?;

    let digest = tree_digest(&files);
    Ok(EmittedTree {
        target: profile.target,
        roles: emitted_roles,
        files,
        digest,
        tokenizer_version: TOKENIZER_VERSION,
    })
}

fn resolve_roles(
    roles: &[&RoleInput],
    profile: &HarnessProfile,
) -> Result<Vec<EmittedRole>, CompileError> {
    let resolve_tools = profile.target != Target::Codex;
    roles
        .iter()
        .map(|role| {
            let resolution = profile
                .model_by_hint
                .get(&role.model_hint)
                .ok_or_else(|| {
                    CompileError::Invalid(format!(
                        "{}: target `{}` has no model mapping for hint `{}`",
                        role.source_path,
                        profile.target.as_str(),
                        role.model_hint
                    ))
                })?;
            validate_model_resolution(role, profile.target, resolution)?;

            let mut seen_tools = BTreeSet::new();
            let mut tools = Vec::new();
            let mut unsupported_capabilities = Vec::new();
            if resolve_tools {
                for capability in &role.capabilities {
                    if let Some(mapped) = profile.tools_by_capability.get(capability) {
                        for tool in mapped {
                            validate_tool(tool)?;
                            if seen_tools.insert(tool.as_str()) {
                                tools.push(tool.clone());
                            }
                        }
                    } else if profile.unsupported_capabilities.contains(capability) {
                        unsupported_capabilities.push(capability.clone());
                    } else {
                        return Err(CompileError::Invalid(format!(
                            "{}: target `{}` has no tool or unsupported-capability mapping for `{capability}`",
                            role.source_path,
                            profile.target.as_str()
                        )));
                    }
                }
            }

            Ok(EmittedRole {
                role: role.role.clone(),
                carrier_path: match profile.target {
                    Target::Claude => format!("agents/{}.md", role.role),
                    Target::Codex => "shepherd.codex.toml".into(),
                    Target::Pi => format!("prompts/{}.md", role.role),
                },
                description: role.description.clone(),
                model: resolution.model.clone(),
                profile: resolution.profile.clone(),
                reasoning_effort: resolution.reasoning_effort.clone(),
                tools,
                unsupported_capabilities,
                capabilities: role.capabilities.clone(),
                write_eligible: role.write_eligible,
                dispatchable: role.dispatchable,
                write_scope: role.write_scope.clone(),
            })
        })
        .collect()
}

fn validate_model_resolution(
    role: &RoleInput,
    target: Target,
    resolution: &ModelResolution,
) -> Result<(), CompileError> {
    if let Some(model) = &resolution.model {
        validate_model_token(model)?;
    }
    if let Some(profile) = &resolution.profile {
        validate_identifier("model profile", profile)?;
    }
    if let Some(effort) = &resolution.reasoning_effort {
        validate_identifier("reasoning effort", effort)?;
    }

    let inherited = role.model_hint == "inherit-caller";
    let valid = match target {
        Target::Claude => {
            resolution.model.is_some()
                && resolution.profile.is_none()
                && resolution.reasoning_effort.is_none()
        }
        Target::Codex if inherited => {
            resolution.model.is_none()
                && resolution.profile.is_none()
                && resolution.reasoning_effort.is_none()
        }
        Target::Codex => {
            resolution.model.is_none()
                && resolution.profile.is_some()
                && resolution.reasoning_effort.is_some()
        }
        Target::Pi if inherited => {
            resolution.model.is_none()
                && resolution.profile.is_none()
                && resolution.reasoning_effort.is_none()
        }
        Target::Pi => {
            resolution.model.is_some()
                && resolution.profile.is_none()
                && resolution.reasoning_effort.is_none()
        }
    };
    if !valid {
        let detail =
            if target == Target::Codex && !inherited && resolution.reasoning_effort.is_none() {
                "profile and reasoning effort"
            } else {
                "target-native model/profile fields"
            };
        return Err(CompileError::Invalid(format!(
            "{}: model mapping for `{}` must provide {detail} for target `{}`",
            role.source_path,
            role.model_hint,
            target.as_str()
        )));
    }
    Ok(())
}

fn validate_input(input: &CompileInput) -> Result<(), CompileError> {
    if input.roles.is_empty() {
        return Err(CompileError::Invalid("content has zero roles".into()));
    }
    if input.skills.is_empty() {
        return Err(CompileError::Invalid("content has zero skills".into()));
    }
    let mut role_names = BTreeSet::new();
    for role in &input.roles {
        validate_identifier("role", &role.role)?;
        if !role_names.insert(role.role.as_str()) {
            return Err(CompileError::Invalid(format!(
                "duplicate role `{}`",
                role.role
            )));
        }
        validate_description(&role.source_path, &role.description)?;
        validate_source_path(&role.source_path)?;
        validate_identifier("model hint", &role.model_hint)?;
        if role.capabilities.is_empty() {
            return Err(CompileError::Invalid(format!(
                "{}: capabilities must not be empty",
                role.source_path
            )));
        }
        for capability in &role.capabilities {
            validate_identifier("capability", capability)?;
        }
        if role.body.trim().is_empty() {
            return Err(CompileError::Invalid(format!(
                "{}: role body must not be empty",
                role.source_path
            )));
        }
        if role.source_content.is_empty() {
            return Err(CompileError::Invalid(format!(
                "{}: source content is empty",
                role.source_path
            )));
        }
    }
    let mut skill_names = BTreeSet::new();
    for skill in &input.skills {
        validate_identifier("skill", &skill.name)?;
        if !skill_names.insert(skill.name.as_str()) {
            return Err(CompileError::Invalid(format!(
                "duplicate skill `{}`",
                skill.name
            )));
        }
        validate_description(&skill.source_path, &skill.description)?;
        validate_source_path(&skill.source_path)?;
        if skill.body.trim().is_empty() {
            return Err(CompileError::Invalid(format!(
                "{}: skill body must not be empty",
                skill.source_path
            )));
        }
        if skill.source_content.is_empty() {
            return Err(CompileError::Invalid(format!(
                "{}: source content is empty",
                skill.source_path
            )));
        }
    }
    Ok(())
}

fn validate_source_path(source_path: &str) -> Result<(), CompileError> {
    if source_path.is_empty()
        || source_path.starts_with('/')
        || source_path.contains('\\')
        || source_path
            .split('/')
            .any(|segment| matches!(segment, "" | "." | ".."))
    {
        return Err(CompileError::Invalid(
            "source path must be a non-empty relative slash path without traversal".into(),
        ));
    }
    Ok(())
}

fn validate_identifier(kind: &str, value: &str) -> Result<(), CompileError> {
    if value.is_empty()
        || value.len() > 64
        || !value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || (index > 0 && byte == b'-')
        })
    {
        return Err(CompileError::Invalid(format!(
            "invalid {kind} identifier `{value}`"
        )));
    }
    Ok(())
}

fn validate_description(path: &str, description: &str) -> Result<(), CompileError> {
    if description.trim().is_empty() {
        return Err(CompileError::Invalid(format!(
            "{path}: description must not be empty"
        )));
    }
    if description.chars().count() > 500 {
        return Err(CompileError::Invalid(format!(
            "{path}: description exceeds 500 characters"
        )));
    }
    if description.contains(['\r', '\n']) {
        return Err(CompileError::Invalid(format!(
            "{path}: description must be one line"
        )));
    }
    Ok(())
}

fn emit_claude(
    roles: &[&RoleInput],
    emitted_roles: &[EmittedRole],
    skills: &[&SkillInput],
) -> Result<Vec<EmittedFile>, CompileError> {
    let mut files = Vec::new();
    for (role, emitted_role) in roles.iter().zip(emitted_roles) {
        let content = frontmatter_file(
            &[
                ("name", role.role.clone()),
                ("description", quote(&role.description)),
                (
                    "model",
                    emitted_role
                        .model
                        .clone()
                        .expect("validated Claude role has a model"),
                ),
                ("tools", inline_array(&emitted_role.tools)),
                ("dispatchable", role.dispatchable.to_string()),
                ("write_eligible", role.write_eligible.to_string()),
                ("write_scope", quote(&role.write_scope)),
            ],
            &role.body,
        )?;
        files.push(emitted(
            format!("agents/{}.md", role.role),
            EmittedKind::Role,
            content,
            &role.source_path,
            &role.source_content,
            BudgetClass::Role,
        )?);
    }
    emit_skills(&mut files, Target::Claude, skills)?;
    Ok(files)
}

fn emit_codex(
    roles: &[&RoleInput],
    emitted_roles: &[EmittedRole],
    skills: &[&SkillInput],
    profile: &HarnessProfile,
) -> Result<Vec<EmittedFile>, CompileError> {
    let mut content = String::from(
        "# Generated by the canonical Rust shepherd compiler. Source: content/roles/*.md.\n\
# Do not hand-edit; regenerate via `shepherd compile --target codex --out <directory>`.\n\n",
    );
    writeln!(
        content,
        "max_concurrent_children = {}\n\n[agent_types]",
        profile.max_concurrent_children
    )
    .expect("writing to String cannot fail");
    for role in roles {
        if role.model_hint == "inherit-caller" {
            continue;
        }
        writeln!(
            content,
            "{} = \"{}\"",
            role.role,
            if role.write_eligible {
                "worker"
            } else {
                "explorer"
            }
        )
        .expect("writing to String cannot fail");
    }
    content.push_str("\n[models]\n");
    let mut profiles = alloc::collections::BTreeMap::new();
    for role in emitted_roles {
        let Some(profile_name) = role.profile.as_deref() else {
            continue;
        };
        let effort = role
            .reasoning_effort
            .as_deref()
            .expect("validated Codex profile has reasoning effort");
        writeln!(content, "{} = \"{profile_name}\"", role.role)
            .expect("writing to String cannot fail");
        if let Some(previous) = profiles.insert(profile_name, effort)
            && previous != effort
        {
            return Err(CompileError::Invalid(format!(
                "Codex profile `{profile_name}` has conflicting reasoning effort"
            )));
        }
    }
    content.push('\n');
    for (profile_name, effort) in profiles {
        writeln!(content, "[profiles.\"{profile_name}\"]").expect("writing to String cannot fail");
        writeln!(content, "reasoning_effort = \"{effort}\"\n")
            .expect("writing to String cannot fail");
    }
    if content.ends_with("\n\n") {
        content.pop();
    }
    let source = roles
        .iter()
        .map(|role| role.source_content.as_str())
        .collect::<String>();
    let mut files = vec![emitted(
        "shepherd.codex.toml".into(),
        EmittedKind::Config,
        content,
        "content/roles/*.md",
        &source,
        BudgetClass::Command,
    )?];
    emit_skills(&mut files, Target::Codex, skills)?;
    Ok(files)
}

fn emit_pi(
    roles: &[&RoleInput],
    emitted_roles: &[EmittedRole],
    skills: &[&SkillInput],
) -> Result<Vec<EmittedFile>, CompileError> {
    let mut files = Vec::new();
    for (role, _emitted_role) in roles.iter().zip(emitted_roles) {
        let content = frontmatter_file(
            &[
                ("name", role.role.clone()),
                ("description", quote(&role.description)),
                ("capabilities", inline_array(&role.capabilities)),
                ("dispatchable", role.dispatchable.to_string()),
                ("write_eligible", role.write_eligible.to_string()),
                ("write_scope", quote(&role.write_scope)),
            ],
            &role.body,
        )?;
        files.push(emitted(
            format!("prompts/{}.md", role.role),
            EmittedKind::Role,
            content,
            &role.source_path,
            &role.source_content,
            BudgetClass::Role,
        )?);
    }
    emit_skills(&mut files, Target::Pi, skills)?;
    Ok(files)
}

fn emit_skills(
    files: &mut Vec<EmittedFile>,
    target: Target,
    skills: &[&SkillInput],
) -> Result<(), CompileError> {
    for skill in skills {
        if skill.portability == Portability::ClaudeOnly && target != Target::Claude {
            continue;
        }
        let content = frontmatter_file(
            &[
                ("name", skill.name.clone()),
                ("description", quote(&skill.description)),
            ],
            &skill.body,
        )?;
        let frontmatter_end = content.find("\n---\n").ok_or_else(|| {
            CompileError::Invalid(format!(
                "{}: emitted frontmatter is malformed",
                skill.source_path
            ))
        })? + 5;
        if frontmatter_end > 1_024 {
            return Err(CompileError::Invalid(format!(
                "{}: frontmatter exceeds 1024 bytes",
                skill.source_path
            )));
        }
        files.push(emitted(
            format!("skills/{}/SKILL.md", skill.name),
            EmittedKind::Skill,
            content,
            &skill.source_path,
            &skill.source_content,
            BudgetClass::Skill,
        )?);
    }
    Ok(())
}

fn frontmatter_file(fields: &[(&str, String)], body: &str) -> Result<String, CompileError> {
    let body = body.trim();
    if body.lines().any(|line| line.trim() == "---") {
        return Err(CompileError::Invalid(
            "body contains a bare `---` frontmatter fence".into(),
        ));
    }
    let mut output = String::from("---\n");
    for (key, value) in fields {
        writeln!(output, "{key}: {value}").expect("writing to String cannot fail");
    }
    output.push_str("---\n\n");
    output.push_str(body);
    output.push('\n');
    Ok(output)
}

fn quote(value: &str) -> String {
    let mut output = String::from("\"");
    for character in value.chars() {
        match character {
            '\\' => output.push_str("\\\\"),
            '"' => output.push_str("\\\""),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            '\0' => output.push_str("\\0"),
            character if character.is_control() => {
                write!(output, "\\u{:04x}", character as u32)
                    .expect("writing to String cannot fail");
            }
            _ => output.push(character),
        }
    }
    output.push('"');
    output
}

fn validate_tool(tool: &str) -> Result<(), CompileError> {
    if tool.is_empty()
        || tool.len() > 64
        || !tool
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return Err(CompileError::Invalid(
            "harness tool names must be non-empty ASCII tokens".into(),
        ));
    }
    Ok(())
}

fn validate_model_token(model: &str) -> Result<(), CompileError> {
    if model.is_empty()
        || model.len() > 128
        || model
            .bytes()
            .any(|byte| byte.is_ascii_control() || matches!(byte, b'"' | b'\\'))
    {
        return Err(CompileError::Invalid(
            "harness model names must be non-empty safe scalar tokens".into(),
        ));
    }
    Ok(())
}

fn inline_array(values: &[String]) -> String {
    format!("[{}]", values.join(", "))
}

fn emitted(
    path: String,
    kind: EmittedKind,
    content: String,
    source_path: &str,
    source_content: &str,
    budget_class: BudgetClass,
) -> Result<EmittedFile, CompileError> {
    let measurement = validate_budget(&path, budget_class, &content)?;
    Ok(EmittedFile {
        path,
        kind,
        source_sha256: sha256(source_content.as_bytes()),
        content_sha256: sha256(content.as_bytes()),
        content,
        source_path: source_path.into(),
        measurement,
    })
}

fn tree_digest(files: &[EmittedFile]) -> String {
    let mut digest = Sha256::new();
    for file in files {
        digest.update(file.path.as_bytes());
        digest.update([0]);
        digest.update(file.content.as_bytes());
        digest.update([0, 0]);
    }
    hex(&digest.finalize())
}

fn sha256(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

fn hex(bytes: &[u8]) -> String {
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        write!(output, "{byte:02x}").expect("writing to String cannot fail");
    }
    output
}
