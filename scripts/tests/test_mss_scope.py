"""Pure scope/graph/fixture regressions; no Rust or Windows qualification."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "mss_scope.py"
spec = importlib.util.spec_from_file_location("mss_scope", MODULE_PATH)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)
POLICY_PATH = MODULE_PATH.parents[1] / "doc/plans/mss-scope-v2.json"


def fixture():
    policy = scope.decode(POLICY_PATH.read_bytes())
    rows = [{"id": key, "depends_on": [], "tests": ["T-019"],
             "acceptance": "Preserve exact original assertions"}
            for key in sorted(scope.PRODUCT_IDS | scope.EXTERNAL_IDS)]
    by_id = {r["id"]: r for r in rows}
    by_id["A02"]["files"] = [".github/workflows/mss-verify.yml (disabled до B06)"]
    by_id["A13"]["depends_on"] = ["A09", "A12", "B06"]
    by_id["B06"]["depends_on"] = ["A02", "B05"]
    inv = sorted(scope.MANDATORY) + [f"fixture-invariant-{i}" for i in range(44)]
    checks = policy["independent_verification_gate"]["equivalent_checks_from"][:]
    checks += [f"fixture-check-{i}" for i in range(68 - len(checks))]
    data = {
        "pr-backlog.json": {"backlog": rows},
        "invariants.json": {"invariants": [{"id": x, "status": "NOT_RUN"} for x in inv]},
        "proposed-tests.json": {"tests": [{"id": x, "status": "NOT_RUN"} for x in checks]},
        "toolkit/operations.raw.json": {"operations": list(range(112))},
        "toolkit/schema.raw.json": {"fixture": True},
        "toolkit/scenario-registry.json": {"scenarios": []},
    }
    return data, policy


class ScopeTests(unittest.TestCase):
    def test_separates_both_graphs_and_retains_independent_gate(self):
        data, policy = fixture()
        out = scope.derive(data, policy)
        self.assertEqual(len(out["mss_packages"]), 15)
        self.assertEqual(len(out["cwg_external_handoff"]), 8)
        a13 = next(r for r in out["mss_packages"] if r["id"] == "A13")
        self.assertEqual(a13["depends_on"], ["A09", "A12", "MSS-V00"])
        b06 = next(r for r in out["cwg_external_handoff"] if r["id"] == "B06")
        self.assertEqual(b06["depends_on"], ["B05"])
        self.assertEqual(b06["external_contract_inputs"], ["A02"])

    def test_does_not_mutate_input_or_historical_assertions(self):
        data, policy = fixture()
        original = copy.deepcopy(data)
        out = scope.derive(data, policy)
        self.assertEqual(data, original)
        self.assertEqual(out["preserved_invariants"], data["invariants.json"]["invariants"])
        self.assertEqual(out["preserved_proposed_checks"], data["proposed-tests.json"]["tests"])
        for old in data["pr-backlog.json"]["backlog"]:
            new = next(r for r in out["mss_packages"] + out["cwg_external_handoff"] if r["id"] == old["id"])
            self.assertEqual(old["tests"], new["tests"])
            self.assertEqual(old["acceptance"], new["acceptance"])

    def test_product_cannot_acquire_a_hidden_cwg_dependency(self):
        data, policy = fixture()
        data["pr-backlog.json"]["backlog"][0]["depends_on"] = ["B02"]
        with self.assertRaises(ValueError):
            scope.derive(data, policy)

    def test_cycle_is_refused(self):
        with self.assertRaises(ValueError):
            scope.check_graph([{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}])

    def test_missing_dependency_is_refused(self):
        with self.assertRaises(ValueError):
            scope.check_graph([{"id": "a", "depends_on": ["absent"]}])

    def test_duplicate_package_and_edge_are_refused(self):
        for rows in [
            [{"id": "a", "depends_on": []}, {"id": "a", "depends_on": []}],
            [{"id": "a", "depends_on": ["b", "b"]}, {"id": "b", "depends_on": []}],
        ]:
            with self.assertRaises(ValueError):
                scope.check_graph(rows)

    def test_scope_cannot_shrink_toolkit_or_claim_runtime_pass(self):
        for field, value in [("toolkit_operation_count", 111), ("runtime_acceptance", "PASS")]:
            data, policy = fixture()
            policy[field] = value
            with self.assertRaises(ValueError):
                scope.derive(data, policy)

    def test_actual_operation_or_test_inventory_cannot_shrink(self):
        for name, field in [("toolkit/operations.raw.json", "operations"), ("proposed-tests.json", "tests")]:
            data, policy = fixture()
            data[name][field].pop()
            with self.assertRaises(ValueError):
                scope.derive(data, policy)

    def test_verification_obligations_cannot_be_dropped(self):
        data, policy = fixture()
        policy["independent_verification_gate"]["invariants"].pop()
        with self.assertRaises(ValueError):
            scope.derive(data, policy)

    def test_native_gate_cannot_be_prequalified_or_depend_on_cwg(self):
        for key, value in [("implementation_status", "PASS"), ("depends_on", ["B06"])]:
            data, policy = fixture()
            policy["independent_verification_gate"][key] = value
            with self.assertRaises(ValueError):
                scope.derive(data, policy)

    def test_executable_cwg_paths_are_refused(self):
        for path in ["native-check-broker/src/main.rs", "scripts/codex-issue/run.mjs",
                     ".github/workflows/codex-issue.yml", "CWG_MCP/src/lib.rs",
                     "NATIVE-CHECK-BROKER/Cargo.toml"]:
            with self.assertRaises(ValueError):
                scope.check_paths([path])

    def test_project_goals_gui_mcp_and_historical_evidence_stay(self):
        scope.check_paths(["goals/MSS-001.json", "MSS_MCP/src/lib.rs",
                           "doc/plans/history.zip", "doc/cwg-separation.md",
                           "doc/cronica/20261030-integration-pr1-4.json"])

    def test_duplicate_json_key_is_refused(self):
        with self.assertRaises(ValueError):
            scope.decode(b'{"schema":"old","schema":"new"}')

    def test_pinned_input_loader_detects_modified_bytes(self):
        data, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pins = {}
            for name, value in data.items():
                raw = json.dumps(value).encode()
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                pins[name] = hashlib.sha256(raw).hexdigest()
            self.assertEqual(scope.load_inputs(root, pins), data)
            (root / "pr-backlog.json").write_bytes(b"{}")
            with self.assertRaises(ValueError):
                scope.load_inputs(root, pins)


if __name__ == "__main__":
    unittest.main()
