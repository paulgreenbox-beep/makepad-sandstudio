# MSS_Render

## Responsibility

Capture frames originating from each Makepad application's renderer, deliver them through MSS_API, and display the selected session in MSS_Desktop with freshness and ownership metadata.

## Planned frame contract

A frame should be bound to session ID, app process identity, renderer generation, monotonically increasing sequence, capture time, dimensions, pixel format, and a content digest. A stale frame or a frame from another session must not appear as the selected app's current state.

The inspected Makepad app Remote can request app-side GPU readback and return PNG data. This is a capture candidate, not proof of a general native GPU sharing API. The inspected hosted Vulkan code transfers swapchain descriptors on a Linux path; it does not establish a cross-platform MSS frame API. HostedView provides two presentations within one app, not multiple independent app sessions.

## Current state

No frame transport, GPU interop, API stream, or Desktop display is implemented. Native rendering and per-session frame ownership remain NOT_VERIFIED.
