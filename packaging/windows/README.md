# Windows MSI candidate

WiX 3.14.1 builds a per-user MSI, a Start menu shortcut and standard Windows Installer uninstall. The WiX tools are build-only. The MSI has no custom actions or bundled runtime/guest installers.

Build the locked Windows release executable. Stage it at the payload root with the five MSS Python modules and the PowerShell launcher under `MSS_MCP/tools`, and the reviewed documentation/license files. The package excludes user data, proofs, Python/PowerShell distributions, Codex, guest EXEs and Makepad source. Python 3.12+ and PowerShell 7.4+ are external requirements.

```powershell
& $candle -nologo -arch x64 "-dPayloadDir=$payload" -out $object packaging/windows/MSS.wxs
& $light -nologo -out $msi $object
```

MSI numeric ProductVersion uses `0.1.1` as Windows Installer's first preview revision. The display label and source version are `0.1.0-preview.1`. Stage and qualify the exact Makepad resource files and notices before public binary distribution. Keep local test MSI unsigned and outside Git. No user data is included in MSI components or removed on uninstall.
