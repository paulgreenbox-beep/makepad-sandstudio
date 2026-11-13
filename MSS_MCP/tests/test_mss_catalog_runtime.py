"""Portable operator runtime selection; no application or Remote is launched."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

helpers = os.environ.get("MSS_TEST_HELPERS")
if helpers:
    sys.path.insert(0, helpers)
tools = Path(os.environ.get("MSS_TEST_TOOLS", Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(tools))
from mss_profiles import Catalog, check_pin
from mss_universal import Router


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

    def test_missing_catalog_and_powershell_allow_empty_catalog_without_writes(self):
        data = self.repo / "new-user-state"
        catalog = Catalog(self.repo, self.python, data_root=data)
        self.assertEqual(catalog.apps(), [])
        self.assertFalse(data.exists())
        self.assertFalse(catalog.pwsh.exists())

    def test_explicit_root_separates_catalog_profiles_and_router_runtime(self):
        data = self.repo / "new-user-state"
        profiles = data / "MSS_MCP/profiles"
        profiles.mkdir(parents=True)
        self.config["profiles"] = [
            {"profile": "external", "title": "External", "kind": "native", "access": "semantic",
             "profile_file": "MSS_MCP/profiles/external.json", "profile_sha256": ""},
        ]
        (profiles / "local.apps.json").write_text(json.dumps(self.config), encoding="utf-8")
        external = profiles / "external.json"
        external.write_text("{}", encoding="utf-8")
        with patch.dict(os.environ, {"MSS_DATA_ROOT": str(data)}):
            router = Router(self.repo)
            self.assertEqual(router.catalog.apps()[0]["profile"], "external")
            self.assertEqual(router.catalog.repo_file(router.catalog.entries["external"]["profile_file"]),
                             external.resolve())
            self.assertTrue(router.launch_directory("app_fixture").parent.is_relative_to(data))
            router.store()
            self.assertTrue((profiles / "local.shared/control.sqlite3").is_file())
        self.assertFalse((self.repo / "proof").exists())
        self.assertFalse((self.repo / "MSS_MCP/profiles/local.shared").exists())

    def test_environment_powershell_override_uses_catalog_digest_without_fallback(self):
        self.config["profiles"] = [
            {"profile": "external", "title": "External", "kind": "native", "access": "semantic"},
        ]
        self.config["launcher_sha256"] = hashlib.sha256(
            (self.repo / "MSS_MCP/tools/Start-MakepadMcp.ps1").read_bytes()).hexdigest()
        candidate = self.repo / "custom.exe"
        candidate.write_bytes(b"wrong runtime bytes")
        run = self.repo / "run"
        run.mkdir()
        with patch.dict(os.environ, {"MSS_PWSH_EXE": str(candidate)}):
            catalog = self.catalog()
            self.assertEqual(catalog.pwsh, candidate)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                with catalog.prepare("external", run):
                    self.fail("PowerShell digest mismatch admitted launch")
        self.assertEqual(list(run.iterdir()), [])

    def test_relative_and_traversal_data_roots_are_rejected(self):
        for value in (Path("relative-state"), self.repo / ".." / "elsewhere"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Catalog(self.repo, self.python, data_root=value)


if __name__ == "__main__":
    unittest.main()
