//! Bounded storage for externally supplied, independently identified frames.
//! No capture, GPU sharing, decoding or Makepad transport is implemented.
#![forbid(unsafe_code)]
use mss_api::{Api, ApiError, RequestContext};
use mss_core::SessionHandle;
use std::collections::BTreeMap;

/// The encoded payload kind; none indicates a GPU shared texture.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameFormat { Png }

/// Frame identity is bound to an exact session incarnation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FrameIdentity {
    /// Exact session handle.
    pub session: SessionHandle,
    /// Monotonically increasing sequence within one session.
    pub sequence: u64,
}

/// A frame received from a future trusted producer, without authenticity claim.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Frame {
    /// Identity for provenance checks.
    pub identity: FrameIdentity,
    /// Pixel width declared by producer.
    pub width: u32,
    /// Pixel height declared by producer.
    pub height: u32,
    /// Bytes encoding.
    pub format: FrameFormat,
    /// Encoded frame bytes.
    pub bytes: Vec<u8>,
}

/// Reasons a frame cannot be stored or retrieved.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameError {
    /// Session and owner mismatch or stale handle.
    Api(ApiError),
    /// Empty or oversized/malformed payload.
    InvalidFrame,
    /// Frame sequence reused or old.
    StaleSequence,
    /// No frame has been submitted for this session.
    NotAvailable,
}
impl From<ApiError> for FrameError { fn from(e: ApiError) -> Self { Self::Api(e) } }

/// Bounded latest-frame cache; avoids unbounded history allocations.
pub struct FrameStore {
    per_frame_cap: usize,
    frames: BTreeMap<u64, Frame>,
}
impl FrameStore {
    /// Constructs a cache with an explicit maximum encoded frame size.
    pub fn new(per_frame_cap: usize) -> Self { Self { per_frame_cap, frames: BTreeMap::new() } }

    /// Stores a frame for the exact authorized session. This is not render proof.
    pub fn publish(&mut self, api: &Api<'_>, ctx: RequestContext, frame: Frame) -> Result<(), FrameError> {
        api.authorize(ctx)?;
        if ctx.session != frame.identity.session || frame.identity.sequence == 0
            || frame.width == 0 || frame.height == 0
            || frame.bytes.is_empty() || frame.bytes.len() > self.per_frame_cap
            || !frame.bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
            return Err(FrameError::InvalidFrame);
        }
        let key = ctx.session.id.get();
        if self.frames.get(&key).is_some_and(|old|
            old.identity.session == ctx.session && frame.identity.sequence <= old.identity.sequence) {
            return Err(FrameError::StaleSequence);
        }
        self.frames.insert(key, frame);
        Ok(())
    }

    /// Reads the latest frame for one authorized session.
    pub fn latest<'a>(&'a self, api: &Api<'_>, ctx: RequestContext) -> Result<&'a Frame, FrameError> {
        api.authorize(ctx)?;
        self.frames.get(&ctx.session.id.get())
            .filter(|frame| frame.identity.session == ctx.session)
            .ok_or(FrameError::NotAvailable)
    }

    /// Drop cached pixels when the owning session is closed.
    pub fn forget(&mut self, handle: SessionHandle) {
        if self.frames.get(&handle.id.get()).is_some_and(|f| f.identity.session == handle) {
            self.frames.remove(&handle.id.get());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mss_core::{RegistryError, SessionRegistry};
    fn sample(ctx: RequestContext, sequence: u64) -> Frame {
        Frame { identity: FrameIdentity { session:ctx.session, sequence }, width:1, height:1,
            format:FrameFormat::Png, bytes:b"\x89PNG\r\n\x1a\nexample".to_vec() }
    }
    #[test]
    fn bounded_frames_and_monotonic_sequence() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let id = r.create_session(a, "A").unwrap();
        let ctx = RequestContext {agent:a,session:r.get_session(id).unwrap().handle()};
        let api = Api::new(&r);
        let mut store = FrameStore::new(100);
        store.publish(&api, ctx, sample(ctx,1)).unwrap();
        assert_eq!(store.latest(&api,ctx).unwrap().identity.sequence,1);
        assert_eq!(store.publish(&api,ctx,sample(ctx,1)),Err(FrameError::StaleSequence));
        store.publish(&api,ctx,sample(ctx,2)).unwrap();
        store.forget(ctx.session);
        assert_eq!(store.latest(&api,ctx),Err(FrameError::NotAvailable));
    }
    #[test]
    fn forbidden_cross_session_and_foreign_read() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let b = r.register_agent().unwrap();
        let id = r.create_session(a, "A").unwrap();
        let other = r.create_session(b, "B").unwrap();
        let ctx = RequestContext {agent:a,session:r.get_session(id).unwrap().handle()};
        let foreign = RequestContext {agent:b,session:r.get_session(id).unwrap().handle()};
        let different = RequestContext {agent:b,session:r.get_session(other).unwrap().handle()};
        let api = Api::new(&r);
        let mut store = FrameStore::new(100);
        assert_eq!(store.publish(&api, foreign, sample(ctx,1)),
            Err(FrameError::Api(ApiError::Registry(RegistryError::ForeignSession))));
        assert_eq!(store.publish(&api,different,sample(ctx,1)),Err(FrameError::InvalidFrame));
        assert_eq!(store.latest(&api,different),Err(FrameError::NotAvailable));
    }
    #[test]
    fn rejects_large_and_empty_frames() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let id = r.create_session(a, "A").unwrap();
        let ctx = RequestContext {agent:a,session:r.get_session(id).unwrap().handle()};
        let api = Api::new(&r);
        let mut store = FrameStore::new(8);
        assert_eq!(store.publish(&api,ctx,sample(ctx,1)),Err(FrameError::InvalidFrame));
    }
}
