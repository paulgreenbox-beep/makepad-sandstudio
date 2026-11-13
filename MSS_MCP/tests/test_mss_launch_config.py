"""Verify build-bound launch settings without starting an executable."""

import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mss_test_fixtures import add_owned_directory_cleanup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mss_builds import BuildError
from mss_profiles import Catalog


class LaunchConfigurationTests(unittest.TestCase):
    def setUp(self):
        fixture = TemporaryDirectory()
        add_owned_directory_cleanup(self, fixture)
        self.root = Path(fixture.name).resolve()
        self.catalog = Catalog.__new__(Catalog)
        self.catalog.repo = self.root
        self.catalog.pwsh = self.root / "pwsh.exe"
        self.catalog.launcher = self.root / "launcher.ps1"
        profiles = self.root / "MSS_MCP" / "profiles"
        profiles.mkdir(parents=True)
        self.descriptor = profiles / "cad-launch.json"
        approved = self.root / "approved"
        approved.mkdir()
        baseline = self.file(self.root / "cad.exe", b"MZ CAD baseline")
        self.candidate = self.file(approved / "cad.exe", b"MZ CAD candidate")
        remote = self.file(self.root / "remote.exe", b"MZ Remote fixture")
        dotnet = self.file(self.root / "dotnet.exe", b"MZ worker runtime")
        self.worker = self.file(self.root / "worker.dll", b"worker bytes")
        self.template = {
            "app_executable": str(baseline), "app_sha256": self.pin(baseline),
            "remote_executable": str(remote), "remote_sha256": self.pin(remote),
            "makepad_revision": "1" * 40, "app_arguments": [],
        }
        self.entry = {
            "profile": "ai-cad", "kind": "native", "access": "read-only",
            "build_roots": [str(approved)], "configured_builds": [],
        }
        self.catalog.entries = {"ai-cad": self.entry}
        self.catalog.native_template = lambda entry: dict(self.template)
        self.config = {
            "schema_version": 1, "profile": "ai-cad", "makepad_revision": "1" * 40,
            "app_arguments": ["--label", "DWG fixture with spaces"],
            "files": {
                "dotnet": {"path": str(dotnet), "sha256": self.pin(dotnet)},
                "worker": {"path": str(self.worker), "sha256": self.pin(self.worker)},
            },
            "environment": {
                "AI_REVIT_ACADSHARP_DOTNET": {"path": "dotnet"},
                "AI_REVIT_ACADSHARP_DOTNET_SHA256": {"sha256": "dotnet"},
                "AI_REVIT_ACADSHARP_WORKER": {"path": "worker"},
                "AI_REVIT_ACADSHARP_WORKER_SHA256": {"sha256": "worker"},
                "AI_REVIT_FILE_ROOTS": {"work_directory": "output"},
                "AI_REVIT_IMPORT_ROOTS": {"work_directory": "imports"},
            },
        }

    @staticmethod
    def file(path, content):
        path.write_bytes(content)
        return path

    @staticmethod
    def pin(path):
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()

    def register(self):
        self.descriptor.write_text(json.dumps(self.config), encoding="utf-8")
        self.entry["configured_builds"] = [{
            "exe_path": str(self.candidate), "sha256": self.pin(self.candidate),
            "launch_config_file": str(self.descriptor.relative_to(self.root)),
            "launch_config_sha256": self.pin(self.descriptor),
        }]
        return self.catalog.build_registry("ai-cad").register(str(self.candidate), self.pin(self.candidate))

    def prepare(self, folder, build_id):
        run = self.root / folder
        run.mkdir()
        return self.catalog.prepare_native("ai-cad", self.entry, run, build_id)

    def assert_refusal(self, expected, build):
        with self.assertRaises(BuildError) as caught:
            self.prepare("refused", build["build_id"])
        self.assertEqual(caught.exception.code, expected)
        self.assertFalse((self.root / "refused" / "profile.json").exists())

    def test_explicit_build_materializes_pinned_worker_args_and_fresh_directories(self):
        record = self.register()
        with patch.dict(os.environ, {"AI_REVIT_API_TOKEN": "ambient", "AI_REVIT_ACADSHARP_WORKER": "ambient"}):
            first = self.prepare("first", record["build_id"])
            second = self.prepare("second", record["build_id"])
        materialized = json.loads((first.cwd.parent / "profile.json").read_bytes())
        self.assertEqual(first.app_image, self.candidate)
        self.assertEqual(first.build_id, record["build_id"])
        self.assertEqual(materialized["launch_config_sha256"], self.pin(self.descriptor))
        self.assertEqual(materialized["app_arguments"], ["--label", "DWG fixture with spaces"])
        self.assertEqual(first.env["AI_REVIT_ACADSHARP_WORKER"], str(self.worker))
        self.assertEqual(first.env["AI_REVIT_ACADSHARP_WORKER_SHA256"], self.pin(self.worker))
        self.assertEqual(first.env["AI_REVIT_IMPORT_ROOTS"], str(first.cwd / "imports"))
        self.assertTrue(Path(first.env["AI_REVIT_IMPORT_ROOTS"]).is_dir())
        self.assertNotEqual(first.env["AI_REVIT_FILE_ROOTS"], second.env["AI_REVIT_FILE_ROOTS"])
        self.assertNotIn("AI_REVIT_API_TOKEN", first.env)
        baseline = self.prepare("baseline", None)
        self.assertEqual(baseline.build_id, "baseline")
        self.assertNotIn("AI_REVIT_ACADSHARP_WORKER", baseline.env)

    def test_configured_build_with_other_makepad_revision_is_refused(self):
        self.config["makepad_revision"] = "2" * 40
        self.assert_refusal("BUILD_CONFIG_INCOMPATIBLE", self.register())

    def test_changed_launch_descriptor_is_refused(self):
        build = self.register()
        self.descriptor.write_text("{}", encoding="utf-8")
        self.assert_refusal("BUILD_CONFIG_INVALID", build)

    def test_changed_worker_is_refused_before_materializing_profile(self):
        build = self.register()
        self.worker.write_bytes(b"replacement")
        self.assert_refusal("BUILD_CONFIG_INVALID", build)

    def test_unapproved_environment_key_is_refused(self):
        self.config["environment"]["PATH"] = {"work_directory": "injected"}
        self.assert_refusal("BUILD_CONFIG_INVALID", self.register())

    def test_remote_flag_is_reserved(self):
        self.config["app_arguments"] = ["--remote=127.0.0.1:1"]
        self.assert_refusal("BUILD_CONFIG_INVALID", self.register())

    def test_mismatched_worker_hash_reference_is_refused(self):
        self.config["environment"]["AI_REVIT_ACADSHARP_WORKER_SHA256"] = {"sha256": "dotnet"}
        self.assert_refusal("BUILD_CONFIG_INVALID", self.register())


if __name__ == "__main__":
    unittest.main()
