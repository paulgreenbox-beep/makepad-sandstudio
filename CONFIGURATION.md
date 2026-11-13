# Local Windows configuration

Desktop loads `MSS_MCP/tools/mss_universal.py` beside the installed EXE, or from the workspace when run from Cargo's target tree. `MSS_RUNTIME_ROOT` can select an absolute runtime directory. The Windows installed layout stores profiles, process state and evidence under `%LOCALAPPDATA%\Makepad SandStudio`; `MSS_DATA_ROOT` selects an independent absolute directory. For source development the default data root is the checkout.

Install a trusted Python 3.12+ and PowerShell 7.4+ separately. Desktop resolves Python on PATH or through the absolute `MSS_DESKTOP_PYTHON` override. Set `MSS_PWSH_EXE` or the local catalog's `pwsh_executable` field to a trusted absolute PowerShell executable. Pin its SHA-256 and the shipped `Start-MakepadMcp.ps1` SHA-256 in the catalog. An empty or missing catalog is valid and exposes no application profiles.

Copy [apps.example.json](MSS_MCP/profiles/apps.example.json) to `MSS_MCP/profiles/local.apps.json` under the data root and set its pins. Add only explicitly admitted profiles. `profile_file` is relative to the data root; `profile_sha256` pins its bytes. A native profile declares its exact Makepad revision, hidden mode and compatible Remote capabilities. Its guest EXE and Makepad Remote are absolute operator-selected paths with SHA-256 pins. Keep local profiles and all user documents out of Git.

A profile defines access and launch policy. A registered build identifies a pinned executable admitted under its configured root. Where `configured_builds` is set, a build also binds a separately pinned descriptor for its arguments, worker, allowed environment and per-run directories. An empty allowlist keeps only the baseline. Removing an optional profile affects new router connections. Keep an owner connection open while its guests are needed.

RudraOffice, AI CAD, the DWG worker and Codex are external. For Codex recording analysis, use an installed authenticated CLI. `MSS_CODEX_EXE` selects its absolute path. Only explicitly selected recording files are delivered.
