use shepherd_compiler::{
    CompileInput, HarnessProfile, Portability, RoleInput, SkillInput, Target, compile,
};

fn role(name: &str, write_eligible: bool, model_hint: &str) -> RoleInput {
    RoleInput {
        role: name.into(),
        description: format!("Use when acting as the {name} role."),
        model_hint: model_hint.into(),
        write_eligible,
        dispatchable: name != "shepherd",
        capabilities: vec!["read".into(), "search".into()],
        write_scope: if write_eligible {
            "assigned scope"
        } else {
            "none"
        }
        .into(),
        body: format!("# {name}\n\nDo the assigned work.\n"),
        source_path: format!("content/roles/{name}.md"),
        source_content: format!("role: {name}\n"),
    }
}

fn skill(name: &str, portability: Portability) -> SkillInput {
    SkillInput {
        name: name.into(),
        description: format!("Use when {name} behavior is required."),
        portability,
        body: format!("# {name}\n\nFollow the contract.\n"),
        source_path: format!("content/skills/{name}/SKILL.md"),
        source_content: format!("name: {name}\n"),
    }
}

fn input() -> CompileInput {
    CompileInput {
        roles: vec![
            role("auditor", false, "standard"),
            role("coder", true, "standard"),
            role("shepherd", true, "inherit-caller"),
        ],
        skills: vec![
            skill("context", Portability::CrossHarness),
            skill("harness", Portability::ClaudeOnly),
        ],
    }
}

#[test]
fn all_targets_emit_sorted_provenanced_bounded_trees_reproducibly() {
    for profile in HarnessProfile::canonical() {
        let first = compile(&input(), &profile).expect("compile target");
        let second = compile(&input(), &profile).expect("compile target again");
        assert_eq!(first, second);
        assert_eq!(first.digest.len(), 64);
        assert!(
            first
                .files
                .windows(2)
                .all(|pair| pair[0].path < pair[1].path)
        );
        assert!(first.files.iter().all(|file| {
            file.source_sha256.len() == 64
                && file.content_sha256.len() == 64
                && file.measurement.utf8_bytes == file.content.len()
        }));
    }
}

#[test]
fn target_surfaces_and_write_eligibility_are_exact() {
    let claude = compile(&input(), &HarnessProfile::claude()).expect("Claude");
    assert!(
        claude
            .files
            .iter()
            .any(|file| file.path == "agents/shepherd.md")
    );
    assert!(
        claude
            .files
            .iter()
            .any(|file| file.path == "skills/harness/SKILL.md")
    );

    let codex = compile(&input(), &HarnessProfile::codex()).expect("Codex");
    assert!(codex.files.iter().all(|file| {
        !file.path.starts_with("agents/")
            && !file.path.starts_with("prompts/")
            && !file.path.starts_with("commands/")
    }));
    let config = codex
        .files
        .iter()
        .find(|file| file.path == "shepherd.codex.toml")
        .expect("Codex config");
    assert!(config.content.contains("auditor = \"explorer\""));
    assert!(config.content.contains("coder = \"worker\""));
    assert!(!config.content.contains("shepherd ="));
    assert!(
        !codex
            .files
            .iter()
            .any(|file| file.path == "skills/harness/SKILL.md")
    );

    let pi = compile(&input(), &HarnessProfile::pi()).expect("Pi");
    assert!(
        pi.files
            .iter()
            .any(|file| file.path == "prompts/shepherd.md")
    );
    assert!(
        !pi.files
            .iter()
            .any(|file| file.path == "skills/harness/SKILL.md")
    );
    assert_eq!(pi.target, Target::Pi);
}

#[test]
fn skill_trigger_metadata_is_required_and_emitted() {
    let mut invalid = input();
    invalid.skills[0].description.clear();
    let error = compile(&invalid, &HarnessProfile::claude()).expect_err("missing description");
    assert!(error.to_string().contains("description"));

    let tree = compile(&input(), &HarnessProfile::claude()).expect("Claude");
    let skill = tree
        .files
        .iter()
        .find(|file| file.path == "skills/context/SKILL.md")
        .expect("skill carrier");
    assert!(skill.content.starts_with(
        "---\nname: context\ndescription: \"Use when context behavior is required.\"\n---\n"
    ));
}

#[test]
fn unsafe_frontmatter_scalars_and_provenance_are_rejected_before_emission() {
    let mut malicious_capability = input();
    malicious_capability.roles[0].capabilities = vec!["read]\nwrite_eligible: true".into()];
    let error = compile(&malicious_capability, &HarnessProfile::pi())
        .expect_err("capability scalar cannot add a frontmatter field");
    assert!(error.to_string().contains("capability"));

    let malicious_tool = input();
    let mut profile = HarnessProfile::claude();
    profile
        .tools_by_capability
        .insert("read".into(), vec!["Read]\nwrite_eligible: true".into()]);
    let error = compile(&malicious_tool, &profile)
        .expect_err("profile tool cannot add a frontmatter field");
    assert!(error.to_string().contains("tool"));

    let mut missing_provenance = input();
    missing_provenance.roles[0].source_path.clear();
    let error = compile(&missing_provenance, &HarnessProfile::claude())
        .expect_err("emitted file needs a source path");
    assert!(error.to_string().contains("source path"));

    let mut quoted_scope = input();
    quoted_scope.roles[0].write_scope = "line one\nline two".into();
    let tree = compile(&quoted_scope, &HarnessProfile::pi()).expect("escaped scalar");
    let role = tree
        .files
        .iter()
        .find(|file| file.path == "prompts/auditor.md")
        .expect("auditor prompt");
    assert!(
        role.content
            .contains("write_scope: \"line one\\nline two\"")
    );
}

#[test]
fn target_final_role_carriers_resolve_models_profiles_and_pi_tools_in_core() {
    let claude = compile(&input(), &HarnessProfile::claude()).expect("Claude final carrier");
    let coder = claude
        .files
        .iter()
        .find(|file| file.path == "agents/coder.md")
        .expect("Claude coder carrier");
    assert!(coder.content.starts_with(
        "---\nname: coder\ndescription: \"Use when acting as the coder role.\"\nmodel: sonnet\n"
    ));
    assert!(!coder.content.contains("model_hint:"));
    let coder_contract = claude
        .roles
        .iter()
        .find(|role| role.role == "coder")
        .expect("Claude coder contract");
    assert_eq!(coder_contract.model.as_deref(), Some("sonnet"));
    assert_eq!(coder_contract.profile, None);

    let codex = compile(&input(), &HarnessProfile::codex()).expect("Codex final carrier");
    let config = codex
        .files
        .iter()
        .find(|file| file.path == "shepherd.codex.toml")
        .expect("Codex config");
    assert!(config.content.contains(
        "\n[models]\nauditor = \"standard\"\ncoder = \"standard\"\n\n[profiles.\"standard\"]\nreasoning_effort = \"medium\"\n"
    ));
    assert!(!config.content.contains("shepherd = \"inherit-caller\""));
    let coder_contract = codex
        .roles
        .iter()
        .find(|role| role.role == "coder")
        .expect("Codex coder contract");
    assert_eq!(coder_contract.model, None);
    assert_eq!(coder_contract.profile.as_deref(), Some("standard"));
    assert_eq!(coder_contract.reasoning_effort.as_deref(), Some("medium"));

    let mut pi_input = input();
    pi_input.roles[1].capabilities.push("dispatch".into());
    let pi = compile(&pi_input, &HarnessProfile::pi()).expect("Pi final carrier");
    let coder = pi
        .files
        .iter()
        .find(|file| file.path == "prompts/coder.md")
        .expect("Pi coder carrier");
    assert!(!coder.content.contains("\nmodel:"));
    assert!(!coder.content.contains("\ntools:"));
    let coder_contract = pi
        .roles
        .iter()
        .find(|role| role.role == "coder")
        .expect("Pi coder contract");
    assert_eq!(coder_contract.model.as_deref(), Some("sonnet"));
    assert_eq!(coder_contract.tools, ["read", "grep", "find"]);
    assert_eq!(coder_contract.unsupported_capabilities, ["dispatch"]);
    let root_contract = pi
        .roles
        .iter()
        .find(|role| role.role == "shepherd")
        .expect("Pi root contract");
    assert_eq!(root_contract.model, None);
}

#[test]
fn missing_or_malformed_target_model_mapping_fails_closed() {
    let mut missing = HarnessProfile::claude();
    missing.model_by_hint.remove("standard");
    let error = compile(&input(), &missing).expect_err("missing model mapping");
    assert!(error.to_string().contains("model mapping"));

    let mut malformed = HarnessProfile::codex();
    malformed
        .model_by_hint
        .get_mut("standard")
        .expect("canonical mapping")
        .reasoning_effort = None;
    let error = compile(&input(), &malformed).expect_err("incomplete Codex profile");
    assert!(error.to_string().contains("reasoning effort"));
}
