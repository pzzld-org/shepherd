//! Structured capability contracts, probes, diffs, and admission status.

#[cfg(feature = "alloc")]
use alloc::{
    collections::BTreeSet,
    string::{String, ToString},
};

use super::{DispatchError, DispatchResult};

#[derive(Clone, Debug, Default, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityContract {
    pub required: BTreeSet<String>,
    pub optional: BTreeSet<String>,
    pub forbidden: BTreeSet<String>,
}

impl CapabilityContract {
    pub fn new<R, O, F, RS, OS, FS>(required: R, optional: O, forbidden: F) -> DispatchResult<Self>
    where
        R: IntoIterator<Item = RS>,
        O: IntoIterator<Item = OS>,
        F: IntoIterator<Item = FS>,
        RS: AsRef<str>,
        OS: AsRef<str>,
        FS: AsRef<str>,
    {
        let contract = Self {
            required: normalized_capabilities(required)?,
            optional: normalized_capabilities(optional)?,
            forbidden: normalized_capabilities(forbidden)?,
        };
        contract.validate()?;
        Ok(contract)
    }

    pub fn validate(&self) -> DispatchResult<()> {
        validate_capability_set(&self.required)?;
        validate_capability_set(&self.optional)?;
        validate_capability_set(&self.forbidden)?;
        self.validate_disjoint()
    }

    #[must_use]
    pub fn evaluate(&self, probe: CapabilityProbe) -> CapabilityReport {
        let declared: BTreeSet<String> = self.required.union(&self.optional).cloned().collect();
        let present = declared.intersection(&probe.observed).cloned().collect();
        let missing_required = self.required.difference(&probe.observed).cloned().collect();
        let missing_optional = self.optional.difference(&probe.observed).cloned().collect();
        let missing = declared.difference(&probe.observed).cloned().collect();
        let extra = probe.observed.difference(&declared).cloned().collect();
        let forbidden_extra = probe
            .observed
            .intersection(&self.forbidden)
            .cloned()
            .collect();
        CapabilityReport {
            declared,
            observed: probe.observed,
            present,
            missing,
            missing_required,
            missing_optional,
            extra,
            forbidden_extra,
            source: probe.source,
            harness_version: probe.harness_version,
            provider_version: probe.provider_version,
            probed_at: probe.probed_at,
        }
    }

    fn validate_disjoint(&self) -> DispatchResult<()> {
        for (left_name, left, right_name, right) in [
            ("required", &self.required, "optional", &self.optional),
            ("required", &self.required, "forbidden", &self.forbidden),
            ("optional", &self.optional, "forbidden", &self.forbidden),
        ] {
            if let Some(capability) = left.intersection(right).next() {
                return Err(DispatchError::CapabilityOverlap {
                    capability: capability.clone(),
                    left: left_name,
                    right: right_name,
                });
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityProbe {
    pub observed: BTreeSet<String>,
    pub source: String,
    pub harness_version: String,
    pub provider_version: Option<String>,
    pub probed_at: i64,
}

impl CapabilityProbe {
    pub fn new<I, S>(
        observed: I,
        source: impl Into<String>,
        harness_version: impl Into<String>,
        provider_version: Option<&str>,
        probed_at: i64,
    ) -> DispatchResult<Self>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let source = source.into();
        let harness_version = harness_version.into();
        let probe = Self {
            observed: normalized_capabilities(observed)?,
            source,
            harness_version,
            provider_version: provider_version.map(ToString::to_string),
            probed_at,
        };
        probe.validate()?;
        Ok(probe)
    }

    pub fn validate(&self) -> DispatchResult<()> {
        validate_capability_set(&self.observed)?;
        if !valid_metadata(&self.source, 256) {
            return Err(DispatchError::InvalidCapability(self.source.clone()));
        }
        if !valid_metadata(&self.harness_version, 128) {
            return Err(DispatchError::InvalidCapability(
                self.harness_version.clone(),
            ));
        }
        if let Some(provider_version) = &self.provider_version
            && !valid_metadata(provider_version, 128)
        {
            return Err(DispatchError::InvalidCapability(provider_version.clone()));
        }
        if self.probed_at < 0 {
            return Err(DispatchError::InvalidTime(
                "capability probe time cannot be negative".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum CapabilityReadiness {
    Ready,
    Degraded,
    Blocked,
}

#[derive(Clone, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct CapabilityReport {
    pub declared: BTreeSet<String>,
    pub observed: BTreeSet<String>,
    pub present: BTreeSet<String>,
    pub missing: BTreeSet<String>,
    pub missing_required: BTreeSet<String>,
    pub missing_optional: BTreeSet<String>,
    pub extra: BTreeSet<String>,
    pub forbidden_extra: BTreeSet<String>,
    pub source: String,
    pub harness_version: String,
    pub provider_version: Option<String>,
    pub probed_at: i64,
}

impl CapabilityReport {
    #[must_use]
    pub fn readiness(&self) -> CapabilityReadiness {
        if !self.missing_required.is_empty() || !self.forbidden_extra.is_empty() {
            CapabilityReadiness::Blocked
        } else if !self.missing_optional.is_empty() {
            CapabilityReadiness::Degraded
        } else {
            CapabilityReadiness::Ready
        }
    }

    pub fn validate(&self) -> DispatchResult<()> {
        for values in [
            &self.declared,
            &self.observed,
            &self.present,
            &self.missing,
            &self.missing_required,
            &self.missing_optional,
            &self.extra,
            &self.forbidden_extra,
        ] {
            validate_capability_set(values)?;
        }
        let expected_present = self
            .declared
            .intersection(&self.observed)
            .cloned()
            .collect::<BTreeSet<_>>();
        let expected_missing = self
            .declared
            .difference(&self.observed)
            .cloned()
            .collect::<BTreeSet<_>>();
        let expected_extra = self
            .observed
            .difference(&self.declared)
            .cloned()
            .collect::<BTreeSet<_>>();
        let partitioned_missing = self
            .missing_required
            .union(&self.missing_optional)
            .cloned()
            .collect::<BTreeSet<_>>();
        let valid = self.present == expected_present
            && self.missing == expected_missing
            && self.extra == expected_extra
            && partitioned_missing == self.missing
            && self.missing_required.is_disjoint(&self.missing_optional)
            && self.forbidden_extra.is_subset(&self.extra)
            && valid_metadata(&self.source, 256)
            && valid_metadata(&self.harness_version, 128)
            && self
                .provider_version
                .as_ref()
                .is_none_or(|version| valid_metadata(version, 128))
            && self.probed_at >= 0;
        if valid {
            Ok(())
        } else {
            Err(DispatchError::InvalidRecord(
                "capability diff is inconsistent".into(),
            ))
        }
    }
}

fn valid_metadata(value: &str, max: usize) -> bool {
    (1..=max).contains(&value.len()) && !value.chars().any(char::is_control)
}

fn normalized_capabilities<I, S>(values: I) -> DispatchResult<BTreeSet<String>>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    values
        .into_iter()
        .map(|value| {
            let value = value.as_ref();
            let bytes = value.as_bytes();
            let valid = (1..=128).contains(&bytes.len())
                && bytes[0].is_ascii_lowercase()
                && bytes.iter().all(|byte| {
                    byte.is_ascii_lowercase()
                        || byte.is_ascii_digit()
                        || matches!(*byte, b'.' | b'_' | b':' | b'-')
                });
            if valid {
                Ok(value.to_string())
            } else {
                Err(DispatchError::InvalidCapability(value.to_string()))
            }
        })
        .collect()
}

fn validate_capability_set(values: &BTreeSet<String>) -> DispatchResult<()> {
    for value in values {
        let normalized = normalized_capabilities([value.as_str()])?;
        if normalized.len() != 1 {
            return Err(DispatchError::InvalidCapability(value.clone()));
        }
    }
    Ok(())
}
