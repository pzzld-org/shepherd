//! Native request boundary over the pure dispatch engine and primary-run store.

use std::{collections::BTreeSet, path::PathBuf};

use shepherd::{
    Harness,
    dispatch::{
        AgentId, AgentType, CapabilityProbe, CapabilityReadiness, CapabilityReport, ContextBundle,
        DispatchError, DispatchRecord, DispatchStart, DispatchState, IdentityError,
        IdentityResolution, LaneId, NativeIdentity, ProjectId, ROOT_SESSION_SCHEMA, Role,
        RootSessionBinding, RunId, SessionId, StopRequest, path_in_write_scope,
    },
};

use crate::{
    DispatchStore, DispatchStoreError, dispatch_scope::derive_write_paths,
    resume_context::build_resume_context,
};

const REQUEST_SCHEMA: &str = "shepherd.dispatch-request/1";
const MAX_LEASE_MS: u64 = 86_400_000;

pub type DispatchServiceResult<T> = core::result::Result<T, DispatchServiceError>;

#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum DispatchServiceError {
    #[error("invalid dispatch request: {0}")]
    InvalidRequest(String),
    #[error(transparent)]
    Store(#[from] DispatchStoreError),
    #[error(transparent)]
    Domain(#[from] DispatchError),
    #[error(transparent)]
    Identity(#[from] IdentityError),
    #[error("cannot materialize resume context: {0}")]
    ResumeContext(String),
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct StartDispatchRequest {
    pub schema: String,
    #[serde(default)]
    pub run: Option<String>,
    pub harness: Harness,
    pub agent_id: String,
    pub agent_type: String,
    pub role_carrier: String,
    pub lane: Option<String>,
    pub parent_agent_id: Option<String>,
    pub session_id: String,
    pub write_scope: Vec<String>,
    pub model: Option<String>,
    pub observed_capabilities: BTreeSet<String>,
    pub capability_source: String,
    pub harness_version: String,
    pub provider_version: Option<String>,
    pub lease_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct BindRootDispatchRequest {
    pub schema: String,
    #[serde(default)]
    pub run: Option<String>,
    pub harness: Harness,
    pub session_id: String,
    pub role_carrier: String,
    pub mode: String,
    pub lease_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResolveDispatchRequest {
    pub schema: String,
    #[serde(default)]
    pub run: Option<String>,
    pub harness: Harness,
    pub agent_id: Option<String>,
    pub agent_type: Option<String>,
    pub role_carrier: Option<String>,
    pub lane: Option<String>,
    pub session_id: String,
    pub tool_call_id: Option<String>,
    #[serde(default)]
    pub tool_name: Option<String>,
    #[serde(default)]
    pub tool_input: Option<serde_json::Value>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct StopDispatchRequest {
    pub schema: String,
    #[serde(default)]
    pub run: Option<String>,
    pub harness: Harness,
    pub agent_id: String,
    pub agent_type: String,
    pub role_carrier: Option<String>,
    pub lane: Option<String>,
    pub session_id: String,
    pub expected_revision: u64,
    pub result_artifact: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResumeDispatchRequest {
    pub schema: String,
    pub source_agent_id: String,
    pub next: StartDispatchRequest,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchResolution {
    pub schema: String,
    pub project_id: ProjectId,
    pub run: RunId,
    pub harness: Harness,
    pub agent_id: Option<String>,
    pub agent_type: Option<AgentType>,
    pub role: Role,
    pub lane: Option<LaneId>,
    pub session_id: SessionId,
    pub write_scope: Vec<String>,
    pub capabilities: Option<CapabilityReport>,
    pub tool_call_id: Option<String>,
    pub mode: Option<String>,
    pub write_paths: Vec<String>,
    pub path_in_write_scope: Option<bool>,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResumeDispatchResponse {
    pub schema: String,
    pub record: DispatchRecord,
    pub context: ContextBundle,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchService {
    store: DispatchStore,
    project_id: ProjectId,
    project_root: Option<PathBuf>,
    registry_path: Option<PathBuf>,
}

impl DispatchService {
    pub fn new(store: DispatchStore, project_id: ProjectId) -> Self {
        Self {
            store,
            project_id,
            project_root: None,
            registry_path: None,
        }
    }

    pub fn with_project_root(
        store: DispatchStore,
        project_id: ProjectId,
        project_root: impl Into<PathBuf>,
    ) -> Self {
        let project_root = project_root.into();
        Self {
            store,
            project_id,
            registry_path: Some(project_root.join(".shepherd/shepherd.db")),
            project_root: Some(project_root),
        }
    }

    pub fn with_context(
        store: DispatchStore,
        project_id: ProjectId,
        project_root: impl Into<PathBuf>,
        registry_path: impl Into<PathBuf>,
    ) -> Self {
        Self {
            store,
            project_id,
            project_root: Some(project_root.into()),
            registry_path: Some(registry_path.into()),
        }
    }

    #[must_use]
    pub fn store(&self) -> &DispatchStore {
        &self.store
    }

    pub fn start(
        &self,
        request: StartDispatchRequest,
        now: i64,
    ) -> DispatchServiceResult<DispatchRecord> {
        validate_schema(&request.schema)?;
        let active = self.store.resolve_active_run()?;
        validate_requested_run(request.run.as_deref(), &active)?;
        let start = self.start_input(request, &active, now, None)?;
        let record = DispatchRecord::start(start)?;
        self.store.publish_active(&record)?;
        Ok(record)
    }

    /// Persist the primary agent's versioned SessionStart identity before any
    /// guarded tool use. Callers cannot supply binding timestamps or project
    /// identity; those facts are derived at this native boundary.
    pub fn bind_root(
        &self,
        request: BindRootDispatchRequest,
        now: i64,
    ) -> DispatchServiceResult<RootSessionBinding> {
        validate_schema(&request.schema)?;
        let active = self.store.resolve_active_run()?;
        validate_requested_run(request.run.as_deref(), &active)?;
        let lease_expires_at = lease_expires_at(request.lease_ms, now)?;
        let binding = RootSessionBinding {
            schema: ROOT_SESSION_SCHEMA.into(),
            project_id: self.project_id.clone(),
            run: active,
            harness: request.harness,
            session_id: SessionId::new(request.session_id)?,
            role: Role::from_carrier(&request.role_carrier)?,
            mode: request.mode,
            bound_at: now,
            expires_at: lease_expires_at,
        };
        binding.validate()?;
        self.store.publish_root_binding(&binding)?;
        Ok(binding)
    }

    pub fn resolve(
        &self,
        request: ResolveDispatchRequest,
        now: i64,
    ) -> DispatchServiceResult<DispatchResolution> {
        validate_schema(&request.schema)?;
        let active = self.store.resolve_active_run()?;
        validate_requested_run(request.run.as_deref(), &active)?;
        let role = request
            .role_carrier
            .as_deref()
            .map(Role::from_carrier)
            .transpose()?;
        let agent_id = request.agent_id.map(AgentId::new).transpose()?;
        let agent_type = request.agent_type.map(AgentType::new).transpose()?;
        let lane = request.lane.map(LaneId::new).transpose()?;
        let session_id = SessionId::new(request.session_id)?;
        let tool_name = request.tool_name;
        let tool_input = request.tool_input;
        let root_binding = if agent_id.is_none() {
            Some(self.store.load_active_root_binding(&session_id)?)
        } else {
            None
        };
        let tool_call_id = request.tool_call_id;
        let native = NativeIdentity {
            harness: request.harness,
            project_id: self.project_id.clone(),
            run: active.clone(),
            lane,
            session_id: session_id.clone(),
            agent_id,
            agent_type,
            role,
            tool_call_id: tool_call_id.clone(),
            now,
            root_binding,
        };
        let (resolution, record) = self.store.resolve_active_identity_with_record(&native)?;
        let mut resolution = match resolution {
            IdentityResolution::Root { role, mode } => DispatchResolution {
                schema: "shepherd.identity-resolution/1".into(),
                project_id: self.project_id.clone(),
                run: active,
                harness: request.harness,
                agent_id: None,
                agent_type: None,
                role,
                lane: None,
                session_id,
                write_scope: vec!["**".into()],
                capabilities: None,
                tool_call_id,
                mode: Some(mode),
                write_paths: Vec::new(),
                path_in_write_scope: None,
            },
            IdentityResolution::Agent { agent_id, role } => DispatchResolution {
                schema: "shepherd.identity-resolution/1".into(),
                project_id: self.project_id.clone(),
                run: active,
                harness: request.harness,
                agent_id: Some(agent_id.to_string()),
                agent_type: record.as_ref().map(|record| record.agent_type.clone()),
                role,
                lane: record.as_ref().and_then(|record| record.lane.clone()),
                session_id,
                write_scope: record
                    .as_ref()
                    .map(|record| record.write_scope.clone())
                    .unwrap_or_default(),
                capabilities: record.map(|record| record.capabilities),
                tool_call_id,
                mode: None,
                write_paths: Vec::new(),
                path_in_write_scope: None,
            },
        };
        if tool_name.is_some() || tool_input.is_some() {
            let primary_root = self.project_root.as_deref().ok_or_else(|| {
                DispatchServiceError::InvalidRequest(
                    "native write-path resolution requires the primary repository root".into(),
                )
            })?;
            let write_paths =
                derive_write_paths(primary_root, tool_name.as_deref(), tool_input.as_ref())?;
            if !write_paths.is_empty() {
                let mut all_in_scope = true;
                for path in &write_paths {
                    all_in_scope &= path_in_write_scope(path, &resolution.write_scope)?;
                }
                resolution.path_in_write_scope = Some(all_in_scope);
                resolution.write_paths = write_paths;
            }
        }
        Ok(resolution)
    }

    pub fn resolve_for_mutation(
        &self,
        agent_id: &str,
        now: i64,
    ) -> DispatchServiceResult<DispatchRecord> {
        let agent_id = AgentId::new(agent_id)?;
        let record = self.store.load_active(&agent_id)?;
        if record.state != DispatchState::Active {
            return Err(IdentityError::Terminal {
                state: record.state,
            }
            .into());
        }
        if now >= record.lease_expires_at {
            return Err(IdentityError::Stale {
                expired_at: record.lease_expires_at,
            }
            .into());
        }
        if record.capabilities.readiness() == CapabilityReadiness::Blocked {
            return Err(IdentityError::CapabilityBlocked.into());
        }
        Ok(record)
    }

    pub fn stop(
        &self,
        request: StopDispatchRequest,
        now: i64,
    ) -> DispatchServiceResult<DispatchRecord> {
        validate_schema(&request.schema)?;
        let active = self.store.resolve_active_run()?;
        validate_requested_run(request.run.as_deref(), &active)?;
        let agent_id = AgentId::new(request.agent_id)?;
        let native = NativeIdentity {
            harness: request.harness,
            project_id: self.project_id.clone(),
            run: active,
            lane: request.lane.map(LaneId::new).transpose()?,
            session_id: SessionId::new(request.session_id)?,
            agent_id: Some(agent_id.clone()),
            agent_type: Some(AgentType::new(request.agent_type)?),
            role: request
                .role_carrier
                .as_deref()
                .map(Role::from_carrier)
                .transpose()?,
            tool_call_id: None,
            now,
            root_binding: None,
        };
        self.store
            .stop_active_verified(
                &native,
                StopRequest {
                    agent_id,
                    expected_revision: request.expected_revision,
                    stopped_at: now,
                    result_artifact: request.result_artifact,
                },
            )
            .map_err(Into::into)
    }

    pub fn resume(
        &self,
        request: ResumeDispatchRequest,
        now: i64,
    ) -> DispatchServiceResult<ResumeDispatchResponse> {
        validate_schema(&request.schema)?;
        validate_schema(&request.next.schema)?;
        let active = self.store.resolve_active_run()?;
        validate_requested_run(request.next.run.as_deref(), &active)?;
        let source_agent_id = AgentId::new(request.source_agent_id)?;
        let next = self.start_input(request.next, &active, now, Some(source_agent_id.clone()))?;
        let source = self.store.load_active(&source_agent_id)?;
        let candidate = source.resume(next.clone())?;
        let registry_path = self.registry_path.as_deref().ok_or_else(|| {
            DispatchServiceError::InvalidRequest(
                "resume context requires the canonical registry path".into(),
            )
        })?;
        let context = build_resume_context(&self.store, registry_path, &candidate)
            .map_err(DispatchServiceError::ResumeContext)?;
        let record = self.store.resume_active(&source_agent_id, next)?;
        if record != candidate {
            return Err(DispatchServiceError::ResumeContext(
                "published resume record differs from the validated candidate".into(),
            ));
        }
        Ok(ResumeDispatchResponse {
            schema: "shepherd.resume-context/1".into(),
            record,
            context,
        })
    }

    fn start_input(
        &self,
        request: StartDispatchRequest,
        run: &RunId,
        now: i64,
        resumes_agent_id: Option<AgentId>,
    ) -> DispatchServiceResult<DispatchStart> {
        let lease_expires_at = lease_expires_at(request.lease_ms, now)?;
        let role = Role::from_carrier(&request.role_carrier)?;
        Ok(DispatchStart {
            project_id: self.project_id.clone(),
            run: run.clone(),
            harness: request.harness,
            agent_id: AgentId::new(request.agent_id)?,
            agent_type: AgentType::new(request.agent_type)?,
            role,
            lane: request.lane.map(LaneId::new).transpose()?,
            parent_agent_id: request.parent_agent_id.map(AgentId::new).transpose()?,
            session_id: SessionId::new(request.session_id)?,
            write_scope: request.write_scope,
            model: request.model,
            capability_contract: role.dispatch_capability_contract()?,
            capability_probe: CapabilityProbe::new(
                request.observed_capabilities,
                request.capability_source,
                request.harness_version,
                request.provider_version.as_deref(),
                now,
            )?,
            started_at: now,
            lease_expires_at,
            resumes_agent_id,
        })
    }
}

fn lease_expires_at(lease_ms: u64, now: i64) -> DispatchServiceResult<i64> {
    if lease_ms == 0 || lease_ms > MAX_LEASE_MS {
        return Err(DispatchServiceError::InvalidRequest(format!(
            "lease_ms must be between 1 and {MAX_LEASE_MS}"
        )));
    }
    let lease_ms = i64::try_from(lease_ms)
        .map_err(|_| DispatchServiceError::InvalidRequest("lease_ms overflow".into()))?;
    now.checked_add(lease_ms)
        .ok_or_else(|| DispatchServiceError::InvalidRequest("lease time overflow".into()))
}

fn validate_schema(schema: &str) -> DispatchServiceResult<()> {
    if schema == REQUEST_SCHEMA {
        Ok(())
    } else {
        Err(DispatchServiceError::InvalidRequest(format!(
            "unsupported schema `{schema}`"
        )))
    }
}

fn validate_requested_run(run: Option<&str>, active: &RunId) -> DispatchServiceResult<()> {
    let Some(run) = run else {
        return Ok(());
    };
    let supplied = RunId::new(run)?;
    if &supplied == active {
        Ok(())
    } else {
        Err(DispatchStoreError::WrongActiveRun {
            supplied,
            active: active.clone(),
        }
        .into())
    }
}
