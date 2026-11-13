# Configure the Windows preview

## 1. Choose the source or installed layout

| Layout | Program root | Default data root |
| --- | --- | --- |
| Source build in the default Cargo target tree | Workspace containing `MSS_MCP/tools/mss_universal.py` | Workspace |
| Installed MSI | Directory beside `mss-desktop.exe`, with `MSS_MCP/tools` beside it | `%LOCALAPPDATA%\Makepad SandStudio` for Desktop |

Set `MSS_DATA_ROOT` to a short, absolute local data directory. Give Desktop and each AI Direct connection the same value to use the same catalog and share instances. A standalone router started without this setting uses its program root for data. `MSS_RUNTIME_ROOT` is an optional absolute program-root override for Desktop. Keep data outside the installed program directory and out of Git. [Runtime paths](MSS_Desktop/src/runtime_paths.rs) · [Router startup](MSS_MCP/tools/mss_universal.py)

Install an approved Python 3.12+ and PowerShell 7.4+. Use an absolute `MSS_DESKTOP_PYTHON` for a reproducible Desktop startup. Otherwise Desktop looks for Python on PATH (skipping the Microsoft Store alias directory), then checks its development fallback in the Codex cache. For guest launches the router selects PowerShell from the absolute `MSS_PWSH_EXE` override or catalog `pwsh_executable`. A legacy catalog without either setting looks for the bundled sibling layout. It verifies the selected EXE against `pwsh_sha256` and verifies `Start-MakepadMcp.ps1` against `launcher_sha256`. [PowerShell selection and admission](MSS_MCP/tools/mss_profiles.py)

After following [BUILDING.md](BUILDING.md) for a source build or installing an approved local MSI, run Desktop from PowerShell with the selected program and runtime paths:

```powershell
# Set these to the actual absolute paths for this installation or checkout.
$env:MSS_DATA_ROOT = 'C:\MSS\data'
$env:MSS_DESKTOP_PYTHON = 'C:\Runtimes\Python\python.exe'
$env:MSS_PWSH_EXE = 'C:\Runtimes\PowerShell\pwsh.exe'
$desktopExe = 'C:\MSS\program\mss-desktop.exe'
& $desktopExe
```

The MSI needs external runtimes and a separately admitted guest. See [what the installer contains and checks](packaging/windows/README.md) and [the path limitation](KNOWN_LIMITATIONS.md). The example paths above are placeholders. Use existing authorized directories and runtimes.

## 2. Admit the guest and its Makepad Remote

Start with [the example catalog](MSS_MCP/profiles/apps.example.json). Copy it to `MSS_MCP/profiles/local.apps.json` under the selected data root. The example is empty. An empty or absent catalog yields no profiles. Keep the program root separate from the data root for an installed instance.

1. Select the built guest EXE and the compatible official Makepad Remote EXE. Qualify native hidden startup, Remote support and required capabilities for the exact guest build. Makepad rev `2271c0eb350cedd497c84373f17ad2b0b662cb72` is the tested guest baseline. Supply the actual revision for your guest.
2. Use `Get-FileHash -LiteralPath <path> -Algorithm SHA256` for the guest, Remote, approved PowerShell and the installed or source launcher. Record the actual values. Pins are local operator admission decisions.
3. Write a UTF-8 JSON profile template under the data root. For a native profile use the fields below. Set `remote_supported` and `hidden_native_supported` only after checking them. The launcher controls Remote and hidden mode and passes `app_arguments` as literal strings. Keep Remote and stdin-loop switches out of that array.

| Native template field | Value |
| --- | --- |
| `schema_version`, `id`, `admission` | `1`, a launcher ID such as `rudra-office-work`, and `"TRUSTED_DEVELOPMENT"` |
| `makepad_revision` | Exact 40-character revision for the guest and its compatibility check |
| `app_executable`, `app_sha256` | Approved absolute local guest EXE path and SHA-256 |
| `remote_executable`, `remote_sha256` | Approved absolute local Makepad Remote EXE path and SHA-256 |
| `remote_supported`, `hidden_native_supported` | `true` for a qualified native profile |
| `app_arguments` | Literal argument array. Use `[]` if the guest needs none. |
| `working_directory`, `session_root` | Absolute local directories when validating the template directly. The router materializes its own directories for each launch. |

4. Hash the template file after saving it. Set catalog `pwsh_executable`, `pwsh_sha256` and `launcher_sha256`. Add a `profiles` entry with `profile`, `title`, `kind: "native"`, `access: "semantic"` or `"read-only"`, `profile_file` relative to the data root and `profile_sha256` for the template bytes. Use `rudraoffice` or `ai-cad` to bind the corresponding Desktop tabs. Local profiles and documents stay outside Git.
5. Start a new router connection and call `mss_list_apps`. The catalog is loaded per connection. Keep the owning connection open while its guest is in use.

To validate a native template directly, supply its existing directories and absolute paths. This verifies its declared fields and executable hashes. The launcher returns `VALIDATED` before guest execution. Use the MSS launch checks below for runtime proof.

```powershell
$launcher = 'C:\MSS\program\MSS_MCP\tools\Start-MakepadMcp.ps1'
$profileFile = 'C:\MSS\data\MSS_MCP\profiles\my-guest.json'
& $env:MSS_PWSH_EXE -NoLogo -NoProfile -NonInteractive -File $launcher -Profile $profileFile -ValidateOnly
```

[Catalog and materialization](MSS_MCP/tools/mss_profiles.py) · [Profile validation](MSS_MCP/tools/Start-MakepadMcp.ps1)

## 3. Register and choose a build

A native catalog entry can use its pinned template baseline directly. To enable candidate registration, set a nonempty `build_roots` list of authorized local directories. Where `configured_builds` is present, admission also matches the exact `exe_path` and `sha256` to a separately pinned `launch_config_file` and `launch_config_sha256`. An empty `configured_builds` array admits the baseline only. A launch descriptor binds schema version, profile, guest Makepad revision, literal arguments, file pins and profile-allowlisted environment references. Use the [descriptor parser](MSS_MCP/tools/mss_profiles.py) for the supported fields and use the AI CAD worker settings only with separately admitted exact binaries.

| Step | MCP tool and required arguments |
| --- | --- |
| Inspect the baseline and active build | `mss_list_builds(profile)` |
| Register a candidate from an admitted directory | `mss_register_build(profile, exe_path, sha256)`. Optional `git_sha` is provenance. |
| Launch the selected build | `mss_launch_app(profile, build_id)`. Omitting `build_id` selects the active build or the pinned profile baseline. |
| Promote a private candidate after live verification | `mss_activate_build(profile, build_id, expected_active, app_id, verification)`. Obtain a tree and PNG, perform the intended test action and confirm its postcondition with `mss_ui_wait`. Keep the candidate private and avoid subsequent mutations that invalidate the evidence. |
| Roll back future launches | `mss_rollback_build(profile, expected_active)`. Inspect current state before deciding after a conflict. |

Registration leaves the active build unchanged. Activate and rollback affect future launches. Close test-owned processes through MSS and retain their receipts. [Build registry](MSS_MCP/tools/mss_builds.py) · [Tool catalog](MSS_MCP/tools/mss_universal.py)

## 4. Use AI Direct and Human View on the same instance

1. Configure a standard MCP client to run the approved Python with `-I -B <absolute program root>/MSS_MCP/tools/mss_universal.py` over stdio. Pass the absolute `MSS_DATA_ROOT` and the catalog-pinned `MSS_PWSH_EXE` in its environment. The router takes no app or profile command-line argument. [Agent rules](AGENTS.md) · [MCP module](MSS_MCP/README.md)
2. On the owning MCP connection call `mss_list_apps`, then `mss_launch_app` with the profile and optional candidate ID. Keep the returned App ID. Call `mss_status` for the selected process and window, and use the same App ID for `mss_ui_tree`, `mss_ui_find`, `mss_grab` and further actions. Use the selected numeric window index for `mss_grab` and require `capture_kind: "pixels"` for a native pixel capture. Verify results by fresh observations.
3. For a Human View of that same instance, the owner calls `mss_share_app` with the App ID and `mode: "read"` or `"control"`. In Desktop, use **Shared app**, **Find shared apps** and **Attach App ID**. Confirm the App ID and PID. The owner and participant must share the data root and Windows session. A read attachment can view the frame. Human View resize, mouse and keyboard are available for the admitted RudraOffice owner or control attachment. AI CAD is view-only in Desktop. Keep the owner connected. **Detach view** leaves the guest running. Closing the app belongs to the owner.
4. For a Desktop-owned launch, select **RudraOffice A**, **RudraOffice B** or **AI CAD**, then **Launch selected app**. These tabs select the configured active build. Use the AI-owned launch and explicit sharing flow above when you need both interfaces on one instance. [Human View](MSS_Desktop/README.md)

## 5. Record and review a demonstration

On a controlled RudraOffice view, start a recording, perform the demonstration, then stop. Choose the permitted data categories and describe the expected result. Select **Prepare for Codex**, review the files, then select **Send to Codex** if you authorize the handoff. **Screenshot** separately saves the guest PNG. For delivery, use an approved authenticated Codex CLI, or set `MSS_CODEX_EXE` to its absolute path. The bounded analysis uses the reviewed package. Treat delivery as received only after the matching model receipt and do not retry an unknown delivery automatically. [Handoff implementation](MSS_Desktop/src/codex_handoff.rs) · [Verification scope](TESTING.md)
