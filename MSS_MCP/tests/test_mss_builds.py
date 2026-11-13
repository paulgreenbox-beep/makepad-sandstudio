"""Exercise the native build registry without launching applications."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mss_test_fixtures import add_owned_directory_cleanup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mss_builds import BuildError, BuildRegistry


VERIFICATION = {"statement": "Registry test attestation", "launcher_receipt": "fixture/session.json"}


class BuildRegistryTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        add_owned_directory_cleanup(self, fixture)
        self.repo = Path(fixture.name)
        (self.repo / "MSS_MCP" / "profiles").mkdir(parents=True)
        self.root = self.repo / "approved"
        self.root.mkdir()
        self.baseline = self.repo / "rudra-office-app.exe"
        self.baseline.write_bytes(b"MZ baseline fixture")
        self.template = {
            "app_executable": str(self.baseline),
            "app_sha256": self.digest(self.baseline),
        }
        self.candidate = self.root / self.baseline.name
        self.candidate.write_bytes(b"MZ new fixture")
        self.store = self.registry()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def registry(self):
        return BuildRegistry(self.repo, "rudraoffice", [str(self.root)], self.template)

    def cad_registry(self, admissions):
        return BuildRegistry(self.repo, "ai-cad", [str(self.root)], self.template, admissions=admissions)

    def admission(self, path, launch_config_sha256):
        return {(path.resolve(), self.digest(path).upper()): launch_config_sha256}

    def register(self, path=None, git_sha=None):
        path = path or self.candidate
        return self.store.register(str(path), self.digest(path), git_sha)

    def assert_error(self, code, action, *args):
        with self.assertRaises(BuildError) as caught:
            action(*args)
        self.assertEqual(caught.exception.code, code)

    def test_baseline_does_not_require_admission_under_candidate_root(self):
        selected = self.store.select()
        self.assertEqual(selected["build_id"], "baseline")
        self.assertEqual(Path(selected["exe_path"]), self.baseline)
        self.assertEqual(selected["sha256"].lower(), self.template["app_sha256"])
        self.assertIsNone(self.store.list()["previous_build_id"])
        self.assert_error("NO_PREVIOUS_BUILD", self.store.rollback, "baseline")

    def test_persists_selection_between_registry_instances_and_rolls_back(self):
        candidate = self.register(git_sha="b" * 40)
        candidate_id = candidate["build_id"]
        second = self.registry()
        self.assertEqual(second.select(candidate_id), candidate)
        self.assertEqual(second.select()["build_id"], "baseline")
        self.store.activate(candidate_id, "baseline", VERIFICATION)
        verified = candidate | {"verification": VERIFICATION}
        self.assertEqual(second.select(), verified)
        self.assertEqual(second.list()["previous_build_id"], "baseline")
        self.assertEqual(candidate["git_sha"], "b" * 40)
        second.rollback(candidate_id)
        self.assertEqual(self.store.select()["build_id"], "baseline")
        self.assertEqual(self.store.select(candidate_id), verified)
        self.assertEqual(self.register(git_sha="b" * 40), verified)

    def test_registration_is_idempotent_and_does_not_activate(self):
        first = self.register(git_sha="a" * 40)
        self.assertEqual(self.register(git_sha="a" * 40), first)
        inventory = self.registry().list()
        self.assertEqual(inventory["active_build_id"], "baseline")
        self.assertEqual({b["build_id"] for b in inventory["builds"]}, {"baseline", first["build_id"]})
        self.assertEqual(len(inventory["builds"]), 2)

    def test_registered_path_cannot_be_reused_for_changed_bytes(self):
        registered = self.register()
        self.candidate.write_bytes(b"MZ different build at the same path")
        self.assert_error("BUILD_CONFLICT", self.register)
        self.assertIn(registered, self.registry().list()["builds"])
        self.assertEqual(self.registry().select()["build_id"], "baseline")

    def test_baseline_path_is_reserved_even_when_inside_an_approved_root(self):
        store = BuildRegistry(self.repo, "baseline-example", [str(self.repo)], self.template)
        baseline = store.select()
        self.assertEqual(store.register(str(self.baseline), self.digest(self.baseline)), baseline)
        self.baseline.write_bytes(b"MZ different build at the baseline path")
        self.assert_error("BUILD_CONFLICT", store.register, str(self.baseline), self.digest(self.baseline))
        self.assertEqual(store.list()["builds"], [baseline])

    def test_candidate_path_must_resolve_inside_the_approved_directory(self):
        similar_root = self.repo / "approved-lookalike"
        similar_root.mkdir()
        escaped = similar_root / self.baseline.name
        escaped.write_bytes(b"MZ outside fixture")
        for path in (escaped, self.root / ".." / similar_root.name / escaped.name):
            with self.subTest(path=path):
                self.assert_error("BUILD_PATH_DENIED", self.store.register, str(path), self.digest(escaped))
        self.assertEqual(self.store.list()["active_build_id"], "baseline")
        self.assertEqual(len(self.store.list()["builds"]), 1)

    def test_wrong_executable_basename_cannot_register(self):
        wrong_name = self.root / "unrelated.exe"
        wrong_name.write_bytes(b"MZ unrelated fixture")
        self.assert_error("BUILD_PATH_DENIED", self.store.register, str(wrong_name), self.digest(wrong_name))
        self.assertEqual(len(self.store.list()["builds"]), 1)

    def test_alternate_stream_and_hard_link_cannot_register(self):
        stream = f"{self.candidate}:alias.exe"
        self.assert_error("BUILD_PATH_DENIED", self.store.register, stream, self.digest(self.candidate))
        alias = self.root / "alias" / self.baseline.name
        alias.parent.mkdir()
        os.link(self.baseline, alias)
        self.assert_error("BUILD_PATH_DENIED", self.store.register, str(alias), self.digest(self.baseline))
        self.assertEqual(len(self.store.list()["builds"]), 1)

    def test_wrong_registration_digest_does_not_persist_candidate(self):
        self.assert_error("BUILD_HASH_MISMATCH", self.store.register, str(self.candidate), "0" * 64)
        self.assertEqual(len(self.registry().list()["builds"]), 1)

    def test_missing_executable_and_invalid_digest_refuse_registration(self):
        missing = self.root / "missing" / self.baseline.name
        self.assert_error("BUILD_MISSING", self.store.register, str(missing), "0" * 64)
        self.assert_error("BUILD_ARGUMENT_INVALID", self.store.register, str(self.candidate), "not-sha256")
        self.assertEqual(len(self.registry().list()["builds"]), 1)

    def test_activation_requires_verification(self):
        candidate_id = self.register()["build_id"]
        self.assert_error("BUILD_VERIFICATION_REQUIRED", self.store.activate, candidate_id, "baseline", {})
        self.assertEqual(self.registry().select()["build_id"], "baseline")

    def test_candidate_drift_blocks_launch_and_activation(self):
        candidate_id = self.register()["build_id"]
        self.candidate.write_bytes(b"MZ changed after registration")
        self.assert_error("BUILD_HASH_MISMATCH", self.store.select, candidate_id)
        self.assert_error("BUILD_HASH_MISMATCH", self.store.activate, candidate_id, "baseline", VERIFICATION)
        self.assertEqual(self.registry().select()["build_id"], "baseline")

    def test_bad_active_executable_can_be_rolled_back_to_the_valid_baseline(self):
        candidate_id = self.register()["build_id"]
        self.store.activate(candidate_id, "baseline", VERIFICATION)
        self.candidate.write_bytes(b"MZ changed after activation")
        self.assert_error("BUILD_HASH_MISMATCH", self.store.select)
        self.store.rollback(candidate_id)
        self.assertEqual(self.registry().select()["build_id"], "baseline")

    def test_failed_rollback_leaves_the_current_build_active(self):
        candidate_id = self.register()["build_id"]
        self.store.activate(candidate_id, "baseline", VERIFICATION)
        self.baseline.write_bytes(b"MZ changed after activation")
        self.assert_error("BUILD_HASH_MISMATCH", self.store.rollback, candidate_id)
        self.assertEqual(self.registry().select()["build_id"], candidate_id)

    def test_concurrent_activation_allows_only_one_compare_and_swap(self):
        first = self.register()["build_id"]
        other = self.root / "another" / self.baseline.name
        other.parent.mkdir()
        other.write_bytes(b"MZ another fixture")
        second = self.register(other)["build_id"]
        begin = Barrier(2, timeout=5)

        def activate(build_id):
            registry = self.registry()
            begin.wait()
            try:
                registry.activate(build_id, "baseline", VERIFICATION)
            except BuildError as error:
                return error.code, build_id
            return "activated", build_id

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(activate, (first, second)))
        self.assertCountEqual([outcome for outcome, _ in results], ["activated", "BUILD_CONFLICT"])
        winner = next(build_id for outcome, build_id in results if outcome == "activated")
        self.assertEqual(self.registry().select()["build_id"], winner)
        self.assert_error("BUILD_CONFLICT", self.store.rollback, "baseline")

    def test_invalid_saved_state_fails_closed_without_rewriting_it(self):
        self.register()
        path = self.repo / "MSS_MCP" / "profiles" / "local.builds" / "rudraoffice.json"
        malformed = b'{"schema_version":1, "active_build_id":'
        path.write_bytes(malformed)
        self.assert_error("BUILD_STATE_INVALID", self.registry().list)
        self.assert_error("BUILD_STATE_INVALID", self.registry().select)
        self.assertEqual(path.read_bytes(), malformed)

    def test_unknown_build_cannot_replace_baseline(self):
        self.assert_error("UNKNOWN_BUILD", self.store.select, "unknown")
        self.assert_error("UNKNOWN_BUILD", self.store.activate, "unknown", "baseline", VERIFICATION)
        self.assertEqual(self.store.select()["build_id"], "baseline")

    def test_pinned_admission_binds_configuration_to_build_identity(self):
        config = "A" * 64
        store = self.cad_registry(self.admission(self.candidate, config))
        candidate = store.register(str(self.candidate), self.digest(self.candidate))
        path = os.path.normcase(str(self.candidate.resolve()))
        exe_sha256 = self.digest(self.candidate).upper()
        identity = hashlib.sha256(f"{path}\0{exe_sha256}\0{config}".encode("utf-8")).hexdigest()
        self.assertEqual(candidate["build_id"], "build_" + identity)
        self.assertEqual(candidate["launch_config_sha256"], config)
        self.assertEqual(store.select(candidate["build_id"]), candidate)
        self.assertNotIn("launch_config_sha256", store.select())
        dynamic = self.register()
        original_identity = hashlib.sha256(f"{path}\0{exe_sha256}".encode("utf-8")).hexdigest()
        self.assertEqual(dynamic["build_id"], "build_" + original_identity)
        self.assertNotIn("launch_config_sha256", dynamic)

    def test_pinned_registration_checks_exact_path_and_executable_digest(self):
        store = self.cad_registry(self.admission(self.candidate, "A" * 64))
        other = self.root / "other" / self.candidate.name
        other.parent.mkdir()
        other.write_bytes(self.candidate.read_bytes())
        self.assert_error("BUILD_NOT_ADMITTED", store.register, str(other), self.digest(other))
        self.assert_error("BUILD_NOT_ADMITTED", store.register, str(self.candidate), "B" * 64)
        self.assertEqual(store.list()["builds"], [store.select()])

    def test_revoked_configuration_lists_and_allows_rollback_to_baseline(self):
        store = self.cad_registry(self.admission(self.candidate, "A" * 64))
        candidate = store.register(str(self.candidate), self.digest(self.candidate))
        build_id = candidate["build_id"]
        store.activate(build_id, "baseline", VERIFICATION)
        revoked = self.cad_registry({})
        self.assertEqual(revoked.list()["active_build_id"], build_id)
        self.assertIn(candidate | {"verification": VERIFICATION}, revoked.list()["builds"])
        self.assert_error("BUILD_NOT_ADMITTED", revoked.select)
        self.assert_error("BUILD_NOT_ADMITTED", revoked.select, build_id)
        revoked.rollback(build_id)
        self.assertEqual(revoked.select()["build_id"], "baseline")
        self.assert_error("BUILD_NOT_ADMITTED", revoked.activate, build_id, "baseline", VERIFICATION)

    def test_rollback_refuses_revoked_previous_candidate(self):
        other = self.root / "other" / self.candidate.name
        other.parent.mkdir()
        other.write_bytes(b"MZ alternate admitted build")
        kept = self.admission(other, "B" * 64)
        store = self.cad_registry(kept | self.admission(self.candidate, "A" * 64))
        first = store.register(str(self.candidate), self.digest(self.candidate))["build_id"]
        second = store.register(str(other), self.digest(other))["build_id"]
        store.activate(first, "baseline", VERIFICATION)
        store.activate(second, first, VERIFICATION)
        revoked = self.cad_registry(kept)
        self.assert_error("BUILD_NOT_ADMITTED", revoked.rollback, second)
        self.assertEqual(revoked.select()["build_id"], second)
        self.assertEqual(revoked.list()["previous_build_id"], first)

    def test_changed_policy_cannot_reuse_previously_registered_path(self):
        store = self.cad_registry(self.admission(self.candidate, "A" * 64))
        candidate = store.register(str(self.candidate), self.digest(self.candidate))
        changed = self.cad_registry(self.admission(self.candidate, "B" * 64))
        self.assertIn(candidate, changed.list()["builds"])
        self.assert_error("BUILD_NOT_ADMITTED", changed.select, candidate["build_id"])
        self.assert_error("BUILD_CONFLICT", changed.register, str(self.candidate), self.digest(self.candidate))
        self.assertEqual(changed.select()["build_id"], "baseline")

    def test_state_config_digest_must_match_saved_identity(self):
        store = self.cad_registry(self.admission(self.candidate, "A" * 64))
        build_id = store.register(str(self.candidate), self.digest(self.candidate))["build_id"]
        state = json.loads(store.state_path.read_bytes())
        state["builds"][build_id]["launch_config_sha256"] = "B" * 64
        corrupted = json.dumps(state).encode("utf-8")
        store.state_path.write_bytes(corrupted)
        changed = self.cad_registry(self.admission(self.candidate, "B" * 64))
        self.assert_error("BUILD_STATE_INVALID", changed.list)
        self.assertEqual(store.state_path.read_bytes(), corrupted)

    def test_legacy_record_remains_listable_but_cannot_launch_under_admission(self):
        legacy = BuildRegistry(self.repo, "ai-cad", [str(self.root)], self.template)
        candidate = legacy.register(str(self.candidate), self.digest(self.candidate))
        store = self.cad_registry(self.admission(self.candidate, "A" * 64))
        self.assertIn(candidate, store.list()["builds"])
        self.assert_error("BUILD_NOT_ADMITTED", store.select, candidate["build_id"])


if __name__ == "__main__":
    unittest.main()
