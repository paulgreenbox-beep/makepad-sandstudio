//! MSS_MCP: architecture placeholder, not a working runtime.
#![forbid(unsafe_code)]

/// Current implementation status.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImplementationStatus {
    /// Native integration has not been implemented.
    NotImplemented,
}

/// Reports the real current implementation state.
pub const fn status() -> ImplementationStatus {
    ImplementationStatus::NotImplemented
}
