/*
    Appellation: guard <test>
    Contrib: @FL03
*/
//! Public contract tests for the portable guard engine.

use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
};

use shepherd_core::guard::{
    Decision, GuardEngine, GuardValue, Verdict, extract_git_subcommands, parse_predicate_toml,
    parse_role_markdown,
};

fn object(entries: impl IntoIterator<Item = (&'static str, GuardValue)>) -> GuardValue {
    GuardValue::Object(
        entries
            .into_iter()
            .map(|(key, value)| (key.into(), value))
            .collect(),
    )
}

fn evaluate(engine: &GuardEngine, request: &GuardValue) -> Verdict {
    engine
        .evaluate(request)
        .expect("a well-typed request evaluates")
}

fn live_source_paths(content_dir: &Path, subdirectory: &str, extension: &str) -> Vec<PathBuf> {
    let mut paths: Vec<_> = std::fs::read_dir(content_dir.join(subdirectory))
        .expect("live content directory is readable")
        .map(|entry| entry.expect("live content entry is readable").path())
        .filter(|path| path.extension().and_then(std::ffi::OsStr::to_str) == Some(extension))
        .collect();
    paths.sort();
    paths
}

fn live_predicate_ids(content_dir: &Path) -> Vec<String> {
    live_source_paths(content_dir, "predicates", "toml")
        .into_iter()
        .map(|path| {
            let source_name = path
                .file_name()
                .and_then(std::ffi::OsStr::to_str)
                .expect("live predicate filename is UTF-8");
            let contents = std::fs::read_to_string(&path).expect("live predicate is readable");
            parse_predicate_toml(source_name, &contents)
                .expect("live predicate parses")
                .id
        })
        .collect()
}

fn live_role_ids(content_dir: &Path) -> Vec<String> {
    live_source_paths(content_dir, "roles", "md")
        .into_iter()
        .map(|path| {
            let source_name = path
                .file_name()
                .and_then(std::ffi::OsStr::to_str)
                .expect("live role filename is UTF-8");
            let contents = std::fs::read_to_string(&path).expect("live role is readable");
            parse_role_markdown(source_name, &contents)
                .expect("live role parses")
                .role
        })
        .collect()
}

#[test]
fn a_non_git_bash_tool_call_allows_without_predicate_data() {
    let engine = GuardEngine::new(Vec::new(), Vec::new()).expect("an empty corpus is loadable");
    let request = GuardValue::Object(BTreeMap::from([
        ("role".into(), GuardValue::from("coder")),
        ("tool_name".into(), GuardValue::from("Bash")),
        (
            "tool_input".into(),
            GuardValue::Object(BTreeMap::from([(
                "command".into(),
                GuardValue::from("printf safe"),
            )])),
        ),
    ]));

    assert_eq!(evaluate(&engine, &request).decision, Decision::Allow);
}

#[test]
fn predicate_toml_parses_into_typed_declaration_order() {
    let source = r#"
[predicate]
id = "probe"
version = 3
description = "probe predicate"

[[rule]]
id = "first"
description = "first reason"
subject = "probe.fact"
action = "fs.write"
effect = "allow_if_no_hit"

[[example]]
name = "probe-example"
kind = "allow"
role = "coder"
action = "fs.write"
symbol = "Probe"
context = { dedup_hit = false }
result = "allow"
"#;

    let predicate = parse_predicate_toml("probe.toml", source).expect("valid TOML parses");

    assert_eq!(predicate.id, "probe");
    assert_eq!(predicate.version, 3);
    assert_eq!(predicate.rules[0].id, "first");
    assert_eq!(predicate.examples[0].name, "probe-example");
    assert_eq!(
        predicate.examples[0].extra.get("symbol"),
        Some(&GuardValue::from("Probe"))
    );
    assert_eq!(
        predicate.examples[0].context.get("dedup_hit"),
        Some(&GuardValue::Bool(false))
    );
}

#[test]
fn role_markdown_parses_frontmatter_facts() {
    let source = r#"---
role: discovery
write_eligible: false
dispatchable: true
capabilities: [read, search, report-write]
---

# discovery
"#;

    let fact = parse_role_markdown("discovery.md", source).expect("valid role parses");

    assert_eq!(fact.role, "discovery");
    assert!(!fact.write_eligible);
    assert!(fact.dispatchable);
    assert_eq!(fact.capabilities, ["read", "search", "report-write"]);
}

#[test]
fn normalized_deny_fires_rules_and_harvests_singleton_halt_code() {
    let predicate = parse_predicate_toml(
        "dedup.toml",
        r#"
[predicate]
id = "dedup-gate"

[[rule]]
id = "hit-requires-justification"
description = "A duplicate requires explicit justification."
subject = "registry.dedup_check"
action = "fs.write"
effect = "deny_if_hit_without_justification"

[[example]]
name = "duplicate"
kind = "deny"
role = "coder"
action = "fs.write"
context = { dedup_hit = true, justification_present = false }
result = "deny"
halt_code = "DEDUP-HIT"
"#,
    )
    .expect("fixture parses");
    let engine = GuardEngine::new(vec![predicate], Vec::new()).expect("corpus is consistent");
    let request = object([
        ("predicate", GuardValue::from("dedup-gate")),
        ("role", GuardValue::from("coder")),
        ("action", GuardValue::from("fs.write")),
        (
            "context",
            object([
                ("dedup_hit", GuardValue::Bool(true)),
                ("justification_present", GuardValue::Bool(false)),
            ]),
        ),
    ]);

    let verdict = evaluate(&engine, &request);

    assert_eq!(verdict.decision, Decision::Deny);
    assert_eq!(verdict.predicate.as_deref(), Some("dedup-gate"));
    assert_eq!(verdict.rule.as_deref(), Some("hit-requires-justification"));
    assert_eq!(verdict.halt_code.as_deref(), Some("DEDUP-HIT"));
    assert_eq!(
        verdict.reason.as_deref(),
        Some("A duplicate requires explicit justification.")
    );
    assert!(verdict.missing.is_empty());
}

fn lane_lead_branch_engine() -> GuardEngine {
    let predicate = parse_predicate_toml(
        "dispatch-scope.toml",
        r#"
[predicate]
id = "dispatch-scope"

[[rule]]
id = "plan-authorship-and-gating-are-root-tier-exclusive"
description = "lane leads cannot dispatch plan or gate roles"
subject = "dispatch.target_role"
action = "dispatch"
effect = "deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role"
"#,
    )
    .expect("lane-lead branch fixture parses");
    GuardEngine::new(vec![predicate], Vec::new()).expect("branch fixture is consistent")
}

#[test]
fn lane_lead_branch_denies_engineer_plan_target() {
    let request = object([
        ("predicate", GuardValue::from("dispatch-scope")),
        ("role", GuardValue::from("conductor")),
        ("action", GuardValue::from("dispatch")),
        (
            "context",
            object([
                ("dispatcher_tier", GuardValue::from("lane-lead")),
                ("target_role", GuardValue::from("engineer")),
            ]),
        ),
    ]);

    let verdict = evaluate(&lane_lead_branch_engine(), &request);

    assert_eq!(verdict.decision, Decision::Deny);
    assert_eq!(
        verdict.rule.as_deref(),
        Some("plan-authorship-and-gating-are-root-tier-exclusive")
    );
}

#[test]
fn lane_lead_branch_denies_critic_gate_target() {
    let request = object([
        ("predicate", GuardValue::from("dispatch-scope")),
        ("role", GuardValue::from("conductor")),
        ("action", GuardValue::from("dispatch")),
        (
            "context",
            object([
                ("dispatcher_tier", GuardValue::from("lane-lead")),
                ("target_role", GuardValue::from("critic")),
            ]),
        ),
    ]);

    let verdict = evaluate(&lane_lead_branch_engine(), &request);

    assert_eq!(verdict.decision, Decision::Deny);
    assert_eq!(
        verdict.rule.as_deref(),
        Some("plan-authorship-and-gating-are-root-tier-exclusive")
    );
}

#[test]
fn lane_lead_branch_allows_implementation_target() {
    let request = object([
        ("predicate", GuardValue::from("dispatch-scope")),
        ("role", GuardValue::from("conductor")),
        ("action", GuardValue::from("dispatch")),
        (
            "context",
            object([
                ("dispatcher_tier", GuardValue::from("lane-lead")),
                ("target_role", GuardValue::from("coder")),
            ]),
        ),
    ]);

    assert_eq!(
        evaluate(&lane_lead_branch_engine(), &request).decision,
        Decision::Allow
    );
}

#[test]
fn git_tokenizer_handles_options_paths_separators_and_nested_wrappers() {
    let command = concat!(
        "/usr/bin/git -C /repo status; git --git-dir=/repo/.git commit -m x && ",
        "eval 'bash -c \"git rebase main\"'"
    );

    assert_eq!(
        extract_git_subcommands(command),
        ["status", "commit", "rebase"]
    );
}

fn git_custody_engine() -> GuardEngine {
    let predicate = parse_predicate_toml(
        "git-custody.toml",
        r#"
[predicate]
id = "git-custody"

[[rule]]
id = "implementer-never-writes-git"
description = "Implementers never write git."
subject = "role.tier"
action = "vcs.write"
effect = "deny_if_role_is_implementer"

[[rule]]
id = "cross-lane-integration-is-root-exclusive"
description = "Integration is root-exclusive."
subject = "role.tier"
action = "vcs.integrate"
effect = "deny_unless_root"

[[example]]
name = "coder-commit"
kind = "deny"
role = "coder"
action = "vcs.write"
context = { role_tier = "implementer" }
result = "deny"
halt_code = "CODER-GIT-WRITE"

[[example]]
name = "conductor-rebase"
kind = "deny"
role = "conductor"
action = "vcs.integrate"
context = { role_tier = "lane-lead" }
result = "deny"
halt_code = "TEAMMATE-GIT-WRITE"
"#,
    )
    .expect("fixture parses");
    GuardEngine::new(vec![predicate], Vec::new()).expect("corpus is consistent")
}

fn lane_branch_custody_engine() -> GuardEngine {
    let predicate = parse_predicate_toml(
        "git-custody.toml",
        r#"
[predicate]
id = "git-custody"

[[rule]]
id = "lane-lead-owns-its-own-branch-only"
description = "Lane leads write only their own lane branch."
subject = "dispatch.git_custody"
action = "vcs.write"
effect = "deny_if_branch_outside_own_lane"
"#,
    )
    .expect("lane branch fixture parses");
    GuardEngine::new(vec![predicate], Vec::new()).expect("branch fixture is consistent")
}

fn evaluate_lane_branch(is_own_lane_branch: bool) -> Verdict {
    evaluate(
        &lane_branch_custody_engine(),
        &object([
            ("predicate", GuardValue::from("git-custody")),
            ("role", GuardValue::from("conductor")),
            ("action", GuardValue::from("vcs.write")),
            (
                "context",
                object([("is_own_lane_branch", GuardValue::Bool(is_own_lane_branch))]),
            ),
        ]),
    )
}

#[test]
fn lane_lead_write_denies_a_branch_outside_its_own_lane() {
    let verdict = evaluate_lane_branch(false);

    assert_eq!(verdict.decision, Decision::Deny);
    assert_eq!(
        verdict.rule.as_deref(),
        Some("lane-lead-owns-its-own-branch-only")
    );
}

#[test]
fn lane_lead_write_allows_its_own_lane_branch() {
    let verdict = evaluate_lane_branch(true);

    assert_eq!(verdict.decision, Decision::Allow);
    assert_eq!(verdict.rule, None);
}

#[test]
fn raw_bash_integrate_verb_takes_precedence_over_plain_write() {
    let engine = git_custody_engine();
    let request = object([
        ("role", GuardValue::from("coder")),
        ("tool_name", GuardValue::from("Bash")),
        (
            "tool_input",
            object([(
                "command",
                GuardValue::from("git commit -m x; git rebase main"),
            )]),
        ),
    ]);

    let verdict = evaluate(&engine, &request);

    assert_eq!(verdict.decision, Decision::Deny);
    assert_eq!(
        verdict.rule.as_deref(),
        Some("cross-lane-integration-is-root-exclusive")
    );
    assert_eq!(verdict.halt_code.as_deref(), Some("TEAMMATE-GIT-WRITE"));
}

#[test]
fn compatibility_unknown_git_subcommand_allows() {
    let request = object([
        ("role", GuardValue::from("coder")),
        ("tool_name", GuardValue::from("Bash")),
        (
            "tool_input",
            object([("command", GuardValue::from("git mystery"))]),
        ),
    ]);

    assert_eq!(
        evaluate(&git_custody_engine(), &request).decision,
        Decision::Allow
    );
}

#[test]
fn compatibility_glued_separator_hides_following_git_write() {
    let request = object([
        ("role", GuardValue::from("coder")),
        ("tool_name", GuardValue::from("Bash")),
        (
            "tool_input",
            object([("command", GuardValue::from("git status;git commit -m x"))]),
        ),
    ]);

    assert_eq!(
        evaluate(&git_custody_engine(), &request).decision,
        Decision::Allow
    );
}

#[test]
fn verdict_serializer_matches_guard_wire_bytes_and_field_presence() {
    let deny = Verdict {
        decision: Decision::Deny,
        predicate: Some("probe".into()),
        rule: Some("first,second".into()),
        halt_code: None,
        reason: Some("café ☕ 🎉".into()),
        missing: Vec::new(),
    };

    assert_eq!(
        deny.to_wire_json(),
        r#"{"decision": "deny", "predicate": "probe", "rule": "first,second", "reason": "caf\u00e9 \u2615 \ud83c\udf89"}"#
    );
    assert_eq!(
        Verdict {
            decision: Decision::Allow,
            predicate: Some("must-be-omitted".into()),
            rule: None,
            halt_code: None,
            reason: Some("must-be-omitted".into()),
            missing: vec!["must-be-omitted".into()],
        }
        .to_wire_json(),
        r#"{"decision": "allow"}"#
    );
}

#[test]
fn deny_serializer_emits_halt_code_in_contract_field_order() {
    let verdict = Verdict {
        decision: Decision::Deny,
        predicate: Some("git-custody".into()),
        rule: Some("implementer-never-writes-git".into()),
        halt_code: Some("CODER-GIT-WRITE".into()),
        reason: Some("denied".into()),
        missing: vec!["must-be-omitted".into()],
    };

    assert_eq!(
        verdict.to_wire_json(),
        r#"{"decision": "deny", "predicate": "git-custody", "rule": "implementer-never-writes-git", "halt_code": "CODER-GIT-WRITE", "reason": "denied"}"#
    );
}

#[test]
fn unresolved_serializer_emits_nonempty_missing_after_reason() {
    let verdict = Verdict {
        decision: Decision::Unresolved,
        predicate: Some("must-be-omitted".into()),
        rule: Some("must-be-omitted".into()),
        halt_code: Some("must-be-omitted".into()),
        reason: Some("needs facts".into()),
        missing: vec!["role".into(), "context.path".into()],
    };

    assert_eq!(
        verdict.to_wire_json(),
        r#"{"decision": "unresolved", "reason": "needs facts", "missing": ["role", "context.path"]}"#
    );
}

#[test]
fn compatibility_ascii_escapes_outside_printable_boundaries() {
    let verdict = Verdict {
        decision: Decision::Unresolved,
        predicate: None,
        rule: None,
        halt_code: None,
        reason: Some("\u{001f} ~\u{007f}\"\\".into()),
        missing: Vec::new(),
    };

    // Pinned fixture over U+001F, U+0020, U+007E, U+007F, quote, and
    // backslash in that order.
    assert_eq!(
        verdict.to_wire_json(),
        r#"{"decision": "unresolved", "reason": "\u001f ~\u007f\"\\"}"#
    );
}

#[test]
fn explicit_content_loader_discovers_every_live_predicate() {
    let content_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content");
    let engine = GuardEngine::load_content(&content_dir).expect("live content loads");
    let predicate_ids = live_predicate_ids(&content_dir);
    let expected_ids: BTreeSet<_> = LIVE_EXPECTATIONS
        .iter()
        .map(|expected| expected.predicate)
        .collect();
    let discovered_ids: BTreeSet<_> = predicate_ids.iter().map(String::as_str).collect();

    assert_eq!(discovered_ids, expected_ids, "predicate coverage drift");
    let example_count: usize = predicate_ids
        .iter()
        .map(|id| {
            engine
                .predicate(id)
                .expect("every discovered predicate was loaded")
                .examples
                .len()
        })
        .sum();
    assert_eq!(example_count, 17);
}

#[derive(Clone, Copy)]
struct ExpectedRole {
    role: &'static str,
    write_eligible: bool,
    dispatchable: bool,
    capabilities: &'static [&'static str],
}

const LIVE_ROLE_EXPECTATIONS: &[ExpectedRole] = &[
    ExpectedRole {
        role: "auditor",
        write_eligible: false,
        dispatchable: true,
        capabilities: &[
            "read",
            "search",
            "shell",
            "code-intelligence",
            "skill-load",
            "tool-discovery",
            "report-write",
        ],
    },
    ExpectedRole {
        role: "coder",
        write_eligible: true,
        dispatchable: true,
        capabilities: &[
            "read",
            "search",
            "shell",
            "write",
            "skill-load",
            "tool-discovery",
        ],
    },
    ExpectedRole {
        role: "conductor",
        write_eligible: true,
        dispatchable: true,
        capabilities: &[
            "read",
            "search",
            "shell",
            "skill-load",
            "tool-discovery",
            "dispatch",
            "schedule-wakeup",
            "message-peer",
            "task-tracking",
            "web-research",
        ],
    },
    ExpectedRole {
        role: "critic",
        write_eligible: false,
        dispatchable: true,
        capabilities: &["read", "search", "shell", "skill-load"],
    },
    ExpectedRole {
        role: "discovery",
        write_eligible: false,
        dispatchable: true,
        capabilities: &[
            "read",
            "search",
            "shell",
            "skill-load",
            "tool-discovery",
            "web-research",
            "report-write",
        ],
    },
    ExpectedRole {
        role: "engineer",
        write_eligible: true,
        dispatchable: true,
        capabilities: &[
            "read",
            "search",
            "shell",
            "write",
            "skill-load",
            "tool-discovery",
            "dispatch",
            "message-peer",
        ],
    },
    ExpectedRole {
        role: "planter",
        write_eligible: true,
        dispatchable: false,
        capabilities: &[
            "read",
            "search",
            "shell",
            "write",
            "skill-load",
            "tool-discovery",
            "dispatch",
            "ask-operator",
            "task-tracking",
            "web-research",
        ],
    },
    ExpectedRole {
        role: "shepherd",
        write_eligible: true,
        dispatchable: false,
        capabilities: &[
            "read",
            "search",
            "shell",
            "write",
            "skill-load",
            "tool-discovery",
            "dispatch",
            "message-peer",
            "task-tracking",
            "web-research",
        ],
    },
    ExpectedRole {
        role: "worker",
        write_eligible: true,
        dispatchable: true,
        capabilities: &[
            "read",
            "search",
            "shell",
            "write",
            "skill-load",
            "tool-discovery",
        ],
    },
];

#[test]
fn every_live_role_id_and_guard_fact_matches_frontmatter() {
    let content_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content");
    let engine = GuardEngine::load_content(&content_dir).expect("live content loads");
    let discovered_ids: BTreeSet<_> = live_role_ids(&content_dir).into_iter().collect();
    let expected_ids: BTreeSet<_> = LIVE_ROLE_EXPECTATIONS
        .iter()
        .map(|expected| String::from(expected.role))
        .collect();

    assert_eq!(discovered_ids, expected_ids, "role coverage drift");
    for expected in LIVE_ROLE_EXPECTATIONS {
        let fact = engine
            .role_fact(expected.role)
            .expect("every discovered live role was loaded");
        assert_eq!(fact.role, expected.role, "{} role id", expected.role);
        assert_eq!(
            fact.write_eligible, expected.write_eligible,
            "{} write eligibility",
            expected.role
        );
        assert_eq!(
            fact.dispatchable, expected.dispatchable,
            "{} dispatchability",
            expected.role
        );
        assert_eq!(
            fact.capabilities, expected.capabilities,
            "{} capabilities",
            expected.role
        );
    }
}

#[derive(Clone, Copy)]
struct ExpectedExample {
    predicate: &'static str,
    name: &'static str,
    decision: Decision,
    rule: Option<&'static str>,
    halt_code: Option<&'static str>,
    reason: Option<&'static str>,
}

const LIVE_EXPECTATIONS: &[ExpectedExample] = &[
    ExpectedExample {
        predicate: "dedup-gate",
        name: "coder-writes-a-genuinely-new-symbol",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "dedup-gate",
        name: "coder-writes-an-already-existing-public-symbol",
        decision: Decision::Deny,
        rule: Some("hit-requires-justification"),
        halt_code: Some("DEDUP-HIT"),
        reason: Some(
            "A symbol matching an existing one at or above the block threshold is denied UNLESS the dispatch carries an explicit justification block naming why this is a genuine new symbol, not a duplicate.",
        ),
    },
    ExpectedExample {
        predicate: "dedup-gate",
        name: "coder-writes-a-near-duplicate-with-justification",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "dispatch-scope",
        name: "root-dispatches-engineer-at-plan-authorship",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "dispatch-scope",
        name: "conductor-dispatches-coder-inside-its-own-lane",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "dispatch-scope",
        name: "conductor-attempts-to-dispatch-engineer",
        decision: Decision::Deny,
        rule: Some("plan-authorship-and-gating-are-root-tier-exclusive"),
        halt_code: Some("WRONG-TIER-DISPATCH"),
        reason: Some(
            "Only the root orchestrator (shepherd) may dispatch the plan-author (engineer) or gating (critic) roles for sprint-plan authorship/gating; a lane-executor lead (conductor) invoking either directly is refused.",
        ),
    },
    ExpectedExample {
        predicate: "dispatch-scope",
        name: "coder-attempts-to-dispatch-worker-for-a-missing-dependency",
        decision: Decision::Deny,
        rule: Some("implementer-roles-never-dispatch"),
        halt_code: None,
        reason: Some(
            "An implementer role (coder, worker, discovery, auditor, critic) never dispatches any other role at all — a missing dependency is a scope-amendment request or a close-time finding on that same dispatch, never a nested dispatch.",
        ),
    },
    ExpectedExample {
        predicate: "dispatch-scope",
        name: "dispatch-outside-the-closed-flock",
        decision: Decision::Deny,
        rule: Some("closed-flock-only"),
        halt_code: Some("DISPATCH-OFF-FLOCK"),
        reason: Some(
            "The dispatch target MUST be one of the nine content/roles/*.md role ids; any other value is refused on sight.",
        ),
    },
    ExpectedExample {
        predicate: "git-custody",
        name: "conductor-commits-its-own-lane-branch",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "git-custody",
        name: "coder-attempts-a-commit",
        decision: Decision::Deny,
        rule: Some("implementer-never-writes-git"),
        halt_code: Some("CODER-GIT-WRITE"),
        reason: Some(
            "A role dispatched to implement one file-disjoint scope (coder) never performs any version-control write, under any circumstance — custody sits one tier up, always.",
        ),
    },
    ExpectedExample {
        predicate: "git-custody",
        name: "conductor-attempts-cross-lane-rebase",
        decision: Decision::Deny,
        rule: Some("cross-lane-integration-is-root-exclusive"),
        halt_code: Some("TEAMMATE-GIT-WRITE"),
        reason: Some(
            "Rebase/merge/cherry-pick onto the shared integration branch, and worktree add/remove/prune, are denied to every role except the top-level orchestrator (shepherd).",
        ),
    },
    ExpectedExample {
        predicate: "git-custody",
        name: "root-runs-close-time-rebase-merge",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "write-boundary",
        name: "coder-writes-inside-declared-file-scope",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "write-boundary",
        name: "coder-writes-outside-declared-file-scope",
        decision: Decision::Deny,
        rule: Some("path-in-declared-scope"),
        halt_code: Some("SCOPE OVERFLOW"),
        reason: Some(
            "Even a write_eligible = true role's write is denied when the target path falls outside the write_scope this specific dispatch's brief declares (a general write grant is not a blanket grant — the brief's file scope narrows it per dispatch).",
        ),
    },
    ExpectedExample {
        predicate: "write-boundary",
        name: "discovery-writes-its-one-declared-output-path",
        decision: Decision::Allow,
        rule: None,
        halt_code: None,
        reason: None,
    },
    ExpectedExample {
        predicate: "write-boundary",
        name: "discovery-writes-outside-its-declared-output-path",
        decision: Decision::Deny,
        rule: Some("role-write-eligibility,path-in-declared-scope"),
        halt_code: Some("DISCOVERY-WRITE-PATH"),
        reason: Some(
            "fs.write is denied outright when the role's content/roles/<role>.md declares write_eligible: false. / Even a write_eligible = true role's write is denied when the target path falls outside the write_scope this specific dispatch's brief declares (a general write grant is not a blanket grant — the brief's file scope narrows it per dispatch).",
        ),
    },
    ExpectedExample {
        predicate: "write-boundary",
        name: "critic-attempts-any-write",
        decision: Decision::Deny,
        rule: Some("role-write-eligibility,path-in-declared-scope"),
        halt_code: None,
        reason: Some(
            "fs.write is denied outright when the role's content/roles/<role>.md declares write_eligible: false. / Even a write_eligible = true role's write is denied when the target path falls outside the write_scope this specific dispatch's brief declares (a general write grant is not a blanket grant — the brief's file scope narrows it per dispatch).",
        ),
    },
];

#[test]
fn all_seventeen_live_examples_match_complete_verdicts_and_fields() {
    let content_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content");
    let engine = GuardEngine::load_content(&content_dir).expect("live content loads");
    let predicate_ids = live_predicate_ids(&content_dir);
    let mut checked = 0;

    for predicate_id in &predicate_ids {
        let predicate = engine
            .predicate(predicate_id)
            .expect("every discovered predicate was loaded");
        for example in &predicate.examples {
            let expected = LIVE_EXPECTATIONS
                .iter()
                .find(|expected| {
                    expected.predicate == predicate_id.as_str() && expected.name == example.name
                })
                .unwrap_or_else(|| {
                    panic!("unattested live example {predicate_id}/{}", example.name)
                });
            let request = object([
                ("predicate", GuardValue::from(predicate_id.clone())),
                ("role", example.role.clone()),
                ("action", GuardValue::from(example.action.clone())),
                ("context", GuardValue::Object(example.flattened_context())),
            ]);

            let verdict = evaluate(&engine, &request);
            assert_eq!(
                verdict.decision, expected.decision,
                "{predicate_id}/{} decision",
                example.name
            );
            assert_eq!(
                verdict.rule.as_deref(),
                expected.rule,
                "{predicate_id}/{} complete rule string",
                example.name
            );
            assert_eq!(
                verdict.halt_code.as_deref(),
                expected.halt_code,
                "{predicate_id}/{} halt code presence/value",
                example.name
            );
            assert_eq!(
                verdict.reason.as_deref(),
                expected.reason,
                "{predicate_id}/{} reason",
                example.name
            );

            let wire: serde_json::Value = serde_json::from_str(&verdict.to_wire_json())
                .expect("verdict serializer emits valid JSON");
            let fields = wire.as_object().expect("verdict is an object");
            assert_eq!(
                fields.contains_key("predicate"),
                expected.decision == Decision::Deny
            );
            assert_eq!(fields.contains_key("rule"), expected.rule.is_some());
            assert_eq!(
                fields.contains_key("halt_code"),
                expected.halt_code.is_some()
            );
            assert_eq!(fields.contains_key("reason"), expected.reason.is_some());
            assert!(!fields.contains_key("missing"));
            checked += 1;
        }
    }

    assert_eq!(checked, 17, "the live corpus size changed");
    assert_eq!(LIVE_EXPECTATIONS.len(), checked, "stale expectation rows");
}

#[test]
fn json_request_uses_normalized_precedence_when_both_discriminators_exist() {
    let verdict = git_custody_engine()
        .evaluate_json(
            r#"{"predicate":"git-custody","role":"coder","tool_name":"Bash","tool_input":{"command":"git commit -m x"}}"#,
        )
        .expect("request JSON parses");

    assert_eq!(verdict.decision, Decision::Unresolved);
    assert_eq!(verdict.reason.as_deref(), Some("missing `action`"));
    assert_eq!(verdict.missing, ["action"]);
}

fn live_engine() -> GuardEngine {
    let content_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../content");
    GuardEngine::load_content(content_dir).expect("live content loads")
}

#[derive(Clone, Copy)]
struct ExpectedRawVerdict {
    decision: Decision,
    predicate: Option<&'static str>,
    rule: Option<&'static str>,
    halt_code: Option<&'static str>,
}

#[derive(Clone, Copy)]
struct ExpectedRawRoleBehavior {
    role: &'static str,
    write: ExpectedRawVerdict,
    integrate: ExpectedRawVerdict,
    dispatch_engineer: ExpectedRawVerdict,
}

const RAW_ALLOW: ExpectedRawVerdict = ExpectedRawVerdict {
    decision: Decision::Allow,
    predicate: None,
    rule: None,
    halt_code: None,
};
const RAW_IMPLEMENTER_WRITE_DENY: ExpectedRawVerdict = ExpectedRawVerdict {
    decision: Decision::Deny,
    predicate: Some("git-custody"),
    rule: Some("implementer-never-writes-git"),
    halt_code: Some("CODER-GIT-WRITE"),
};
const RAW_INTEGRATE_DENY: ExpectedRawVerdict = ExpectedRawVerdict {
    decision: Decision::Deny,
    predicate: Some("git-custody"),
    rule: Some("cross-lane-integration-is-root-exclusive"),
    halt_code: Some("TEAMMATE-GIT-WRITE"),
};
const RAW_LANE_LEAD_DISPATCH_DENY: ExpectedRawVerdict = ExpectedRawVerdict {
    decision: Decision::Deny,
    predicate: Some("dispatch-scope"),
    rule: Some("plan-authorship-and-gating-are-root-tier-exclusive"),
    halt_code: Some("WRONG-TIER-DISPATCH"),
};
const RAW_IMPLEMENTER_DISPATCH_DENY: ExpectedRawVerdict = ExpectedRawVerdict {
    decision: Decision::Deny,
    predicate: Some("dispatch-scope"),
    rule: Some("implementer-roles-never-dispatch"),
    halt_code: None,
};

const RAW_ROLE_TIER_BEHAVIOR: &[ExpectedRawRoleBehavior] = &[
    ExpectedRawRoleBehavior {
        role: "shepherd",
        write: RAW_ALLOW,
        integrate: RAW_ALLOW,
        dispatch_engineer: RAW_ALLOW,
    },
    ExpectedRawRoleBehavior {
        role: "planter",
        write: RAW_ALLOW,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_ALLOW,
    },
    ExpectedRawRoleBehavior {
        role: "conductor",
        write: RAW_ALLOW,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_LANE_LEAD_DISPATCH_DENY,
    },
    ExpectedRawRoleBehavior {
        role: "engineer",
        write: RAW_ALLOW,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_ALLOW,
    },
    ExpectedRawRoleBehavior {
        role: "critic",
        write: RAW_IMPLEMENTER_WRITE_DENY,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_IMPLEMENTER_DISPATCH_DENY,
    },
    ExpectedRawRoleBehavior {
        role: "coder",
        write: RAW_IMPLEMENTER_WRITE_DENY,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_IMPLEMENTER_DISPATCH_DENY,
    },
    ExpectedRawRoleBehavior {
        role: "auditor",
        write: RAW_IMPLEMENTER_WRITE_DENY,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_IMPLEMENTER_DISPATCH_DENY,
    },
    ExpectedRawRoleBehavior {
        role: "discovery",
        write: RAW_IMPLEMENTER_WRITE_DENY,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_IMPLEMENTER_DISPATCH_DENY,
    },
    ExpectedRawRoleBehavior {
        role: "worker",
        write: RAW_IMPLEMENTER_WRITE_DENY,
        integrate: RAW_INTEGRATE_DENY,
        dispatch_engineer: RAW_IMPLEMENTER_DISPATCH_DENY,
    },
];

fn assert_raw_verdict(
    role: &str,
    operation: &str,
    verdict: &Verdict,
    expected: ExpectedRawVerdict,
) {
    assert_eq!(
        verdict.decision, expected.decision,
        "{role} {operation} decision"
    );
    assert_eq!(
        verdict.predicate.as_deref(),
        expected.predicate,
        "{role} {operation} predicate"
    );
    assert_eq!(
        verdict.rule.as_deref(),
        expected.rule,
        "{role} {operation} rule"
    );
    assert_eq!(
        verdict.halt_code.as_deref(),
        expected.halt_code,
        "{role} {operation} halt code"
    );
}

#[test]
fn every_hardcoded_role_tier_has_exact_raw_tool_behavior() {
    let expected_roles: BTreeSet<_> = LIVE_ROLE_EXPECTATIONS
        .iter()
        .map(|expected| expected.role)
        .collect();
    let raw_roles: BTreeSet<_> = RAW_ROLE_TIER_BEHAVIOR
        .iter()
        .map(|expected| expected.role)
        .collect();
    assert_eq!(raw_roles, expected_roles, "raw tier coverage drift");

    let engine = live_engine();
    for expected in RAW_ROLE_TIER_BEHAVIOR {
        let write = evaluate(
            &engine,
            &object([
                ("role", GuardValue::from(expected.role)),
                ("tool_name", GuardValue::from("Bash")),
                (
                    "tool_input",
                    object([("command", GuardValue::from("git commit -m fixture"))]),
                ),
            ]),
        );
        assert_raw_verdict(expected.role, "write", &write, expected.write);

        let integrate = evaluate(
            &engine,
            &object([
                ("role", GuardValue::from(expected.role)),
                ("tool_name", GuardValue::from("Bash")),
                (
                    "tool_input",
                    object([("command", GuardValue::from("git rebase main"))]),
                ),
            ]),
        );
        assert_raw_verdict(expected.role, "integrate", &integrate, expected.integrate);

        let dispatch = evaluate(
            &engine,
            &object([
                ("role", GuardValue::from(expected.role)),
                ("tool_name", GuardValue::from("Agent")),
                (
                    "tool_input",
                    object([("target_role", GuardValue::from("engineer"))]),
                ),
            ]),
        );
        assert_raw_verdict(
            expected.role,
            "dispatch engineer",
            &dispatch,
            expected.dispatch_engineer,
        );
    }
}

#[test]
fn malformed_and_missing_normalized_fields_are_unresolved() {
    let engine = live_engine();
    let cases = [
        (
            GuardValue::Null,
            "request body is not a JSON object",
            vec!["body"],
        ),
        (
            object([]),
            "request carries neither `predicate` nor `tool_name`",
            vec!["predicate", "tool_name"],
        ),
        (
            object([
                ("predicate", GuardValue::Null),
                ("tool_name", GuardValue::from("Bash")),
            ]),
            "missing `predicate`",
            vec!["predicate"],
        ),
        (
            object([
                ("predicate", GuardValue::from("missing")),
                ("role", GuardValue::from("coder")),
                ("action", GuardValue::from("fs.write")),
            ]),
            "no such predicate `missing`",
            vec!["predicate"],
        ),
        (
            object([
                ("predicate", GuardValue::from("dedup-gate")),
                ("role", GuardValue::from("coder")),
            ]),
            "missing `action`",
            vec!["action"],
        ),
        (
            object([
                ("predicate", GuardValue::from("dedup-gate")),
                ("action", GuardValue::from("fs.write")),
            ]),
            "missing `role` -- cannot identify the acting role",
            vec!["role"],
        ),
        (
            object([
                ("predicate", GuardValue::from("dedup-gate")),
                ("role", GuardValue::from("coder")),
                ("action", GuardValue::from("fs.write")),
                ("context", GuardValue::Array(Vec::new())),
            ]),
            "`context` must be a JSON object",
            vec!["context"],
        ),
        (
            object([
                ("predicate", GuardValue::from("dedup-gate")),
                ("role", GuardValue::from("coder")),
                ("action", GuardValue::from("wrong.action")),
            ]),
            "predicate `dedup-gate` has no rule scoped to action `wrong.action`",
            Vec::new(),
        ),
    ];

    for (request, reason, missing) in cases {
        let verdict = evaluate(&engine, &request);
        assert_eq!(verdict.decision, Decision::Unresolved, "{reason}");
        assert_eq!(verdict.reason.as_deref(), Some(reason));
        assert_eq!(verdict.missing, missing);
    }
}

#[test]
fn raw_write_and_dispatch_tool_mappings_match_the_oracle() {
    let engine = live_engine();

    let critic_write = evaluate(
        &engine,
        &object([
            ("role", GuardValue::from("critic")),
            ("tool_name", GuardValue::from("Write")),
            ("tool_input", object([])),
        ]),
    );
    assert_eq!(critic_write.decision, Decision::Deny);
    assert_eq!(critic_write.predicate.as_deref(), Some("write-boundary"));
    assert_eq!(critic_write.rule.as_deref(), Some("role-write-eligibility"));
    assert_eq!(critic_write.halt_code, None);

    for role in ["coder", "discovery"] {
        let verdict = evaluate(
            &engine,
            &object([
                ("role", GuardValue::from(role)),
                ("tool_name", GuardValue::from("apply_patch")),
            ]),
        );
        assert_eq!(verdict.decision, Decision::Unresolved, "{role}");
        assert_eq!(verdict.missing, ["dispatch.path_in_write_scope"], "{role}");
    }

    let scoped_write = |role: &'static str, in_scope: bool| {
        evaluate(
            &engine,
            &object([
                ("role", GuardValue::from(role)),
                ("tool_name", GuardValue::from("Write")),
                (
                    "tool_input",
                    object([(
                        "file_path",
                        GuardValue::from("crates/core/src/dispatch/identity.rs"),
                    )]),
                ),
                (
                    "dispatch",
                    object([
                        ("schema", GuardValue::from("shepherd.identity-resolution/1")),
                        ("role", GuardValue::from(role)),
                        (
                            "write_paths",
                            GuardValue::Array(vec![GuardValue::from(
                                "crates/core/src/dispatch/identity.rs",
                            )]),
                        ),
                        ("path_in_write_scope", GuardValue::from(in_scope)),
                    ]),
                ),
            ]),
        )
    };
    assert_eq!(scoped_write("coder", true).decision, Decision::Allow);
    let outside = scoped_write("coder", false);
    assert_eq!(outside.decision, Decision::Deny);
    assert_eq!(outside.predicate.as_deref(), Some("write-boundary"));
    assert_eq!(outside.rule.as_deref(), Some("path-in-declared-scope"));
    assert_eq!(scoped_write("discovery", true).decision, Decision::Allow);

    let conductor_to_engineer = evaluate(
        &engine,
        &object([
            ("role", GuardValue::from("conductor")),
            ("tool_name", GuardValue::from("Agent")),
            (
                "tool_input",
                object([
                    ("subagent_type", GuardValue::from("")),
                    ("target_role", GuardValue::from("engineer")),
                ]),
            ),
        ]),
    );
    assert_eq!(conductor_to_engineer.decision, Decision::Deny);
    assert_eq!(
        conductor_to_engineer.rule.as_deref(),
        Some("plan-authorship-and-gating-are-root-tier-exclusive")
    );
    assert_eq!(
        conductor_to_engineer.halt_code.as_deref(),
        Some("WRONG-TIER-DISPATCH")
    );

    let root_to_engineer = evaluate(
        &engine,
        &object([
            ("role", GuardValue::from("shepherd")),
            ("tool_name", GuardValue::from("Workflow")),
            (
                "tool_input",
                object([("role", GuardValue::from("engineer"))]),
            ),
        ]),
    );
    assert_eq!(root_to_engineer.decision, Decision::Allow);

    let missing_target = evaluate(
        &engine,
        &object([
            ("role", GuardValue::from("shepherd")),
            ("tool_name", GuardValue::from("Agent")),
            ("tool_input", object([])),
        ]),
    );
    assert_eq!(missing_target.decision, Decision::Unresolved);
    assert_eq!(missing_target.missing, ["tool_input.subagent_type"]);
}

#[test]
fn malformed_raw_tool_calls_are_unresolved_but_empty_bash_allows() {
    let engine = live_engine();

    for request in [
        object([("tool_name", GuardValue::Null)]),
        object([
            ("tool_name", GuardValue::from("Bash")),
            ("tool_input", GuardValue::from("not-an-object")),
        ]),
        object([("tool_name", GuardValue::from("UnknownTool"))]),
    ] {
        assert_eq!(evaluate(&engine, &request).decision, Decision::Unresolved);
    }

    for request in [
        object([
            ("tool_name", GuardValue::from("Bash")),
            ("role", GuardValue::from("coder")),
        ]),
        object([
            ("role", GuardValue::from("coder")),
            ("tool_name", GuardValue::from("Bash")),
            ("tool_input", object([("command", GuardValue::Integer(42))])),
        ]),
    ] {
        assert_eq!(evaluate(&engine, &request).decision, Decision::Allow);
    }
}

#[test]
fn round_four_raw_shape_validation_precedes_role_consumption() {
    let engine = live_engine();

    // Literal outputs are pinned guard-wire bytes.
    for (request, expected) in [
        (
            r#"{"role":false,"tool_name":null}"#,
            r#"{"decision": "unresolved", "reason": "missing `tool_name`", "missing": ["tool_name"]}"#,
        ),
        (
            r#"{"role":false,"tool_name":"Bash","tool_input":"bad"}"#,
            r#"{"decision": "unresolved", "reason": "`tool_input` must be a JSON object", "missing": ["tool_input"]}"#,
        ),
        (
            r#"{"role":false,"tool_name":"UnknownTool"}"#,
            r#"{"decision": "unresolved", "reason": "no (predicate, action) mapping known for tool `UnknownTool`", "missing": ["tool_name mapping"]}"#,
        ),
    ] {
        let verdict = engine
            .evaluate_json(request)
            .expect("malformed raw roles produce verdicts, not engine errors");
        assert_eq!(verdict.to_wire_json(), expected, "{request}");
    }
}

#[test]
fn round_four_safe_and_read_only_bash_allow_without_role() {
    let engine = live_engine();

    for request in [
        r#"{"tool_name":"Bash","tool_input":{"command":"printf safe"}}"#,
        r#"{"tool_name":"Bash","tool_input":{"command":"git status"}}"#,
        r#"{"role":null,"tool_name":"Bash","tool_input":{"command":"git log"}}"#,
        r#"{"role":false,"tool_name":"Bash","tool_input":{"command":""}}"#,
    ] {
        let verdict = engine
            .evaluate_json(request)
            .expect("role-free Bash classification produces a verdict");
        assert_eq!(
            verdict.to_wire_json(),
            r#"{"decision": "allow"}"#,
            "{request}"
        );
    }
}

#[test]
fn round_four_raw_non_string_role_is_oracle_unresolved_for_role_consuming_tools() {
    let engine = live_engine();

    for (request, expected) in [
        (
            r#"{"role":false,"tool_name":"Write"}"#,
            r#"{"decision": "unresolved", "reason": "unknown role `False`", "missing": ["role_facts"]}"#,
        ),
        (
            r#"{"role":false,"tool_name":"Bash","tool_input":{"command":"git commit -m x"}}"#,
            r#"{"decision": "unresolved", "reason": "unknown role `False`", "missing": ["role"]}"#,
        ),
        (
            r#"{"role":false,"tool_name":"Agent","tool_input":{"subagent_type":"coder"}}"#,
            r#"{"decision": "unresolved", "reason": "unknown role `False`", "missing": ["role"]}"#,
        ),
        (
            r#"{"role":false,"tool_name":"Agent","tool_input":{}}"#,
            r#"{"decision": "unresolved", "reason": "cannot determine the dispatch target role from `tool_input`", "missing": ["tool_input.subagent_type"]}"#,
        ),
    ] {
        let verdict = engine
            .evaluate_json(request)
            .expect("a non-string role is recoverable raw input");
        assert_eq!(verdict.to_wire_json(), expected, "{request}");
    }
}

#[test]
fn compatibility_raw_missing_or_null_role_is_unresolved_when_role_is_consumed() {
    let engine = live_engine();

    for (request, expected) in [
        (
            r#"{"tool_name":"Write"}"#,
            r#"{"decision": "unresolved", "reason": "missing `role` -- cannot identify the acting role", "missing": ["role"]}"#,
        ),
        (
            r#"{"role":null,"tool_name":"Bash","tool_input":{"command":"git push"}}"#,
            r#"{"decision": "unresolved", "reason": "missing `role` -- cannot identify the acting role", "missing": ["role"]}"#,
        ),
        (
            r#"{"tool_name":"Workflow","tool_input":{"target_role":"coder"}}"#,
            r#"{"decision": "unresolved", "reason": "missing `role` -- cannot identify the dispatching role", "missing": ["role"]}"#,
        ),
    ] {
        let verdict = engine
            .evaluate_json(request)
            .expect("missing role remains an unresolved verdict");
        assert_eq!(verdict.to_wire_json(), expected, "{request}");
    }
}

#[test]
fn tokenizer_matches_global_option_wrapper_fallback_and_depth_edges() {
    assert_eq!(
        extract_git_subcommands(
            "git --git-dir /tmp --work-tree /tmp -c x=y --namespace ns --exec-path p --config-env foo=ENV --super-prefix sp commit"
        ),
        ["commit"]
    );
    assert_eq!(
        extract_git_subcommands("git --git-dir=/tmp --work-tree=/tmp --no-pager push"),
        ["push"]
    );
    assert_eq!(
        extract_git_subcommands("env bash -c 'git push'"),
        ["push", "push"],
        "the wrapper's duplicate recursion is oracle behavior"
    );
    assert_eq!(
        extract_git_subcommands("xargs sh -c 'git reset'"),
        ["reset", "reset"]
    );
    assert_eq!(
        extract_git_subcommands("/opt/git status | /usr/bin/git log"),
        ["status", "log"]
    );

    fn wrapped(mut command: String, count: usize) -> String {
        for _ in 0..count {
            let escaped = command.replace('\\', "\\\\").replace('"', "\\\"");
            command = format!("bash -c \"{escaped}\"");
        }
        command
    }

    assert_eq!(
        extract_git_subcommands(&wrapped("git commit".into(), 6)),
        ["commit"]
    );
    assert!(
        extract_git_subcommands(&wrapped("git commit".into(), 7)).is_empty(),
        "depth seven exceeds the oracle's `depth > 6` cutoff"
    );
}

#[test]
fn compatibility_shell_whitespace_is_space_tab_cr_lf_only() {
    // These fixtures pin the compatibility shell splitter's whitespace set.
    for command in ["git commit", "git\tcommit", "git\rcommit", "git\ncommit"] {
        assert_eq!(extract_git_subcommands(command), ["commit"], "{command:?}");
    }

    for command in [
        "git\u{00a0}commit",
        "git\u{000b}commit",
        "git\u{000c}commit",
    ] {
        assert!(
            extract_git_subcommands(command).is_empty(),
            "NBSP, VT, and FF are token content in the pinned shell splitter: {command:?}"
        );
    }
}

#[test]
fn compatibility_unterminated_quote_falls_back_to_whitespace_splitting() {
    assert_eq!(
        extract_git_subcommands("git \"unterminated"),
        ["\"unterminated"],
        "malformed shell text falls back to whitespace splitting"
    );
}

#[test]
fn empty_and_malformed_predicate_content_returns_typed_errors() {
    let empty = parse_predicate_toml("empty.toml", "").expect_err("empty has no predicate id");
    assert_eq!(empty.to_string(), "empty.toml: missing [predicate].id");

    let malformed =
        parse_predicate_toml("broken.toml", "[predicate\nid = 1").expect_err("invalid TOML fails");
    assert!(
        malformed
            .to_string()
            .starts_with("broken.toml: malformed TOML:")
    );

    let missing_effect = parse_predicate_toml(
        "missing-effect.toml",
        r#"
[predicate]
id = "broken"
[[rule]]
id = "r"
subject = "x"
action = "x"
"#,
    )
    .expect_err("a typed rule requires its effect");
    assert_eq!(
        missing_effect.to_string(),
        "missing-effect.toml: rule #1 missing string `effect`"
    );
}

#[test]
fn predicate_toml_rejects_an_empty_predicate_id() {
    let error = parse_predicate_toml("empty-id.toml", "[predicate]\nid = \"\"\n")
        .expect_err("an empty predicate id is invalid in the guard contract");

    assert_eq!(error.to_string(), "empty-id.toml: missing [predicate].id");
}

#[test]
fn malformed_role_content_returns_typed_errors() {
    assert_eq!(
        parse_role_markdown("none.md", "# no frontmatter")
            .expect_err("frontmatter is required")
            .to_string(),
        "none.md: missing YAML frontmatter"
    );
    assert_eq!(
        parse_role_markdown("missing.md", "---\nwrite_eligible: false\n---")
            .expect_err("role id is required")
            .to_string(),
        "missing.md: missing `role:` in frontmatter"
    );
    assert_eq!(
        parse_role_markdown("bad.md", "---\nrole: coder\ncapabilities: write\n---")
            .expect_err("capabilities must be typed")
            .to_string(),
        "bad.md: `capabilities` must be an inline string array"
    );
}

#[test]
fn role_frontmatter_rejects_unsupported_block_capability_sequences() {
    let error = parse_role_markdown(
        "block.md",
        "---\nrole: coder\ncapabilities:\n  - read\n  - search\n---",
    )
    .expect_err("the portable grammar does not accept YAML block sequences");

    assert_eq!(
        error.to_string(),
        "block.md: `capabilities` must be an inline string array; block sequences are unsupported"
    );
}

#[test]
fn role_frontmatter_rejects_commas_inside_quoted_capabilities() {
    let error = parse_role_markdown(
        "quoted-comma.md",
        "---\nrole: coder\ncapabilities: [\"read,search\", report-write]\n---",
    )
    .expect_err("a quoted comma cannot be represented by the portable subset");

    assert_eq!(
        error.to_string(),
        "quoted-comma.md: `capabilities` does not support commas inside quoted items"
    );
}

#[test]
fn role_frontmatter_rejects_double_quoted_unicode_escape_role() {
    let error = parse_role_markdown(
        "unicode-role.md",
        r#"---
role: "\u0063oder"
capabilities: [read]
---"#,
    )
    .expect_err("the portable subset does not decode YAML Unicode escapes");

    assert_eq!(
        error.to_string(),
        "unicode-role.md: `role` does not support YAML escape sequences"
    );
}

#[test]
fn role_frontmatter_rejects_double_quoted_unicode_escape_capability() {
    let error = parse_role_markdown(
        "unicode-capability.md",
        r#"---
role: coder
capabilities: ["\u0072ead"]
---"#,
    )
    .expect_err("the portable subset does not decode YAML Unicode escapes");

    assert_eq!(
        error.to_string(),
        "unicode-capability.md: `capabilities` does not support YAML escape sequences"
    );
}

#[test]
fn role_frontmatter_rejects_trailing_comma_empty_capability() {
    let error = parse_role_markdown(
        "trailing-capability.md",
        "---\nrole: coder\ncapabilities: [read,]\n---",
    )
    .expect_err("the portable subset rejects an empty array item");

    assert_eq!(
        error.to_string(),
        "trailing-capability.md: `capabilities` does not support empty items"
    );
}

#[test]
fn role_frontmatter_rejects_falsy_non_string_role() {
    let error = parse_role_markdown(
        "false-role.md",
        "---\nrole: false\ncapabilities: [read]\n---",
    )
    .expect_err("YAML false is not a role string");

    assert_eq!(
        error.to_string(),
        "false-role.md: `role` must be a non-empty string"
    );
}

#[test]
fn role_frontmatter_rejects_every_yaml_1_1_implicit_word() {
    for literal in ["yes", "no", "true", "false", "on", "off", "null"] {
        let source = format!("---\nrole: {literal}\n---");
        let error = parse_role_markdown("implicit-role.md", &source)
            .expect_err("an unquoted YAML 1.1 typed word is not a string");

        assert_eq!(
            error.to_string(),
            "implicit-role.md: `role` must be a non-empty string",
            "{literal}"
        );
    }
}

#[test]
fn role_frontmatter_rejects_unquoted_yaml_no_boolean() {
    let error = parse_role_markdown("no-role.md", "---\nrole: no\n---")
        .expect_err("PyYAML resolves unquoted `no` to false");

    assert_eq!(
        error.to_string(),
        "no-role.md: `role` must be a non-empty string"
    );
}

#[test]
fn role_frontmatter_rejects_unquoted_yaml_off_boolean() {
    let error = parse_role_markdown("off-role.md", "---\nrole: off\n---")
        .expect_err("PyYAML resolves unquoted `off` to false");

    assert_eq!(
        error.to_string(),
        "off-role.md: `role` must be a non-empty string"
    );
}

#[test]
fn role_frontmatter_rejects_unquoted_yaml_zero_integer() {
    let error = parse_role_markdown("zero-role.md", "---\nrole: 0\n---")
        .expect_err("PyYAML resolves unquoted `0` to an integer");

    assert_eq!(
        error.to_string(),
        "zero-role.md: `role` must be a non-empty string"
    );
}

#[test]
fn role_frontmatter_rejects_unquoted_yaml_signed_integer() {
    let error = parse_role_markdown("signed-role.md", "---\nrole: -7\n---")
        .expect_err("PyYAML resolves an unquoted signed number to an integer");

    assert_eq!(
        error.to_string(),
        "signed-role.md: `role` must be a non-empty string"
    );
}

#[test]
fn role_frontmatter_rejects_unquoted_yaml_float() {
    let error = parse_role_markdown("float-role.md", "---\nrole: 1.5\n---")
        .expect_err("PyYAML resolves an unquoted decimal to a float");

    assert_eq!(
        error.to_string(),
        "float-role.md: `role` must be a non-empty string"
    );
}

#[test]
fn role_frontmatter_rejects_unterminated_double_quote() {
    let error = parse_role_markdown("double-quote.md", "---\nrole: \"unterminated\n---")
        .expect_err("PyYAML rejects an unterminated double-quoted scalar");

    assert_eq!(
        error.to_string(),
        "double-quote.md: `role` contains an unterminated quoted item"
    );
}

#[test]
fn role_frontmatter_rejects_unterminated_single_quote() {
    let error = parse_role_markdown("single-quote.md", "---\nrole: 'unterminated\n---")
        .expect_err("PyYAML rejects an unterminated single-quoted scalar");

    assert_eq!(
        error.to_string(),
        "single-quote.md: `role` contains an unterminated quoted item"
    );
}

#[test]
fn role_frontmatter_decodes_yaml_single_quote_doubling() {
    let fact = parse_role_markdown("quoted-role.md", "---\nrole: 'cod''er'\n---")
        .expect("the supported single-quoted grammar decodes exactly");

    assert_eq!(fact.role, "cod'er");
}

#[test]
fn role_frontmatter_rejects_typed_capability_items() {
    let error = parse_role_markdown(
        "typed-capabilities.md",
        "---\nrole: coder\ncapabilities: [true, null, 42]\n---",
    )
    .expect_err("PyYAML resolves these items to bool, null, and integer values");

    assert_eq!(
        error.to_string(),
        "typed-capabilities.md: `capabilities` must contain only strings"
    );
}

#[test]
fn role_frontmatter_accepts_quoted_scalar_lookalikes_as_strings() {
    for (literal, expected) in [
        ("\"no\"", "no"),
        ("'off'", "off"),
        ("\"0\"", "0"),
        ("'-7'", "-7"),
        ("\"+7\"", "+7"),
        ("'1.5'", "1.5"),
    ] {
        let source = format!("---\nrole: {literal}\n---");
        let fact = parse_role_markdown("quoted-scalar.md", &source)
            .expect("quoted scalar lookalikes are YAML strings");

        assert_eq!(fact.role, expected, "{literal}");
    }
}

#[test]
fn role_frontmatter_accepts_quoted_capability_lookalikes_as_strings() {
    let fact = parse_role_markdown(
        "quoted-capabilities.md",
        "---\nrole: coder\ncapabilities: [\"true\", 'null', \"42\"]\n---",
    )
    .expect("quoted capability lookalikes are YAML strings");

    assert_eq!(fact.capabilities, ["true", "null", "42"]);
}

#[test]
fn round_four_role_frontmatter_rejects_glued_hash_after_role() {
    let error = parse_role_markdown("glued-role.md", "---\nrole: coder#comment\n---")
        .expect_err("an unseparated hash is scalar content, not a closed-subset comment");

    assert!(error.to_string().contains("comment marker"));
}

#[test]
fn round_four_role_frontmatter_rejects_glued_hash_after_write_eligible() {
    let error = parse_role_markdown(
        "glued-write.md",
        "---\nrole: coder\nwrite_eligible: false#comment\n---",
    )
    .expect_err("PyYAML types the glued value as a string, not a boolean");

    assert!(error.to_string().contains("comment marker"));
}

#[test]
fn round_four_role_frontmatter_rejects_glued_hash_after_branch_eligible() {
    let error = parse_role_markdown(
        "glued-branch.md",
        "---\nrole: coder\nbranch_eligible: false#comment\n---",
    )
    .expect_err("unsupported fields must not hide malformed YAML lexical forms");

    assert!(error.to_string().contains("comment marker"));
}

#[test]
fn round_four_role_frontmatter_rejects_glued_hash_after_capabilities() {
    let error = parse_role_markdown(
        "glued-capabilities.md",
        "---\nrole: coder\ncapabilities: [read]#comment\n---",
    )
    .expect_err("the closed subset requires comment separation after an inline array");

    assert!(error.to_string().contains("comment marker"));
}

#[test]
fn round_four_role_frontmatter_requires_mapping_value_separation() {
    let error = parse_role_markdown("unseparated-mapping.md", "---\nrole:coder\n---")
        .expect_err("PyYAML treats `role:coder` as a scalar, not a mapping");

    assert!(error.to_string().contains("mapping separator"));
}

#[test]
fn round_four_role_frontmatter_rejects_tab_indentation() {
    let error = parse_role_markdown("tab-indent.md", "---\n\trole: coder\n---")
        .expect_err("PyYAML rejects a tab at the start of a mapping line");

    assert!(error.to_string().contains("tab"));
}

#[test]
fn round_four_role_frontmatter_rejects_tab_after_mapping_colon() {
    let error = parse_role_markdown("tab-separator.md", "---\nrole:\tcoder\n---")
        .expect_err("PyYAML rejects a tab as the mapping-value separator");

    assert!(error.to_string().contains("tab"));
}

#[test]
fn round_four_role_frontmatter_comments_require_space_and_stay_literal_in_quotes() {
    let fact = parse_role_markdown(
        "separated-comments.md",
        "---\nrole: 'coder#literal' # comment\nwrite_eligible: true # comment\ncapabilities: [\"read#literal\", shell] # comment\n---",
    )
    .expect("a separated hash is a comment and quoted hashes remain string content");

    assert_eq!(fact.role, "coder#literal");
    assert!(fact.write_eligible);
    assert_eq!(fact.capabilities, ["read#literal", "shell"]);
}

#[test]
fn conflicting_singleton_halt_codes_reject_the_corpus() {
    let predicate = parse_predicate_toml(
        "conflict.toml",
        r#"
[predicate]
id = "conflict"
[[rule]]
id = "hit"
description = "hit"
subject = "registry"
action = "fs.write"
effect = "deny_if_hit_without_justification"
[[example]]
name = "one"
kind = "deny"
role = "coder"
action = "fs.write"
context = { dedup_hit = true }
result = "deny"
halt_code = "ONE"
[[example]]
name = "two"
kind = "deny"
role = "coder"
action = "fs.write"
context = { dedup_hit = true }
result = "deny"
halt_code = "TWO"
"#,
    )
    .expect("fixture parses");

    let error = GuardEngine::new(vec![predicate], Vec::new()).expect_err("codes conflict");
    assert!(error.to_string().contains("ambiguous halt code"));
    assert!(error.to_string().contains("ONE"));
    assert!(error.to_string().contains("TWO"));
}

#[test]
fn unsupported_effect_becomes_an_unresolved_verdict() {
    let predicate = parse_predicate_toml(
        "unsupported.toml",
        r#"
[predicate]
id = "unsupported"
[[rule]]
id = "unknown"
description = "unknown"
subject = "x"
action = "x"
effect = "not_a_real_effect"
"#,
    )
    .expect("fixture parses");
    let engine = GuardEngine::new(vec![predicate], Vec::new()).expect("no examples to harvest");
    let verdict = evaluate(
        &engine,
        &object([
            ("predicate", GuardValue::from("unsupported")),
            ("role", GuardValue::from("coder")),
            ("action", GuardValue::from("x")),
        ]),
    );

    assert_eq!(verdict.decision, Decision::Unresolved);
    assert_eq!(
        verdict.reason.as_deref(),
        Some("no handler for effect `not_a_real_effect` (predicate `unsupported`, rule `unknown`)")
    );
    assert!(verdict.missing.is_empty());
}

#[test]
fn malformed_json_is_an_engine_error_not_a_verdict() {
    let error = live_engine()
        .evaluate_json("not valid json{")
        .expect_err("wire text is malformed");
    assert!(error.to_string().starts_with("malformed JSON:"));
}
