"""Stage only the pinned Makepad fonts declared by the Windows Desktop PE."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct


MAKEPAD_REV = "130be1d0318adcf69453d925342607466353152c"
FONT_DIR = PurePosixPath("makepad_widgets/resources")
FONT_SHA256 = {
    "IBMPlexSans-Text.ttf": "8c358c56c56f76a28cecb8ca10734c1c9cafa01a752dc8364b9ef7de412437dc",
    "IBMPlexSans-SemiBold.ttf": "391bd290357cb19bacccd66dc82f3213e0c66c34025a4dd3e15c49d3db7c585e",
    "IBMPlexSans-Italic.ttf": "21effb0b8dabbbd6548db1c581c68c6335f6ffaabd6946a6a73ade24dec050eb",
    "IBMPlexSans-BoldItalic.ttf": "451f1e35cf09ef4411c9f38e7eb7d4967aef427c52e048dff26cc36393937882",
    "LiberationMono-Regular.ttf": "3e396ddd3d1c7d3dca1fb16dd64802b32f295f856ac10c0c1f2ab1c738196045",
    "fa-solid-900.ttf": "d2f0593540b0e33ba6de255a54f272d466e31144806956bea8cfdbf7edffc9bd",
    "LXGWWenKaiRegular.ttf": "0819604ad9357afbc6e7cc097328a16ed85143ee0848ffda09fda35a30da6506",
    "LXGWWenKaiBold.ttf": "7a356605eb36c92e29cc64090e2856e4675694572a2ae4da84adbadffecae907",
    "NotoColorEmoji.ttf": "39ee3c587e10e89669b9ff32703261d10d5f9c4dd5ad147b6b5a1c5200591817",
}


def font_manifest(pe):
    pe_offset = struct.unpack_from("<I", pe, 0x3C)[0]
    if pe[:2] != b"MZ" or pe[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("expected a Windows PE executable")
    machine, count = struct.unpack_from("<HH", pe, pe_offset + 4)
    if machine != 0x8664:
        raise ValueError("expected the Windows x64 Desktop executable")

    optional_size = struct.unpack_from("<H", pe, pe_offset + 20)[0]
    first_section = pe_offset + 24 + optional_size
    for index in range(count):
        offset = first_section + index * 40
        if pe[offset : offset + 8] != b".makepad":
            continue
        virtual_size, _, raw_size, raw_offset = struct.unpack_from("<IIII", pe, offset + 8)
        if virtual_size > raw_size or raw_offset + raw_size > len(pe):
            raise ValueError("invalid .makepad section bounds")
        manifest = pe[raw_offset : raw_offset + virtual_size]
        lines = manifest.decode("ascii").splitlines()
        expected = ["format=makepad.font-assets.v1", "set=International"]
        expected.extend(f"asset={FONT_DIR / name}" for name in FONT_SHA256)
        if lines != expected:
            raise ValueError("unexpected Makepad asset manifest; review the WiX resources and notices")
        return manifest
    raise ValueError("Desktop PE is missing the .makepad resource manifest")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def stage(exe, checkout, payload):
    desktop = exe.read_bytes()
    manifest = font_manifest(desktop)
    assets = {}
    for name, expected_hash in FONT_SHA256.items():
        source = checkout / "widgets" / "resources" / name
        data = source.read_bytes()
        if sha256(data) != expected_hash:
            raise ValueError(f"{name} does not match the pinned Makepad resource SHA-256")
        assets[name] = data

    directory = payload / "resources" / FONT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in assets.items():
        (directory / name).write_bytes(data)

    return {
        "makepad_revision": MAKEPAD_REV,
        "desktop_sha256": sha256(desktop),
        "font_manifest_sha256": sha256(manifest),
        "resources": [
            {
                "path": f"resources/{FONT_DIR / name}",
                "bytes": len(data),
                "sha256": FONT_SHA256[name],
            }
            for name, data in assets.items()
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--makepad-checkout", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = stage(args.exe, args.makepad_checkout, args.payload)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"cannot stage Makepad resources: {error}\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
