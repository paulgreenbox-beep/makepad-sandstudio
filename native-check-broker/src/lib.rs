//! Protocol validation and a probe-only native supervisor.
//! Repository-code execution is deliberately unavailable until its independent
//! controller identity, source import, filesystem and network gates are qualified.
#[cfg(all(windows, feature = "native-probes"))]
pub mod native;
pub mod protocol;
