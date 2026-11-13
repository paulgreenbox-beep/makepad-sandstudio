# Windows MSI candidate

The preview branch distributes source. The local RC2 is an unsigned Windows x64 MSI candidate. WiX 3.14.1 builds a per-user installation, Start menu shortcut and standard Windows Installer uninstall. Build tools are only needed to create the MSI. Guest runtimes and app profiles are configured separately.

## Build the package

Build the locked Windows release executable using [BUILDING.md](../../BUILDING.md). Stage `mss-desktop.exe` at the payload root. Stage the five MSS Python modules and `Start-MakepadMcp.ps1` in `MSS_MCP/tools`, alongside the payload's `LICENSE`, `THIRD_PARTY_NOTICES.md` and `CONFIGURATION.md` at the root. Check all file pins before building.

```powershell
& $candle -nologo -arch x64 "-dPayloadDir=$payload" -out $object packaging/windows/MSS.wxs
& $light -nologo -out $msi $object
```

Set `$candle` and `$light` to the approved WiX executables and supply a staging directory and output paths. MSI ProductVersion uses `0.1.1`. The display label and source version are `0.1.0-preview.1`. The packaged program files are separate from the data root. Uninstall removes the installer-owned program and shortcut. The same-host test confirmed that its external data and profile files survived.

## Run an installed preview

Provision approved Python 3.12+ and PowerShell 7.4+, then configure the guest and its compatible official Makepad Remote as described in [CONFIGURATION.md](../../CONFIGURATION.md). The RC2 payload has no bundled Python, PowerShell, Codex, guest, Remote or standalone font files. The published `MSS.wxs` at the audited release base does not check runtime versions at installation.

A separate local MSI candidate adds file-version gates for both prerequisites. It rejected a missing Python and a missing PowerShell before copying product files. With explicitly selected standalone Python 3.14.10 and PowerShell 7.6.10, installation, one installed RudraOffice attach/render/detach scenario and uninstall passed on the development Windows host. Those gates and results belong to that candidate. Clean-host loading of Makepad resources remains `NOT_RUN`. Qualify the exact resources and notices before any binary release. [Known limitations](../../KNOWN_LIMITATIONS.md)
