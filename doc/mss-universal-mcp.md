# Use MSS as one local MCP

Follow the build steps in the [README](../README.md#getting-started) from the repository root. Generate profiles from the locally built Todo, Counter, and Makepad Remote executables. The launcher uses a new working directory and private temporary directory for each app instance.

The active catalogue is `MSS_MCP/profiles/local.apps.json`. Its profile references are relative to the MSS repository. The generated Todo and Counter profiles live under `local/makepad-profiles/` and record absolute local executable paths and SHA-256 digests. After an intentional rebuild or replacement, archive the old generated catalogue and profile files locally, review the new binaries, and run the initializer again. The initializer refuses to overwrite existing records with different content. If the build used a custom `CARGO_TARGET_DIR` or `--target-dir`, give the initializer that same directory through `-TargetDirectory`.

For an additional app, start from [the blocked profile template](../MSS_MCP/profiles/application.example.json). Verify the exact Makepad revision, native Remote and hidden-window support, executable hashes, and isolated test data. Set the admission fields only after confirming these requirements. Add the reviewed profile to the local catalogue. The `mss` MCP registration is shared across profiles.

## Todo example

These are MCP tool calls to make from a new local Codex chat.

1. Call `mss_list_apps({})`.
2. Call `mss_launch_app({"profile":"todo"})` and save the returned `app_id`.
3. Call `mss_ui_tree({"app_id":"<APP_ID>","json":true})`. Find `todo_input` and `add_button` in the returned tree. Use the exact node ID and window ID returned for this app.
4. Set the input value and read the tree again to verify the value before pressing Add.

```text
mss_ui_act({"app_id":"<APP_ID>","w":"<WINDOW_ID>","node":"<INPUT_NODE>","action":"set_value","v":"MSS demo"})
mss_ui_tree({"app_id":"<APP_ID>","json":true})
mss_ui_act({"app_id":"<APP_ID>","w":"<WINDOW_ID>","node":"<ADD_NODE>","action":"press","wait":true})
mss_ui_wait({"app_id":"<APP_ID>","q":"name=\"MSS demo\"","json":true})
mss_grab({"app_id":"<APP_ID>"})
mss_close_app({"app_id":"<APP_ID>"})
```

Use the latest tree when resolving the Add button. The wait result should contain the new Todo item. `mss_grab` returns the app's PNG and its metadata. `mss_close_app` returns `CLOSED` after checking the launcher's normal exit receipt.

`mss_find_app` lists instances for the current MCP connection. `mss_status` reports process and window status, `mss_logs` reads the app log, and `mss_ui_find` searches semantic nodes. `mss_ui_type` uses an advertised semantic text replacement action. A node ID is meaningful in the app and window whose tree supplied it.

## Testing

From the MSS repository root, run the Rust workspace checks.

```powershell
cargo check --workspace --all-targets --locked
cargo test --workspace --locked
```

The connector tests take the generated profile paths and a local evidence directory. The profile checks exercise admission and argument validation. The native test runs Todo and Counter through the existing launcher and checks the app state, PNG capture, and normal cleanup.

```powershell
$repo = (Get-Location).Path
$catalog = Get-Content MSS_MCP/profiles/local.apps.json -Raw | ConvertFrom-Json
$todo = $catalog.profiles | Where-Object profile -eq 'todo'
$counter = $catalog.profiles | Where-Object profile -eq 'counter'
$todoProfile = Join-Path $repo $todo.profile_file
$counterProfile = Join-Path $repo $counter.profile_file
$evidence = Join-Path $repo 'proof/public-checks'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null

pwsh -NoProfile -File MSS_MCP/tests/Test-MakepadProfiles.ps1 -BaselineProfile $todoProfile -EvidenceRoot $evidence
pwsh -NoProfile -File MSS_MCP/tests/Test-NativeMcpProfiles.ps1 -TodoProfile $todoProfile -CounterProfile $counterProfile -EvidenceRoot $evidence
```

With `mss` registered, the Codex probe opens two ephemeral App Server sessions and calls MCP directly. It checks separate Todo instances, state, PNG, ownership, and cleanup without a model turn. Pass the native `codex.exe` path to the probe. If it is outside `PATH`, set `$codex` to its absolute path.

```powershell
$python = (Get-Command python.exe -ErrorAction Stop).Source
$codex = (Get-Command codex.exe -CommandType Application -ErrorAction Stop).Source
& $python -I -B MSS_MCP/tests/verify_mss_codex.py --codex $codex --workspace $repo --evidence-root $evidence
```

To exercise the upstream Rust GUI tests, use the test target in the pinned Makepad checkout. Set `CARGO_TARGET_DIR` in that shell so the harness and its child Cargo process use the same build target. The example selects one existing `#[makepad_test]` smoke test. It is an upstream app test, separate from MSS's connector checks.

```powershell
$env:CARGO_TARGET_DIR = Join-Path $repo 'makepad-work-target'
cargo test --manifest-path makepad-work/Cargo.toml --release --locked -p makepad-example-todo --test ui -- todo_smoke --exact --test-threads=1
```

For your own Makepad app, put `#[makepad_test]` cases in its `tests/` directory, use the compatible upstream `makepad-test` dependency, and run that app's normal Cargo test target. Assert the result by reading the semantic tree after an action and verify the app shuts down.
When the upstream test harness rebuilds a fixture executable, compare its hash with the admitted profile. Archive and regenerate the local profiles if the hash changes before launching that fixture again.
