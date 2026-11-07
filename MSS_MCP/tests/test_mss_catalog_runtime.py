"""Portable operator runtime selection; no application or Remote is launched."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mss_profiles import Catalog, check_pin


class CatalogRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="mss-runtime-catalog-")
        self.addCleanup(self.fixture.cleanup)
        self.repo = Path(self.fixture.name)
        (self.repo / "MSS_MCP/profiles").mkdir(parents=True)
        (self.repo / "MSS_MCP/tools").mkdir()
        (self.repo / "MSS_MCP/tools/Start-MakepadMcp.ps1").write_bytes(b"# fixture\n")
        self.python = self.repo / "unrelated-python/python.exe"
        self.python.parent.mkdir()
        self.python.write_bytes(b"not executed")
        self.pwsh = self.repo / "operator-runtime/pwsh.exe"
        self.pwsh.parent.mkdir()
        self.pwsh.write_bytes(b"not executed either")
        self.config = {
            "schema_version": 1, "profiles": [], "launcher_sha256": "",
            "pwsh_executable": str(self.pwsh),
            "pwsh_sha256": hashlib.sha256(self.pwsh.read_bytes()).hexdigest(),
        }

    def catalog(self):
        (self.repo / "MSS_MCP/profiles/local.apps.json").write_text(
            json.dumps(self.config), encoding="utf-8")
        return Catalog(self.repo, self.python)

    def test_explicit_operator_path_does_not_depend_on_python_layout(self):
        catalog = self.catalog()
        self.assertEqual(catalog.pwsh, self.pwsh.resolve())
        check_pin(catalog.pwsh, catalog.pwsh_sha256)
        self.assertEqual(catalog.apps(), [])

    def test_existing_bundled_runtime_layout_remains_supported(self):
        del self.config["pwsh_executable"]
        bundled = self.python.parent.parent / "native/powershell/pwsh.exe"
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(self.pwsh.read_bytes())
        self.assertEqual(self.catalog().pwsh, bundled.resolve())

    def test_missing_explicit_path_never_falls_back_to_path(self):
        self.config["pwsh_executable"] = str(self.repo / "missing/pwsh.exe")
        with self.assertRaises(OSError):
            self.catalog()

    def test_relative_explicit_path_is_rejected(self):
        self.config["pwsh_executable"] = "pwsh.exe"
        with self.assertRaises(ValueError):
            self.catalog()

    def test_modified_runtime_is_rejected_by_same_pin_check(self):
        catalog = self.catalog()
        self.pwsh.write_bytes(b"modified fixture")
        with self.assertRaises(ValueError):
            check_pin(catalog.pwsh, catalog.pwsh_sha256)


if __name__ == "__main__":
    unittest.main()
