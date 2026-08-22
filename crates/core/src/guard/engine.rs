/*
    Appellation: guard-engine <module>
    Created At: 2026.08.14:00:00:00
    Contrib: @FL03
*/
//! Pure request mapping and predicate evaluation.

use alloc::{
    collections::BTreeMap,
    format,
    string::{String, ToString},
    vec::Vec,
};

use super::{
    GuardError, GuardValue, PredicateDoc, RoleFact, Rule, Verdict, extract_git_subcommands,
};

type Context = BTreeMap<String, GuardValue>;
type HaltTable = BTreeMap<(String, String), Option<String>>;

const WRITE_TOOL_NAMES: &[&str] = &["Write", "Edit", "apply_patch"];
const DISPATCH_TOOL_NAMES: &[&str] = &["Agent", "Workflow"];
const GIT_INTEGRATE_VERBS: &[&str] = &["rebase", "merge", "cherry-pick", "worktree"];
const GIT_ALL_WRITE_VERBS: &[&str] = &[
    "add",
    "rm",
    "mv",
    "commit",
    "commit-tree",
    "merge",
    "merge-file",
    "merge-index",
    "rebase",
    "reset",
    "restore",
    "checkout",
    "checkout-index",
    "switch",
    "stash",
    "clean",
    "cherry-pick",
    "revert",
    "push",
    "pull",
    "fetch",
    "clone",
    "init",
    "gc",
    "prune",
    "repack",
    "apply",
    "am",
    "worktree",
    "remote",
    "tag",
    "branch",
    "config",
    "notes",
    "submodule",
    "update-ref",
    "update-index",
    "update-server-info",
    "replace",
    "filter-branch",
    "filter-repo",
    "fast-import",
    "sparse-checkout",
    "bisect",
    "format-patch",
    "request-pull",
    "write-tree",
    "hash-object",
    "symbolic-ref",
    "read-tree",
    "reflog",
    "send-pack",
    "receive-pack",
    "http-push",
    "http-fetch",
    "credential",
    "maintenance",
    "mergetool",
    "difftool",
    "commit-graph",
    "multi-pack-index",
    "pack-refs",
    "mktree",
    "mktag",
    "pack-objects",
    "unpack-objects",
    "prune-packed",
    "fsck",
];

/// A loaded predicate corpus and its role facts.
#[derive(Clone, Debug)]
pub struct GuardEngine {
    predicates: BTreeMap<String, PredicateDoc>,
    role_facts: BTreeMap<String, RoleFact>,
    halt_table: HaltTable,
}

impl GuardEngine {
    /// Build an engine from already parsed, caller-owned content.
    pub fn new(
        predicates: Vec<PredicateDoc>,
        role_facts: Vec<RoleFact>,
    ) -> Result<Self, GuardError> {
        let predicates: BTreeMap<_, _> = predicates
            .into_iter()
            .map(|predicate| (predicate.id.clone(), predicate))
            .collect();
        let role_facts: BTreeMap<_, _> = role_facts
            .into_iter()
            .map(|fact| (fact.role.clone(), fact))
            .collect();
        let halt_table = harvest_halt_codes(&predicates, &role_facts)?;

        Ok(Self {
            predicates,
            role_facts,
            halt_table,
        })
    }

    /// Evaluate a normalized request or raw tool call.
    ///
    /// Raw calls validate and classify `tool_name` and `tool_input` before a
    /// mapped operation consumes `role`. Bash command shape is always required;
    /// opaque effects under native dispatch facts fail closed without trying to
    /// infer filesystem targets from shell text.
    ///
    /// # Errors
    ///
    /// Request-shape defects are verdicts rather than engine errors. The result
    /// boundary is retained for unrecoverable typed-engine failures.
    pub fn evaluate(&self, request: &GuardValue) -> Result<Verdict, GuardError> {
        let GuardValue::Object(payload) = request else {
            return Ok(Verdict::unresolved(
                "request body is not a JSON object",
                &["body"],
            ));
        };

        if payload.contains_key("predicate") {
            return Ok(self.evaluate_normalized(payload));
        }

        if payload.contains_key("tool_name") {
            Ok(self.evaluate_tool_call(payload))
        } else {
            Ok(Verdict::unresolved(
                "request carries neither `predicate` nor `tool_name`",
                &["predicate", "tool_name"],
            ))
        }
    }

    /// The parsed predicate identified by `id`.
    pub fn predicate(&self, id: &str) -> Option<&PredicateDoc> {
        self.predicates.get(id)
    }

    /// Iterate over loaded predicates in stable identifier order.
    pub fn predicates(&self) -> impl Iterator<Item = (&str, &PredicateDoc)> {
        self.predicates
            .iter()
            .map(|(id, predicate)| (id.as_str(), predicate))
    }

    /// The parsed role identified by `id`.
    pub fn role_fact(&self, id: &str) -> Option<&RoleFact> {
        self.role_facts.get(id)
    }

    fn evaluate_normalized(&self, payload: &Context) -> Verdict {
        let predicate_id = payload.get("predicate").and_then(GuardValue::as_str);
        let Some(predicate_id) = predicate_id.filter(|value| !value.is_empty()) else {
            return Verdict::unresolved("missing `predicate`", &["predicate"]);
        };
        if !self.predicates.contains_key(predicate_id) {
            return Verdict::unresolved(
                format!("no such predicate `{predicate_id}`"),
                &["predicate"],
            );
        }
        let action = payload.get("action").and_then(GuardValue::as_str);
        let Some(action) = action.filter(|value| !value.is_empty()) else {
            return Verdict::unresolved("missing `action`", &["action"]);
        };
        let Some(role) = payload.get("role").filter(|value| !value.is_null()) else {
            return Verdict::unresolved(
                "missing `role` -- cannot identify the acting role",
                &["role"],
            );
        };
        let context = match payload.get("context") {
            None | Some(GuardValue::Null) => BTreeMap::new(),
            Some(GuardValue::Object(context)) => context.clone(),
            Some(_) => {
                return Verdict::unresolved("`context` must be a JSON object", &["context"]);
            }
        };

        self.decide(predicate_id, action, role, &context)
    }

    fn evaluate_tool_call(&self, payload: &Context) -> Verdict {
        let tool_name = payload.get("tool_name").and_then(GuardValue::as_str);
        let Some(tool_name) = tool_name.filter(|value| !value.is_empty()) else {
            return Verdict::unresolved("missing `tool_name`", &["tool_name"]);
        };
        let empty = BTreeMap::new();
        let tool_input = match payload.get("tool_input") {
            None | Some(GuardValue::Null) => &empty,
            Some(GuardValue::Object(value)) => value,
            Some(_) => {
                return Verdict::unresolved("`tool_input` must be a JSON object", &["tool_input"]);
            }
        };
        let role = payload.get("role");
        if WRITE_TOOL_NAMES.contains(&tool_name) {
            self.evaluate_write_tool(role, tool_input, payload.get("dispatch"))
        } else if tool_name == "Bash" {
            self.evaluate_bash_tool(role, tool_input, payload.get("dispatch"))
        } else if DISPATCH_TOOL_NAMES.contains(&tool_name) {
            self.evaluate_dispatch_tool(role, tool_input, tool_name)
        } else {
            Verdict::unresolved(
                format!("no (predicate, action) mapping known for tool `{tool_name}`"),
                &["tool_name mapping"],
            )
        }
    }

    fn evaluate_write_tool(
        &self,
        role: Option<&GuardValue>,
        tool_input: &Context,
        dispatch: Option<&GuardValue>,
    ) -> Verdict {
        let Some(role) = role.filter(|value| !value.is_null()) else {
            return Verdict::unresolved(
                "missing `role` -- cannot identify the acting role",
                &["role"],
            );
        };
        let fact = role
            .as_str()
            .and_then(|role_name| self.role_facts.get(role_name));
        let Some(fact) = fact else {
            return Verdict::unresolved(
                format!("unknown role `{}`", compatibility_display(role)),
                &["role_facts"],
            );
        };
        if !fact.permits_structured_write() && !fact.has_capability("report-write") {
            return Verdict::deny(
                "write-boundary",
                "role-write-eligibility",
                None,
                "role holds no write capability at all",
            );
        }
        let Some(GuardValue::Object(dispatch)) = dispatch else {
            return Verdict::unresolved(
                "native dispatch write-scope resolution is missing",
                &["dispatch.path_in_write_scope"],
            );
        };
        if dispatch.get("schema").and_then(GuardValue::as_str)
            != Some("shepherd.identity-resolution/1")
            || dispatch.get("role").and_then(GuardValue::as_str) != role.as_str()
        {
            return Verdict::unresolved(
                "native dispatch resolution does not match the acting role",
                &["dispatch.schema", "dispatch.role"],
            );
        }
        let write_paths = match dispatch.get("write_paths") {
            Some(GuardValue::Array(paths))
                if !paths.is_empty()
                    && paths
                        .iter()
                        .all(|path| path.as_str().is_some_and(|path| !path.is_empty())) =>
            {
                paths
            }
            _ => {
                return Verdict::unresolved(
                    "native dispatch resolution contains no validated write paths",
                    &["dispatch.write_paths"],
                );
            }
        };
        let path_in_scope = match dispatch.get("path_in_write_scope") {
            Some(GuardValue::Bool(value)) => *value,
            _ => {
                return Verdict::unresolved(
                    "native dispatch resolution contains no write-scope fact",
                    &["dispatch.path_in_write_scope"],
                );
            }
        };
        if !fact.permits_structured_write() && fact.has_capability("report-write") {
            let report_path = match dispatch.get("write_scope") {
                Some(GuardValue::Array(scope)) if scope.len() == 1 => {
                    scope[0].as_str().filter(|path| {
                        !path.is_empty()
                            && !path
                                .chars()
                                .any(|character| matches!(character, '*' | '?' | '[' | ']'))
                    })
                }
                _ => None,
            };
            let Some(report_path) = report_path else {
                return Verdict::unresolved(
                    "report-write requires one exact dispatch-declared output path",
                    &["dispatch.write_scope"],
                );
            };
            if write_paths.len() != 1 || write_paths[0].as_str() != Some(report_path) {
                return Verdict::unresolved(
                    "report-write target does not match its one declared output path",
                    &["dispatch.write_scope", "dispatch.write_paths"],
                );
            }
        }
        if let Some(path) = ["file_path", "path"]
            .into_iter()
            .find_map(|key| tool_input.get(key).and_then(GuardValue::as_str))
            .filter(|path| !path.starts_with('/'))
            && !write_paths
                .iter()
                .any(|resolved| resolved.as_str() == Some(path))
        {
            return Verdict::unresolved(
                "native dispatch write paths do not match the tool target",
                &["dispatch.write_paths"],
            );
        }
        let effective_write_eligibility =
            fact.permits_structured_write() || fact.has_capability("report-write");
        self.decide(
            "write-boundary",
            "fs.write",
            role,
            &BTreeMap::from([
                (
                    String::from("write_eligible"),
                    GuardValue::from(effective_write_eligibility),
                ),
                (
                    String::from("path_in_dispatch_write_scope"),
                    GuardValue::from(path_in_scope),
                ),
            ]),
        )
    }

    fn evaluate_bash_tool(
        &self,
        role: Option<&GuardValue>,
        tool_input: &Context,
        dispatch: Option<&GuardValue>,
    ) -> Verdict {
        let Some(command) = tool_input
            .get("command")
            .and_then(GuardValue::as_str)
            .filter(|command| !command.is_empty())
        else {
            return Verdict::unresolved(
                "missing or invalid Bash `command`",
                &["tool_input.command"],
            );
        };

        let bounded_dispatch = match dispatch {
            None | Some(GuardValue::Null) => false,
            Some(GuardValue::Object(native)) => {
                let Some(role) = role.filter(|value| !value.is_null()) else {
                    return Verdict::unresolved(
                        "missing `role` -- cannot identify the acting role",
                        &["role"],
                    );
                };
                let Some(role_name) = role.as_str() else {
                    return Verdict::unresolved(
                        format!("unknown role `{}`", compatibility_display(role)),
                        &["role"],
                    );
                };
                if native.get("schema").and_then(GuardValue::as_str)
                    != Some("shepherd.identity-resolution/1")
                    || native.get("role").and_then(GuardValue::as_str) != Some(role_name)
                {
                    return Verdict::unresolved(
                        "native dispatch resolution does not match the acting role",
                        &["dispatch.schema", "dispatch.role"],
                    );
                }
                if !self.role_facts.contains_key(role_name) {
                    return Verdict::unresolved(
                        format!("unknown role `{role_name}`"),
                        &["role_facts"],
                    );
                }
                let has_child_agent_id = match native.get("agent_id") {
                    Some(GuardValue::Null) => false,
                    Some(GuardValue::String(value)) if !value.is_empty() => true,
                    _ => {
                        return Verdict::unresolved(
                            "native dispatch `agent_id` must be null or a non-empty string",
                            &["dispatch.agent_id"],
                        );
                    }
                };
                let has_named_lane = match native.get("lane") {
                    Some(GuardValue::Null) => false,
                    Some(GuardValue::String(value)) if !value.is_empty() => true,
                    _ => {
                        return Verdict::unresolved(
                            "native dispatch `lane` must be null or a non-empty string",
                            &["dispatch.lane"],
                        );
                    }
                };
                // Complete root facts validate identity; they do not make an
                // opaque shell effect fit the root's structured `*.md` scope.
                if !has_child_agent_id && !has_named_lane && role_name == "shepherd" {
                    let root_mode = native
                        .get("mode")
                        .and_then(GuardValue::as_str)
                        .is_some_and(|mode| !mode.is_empty());
                    let root_scope = matches!(
                        native.get("write_scope"),
                        Some(GuardValue::Array(scope))
                            if scope.len() == 1 && scope[0].as_str() == Some("*.md")
                    );
                    if !root_mode || !root_scope {
                        return Verdict::unresolved(
                            "native root dispatch resolution is incomplete",
                            &["dispatch.mode", "dispatch.write_scope"],
                        );
                    }
                }
                true
            }
            Some(_) => {
                return Verdict::unresolved(
                    "native dispatch resolution must be a JSON object",
                    &["dispatch"],
                );
            }
        };

        let subcommands = extract_git_subcommands(command);
        let action = if subcommands
            .iter()
            .any(|subcommand| GIT_INTEGRATE_VERBS.contains(&subcommand.as_str()))
        {
            Some("vcs.integrate")
        } else if subcommands.iter().any(|subcommand| {
            GIT_ALL_WRITE_VERBS.contains(&subcommand.as_str())
                && !GIT_INTEGRATE_VERBS.contains(&subcommand.as_str())
        }) {
            Some("vcs.write")
        } else {
            None
        };

        if let Some(action) = action {
            let Some(role) = role.filter(|value| !value.is_null()) else {
                return Verdict::unresolved(
                    "missing `role` -- cannot identify the acting role",
                    &["role"],
                );
            };
            let tier = role.as_str().and_then(role_tier);
            let Some(tier) = tier else {
                return Verdict::unresolved(
                    format!("unknown role `{}`", compatibility_display(role)),
                    &["role"],
                );
            };
            return self.decide(
                "git-custody",
                action,
                role,
                &BTreeMap::from([(String::from("role_tier"), GuardValue::from(tier))]),
            );
        }

        let non_writable_role = role
            .and_then(GuardValue::as_str)
            .and_then(|role| self.role_facts.get(role))
            .is_some_and(|fact| !fact.write_eligible);
        if bounded_dispatch || non_writable_role {
            return Verdict::deny(
                "write-boundary",
                "opaque-shell-effect",
                None,
                "opaque Bash effects require an unbounded native authorization; bounded or non-writable dispatch facts fail closed without shell-text inference",
            );
        }

        Verdict::allow()
    }

    fn evaluate_dispatch_tool(
        &self,
        role: Option<&GuardValue>,
        tool_input: &Context,
        tool_name: &str,
    ) -> Verdict {
        let target = ["subagent_type", "target_role", "role"]
            .into_iter()
            .filter_map(|key| tool_input.get(key))
            .find(|value| value.is_truthy())
            .and_then(GuardValue::as_str)
            .map(carrier_role)
            .filter(|value| !value.is_empty());
        // `Workflow` fans out inside its own script, so its `tool_input` carries
        // no single target role. `Agent` always carries one, so a missing target
        // there is still unresolved.
        if target.is_none() && tool_name != "Workflow" {
            return Verdict::unresolved(
                "cannot determine the dispatch target role from `tool_input`",
                &["tool_input.subagent_type"],
            );
        }
        let Some(role) = role.filter(|value| !value.is_null()) else {
            return Verdict::unresolved(
                "missing `role` -- cannot identify the dispatching role",
                &["role"],
            );
        };
        let tier = role.as_str().and_then(role_tier);
        let Some(tier) = tier else {
            return Verdict::unresolved(
                format!("unknown role `{}`", compatibility_display(role)),
                &["role"],
            );
        };
        // Two dispatch-scope rules key on the TARGET, so an undeclared target
        // makes them unenforceable. That is fine for a role no target-keyed rule
        // restricts -- there is nothing to evade. It is NOT fine for a role that
        // one does: a lane lead denied `engineer` by name could otherwise obtain
        // it by writing the dispatch as a script string, which is a bypass by
        // payload shape rather than by permission. Such a role must declare.
        if target.is_none() && restricted_by_target_rule(tier) {
            return Verdict::deny(
                "dispatch-scope",
                "plan-authorship-and-gating-are-root-tier-exclusive",
                Some(String::from("WRONG-TIER-DISPATCH")),
                "a lane-executor lead must DECLARE the roles it dispatches: pass \
`target_role` (or `subagent_type`) in `tool_input`. Two dispatch-scope rules key on the \
target, so an undeclared target would let a refused dispatch through by payload shape.",
            );
        }
        let mut context =
            BTreeMap::from([(String::from("dispatcher_tier"), GuardValue::from(tier))]);
        if let Some(target) = target {
            context.insert(String::from("target_role"), GuardValue::from(target));
        }
        self.decide("dispatch-scope", "dispatch", role, &context)
    }

    fn decide(
        &self,
        predicate_id: &str,
        action: &str,
        role: &GuardValue,
        context: &Context,
    ) -> Verdict {
        let fired = match evaluate_predicate(
            predicate_id,
            action,
            context,
            &self.predicates,
            &self.role_facts,
        ) {
            Ok(fired) => fired,
            Err(error) => return Verdict::unresolved(error.to_string(), &[]),
        };
        if fired.is_empty() {
            return Verdict::allow();
        }

        let halt_code = self.resolve_halt_code(predicate_id, &fired, context, role);
        let predicate = &self.predicates[predicate_id];
        let descriptions: Vec<&str> = predicate
            .rules
            .iter()
            .filter(|rule| fired.iter().any(|id| id == &rule.id))
            .map(|rule| rule.description.as_str())
            .collect();
        let rule_ids = fired.join(",");
        let reason = if descriptions.is_empty() {
            format!("{predicate_id}: rule(s) {} fired", fired.join(", "))
        } else {
            descriptions.join(" / ")
        };
        Verdict::deny(predicate_id, rule_ids, halt_code, reason)
    }

    fn resolve_halt_code(
        &self,
        predicate_id: &str,
        fired: &[String],
        context: &Context,
        role: &GuardValue,
    ) -> Option<String> {
        if predicate_id == "write-boundary" {
            let fact = role.as_str().and_then(|role| self.role_facts.get(role));
            if fact.is_some_and(|fact| {
                fact.capabilities
                    .iter()
                    .any(|capability| capability == "report-write")
            }) {
                return Some(String::from("DISCOVERY-WRITE-PATH"));
            }
            if context
                .get("write_eligible")
                .is_some_and(GuardValue::is_true)
            {
                return Some(String::from("SCOPE OVERFLOW"));
            }
            return None;
        }
        if fired.len() == 1 {
            return self
                .halt_table
                .get(&(String::from(predicate_id), fired[0].clone()))
                .cloned()
                .flatten();
        }
        None
    }
}

/// Strip shepherd's own carrier prefix from a dispatch target.
///
/// A host names a plugin agent `<plugin>:<agent>`, so Claude Code sends
/// `shepherd:conductor` where `role_facts` is keyed on the bare `conductor`.
/// Without this, every dispatch to a real flock role was refused as off-flock
/// and the plugin could not dispatch through its own guard. Only shepherd's
/// prefix is stripped: another plugin's `coder` is not this flock's `coder`.
/// Whether any `dispatch-scope` rule restricts this tier BY TARGET.
///
/// Only the lane lead is: `plan-authorship-and-gating-are-root-tier-exclusive`
/// forbids it `engineer` and `critic`. Root has no target-keyed restriction it
/// could evade, and an implementer is refused by acting role alone, which no
/// payload shape can hide.
fn restricted_by_target_rule(tier: &str) -> bool {
    tier == "lane-lead"
}

fn carrier_role(value: &str) -> &str {
    value.strip_prefix("shepherd:").unwrap_or(value)
}

fn role_tier(role: &str) -> Option<&'static str> {
    match role {
        "shepherd" => Some("root"),
        "planter" => Some("meta"),
        "conductor" => Some("lane-lead"),
        "engineer" => Some("plan-author"),
        "critic" | "coder" | "auditor" | "discovery" | "worker" => Some("implementer"),
        _ => None,
    }
}

fn compatibility_display(value: &GuardValue) -> String {
    match value {
        GuardValue::Null => String::from("None"),
        GuardValue::Bool(true) => String::from("True"),
        GuardValue::Bool(false) => String::from("False"),
        GuardValue::Integer(value) => value.to_string(),
        GuardValue::Unsigned(value) => value.to_string(),
        GuardValue::Float(value) => value.to_string(),
        GuardValue::String(value) => value.clone(),
        GuardValue::Array(_) => String::from("[...]"),
        GuardValue::Object(_) => String::from("{...}"),
    }
}

fn harvest_halt_codes(
    predicates: &BTreeMap<String, PredicateDoc>,
    role_facts: &BTreeMap<String, RoleFact>,
) -> Result<HaltTable, GuardError> {
    let mut halt_table = BTreeMap::new();
    for (predicate_id, predicate) in predicates {
        for example in &predicate.examples {
            if example.result != "deny" {
                continue;
            }
            let fired = evaluate_predicate(
                predicate_id,
                &example.action,
                &example.flattened_context(),
                predicates,
                role_facts,
            )?;
            if fired.len() != 1 {
                continue;
            }
            let key = (predicate_id.clone(), fired[0].clone());
            if let Some(existing) = halt_table.get(&key)
                && existing != &example.halt_code
            {
                return Err(GuardError::Predicate(format!(
                    "ambiguous halt code for ({:?}, {:?}): {:?} vs {:?} (example `{}`)",
                    key.0, key.1, existing, example.halt_code, example.name
                )));
            }
            halt_table.insert(key, example.halt_code.clone());
        }
    }
    Ok(halt_table)
}

fn evaluate_predicate(
    predicate_id: &str,
    action: &str,
    context: &Context,
    predicates: &BTreeMap<String, PredicateDoc>,
    role_facts: &BTreeMap<String, RoleFact>,
) -> Result<Vec<String>, GuardError> {
    let predicate = predicates
        .get(predicate_id)
        .ok_or_else(|| GuardError::Predicate(format!("no such predicate `{predicate_id}`")))?;
    let applicable: Vec<&Rule> = predicate
        .rules
        .iter()
        .filter(|rule| rule.action == action)
        .collect();
    if applicable.is_empty() {
        return Err(GuardError::Predicate(format!(
            "predicate `{predicate_id}` has no rule scoped to action `{action}`"
        )));
    }

    let mut fired = Vec::new();
    for rule in applicable {
        if effect_fires(rule, context, role_facts).map_err(|effect| {
            GuardError::Predicate(format!(
                "no handler for effect `{effect}` (predicate `{predicate_id}`, rule `{}`)",
                rule.id
            ))
        })? {
            fired.push(rule.id.clone());
        }
    }
    Ok(fired)
}

fn effect_fires<'a>(
    rule: &'a Rule,
    context: &Context,
    role_facts: &BTreeMap<String, RoleFact>,
) -> Result<bool, &'a str> {
    let value = match rule.effect.as_str() {
        "deny_if_false" => {
            context
                .get("write_eligible")
                .is_some_and(GuardValue::is_false)
                && !context
                    .get("path_in_dispatch_write_scope")
                    .is_some_and(GuardValue::is_true)
        }
        "deny_if_path_outside_scope" => context
            .get("path_in_dispatch_write_scope")
            .is_some_and(GuardValue::is_false),
        "allow_if_no_hit" => false,
        "deny_if_hit_without_justification" => {
            context.get("dedup_hit").is_some_and(GuardValue::is_true)
                && !context
                    .get("justification_present")
                    .is_some_and(GuardValue::is_true)
        }
        "deny_if_target_outside_flock" => context
            .get("target_role")
            .and_then(GuardValue::as_str)
            .is_some_and(|target| !role_facts.contains_key(target)),
        "deny_if_dispatcher_is_lane_lead_and_target_is_plan_or_gate_role" => {
            context.get("dispatcher_tier").and_then(GuardValue::as_str) == Some("lane-lead")
                // `planter` holds the operator channel (`AskUserQuestion`) and
                // `shepherd` is the root orchestrator itself -- a lane lead
                // reaching either inverts the dispatch tier the same way
                // reaching `engineer`/`critic` does (#323).
                && matches!(
                    context.get("target_role").and_then(GuardValue::as_str),
                    Some("engineer" | "critic" | "planter" | "shepherd")
                )
        }
        "deny_if_dispatcher_is_implementer" => {
            context.get("dispatcher_tier").and_then(GuardValue::as_str) == Some("implementer")
        }
        "deny_if_role_is_implementer" => {
            context.get("role_tier").and_then(GuardValue::as_str) == Some("implementer")
        }
        "deny_if_branch_outside_own_lane" => context
            .get("is_own_lane_branch")
            .is_some_and(GuardValue::is_false),
        "deny_unless_root" => context.get("role_tier").and_then(GuardValue::as_str) != Some("root"),
        effect => return Err(effect),
    };
    Ok(value)
}
