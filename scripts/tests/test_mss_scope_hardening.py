"""Planning/checkout-hygiene regressions, not native sandbox qualification."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_mss_scope import fixture, scope


class BoundaryTests(unittest.TestCase):
    def test_nonfinite_json_numbers_are_refused(self):
        for value in [b'NaN', b'Infinity', b'-Infinity', b'1e9999']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                scope.decode(b'{"value":' + value + b'}')

    def test_non_utf8_and_lone_surrogates_are_refused(self):
        for raw in [b'{"value":"\\ud800"}', '{"value":1}'.encode('utf-16'), b'{"x":"\xff"}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                scope.decode(raw)
        self.assertEqual(scope.decode('{"value":"я"}'.encode()), {"value": "я"})

    def test_nested_cwg_modules_and_broker_are_refused(self):
        for name in ["tools/CWG_Core/src/lib.rs", "tools/cwg-core/Cargo.toml",
                     "tools/native-check-broker/src/main.rs", "tools/scripts/codex-issue/run.mjs",
                     ".github/workflows/codex-issue.yaml"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                scope.check_paths([name])

    def test_noncanonical_paths_and_case_aliases_are_refused(self):
        for name in ["/CWG_Core/x", "../CWG_Core/x", "tools\\CWG_Core\\x", "x//y",
                     "./x", "x/../y", "x /y", "x./y", "x\n/y", "C:/x", ".git/config"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                scope.check_paths([name])
        with self.assertRaises(ValueError):
            scope.check_paths(["MSS_Core/src/lib.rs", "mss_core/src/lib.rs"])

    def test_path_inventory_must_be_a_list(self):
        for invalid in ["CWG_Core", None, {"Cargo.toml": 1}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                scope.check_paths(invalid)

    def test_cargo_members_must_be_a_list(self):
        with self.assertRaises(ValueError):
            scope.check_cargo(b'[workspace]\nmembers="CWG_Core"')

    def test_historical_docs_and_mss_modules_remain_allowed(self):
        scope.check_paths(["doc/cwg-separation.md", "doc/plans/history.zip", "MSS_MCP/src/lib.rs",
                           "goals/MSS-001.json", "doc/cronica/broker-research.json"])

    def test_declared_dependency_alias_path_and_git_are_refused(self):
        for declaration in [
            'cwg-core = "1"',
            'alias = { package = "cwg-router", version = "1" }',
            'alias = { path = "../CWG_Core" }',
            'alias = { git = "https://github.com/owner/Chat_Worker_GitHub" }',
            'alias = { package = "mss-native-check-broker", version = "1" }',
        ]:
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                scope.check_cargo(('[dependencies]\n' + declaration).encode())

    def test_target_build_patch_and_workspace_dependencies_are_inspected(self):
        for table in ['target.\'cfg(windows)\'.build-dependencies', 'workspace.dependencies',
                      'patch.crates-io', 'replace', 'dev-dependencies']:
            with self.subTest(table=table), self.assertRaises(ValueError):
                scope.check_cargo(('[' + table + ']\nalias = {package="cwg-router",version="1"}').encode())
        with self.assertRaises(ValueError):
            scope.check_cargo(b'[workspace]\nmembers=["MSS_Core", "../CWG_Core"]')

    def test_cargo_lock_cannot_smuggle_a_cwg_package(self):
        for raw in [b'[[package]]\nname="cwg-router"\nversion="1"',
                    b'[[package]]\nname="neutral"\nsource="git+https://example/Chat_Worker_GitHub"']:
            with self.assertRaises(ValueError):
                scope.check_cargo(raw)

    def test_normal_cargo_and_documentary_links_are_allowed(self):
        scope.check_cargo(b'[workspace]\nmembers=["MSS_Core","MSS_API"]\n'
                          b'[workspace.dependencies]\nmss-core={path="MSS_Core"}\n'
                          b'[workspace.metadata]\nreference="https://example/Chat_Worker_GitHub"')
        scope.check_cargo(b'[[package]]\nname="mss-core"\nversion="0.1.0"')

    def test_invalid_toml_fails_without_execution(self):
        with self.assertRaises(ValueError):
            scope.check_cargo(b'[invalid')

    def test_native_checks_cannot_be_empty_dropped_or_duplicated(self):
        for mode in ['empty', 'drop', 'duplicate']:
            data, policy = fixture()
            checks = policy['independent_verification_gate']['equivalent_checks_from']
            if mode == 'empty':
                checks.clear()
            elif mode == 'drop':
                checks.pop()
            else:
                checks.append(checks[0])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                scope.derive(data, policy)

    def test_invariant_duplicates_do_not_hide_behind_a_set(self):
        data, policy = fixture()
        invariants = policy['independent_verification_gate']['invariants']
        invariants.append(invariants[0])
        with self.assertRaises(ValueError):
            scope.derive(data, policy)

    def test_operation_count_must_be_an_integer(self):
        data, policy = fixture()
        policy['toolkit_operation_count'] = 112.0
        with self.assertRaises(ValueError):
            scope.derive(data, policy)

    def test_dependency_edges_are_lists_not_strings(self):
        for edges in ['b', None, {}, [1], [[]]]:
            with self.subTest(edges=edges), self.assertRaises(ValueError):
                scope.check_graph([{'id': 'a', 'depends_on': edges}, {'id': 'b', 'depends_on': []}])

    def test_graph_size_is_bounded_before_traversal(self):
        with self.assertRaises(ValueError):
            scope.check_graph([{'id': str(i), 'depends_on': []} for i in range(scope.MAX_GRAPH_ROWS + 1)])
        with self.assertRaises(ValueError):
            scope.check_graph([])

    def test_projection_output_cannot_mutate_historical_input(self):
        data, policy = fixture()
        before, pins = copy.deepcopy(data), copy.deepcopy(policy['source_inputs_sha256'])
        out = scope.derive(data, policy)
        out['preserved_invariants'][0]['status'] = 'FAKE_PASS'
        out['preserved_proposed_checks'].clear()
        out['source_inputs_sha256'].clear()
        self.assertEqual(data, before)
        self.assertEqual(policy['source_inputs_sha256'], pins)

    def test_oversized_source_is_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            with path.open('wb') as stream:
                stream.truncate(scope.MAX_INPUT_BYTES + 1)
            with self.assertRaises(ValueError):
                scope.read_regular(path)

    def test_observed_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').write_bytes(b'{}')
            try:
                (root / 'alias').symlink_to(root / 'data')
            except OSError as error:
                self.skipTest(f'OS symlink prerequisite: {error.errno}')
            with self.assertRaises(ValueError):
                scope.read_regular(root / 'alias')
            self.assertEqual(scope.read_regular(root / 'data'), b'{}')

    def test_observed_hardlink_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').write_bytes(b'{}')
            try:
                os.link(root / 'data', root / 'alias')
            except OSError as error:
                self.skipTest(f'OS hardlink prerequisite: {error.errno}')
            with self.assertRaises(ValueError):
                scope.read_regular(root / 'alias')

    def test_invalid_hash_type_is_refused(self):
        data, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root, pins = Path(directory), {}
            for name, value in data.items():
                raw = json.dumps(value).encode()
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                pins[name] = hashlib.sha256(raw).hexdigest()
            pins['pr-backlog.json'] = None
            with self.assertRaises(ValueError):
                scope.load_inputs(root, pins)

    def test_cli_checks_actual_git_index_and_declared_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
            manifest = root / 'Cargo.toml'
            manifest.write_text('[workspace]\nmembers=["MSS_Core"]\n')
            subprocess.run(['git', '-C', str(root), 'add', 'Cargo.toml'], check=True)
            scope.check_repo(root)
            manifest.write_text('[workspace.dependencies]\nalias={package="cwg-core",version="1"}')
            with self.assertRaises(ValueError):
                scope.check_repo(root)


if __name__ == '__main__':
    unittest.main()
