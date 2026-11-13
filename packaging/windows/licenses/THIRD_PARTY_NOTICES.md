# Third-party notices for Makepad SandStudio 0.1.0-preview.1

The Windows installer includes Makepad SandStudio under the MIT license in the installed `LICENSE` file. This directory identifies the code and assets supplied alongside it or incorporated in the Desktop executable.

- [Component inventory](COMPONENTS.json) identifies the pinned SDK, build dependency versions, font files and SHA-256 values.
- [Dependency licenses](DEPENDENCY-LICENSES.txt) contains original notices from the components listed in the inventory, including the Makepad B.V. MIT notice and the font license texts.
- [Makepad resource notices](MAKEPAD-RESOURCES.md) identifies embedded icons and separately installed fonts.
- [Rust standard library notices](RUST-COPYRIGHT.html) is the original copyright report from the Rust 1.97.1 Windows toolchain used to build the Desktop executable.

The Makepad source is pinned to [130be1d0318adcf69453d925342607466353152c](https://github.com/makepad/makepad/tree/130be1d0318adcf69453d925342607466353152c). For Makepad-authored code under a choice of terms, the bundle includes the Makepad MIT notice. Vendored or adapted third-party code retains its own notices. In particular, Makepad's `ab_glyph_rasterizer` fork includes changes relative to [published upstream 0.1.8](https://crates.io/crates/ab_glyph_rasterizer/0.1.8). The original Apache 2.0 text, Google 2015 font-rs attribution, Alex Butler 2020 attribution and stb notice apply alongside the Makepad fork's MIT notice. Makepad's root MIT text does not replace the upstream Apache 2.0 terms.

The source identifies derivative code in `makepad-fast-inflate` from libdeflate and miniz_oxide, in `makepad-git` from RustCrypto SHA-1, and in `makepad-regex` from Unicode 14.0.0 character data. The included licenses retain the original authors' notices where the source identifies them. Cargo build units include proc macros and build scripts. Final linker symbol membership is tracked separately in the release verification evidence.

Microsoft Windows, the device's GPU drivers, CPython, PowerShell, Makepad Remote, Codex CLI and approved guest applications are external prerequisites or separately supplied components. This installer does not contain RudraOffice, AI CAD, CPython, PowerShell, Makepad Remote or Codex. WiX, Cargo, rustc and the MSVC SDK are build tools.

This notice accompanies a private validation candidate. Public distribution remains blocked pending verification of the exact Liberation Mono corresponding source and applicable redistribution terms. The license texts preserve the historical Liberation 1.04 conditions for review.
