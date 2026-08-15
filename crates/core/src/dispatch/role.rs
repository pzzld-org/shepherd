//! Closed nine-role registry and stable semantic carriers.

#[cfg(feature = "alloc")]
use alloc::{format, string::String};

use super::{CapabilityContract, DispatchError, DispatchResult};

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum Role {
    Auditor,
    Coder,
    Conductor,
    Critic,
    Discovery,
    Engineer,
    Planter,
    Shepherd,
    Worker,
}

impl Role {
    /// The complete closed role registry in deterministic order.
    pub const ALL: [Self; 9] = [
        Self::Auditor,
        Self::Coder,
        Self::Conductor,
        Self::Critic,
        Self::Discovery,
        Self::Engineer,
        Self::Planter,
        Self::Shepherd,
        Self::Worker,
    ];

    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Auditor => "auditor",
            Self::Coder => "coder",
            Self::Conductor => "conductor",
            Self::Critic => "critic",
            Self::Discovery => "discovery",
            Self::Engineer => "engineer",
            Self::Planter => "planter",
            Self::Shepherd => "shepherd",
            Self::Worker => "worker",
        }
    }

    #[must_use]
    pub fn carrier(self) -> String {
        format!("shepherd:{}", self.as_str())
    }

    pub fn from_carrier(value: &str) -> DispatchResult<Self> {
        let Some(role) = value.strip_prefix("shepherd:") else {
            return Err(DispatchError::InvalidRole(value.into()));
        };
        Self::from_name(role)
    }

    pub fn from_name(value: &str) -> DispatchResult<Self> {
        Self::ALL
            .into_iter()
            .find(|role| role.as_str() == value)
            .ok_or_else(|| DispatchError::InvalidRole(value.into()))
    }

    pub fn capability_contract(self) -> DispatchResult<CapabilityContract> {
        let (required, optional): (&[&str], &[&str]) = match self {
            Self::Auditor => (
                &[
                    "read",
                    "search",
                    "shell",
                    "code-intelligence",
                    "skill-load",
                    "report-write",
                ],
                &["tool-discovery"],
            ),
            Self::Coder | Self::Worker => (
                &["read", "search", "shell", "write", "skill-load"],
                &["tool-discovery"],
            ),
            Self::Conductor => (
                &[
                    "read",
                    "search",
                    "shell",
                    "skill-load",
                    "dispatch",
                    "message-peer",
                    "task-tracking",
                ],
                &["schedule-wakeup", "tool-discovery", "web-research"],
            ),
            Self::Critic => (&["read", "search", "shell", "skill-load"], &[]),
            Self::Discovery => (
                &["read", "search", "shell", "skill-load", "report-write"],
                &["tool-discovery", "web-research"],
            ),
            Self::Engineer => (
                &[
                    "read",
                    "search",
                    "shell",
                    "write",
                    "skill-load",
                    "dispatch",
                    "message-peer",
                ],
                &["tool-discovery"],
            ),
            Self::Planter => (
                &[
                    "read",
                    "search",
                    "shell",
                    "write",
                    "skill-load",
                    "dispatch",
                    "ask-operator",
                    "task-tracking",
                ],
                &["tool-discovery", "web-research"],
            ),
            Self::Shepherd => (
                &[
                    "read",
                    "search",
                    "shell",
                    "write",
                    "skill-load",
                    "dispatch",
                    "message-peer",
                    "task-tracking",
                ],
                &["tool-discovery", "web-research"],
            ),
        };
        let forbidden: &[&str] = match self {
            Self::Auditor | Self::Critic | Self::Discovery => {
                &["admin", "sudo", "write", "edit", "dispatch"]
            }
            Self::Coder | Self::Worker => &["admin", "sudo", "dispatch"],
            Self::Conductor => &["admin", "sudo", "write", "edit"],
            Self::Engineer | Self::Planter | Self::Shepherd => &["admin", "sudo"],
        };
        CapabilityContract::new(required, optional, forbidden)
    }

    pub fn dispatch_capability_contract(self) -> DispatchResult<CapabilityContract> {
        let mut contract = self.capability_contract()?;
        contract.required.insert("subagent-provider".into());
        contract.validate()?;
        Ok(contract)
    }
}

impl core::fmt::Display for Role {
    fn fmt(&self, formatter: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl serde::Serialize for Role {
    fn serialize<S>(&self, serializer: S) -> core::result::Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> serde::Deserialize<'de> for Role {
    fn deserialize<D>(deserializer: D) -> core::result::Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::from_name(&value).map_err(serde::de::Error::custom)
    }
}
