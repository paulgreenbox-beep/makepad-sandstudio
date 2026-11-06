# MSS_SDK

## Responsibility

Provide a typed, opt-in application integration contract for stable semantic widget identity, declared actions, state readback, runtime health, telemetry, and observations.

## Planned contract

The app declares stable automation IDs and supported action capabilities. An action reply identifies its session, request, and app state generation. MSS observes the requested postcondition and runtime health independently. Unsupported operations return an explicit capability error; they are never translated to physical input without measured and accepted parity.

This SDK must stay a thin integration layer over the selected Makepad version. It must not copy or vendor Makepad crates. The version and source commit must be reviewed before any dependency or API is added.

## Current state

No SDK API, widget adapter, telemetry producer, or app integration is implemented. The tools-2 semantic contract is a prototype and does not establish an app-side producer.
