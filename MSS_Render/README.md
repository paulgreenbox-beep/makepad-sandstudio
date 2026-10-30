# MSS_Render

## Responsibility

Capture frames originating from each Makepad application's renderer, deliver them through MSS_API, and display the selected session in MSS_Desktop with freshness and ownership metadata.

## Planned frame contract

A frame should be bound to session ID, app process identity, renderer generation, monotonically increasing sequence, capture time, dimensions, pixel format, and a content digest. A stale frame or a frame from another session must not appear as the selected app's current state.

The inspected Makepad app Remote can request app-side GPU readback and return PNG data. This is a capture candidate, not proof of a general native GPU sharing API. The inspected hosted Vulkan code transfers swapchain descriptors on a Linux path; it does not establish a cross-platform MSS frame API. HostedView provides two presentations within one app, not multiple independent app sessions.

## Current state

`FrameStore` is an in-process latest-frame cache for supplied PNG bytes. Publish,
read and live removal require MSS_API authorization for the exact session and
generation. Keys retain the Core registry namespace. Identity and sequence are
checked before changing stored data; removing live pixels retains the sequence
watermark. The immutable Closed Session returned by Core permits exact-session
cache cleanup after the live record has been removed. A live Session snapshot
cannot authorize that cleanup. This controller capability is not a network API.

Limits cover per-frame and aggregate encoded bytes, cached frame and watermark
counts, dimensions and decoded bytes. Admission decodes a bounded static PNG
profile: noninterlaced 8-bit grayscale, RGB, grayscale-alpha or RGBA, with IHDR,
consecutive IDAT and final IEND chunks only. Chunk CRC, zlib/Adler integrity,
declared dimensions and decoded scanline length are checked. Other legal PNG
profiles/metadata are explicitly refused; this is not universal PNG conformance.
Rejected data must preserve the previous frame and watermark.

The decoded-byte cap limits accepted pixels, not exact peak process memory.
The pinned inflater's limit is best effort; temporary allocations also depend
on the bounded encoded input and decoder buffers. Host-selected bounds must be
conservative. No OS memory containment or adversarial-process sandbox is claimed.

The tests use synthetic PNG fixtures. App-origin authenticity, GPU capture,
capture time, process identity, content-digest evidence, transport/API streaming
and live Desktop presentation remain NOT_IMPLEMENTED / NOT_VERIFIED. Storing a
valid PNG does not prove that a Makepad renderer produced it. See
[verification](../doc/testing.md) and [dependency review](../doc/compatibility.md).
