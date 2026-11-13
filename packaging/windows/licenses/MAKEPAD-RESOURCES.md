# Makepad resource notices

## Embedded application and file icons

The Desktop executable includes assets from the [seven Makepad theme icon families](https://github.com/makepad/makepad/tree/130be1d0318adcf69453d925342607466353152c/widgets/themes) at the pinned revision. [Makepad's generator](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/widgets/themes/build_icons.py) expresses application and file artwork as SVG geometry and mirrors selected file glyphs from Makepad's own `apps/files/resources/icons` directory. The same revision's [theme documentation](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/widgets/themes/README.md#L95-L104) describes original application symbols drawn in each OS's visual style.

The Makepad B.V. MIT notice in [Dependency licenses](DEPENDENCY-LICENSES.txt) covers Makepad-origin theme artwork. The family names describe rendering styles. Several additional application icons are checked in outside the generator's current catalog. The 56 additional assets have identical Git blobs in the [later Makepad app-icons crate](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/libs/app_icons/Cargo.toml), which declares MIT or Apache-2.0. The evidence records the Makepad introduction commit and the limit of independent authorship verification. Font Awesome's font license applies to the font file.

## Installed International fonts

The exact files, SHA-256 values, family and version metadata are in [Component inventory](COMPONENTS.json). The original font copyright and license notices are in [Dependency licenses](DEPENDENCY-LICENSES.txt).

| Font | Identity in the pinned SDK | Notice |
| --- | --- | --- |
| IBM Plex Sans Text, SemiBold, Italic and BoldItalic | IBM Corp. © 2018, publisher revision 5be84436 | SIL OFL 1.1 and reserved font name Plex |
| Font Awesome Free Solid | Font Awesome 6.7.2 | SIL OFL 1.1 for the desktop font |
| LXGW WenKai Regular and Bold | LXGW © 2021–2024 and The Klee Project Authors © 2020, release v1.330 | SIL OFL 1.1 |
| Noto Color Emoji | Google Inc. © 2022, release v2.047 | SIL OFL 1.1 |
| Liberation Mono Regular | Unmodified publisher Liberation Mono 2.1.5, OFL font package archived by Fedora | SIL OFL 1.1, original copyright and license included |

The package uses the original font bytes under the filenames expected by the pinned Makepad loader. The previous Liberation Mono 1.04 was replaced by 2.1.5. The IBM Plex Italic, BoldItalic and Font Awesome files come directly from the pinned publishers.
