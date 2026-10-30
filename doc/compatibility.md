# Rust Makepad Toolkit parity matrix (initial inventory)

**Goal: identical public test operation coverage; current status: NOT IMPLEMENTED.**
The authoritative, exact operation list is `prototypes/ai-ui-test-tool-auto-probe/operations.json` in rust-makepad-toolkit. This is a **category map**, not yet a complete per-operation inventory. Freeze revision and enumerate every operation before claiming coverage.

| Toolkit capability | MSS intended boundary | Status |
|---|---|---|
| Semantic tree / AutomationId / Invoke | SDK -> Remote -> API | NOT_IMPLEMENTED |
| Value / selection and independent readback | SDK + API | NOT_IMPLEMENTED |
| Keyboard / pointer / hotkey / drag / wheel | Remote, exact session | NOT_IMPLEMENTED |
| Spatial and canvas assertions | SDK + API | NOT_IMPLEMENTED |
| Windows HWND/bounds/DPI/frame gestures | native approved backend | NOT_IMPLEMENTED |
| GPU screenshot / visual assertions | Render + API | NOT_IMPLEMENTED |
| Runtime/async/API/log observation | SDK + API | NOT_IMPLEMENTED |
| Trusted file assertions and stability | API + owner policy | NOT_IMPLEMENTED |
| .aiui JSON runner/validation | reuse Toolkit runner adapter | NOT_IMPLEMENTED |
| Generator/inventory/coverage | reuse Toolkit contracts | NOT_IMPLEMENTED |
| Scheduler/worker pool/cancel | reuse Toolkit contracts, Core owner | NOT_IMPLEMENTED |
| Verification Core / evidence | reuse same thresholds and formats | NOT_IMPLEMENTED |
| Cleanup + ownership + health | Core + API | NOT_IMPLEMENTED |

For each future row capture exact operation ID, input/output schema, native mechanism, preconditions, postconditions, evidence, refusal cases and comparative test receipt. Preserve actual Windows UIA vs Makepad Remote semantic differences.
