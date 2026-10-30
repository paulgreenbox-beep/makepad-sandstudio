//! Bounded storage for externally supplied, independently identified frames.
//! Admission decodes a bounded static PNG profile. No capture, GPU sharing,
//! producer authenticity, or Makepad transport is established.
#![forbid(unsafe_code)]
use makepad_zune_core::{bytestream::ZCursor, options::DecoderOptions};
use makepad_zune_inflate::{DeflateDecoder, DeflateOptions};
use makepad_zune_png::PngDecoder;
use mss_api::{Api, ApiError, RequestContext};
use mss_core::{Session, SessionGeneration, SessionHandle, SessionId, SessionState};
use std::collections::BTreeMap;

/// The encoded payload kind; none indicates a GPU shared texture.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameFormat {
    Png,
}

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
    /// A cache, replay-fence, or decoding allocation bound was reached.
    CapacityExceeded,
    /// Cleanup requires an immutable logical Closed receipt from Core.
    InvalidClosedSession,
}
impl From<ApiError> for FrameError {
    fn from(e: ApiError) -> Self {
        Self::Api(e)
    }
}

/// Host-selected bounds. These are memory/admission policy, not GPU evidence.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FrameLimits {
    /// Maximum encoded bytes in one frame.
    pub per_frame_cap: usize,
    /// Maximum encoded bytes retained across frames.
    pub total_encoded_cap: usize,
    /// Maximum simultaneously retained frames.
    pub frame_count_cap: usize,
    /// Maximum exact-incarnation replay fences, including live forgotten frames.
    pub watermark_count_cap: usize,
    /// Maximum admitted PNG width.
    pub max_width: u32,
    /// Maximum admitted PNG height.
    pub max_height: u32,
    /// Maximum accepted pixel bytes, not peak temporary allocation or host RAM.
    /// The pinned inflater's best-effort limit can overshoot; scratch memory
    /// also depends on the independently bounded encoded input and decoder state.
    pub max_decoded_bytes: usize,
}

/// Bounded latest-frame cache with persistent live-session sequence fences.
pub struct FrameStore {
    limits: FrameLimits,
    frames: BTreeMap<SessionId, Frame>,
    watermarks: BTreeMap<(SessionId, SessionGeneration), u64>,
    total_encoded: usize,
}
impl FrameStore {
    /// Constructs a cache with an explicit maximum encoded frame size.
    pub fn new(per_frame_cap: usize) -> Self {
        Self::with_limits(FrameLimits {
            per_frame_cap,
            total_encoded_cap: per_frame_cap.saturating_mul(64),
            frame_count_cap: 64,
            watermark_count_cap: 256,
            max_width: 4096,
            max_height: 4096,
            max_decoded_bytes: 16 * 1024 * 1024,
        })
    }

    /// Zero bounds deny admission. No frame is evicted to satisfy a quota.
    pub fn with_limits(limits: FrameLimits) -> Self {
        Self {
            limits,
            frames: BTreeMap::new(),
            watermarks: BTreeMap::new(),
            total_encoded: 0,
        }
    }

    /// Stores a frame for the exact authorized session. This is not render proof.
    pub fn publish(
        &mut self,
        api: &Api<'_>,
        ctx: RequestContext,
        frame: Frame,
    ) -> Result<(), FrameError> {
        api.authorize(ctx)?;
        if ctx.session != frame.identity.session
            || frame.identity.sequence == 0
            || frame.width == 0
            || frame.height == 0
            || frame.bytes.is_empty()
            || frame.bytes.len() > self.limits.per_frame_cap
        {
            return Err(FrameError::InvalidFrame);
        }
        let key = ctx.session.id;
        let fence = (key, ctx.session.generation);
        if self
            .watermarks
            .get(&fence)
            .is_some_and(|last| frame.identity.sequence <= *last)
        {
            return Err(FrameError::StaleSequence);
        }
        let old_size = self.frames.get(&key).map_or(0, |old| old.bytes.len());
        let total = self
            .total_encoded
            .checked_sub(old_size)
            .and_then(|n| n.checked_add(frame.bytes.len()))
            .ok_or(FrameError::CapacityExceeded)?;
        if total > self.limits.total_encoded_cap
            || (!self.frames.contains_key(&key) && self.frames.len() >= self.limits.frame_count_cap)
            || (!self.watermarks.contains_key(&fence)
                && self.watermarks.len() >= self.limits.watermark_count_cap)
        {
            return Err(FrameError::CapacityExceeded);
        }
        validate_png(&frame, &self.limits)?;
        // Every refusal above precedes both cache and replay-fence mutations.
        self.watermarks.insert(fence, frame.identity.sequence);
        self.frames.insert(key, frame);
        self.total_encoded = total;
        Ok(())
    }

    /// Reads the latest frame for one authorized session.
    pub fn latest<'a>(
        &'a self,
        api: &Api<'_>,
        ctx: RequestContext,
    ) -> Result<&'a Frame, FrameError> {
        api.authorize(ctx)?;
        self.frames
            .get(&ctx.session.id)
            .filter(|frame| frame.identity.session == ctx.session)
            .ok_or(FrameError::NotAvailable)
    }

    /// Authorized live pixel removal; sequence history remains until close.
    pub fn forget(&mut self, api: &Api<'_>, ctx: RequestContext) -> Result<bool, FrameError> {
        api.authorize(ctx)?;
        Ok(self.remove_pixels(ctx.session))
    }

    /// Release only the exact incarnation recorded by Core's immutable Closed
    /// receipt. This proves logical cache cleanup, never native process cleanup.
    pub fn forget_closed(&mut self, closed: &Session) -> Result<bool, FrameError> {
        if closed.state() != SessionState::Closed {
            return Err(FrameError::InvalidClosedSession);
        }
        let handle = closed.handle();
        let pixels = self.remove_pixels(handle);
        let fence = self
            .watermarks
            .remove(&(handle.id, handle.generation))
            .is_some();
        Ok(pixels || fence)
    }

    fn remove_pixels(&mut self, handle: SessionHandle) -> bool {
        if self
            .frames
            .get(&handle.id)
            .is_some_and(|f| f.identity.session == handle)
        {
            let removed = self
                .frames
                .remove(&handle.id)
                .expect("matched exact cached frame");
            self.total_encoded -= removed.bytes.len();
            true
        } else {
            false
        }
    }
}

fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = u32::MAX;
    for byte in bytes {
        crc ^= u32::from(*byte);
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xedb8_8320 & 0u32.wrapping_sub(crc & 1));
        }
    }
    !crc
}

/// Deliberately narrower than universal PNG: only static noninterlaced 8-bit
/// grayscale/RGB/grayscale-alpha/RGBA, IHDR + consecutive IDAT + IEND, no metadata.
/// Legal palette, 16-bit, interlaced, ancillary-metadata and APNG files are refused.
fn validate_png(frame: &Frame, limits: &FrameLimits) -> Result<(), FrameError> {
    let invalid = FrameError::InvalidFrame;
    let bytes = &frame.bytes;
    if !bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Err(invalid);
    }
    let mut cursor = 8usize;
    let mut components = None;
    let mut idat = Vec::new();
    let mut ended = false;
    while cursor < bytes.len() {
        let header = bytes
            .get(cursor..cursor.checked_add(8).ok_or(invalid)?)
            .ok_or(invalid)?;
        let length = u32::from_be_bytes(header[..4].try_into().map_err(|_| invalid)?) as usize;
        let data_start = cursor.checked_add(8).ok_or(invalid)?;
        let data_end = data_start.checked_add(length).ok_or(invalid)?;
        let end = data_end.checked_add(4).ok_or(invalid)?;
        let data = bytes.get(data_start..data_end).ok_or(invalid)?;
        let expected_crc = u32::from_be_bytes(
            bytes
                .get(data_end..end)
                .ok_or(invalid)?
                .try_into()
                .map_err(|_| invalid)?,
        );
        if crc32(bytes.get(cursor + 4..data_end).ok_or(invalid)?) != expected_crc {
            return Err(invalid);
        }
        match &header[4..8] {
            b"IHDR" if cursor == 8 && length == 13 => {
                let width = u32::from_be_bytes(data[..4].try_into().map_err(|_| invalid)?);
                let height = u32::from_be_bytes(data[4..8].try_into().map_err(|_| invalid)?);
                if width != frame.width
                    || height != frame.height
                    || width == 0
                    || height == 0
                    || width > limits.max_width
                    || height > limits.max_height
                    || data[8] != 8
                    || data[10..] != [0, 0, 0]
                {
                    return Err(invalid);
                }
                components = Some(match data[9] {
                    0 => 1usize,
                    2 => 3,
                    4 => 2,
                    6 => 4,
                    _ => return Err(invalid),
                });
            }
            b"IDAT" if components.is_some() && !ended => {
                idat.try_reserve(data.len())
                    .map_err(|_| FrameError::CapacityExceeded)?;
                idat.extend_from_slice(data);
            }
            b"IEND"
                if components.is_some()
                    && !idat.is_empty()
                    && length == 0
                    && end == bytes.len() =>
            {
                ended = true;
            }
            _ => return Err(invalid),
        }
        cursor = end;
    }
    if !ended || idat.len() < 6 || idat[1] & 0x20 != 0 {
        return Err(invalid);
    }
    let width = usize::try_from(frame.width).map_err(|_| invalid)?;
    let height = usize::try_from(frame.height).map_err(|_| invalid)?;
    let row = width
        .checked_mul(components.ok_or(invalid)?)
        .ok_or(invalid)?;
    let decoded_size = row
        .checked_mul(height)
        .filter(|n| *n <= limits.max_decoded_bytes)
        .ok_or(invalid)?;
    let filtered_size = row
        .checked_add(1)
        .and_then(|n| n.checked_mul(height))
        .ok_or(invalid)?;
    let inflate_options = DeflateOptions::default()
        .set_limit(filtered_size)
        .set_size_hint(filtered_size)
        .set_confirm_checksum(true);
    // Upstream checks the limit after some copies and omits it on literal paths.
    // Treat it as best effort: temporary allocation also depends on encoded size,
    // not a fixed decoded-limit overhead. This is not a process RAM boundary.
    let filtered = DeflateDecoder::new_with_options(&idat, inflate_options)
        .decode_zlib()
        .map_err(|_| invalid)?;
    if filtered.len() != filtered_size || filtered.chunks_exact(row + 1).any(|line| line[0] > 4) {
        return Err(invalid);
    }
    drop(filtered);
    // The pinned public inflater does not expose consumed input length. Reject
    // ignored trailing compressed bytes: removing the final checksum byte from
    // a complete, checksum-verified stream must make it undecodable.
    if DeflateDecoder::new_with_options(&idat[..idat.len() - 1], inflate_options)
        .decode_zlib()
        .is_ok()
    {
        return Err(invalid);
    }
    let options = DecoderOptions::default()
        .set_strict_mode(true)
        .set_use_unsafe(false)
        .set_max_width(width)
        .set_max_height(height)
        .png_set_decode_animated(false);
    let mut decoder = PngDecoder::new_with_options(ZCursor::new(bytes.as_slice()), options);
    decoder.decode_headers().map_err(|_| invalid)?;
    if decoder.dimensions() != Some((width, height))
        || decoder.output_buffer_size() != Some(decoded_size)
    {
        return Err(invalid);
    }
    let mut decoded = Vec::new();
    decoded
        .try_reserve_exact(decoded_size)
        .map_err(|_| FrameError::CapacityExceeded)?;
    decoded.resize(decoded_size, 0);
    decoder.decode_into(&mut decoded).map_err(|_| invalid)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use mss_core::{RegistryError, SessionRegistry};
    fn sample(ctx: RequestContext, sequence: u64) -> Frame {
        Frame {
            identity: FrameIdentity {
                session: ctx.session,
                sequence,
            },
            width: 1,
            height: 1,
            format: FrameFormat::Png,
            bytes: include_bytes!("../tests/fixtures/rgba1x1.png.bin").to_vec(),
        }
    }
    #[test]
    fn bounded_frames_and_monotonic_sequence() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let id = r.create_session(a, "A").unwrap();
        let ctx = RequestContext {
            agent: a,
            session: r.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut store = FrameStore::new(100);
        store.publish(&api, ctx, sample(ctx, 1)).unwrap();
        assert_eq!(store.latest(&api, ctx).unwrap().identity.sequence, 1);
        assert_eq!(
            store.publish(&api, ctx, sample(ctx, 1)),
            Err(FrameError::StaleSequence)
        );
        store.publish(&api, ctx, sample(ctx, 2)).unwrap();
        assert_eq!(store.forget(&api, ctx), Ok(true));
        assert_eq!(store.latest(&api, ctx), Err(FrameError::NotAvailable));
    }
    #[test]
    fn forbidden_cross_session_and_foreign_read() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let b = r.register_agent().unwrap();
        let id = r.create_session(a, "A").unwrap();
        let other = r.create_session(b, "B").unwrap();
        let ctx = RequestContext {
            agent: a,
            session: r.get_session(id).unwrap().handle(),
        };
        let foreign = RequestContext {
            agent: b,
            session: r.get_session(id).unwrap().handle(),
        };
        let different = RequestContext {
            agent: b,
            session: r.get_session(other).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut store = FrameStore::new(100);
        assert_eq!(
            store.publish(&api, foreign, sample(ctx, 1)),
            Err(FrameError::Api(ApiError::Registry(
                RegistryError::ForeignSession
            )))
        );
        assert_eq!(
            store.publish(&api, different, sample(ctx, 1)),
            Err(FrameError::InvalidFrame)
        );
        assert_eq!(store.latest(&api, different), Err(FrameError::NotAvailable));
    }
    #[test]
    fn rejects_large_and_empty_frames() {
        let mut r = SessionRegistry::new();
        let a = r.register_agent().unwrap();
        let id = r.create_session(a, "A").unwrap();
        let ctx = RequestContext {
            agent: a,
            session: r.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut store = FrameStore::new(8);
        assert_eq!(
            store.publish(&api, ctx, sample(ctx, 1)),
            Err(FrameError::InvalidFrame)
        );
    }

    fn limits() -> FrameLimits {
        FrameLimits {
            per_frame_cap: 4096,
            total_encoded_cap: 8192,
            frame_count_cap: 8,
            watermark_count_cap: 16,
            max_width: 4096,
            max_height: 4096,
            max_decoded_bytes: 16 * 1024 * 1024,
        }
    }

    fn chunk(kind: &[u8; 4], data: &[u8]) -> Vec<u8> {
        let mut result = (data.len() as u32).to_be_bytes().to_vec();
        result.extend_from_slice(kind);
        result.extend_from_slice(data);
        let crc = crc32(&result[4..]);
        result.extend_from_slice(&crc.to_be_bytes());
        result
    }

    fn stored_zlib(raw: &[u8]) -> Vec<u8> {
        let len = u16::try_from(raw.len()).unwrap();
        let mut bytes = vec![0x78, 0x01, 0x01];
        bytes.extend_from_slice(&len.to_le_bytes());
        bytes.extend_from_slice(&(!len).to_le_bytes());
        bytes.extend_from_slice(raw);
        let (mut a, mut b) = (1u32, 0u32);
        for byte in raw {
            a = (a + u32::from(*byte)) % 65521;
            b = (b + a) % 65521;
        }
        bytes.extend_from_slice(&((b << 16) | a).to_be_bytes());
        bytes
    }

    fn png_with_idat(idat: &[u8]) -> Vec<u8> {
        let mut bytes = include_bytes!("../tests/fixtures/rgba1x1.png.bin")[..33].to_vec();
        bytes.extend_from_slice(&chunk(b"IDAT", idat));
        bytes.extend_from_slice(&chunk(b"IEND", &[]));
        bytes
    }

    fn repair_ihdr_crc(bytes: &mut [u8]) {
        let crc = crc32(&bytes[12..29]);
        bytes[29..33].copy_from_slice(&crc.to_be_bytes());
    }

    #[test]
    fn malformed_png_refusals_preserve_frame_and_sequence_fence() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let id = r.create_session(agent, "PNG validation").unwrap();
        let ctx = RequestContext {
            agent,
            session: r.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut store = FrameStore::with_limits(limits());
        store.publish(&api, ctx, sample(ctx, 1)).unwrap();
        let original = store.latest(&api, ctx).unwrap().clone();
        let valid = sample(ctx, 2);
        let mut bad_crc = valid.clone();
        bad_crc.bytes[29] ^= 1;
        let mut truncated = valid.clone();
        truncated.bytes.pop();
        let mut mismatch = valid.clone();
        mismatch.width = 2;
        let mut junk = valid.clone();
        junk.bytes = b"\x89PNG\r\n\x1a\nexample".to_vec();
        let mut invalid_idat = valid.clone();
        invalid_idat.bytes = png_with_idat(b"not zlib");
        let mut short = valid.clone();
        short.bytes = png_with_idat(&stored_zlib(&[0; 4]));
        let mut extra = valid.clone();
        extra.bytes = png_with_idat(&stored_zlib(&[0; 6]));
        let mut invalid_filter = valid.clone();
        invalid_filter.bytes = png_with_idat(&stored_zlib(&[5, 0, 0, 0, 255]));
        let mut bad_adler = stored_zlib(&[0, 0, 0, 0, 255]);
        *bad_adler.last_mut().unwrap() ^= 1;
        let mut checksum = valid.clone();
        checksum.bytes = png_with_idat(&bad_adler);
        let mut trailing_zlib = stored_zlib(&[0, 0, 0, 0, 255]);
        trailing_zlib.push(0);
        let mut trailing = valid.clone();
        trailing.bytes = png_with_idat(&trailing_zlib);
        let mut after_iend = valid.clone();
        after_iend.bytes.push(0);
        let mut empty = valid.clone();
        empty.bytes.clear();
        let mut bomb = valid.clone();
        bomb.bytes = png_with_idat(include_bytes!(
            "../tests/fixtures/overlong-scanline.zlib.bin"
        ));
        assert!(bomb.bytes.len() < 200); // encoded84B inflates to65536B, expected5B.
        let mut metadata = valid.clone();
        metadata
            .bytes
            .splice(33..33, chunk(b"zTXt", b"bomb\0\0compressed metadata"));
        let mut huge = valid.clone();
        huge.width = u32::MAX;
        huge.bytes[16..20].copy_from_slice(&u32::MAX.to_be_bytes());
        repair_ihdr_crc(&mut huge.bytes);
        for (name, frame) in [
            ("signature-only junk", junk),
            ("CRC", bad_crc),
            ("truncated", truncated),
            ("dimension mismatch", mismatch),
            ("invalid IDAT", invalid_idat),
            ("short scanline", short),
            ("extra scanline bytes", extra),
            ("invalid filter", invalid_filter),
            ("Adler", checksum),
            ("zlib trailing bytes", trailing),
            ("PNG trailing bytes", after_iend),
            ("empty", empty),
            ("compressed expansion bomb", bomb),
            ("metadata", metadata),
            ("huge dimensions", huge),
        ] {
            assert_eq!(
                store.publish(&api, ctx, frame),
                Err(FrameError::InvalidFrame),
                "{name}"
            );
            assert_eq!(store.latest(&api, ctx), Ok(&original), "{name}");
        }
        store.publish(&api, ctx, valid).unwrap();
        assert_eq!(store.latest(&api, ctx).unwrap().identity.sequence, 2);
    }

    #[test]
    fn legal_profiles_outside_static_admission_and_decoded_limit_are_refused() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let id = r.create_session(agent, "Profile").unwrap();
        let ctx = RequestContext {
            agent,
            session: r.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut store = FrameStore::with_limits(limits());
        let mut interlaced = sample(ctx, 1);
        interlaced.bytes[28] = 1;
        repair_ihdr_crc(&mut interlaced.bytes);
        assert_eq!(
            store.publish(&api, ctx, interlaced),
            Err(FrameError::InvalidFrame)
        );
        let mut sixteen = sample(ctx, 1);
        sixteen.bytes = png_with_idat(&stored_zlib(&[0; 9]));
        sixteen.bytes[24] = 16;
        repair_ihdr_crc(&mut sixteen.bytes);
        assert_eq!(
            store.publish(&api, ctx, sixteen),
            Err(FrameError::InvalidFrame)
        );
        let mut cap = limits();
        cap.max_decoded_bytes = 3;
        let mut constrained = FrameStore::with_limits(cap);
        assert_eq!(
            constrained.publish(&api, ctx, sample(ctx, 1)),
            Err(FrameError::InvalidFrame)
        );
        assert_eq!(constrained.latest(&api, ctx), Err(FrameError::NotAvailable));
        store.publish(&api, ctx, sample(ctx, 1)).unwrap();
    }

    #[test]
    fn frame_count_and_encoded_budgets_refuse_without_eviction_or_fence_advance() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let a = r.create_session(agent, "A").unwrap();
        let b = r.create_session(agent, "B").unwrap();
        let a = RequestContext {
            agent,
            session: r.get_session(a).unwrap().handle(),
        };
        let b = RequestContext {
            agent,
            session: r.get_session(b).unwrap().handle(),
        };
        let api = Api::new(&r);
        for (frame_count_cap, total_encoded_cap) in [(1, 146), (2, 73)] {
            let mut cap = limits();
            cap.frame_count_cap = frame_count_cap;
            cap.total_encoded_cap = total_encoded_cap;
            let mut store = FrameStore::with_limits(cap);
            store.publish(&api, a, sample(a, 1)).unwrap();
            assert_eq!(
                store.publish(&api, b, sample(b, 1)),
                Err(FrameError::CapacityExceeded)
            );
            assert_eq!(store.latest(&api, a).unwrap().identity.sequence, 1);
            assert_eq!(store.latest(&api, b), Err(FrameError::NotAvailable));
            assert_eq!(store.forget(&api, a), Ok(true));
            store.publish(&api, b, sample(b, 1)).unwrap();
            assert_eq!(
                store.publish(&api, a, sample(a, 1)),
                Err(FrameError::StaleSequence)
            );
            assert_eq!(
                store.publish(&api, a, sample(a, 2)),
                Err(FrameError::CapacityExceeded)
            );
            assert_eq!(store.forget(&api, b), Ok(true));
            store.publish(&api, a, sample(a, 2)).unwrap();
        }
    }

    #[test]
    fn live_forget_keeps_bounded_watermark_until_exact_closed_receipt() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let a = r.create_session(agent, "A").unwrap();
        let b = r.create_session(agent, "B").unwrap();
        let a = RequestContext {
            agent,
            session: r.get_session(a).unwrap().handle(),
        };
        let b = RequestContext {
            agent,
            session: r.get_session(b).unwrap().handle(),
        };
        let mut cap = limits();
        cap.watermark_count_cap = 1;
        let mut store = FrameStore::with_limits(cap);
        {
            let api = Api::new(&r);
            store.publish(&api, a, sample(a, 9)).unwrap();
            assert_eq!(store.forget(&api, a), Ok(true));
            assert_eq!(store.forget(&api, a), Ok(false));
            assert_eq!(
                store.publish(&api, a, sample(a, 9)),
                Err(FrameError::StaleSequence)
            );
            assert_eq!(
                store.publish(&api, b, sample(b, 1)),
                Err(FrameError::CapacityExceeded)
            );
            store.publish(&api, a, sample(a, 10)).unwrap();
            assert_eq!(
                store.forget_closed(r.get_session(a.session.id).unwrap()),
                Err(FrameError::InvalidClosedSession)
            );
            assert_eq!(store.latest(&api, a).unwrap().identity.sequence, 10);
        }
        let closed = r.close_owned_session(a.session, agent).unwrap();
        assert_eq!(store.forget_closed(&closed), Ok(true));
        assert_eq!(store.forget_closed(&closed), Ok(false));
        let api = Api::new(&r);
        assert_eq!(
            store.forget(&api, a),
            Err(FrameError::Api(ApiError::Registry(
                RegistryError::UnknownSession
            )))
        );
        store.publish(&api, b, sample(b, 1)).unwrap();
        assert_eq!(store.latest(&api, b).unwrap().identity.sequence, 1);
    }

    #[test]
    fn unauthorized_forget_and_other_registry_receipts_preserve_owned_frame() {
        let mut r = SessionRegistry::new();
        let owner = r.register_agent().unwrap();
        let foreign = r.register_agent().unwrap();
        let id = r.create_session(owner, "Owned").unwrap();
        let ctx = RequestContext {
            agent: owner,
            session: r.get_session(id).unwrap().handle(),
        };
        let api = Api::new(&r);
        let mut store = FrameStore::new(100);
        store.publish(&api, ctx, sample(ctx, 1)).unwrap();
        assert_eq!(
            store.forget(
                &api,
                RequestContext {
                    agent: foreign,
                    ..ctx
                }
            ),
            Err(FrameError::Api(ApiError::Registry(
                RegistryError::ForeignSession
            )))
        );
        let stale = RequestContext {
            session: SessionHandle {
                generation: SessionGeneration::new(2).unwrap(),
                ..ctx.session
            },
            ..ctx
        };
        assert_eq!(
            store.forget(&api, stale),
            Err(FrameError::Api(ApiError::Registry(
                RegistryError::StaleGeneration
            )))
        );
        assert_eq!(
            store.publish(&api, stale, sample(stale, 2)),
            Err(FrameError::Api(ApiError::Registry(
                RegistryError::StaleGeneration
            )))
        );
        assert_eq!(store.latest(&api, ctx).unwrap().identity.sequence, 1);
        let mut other = SessionRegistry::new();
        let other_agent = other.register_agent().unwrap();
        let other_id = other
            .create_session(other_agent, "Independent namespace")
            .unwrap();
        let other_ctx = RequestContext {
            agent: other_agent,
            session: other.get_session(other_id).unwrap().handle(),
        };
        let other_api = Api::new(&other);
        store
            .publish(&other_api, other_ctx, sample(other_ctx, 2))
            .unwrap();
        assert_eq!(store.latest(&api, ctx).unwrap().identity.sequence, 1);
        assert_eq!(
            store
                .latest(&other_api, other_ctx)
                .unwrap()
                .identity
                .sequence,
            2
        );
        let other_closed = other
            .close_owned_session(other_ctx.session, other_agent)
            .unwrap();
        assert_eq!(store.forget_closed(&other_closed), Ok(true));
        assert_eq!(store.latest(&api, ctx).unwrap().identity.sequence, 1);
        assert_eq!(store.forget(&api, ctx), Ok(true));
        assert_eq!(
            store.publish(&api, ctx, sample(ctx, 1)),
            Err(FrameError::StaleSequence)
        );
    }

    #[test]
    fn closed_receipt_does_not_erase_pixels_or_fence_of_another_generation() {
        let mut r = SessionRegistry::new();
        let agent = r.register_agent().unwrap();
        let id = r.create_session(agent, "Generation cleanup").unwrap();
        let ctx = RequestContext {
            agent,
            session: r.get_session(id).unwrap().handle(),
        };
        let mut store = FrameStore::new(100);
        store.publish(&Api::new(&r), ctx, sample(ctx, 1)).unwrap();
        // Core does not expose runtime rebinding. Arrange only cache state here
        // to prove the exact-incarnation cleanup contract, not new authority.
        let next_handle = SessionHandle {
            generation: SessionGeneration::new(2).unwrap(),
            ..ctx.session
        };
        let next_ctx = RequestContext {
            session: next_handle,
            ..ctx
        };
        let future_frame = sample(next_ctx, 7);
        let encoded = future_frame.bytes.len();
        store.frames.insert(id, future_frame.clone());
        store.watermarks.insert((id, next_handle.generation), 7);
        let closed = r.close_owned_session(ctx.session, agent).unwrap();
        assert_eq!(store.forget_closed(&closed), Ok(true));
        assert_eq!(store.forget_closed(&closed), Ok(false));
        assert_eq!(store.frames.get(&id), Some(&future_frame));
        assert_eq!(
            store.watermarks.get(&(id, next_handle.generation)),
            Some(&7)
        );
        assert!(!store.watermarks.contains_key(&(id, ctx.session.generation)));
        assert_eq!(store.total_encoded, encoded);
    }
}
