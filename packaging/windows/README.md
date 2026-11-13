# Windows MSI candidate

WiX 3.14.1 creates a per-user Windows x64 installation with a Start menu shortcut and standard Windows Installer uninstall. The preview branch distributes source. Keep local unsigned candidates out of public release assets until the package is qualified and all redistribution terms are satisfied.

## Build the package

Build from the pinned source and Cargo.lock as described in [BUILDING.md](../../BUILDING.md). Set the Makepad package root at compile time and use a separate Cargo target directory for the MSI build. Symbol stripping removes development debug data. Use rustc path remapping for source/build paths when building a release and audit the resulting PE separately because remapping does not cover all embedded strings.

```powershell
$env:MAKEPAD_PACKAGE_DIR = 'resources'
$env:CARGO_PROFILE_RELEASE_STRIP = 'symbols'
cargo build -p mss-desktop --release --locked --target-dir $packageTarget
```

Use a fresh staging directory. Stage the packaged `mss-desktop.exe`, `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `CONFIGURATION.md` at the payload root. Stage the five MSS Python modules and `Start-MakepadMcp.ps1` under `MSS_MCP/tools`, and stage the five reviewed license and inventory files from `packaging/windows/licenses` under `licenses`.

The pinned Makepad loader resolves the packaged paths relative to the executable when launched from an unrelated working directory. The staging script checks the PE's exact International font manifest and the SHA-256 of each required font, then copies nine files under `resources/makepad_widgets/resources` beside the executable. The pinned theme SVGs are embedded by Makepad.

```powershell
& $python -I -B packaging/windows/stage_makepad_resources.py `
    --exe "$payload/mss-desktop.exe" --makepad-checkout $makepadCheckout --payload $payload
& $candle -nologo -arch x64 "-dPayloadDir=$payload" -out $object packaging/windows/MSS.wxs
& $light -nologo -out $msi $object
```

Set the tool variables to approved executables. Use the checkout at `130be1d0318adcf69453d925342607466353152c` for `$makepadCheckout`, and set `$object` and `$msi` to local output paths. Keep the staging receipt with the package verification evidence. MSI ProductVersion is `0.1.1`, while the display and source version is `0.1.0-preview.1`.

## Run an installed preview

Provision CPython 3.12+ and PowerShell 7.4+. The MSI checks the runtime versions and reports a missing prerequisite before installation. It checks registered supported CPython versions and the standard PowerShell 7 directory, and accepts explicit runtime directories for standalone installs.

```powershell
msiexec.exe /i "$msi" "PYTHONRUNTIMEDIR=$pythonDirectory" "PWSHRUNTIMEDIR=$powerShellDirectory"
```

The properties name directories containing `python.exe` and `pwsh.exe`. At runtime point `MSS_DESKTOP_PYTHON` and `MSS_PWSH_EXE` to the approved executables when needed. Configure the operator-supplied guest and its compatible official Makepad Remote as described in [CONFIGURATION.md](../../CONFIGURATION.md). Installed program files and the external data root have separate lifecycles. MSI uninstall removes installer-owned files and the shortcut. See [known limitations](../../KNOWN_LIMITATIONS.md) for the qualification and release scope.
