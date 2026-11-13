# Third-party notices

## Source preview

Makepad SandStudio's own files are covered by the repository [MIT license](LICENSE). The Rust build fetches Makepad from Git and other dependencies from crates.io as pinned in [Cargo.lock](Cargo.lock). The source preview references these dependencies. Their separate licenses apply to their respective source and binaries.

| Dependency | Attribution and terms |
| --- | --- |
| Makepad, `130be1d0318adcf69453d925342607466353152c` | Copyright (c) 2023 Makepad B.V. The root license is MIT. The pinned widgets, draw, and platform package manifests offer MIT or Apache-2.0. [Makepad source](https://github.com/makepad/makepad/tree/130be1d0318adcf69453d925342607466353152c) |
| Rust crates and Makepad's nested packages | Each package retains its own license. The target-independent lockfile includes packages under MIT, Apache-2.0, ISC, Zlib, CC0-1.0, Unlicense and Unicode-3.0, including alternative and combined expressions. [Pinned dependency list](Cargo.lock) |
| Components incorporated by Makepad | Its fast-inflate source identifies libdeflate (Eric Biggers, MIT) and miniz_oxide (its contributors, MIT). Its Git SHA-1 implementation identifies RustCrypto/hashes (MIT or Apache-2.0). Include their applicable attribution when distributing a build containing these components. [libdeflate](https://github.com/ebiggers/libdeflate), [miniz_oxide](https://github.com/Frommi/miniz_oxide), [RustCrypto/hashes](https://github.com/RustCrypto/hashes) |

## External runtime components

MSS may use separately installed Python, PowerShell, Codex and a guest's Makepad Remote executable. The Windows .NET runtime and ACadSharp apply only to the optional, separately provided experimental DWG guest. Each distribution has its own terms. The source preview excludes the runtime binaries, guest binaries and guest resources.

- [Python license](https://docs.python.org/3/license.html)
- [PowerShell license](https://github.com/PowerShell/PowerShell/blob/master/LICENSE.txt) and [third-party notices](https://github.com/PowerShell/PowerShell/blob/master/ThirdPartyNotices.txt)
- [Codex CLI source license](https://github.com/openai/codex/blob/main/docs/license.md)
- [ACadSharp license](https://github.com/DomCR/ACadSharp/blob/master/LICENSE)
- [.NET distribution licensing](https://github.com/dotnet/core/blob/main/license-information.md)

## Binary distribution

The installer requires a separate notice set generated from the exact packaged dependencies and resource files. Check Makepad fonts and icons individually. The cached Liberation Mono 1.04 belongs to the upstream v1 license family. Font Awesome Free 6.7.2 uses distinct terms for fonts and SVG icons. See the [license audit](LICENSE_AUDIT.md) for evidence and open items.
