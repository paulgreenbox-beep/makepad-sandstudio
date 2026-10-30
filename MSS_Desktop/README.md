# MSS_Desktop

## Responsibility

Build the native Makepad desktop interface: session and app tabs, agent and test status, lifecycle controls, evidence access, and a selected-app viewing area.

## Planned interaction

The left panel shows independent sessions and their lifecycle/test state. The right panel displays a fresh frame delivered for the selected session by MSS_Render. All UI actions call MSS_API with the selected session identity; switching tabs must not transfer keyboard focus or input to another application.

The HostedView found in upstream Makepad presents full and tile views of one app and does not implement this multi-process host. The MSS interface remains a separate planned application.

## Current source prototype

The native shell in [src/main.rs](src/main.rs) renders a top bar, three illustrative session rows, status labels, and a no-frame placeholder. It uses the Makepad revision pinned in [Cargo.toml](Cargo.toml). It has no session backend, process ownership, app capture, Toolkit runner, or live accessibility contract. The view is a GUI prototype, not MSS runtime acceptance.

The prototype has not been compiled or exercised as a live application in this task. The full workspace Cargo check, if successful, proves compilation only.
