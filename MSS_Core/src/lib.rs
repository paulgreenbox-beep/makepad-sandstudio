//! MSS_Core: architecture placeholder only.
//! No runtime behavior or Toolkit parity is implemented.
#![forbid(unsafe_code)]

/// Status of this crate's native integration.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImplementationStatus {
    /// Runtime integration has not been implemented or verified.
    NotImplemented,
}

/// Returns the truthful integration status.
pub const fn status() -> ImplementationStatus {
    ImplementationStatus::NotImplemented
}
