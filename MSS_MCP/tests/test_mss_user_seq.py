"""Model-free dispatch-boundary regressions; no native app or OS input."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ.get('MSS_TEST_TOOLS', str(Path(__file__).resolve().parents[1] / 'tools')))
import mss_universal as mss


APP_ID = 'app_' + 'a' * 32
NATIVE_ERROR = {'content': [{'type': 'text', 'text':
    'failed: {"err":"user_intervened: read activity and retry after inspecting the result"}'}], 'isError': True}


class Peer:
    def __init__(self):
        self.process = SimpleNamespace(poll=lambda: None)
        self.calls = []
        self.activity = mss.result_json({'user_seq': 7})
        self.action_result = mss.result_json({'result': 'handled'})
        self.actions = 'select,replace_text,focus'

    def call(self, name, args):
        self.calls.append((name, deepcopy(args)))
        if name == 'ui__ui':
            return mss.result_json({'trees': [{'window': '1:0', 'nodes': [
                {'id': 'node', 'actions': self.actions}]}]})
        if name == 'ui__status':
            return mss.result_json({'pid': 1734, 'w': [{'i': 0, 'sz': [800, 600]}]})
        if name == 'ui__activity':
            if isinstance(self.activity, Exception):
                raise self.activity
            return deepcopy(self.activity)
        if isinstance(self.action_result, Exception):
            raise self.action_result
        return deepcopy(self.action_result)


class Queue:
    """Only the queue interface is a fixture; Router.queued executes unchanged."""
    def __init__(self, app):
        self.row = {'state': 'READY'}
        self.finished = []
        self.on_turn = lambda: None
        self.allowed = True

    def permission(self, app_id, **kwargs):
        if not self.allowed:
            raise mss.SharedError('ACCESS_DENIED', 'Fixture revoked')
        return 'owner'

    def app(self, app_id):
        return self.row

    def enqueue(self, app_id, name, timeout):
        return {'operation_id': 'op_fixture'}

    def wait_turn(self, operation_id):
        self.on_turn()
        return {'operation_id': operation_id, 'state': 'RUNNING', 'sequence': 1}

    def finish(self, operation_id, state, code=None, effect='NOT_VERIFIED'):
        self.finished.append((state, code, effect))
        if state == 'OUTCOME_UNKNOWN':
            self.row['state'] = state
        return {'operation_id': operation_id, 'state': state, 'sequence': 1}


class UserSequenceTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix='mss-user-sequence-')
        self.addCleanup(fixture.cleanup)
        directory = Path(fixture.name)
        self.app = mss.App('todo', APP_ID, directory)
        image = directory / 'not-executed.exe'
        sessions = directory / 'sessions'
        session = sessions / 'fixture'
        session.mkdir(parents=True)
        self.app.plan = SimpleNamespace(access='semantic', app_image=image, app_sha256='a' * 64,
            remote_sha256='b' * 64, profile_sha256='d' * 64, makepad_revision='e' * 40,
            session_root=sessions, build_id=None)
        self.app.identity = {'app_pid': 1734, 'app_birth_utc': '2026-11-07T00:00:00.0000000Z',
                             'app_image': str(image)}
        self.receipt = {'status': 'READY', **self.app.identity, 'session_id': 'fixture',
            'profile_sha256': 'd' * 64, 'app_sha256': 'a' * 64, 'remote_sha256': 'b' * 64,
            'makepad_revision_declared': 'e' * 40}
        (session / 'session.json').write_text(json.dumps(self.receipt), encoding='utf-8')
        self.app.os_identity = {'pid': 1734, 'birth': 123, 'image': str(image), 'windows_session': 1}
        # Process identity observation is synthetic; the real receipt and
        # ensure_ready/window/permission/queued/call code paths remain active.
        identity_patch = patch.object(mss, 'confirm_app', return_value=self.app.os_identity)
        self.identity_check = identity_patch.start()
        self.addCleanup(identity_patch.stop)
        self.app.state, self.app.peer = 'READY', Peer()
        self.peer = self.app.peer
        self.app.native_tools = {'ui__ui_act', 'ui__activity', 'ui__ui', 'ui__key', 'ui__mouse', 'ui__drop'}
        self.router = mss.Router.__new__(mss.Router)
        self.router.apps = {APP_ID: self.app}
        self.router.closed_apps, self.router.shared = {}, None

    def args(self, **overrides):
        return {'app_id': APP_ID, 'node': 'node', 'w': '1:0', 'action': 'select',
                'v': 'red', 'if_user_seq': 7} | overrides

    def run_action(self, args=None, name='mss_ui_act'):
        return self.router.run_tool(name, self.args() if args is None else args)

    def native_mutations(self):
        return [(name, args) for name, args in self.peer.calls
                if name not in {'ui__activity', 'ui__ui', 'ui__status'}]

    def assert_refused(self, result, code):
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['code'], code)
        self.assertIs(result['structuredContent']['action_dispatched'], False)
        self.assertEqual(self.native_mutations(), [])
        self.assertEqual(self.app.state, 'READY')

    def test_stale_sequence_refused_without_native_action(self):
        result = self.run_action(self.args(if_user_seq=999999))
        self.assert_refused(result, 'REFUSED_STALE_USER_SEQ')
        self.assertEqual(result['structuredContent']['observed_user_seq'], 7)
        self.assertEqual(result['structuredContent']['expected_user_seq'], 999999)
        self.identity_check.assert_called_once_with(self.app.identity, self.app.os_identity)

    def test_missing_or_invalid_activity_never_defaults_to_zero(self):
        for value in ({}, {'user_seq': None}, {'user_seq': True}, {'user_seq': '0'},
                      {'user_seq': -1}, {'user_seq': 1.5}, {'user_seq': 2**64}, [], None):
            with self.subTest(activity=value):
                self.peer.calls.clear()
                self.peer.activity = mss.result_json(value)
                self.assert_refused(self.run_action(self.args(if_user_seq=0)), 'REFUSED_ACTIVITY_UNAVAILABLE')

    def test_error_malformed_json_or_transport_before_action_is_controlled_refusal(self):
        for value in (NATIVE_ERROR, {'content': [{'type': 'text', 'text': 'not json'}]},
                      {'content': [{'type': 'text', 'text': '{"user_seq":NaN}'}]},
                      mss.TransportFailure('fixture read loss'), mss.ToolFailure('REMOTE_ERROR', 'fixture error')):
            with self.subTest(kind=type(value).__name__):
                self.peer.calls.clear()
                self.peer.activity = value
                self.assert_refused(self.run_action(), 'REFUSED_ACTIVITY_UNAVAILABLE')

    def test_activity_capability_missing_does_not_dispatch(self):
        self.app.native_tools.remove('ui__activity')
        self.assert_refused(self.run_action(), 'REFUSED_ACTIVITY_UNAVAILABLE')
        self.assertNotIn('ui__activity', [name for name, _ in self.peer.calls])

    def test_deeply_nested_activity_is_refused_before_dispatch_in_queue(self):
        queue = self.router.shared = Queue(self.app)
        self.peer.activity = {'content': [{'type': 'text', 'text': '[' * 2000 + '0' + ']' * 2000}]}
        self.assert_refused(self.run_action(), 'REFUSED_ACTIVITY_UNAVAILABLE')
        self.assertEqual(queue.finished, [('FAILED', 'REFUSED_ACTIVITY_UNAVAILABLE', 'NOT_VERIFIED')])

    def test_matching_sequence_dispatched_once_with_original_native_guard(self):
        result = self.run_action()
        self.assertFalse(result['isError'])
        self.assertEqual(len(self.native_mutations()), 1)
        self.assertEqual(self.native_mutations()[0][1]['if_user_seq'], 7)
        self.assertEqual([name for name, _ in self.peer.calls], ['ui__ui', 'ui__activity', 'ui__ui_act'])
        self.assertNotEqual(result['structuredContent'].get('code'), 'PASS')

    def test_zero_is_a_real_sequence_not_a_missing_default(self):
        self.peer.activity = mss.result_json({'user_seq': 0})
        self.assertFalse(self.run_action(self.args(if_user_seq=0))['isError'])
        self.assertEqual(self.native_mutations()[0][1]['if_user_seq'], 0)

    def test_u64_activity_sequence_not_narrowed_or_float_converted(self):
        self.peer.activity = mss.result_json({'user_seq': 2**64 - 1})
        result = self.run_action()
        self.assert_refused(result, 'REFUSED_STALE_USER_SEQ')
        self.assertEqual(result['structuredContent']['observed_user_seq'], 2**64 - 1)

    def test_no_explicit_guard_keeps_existing_call_path(self):
        args = self.args()
        del args['if_user_seq']
        self.assertFalse(self.run_action(args)['isError'])
        self.assertNotIn('ui__activity', [name for name, _ in self.peer.calls])
        self.assertNotIn('if_user_seq', self.native_mutations()[0][1])

    def test_foreign_app_is_refused_before_any_native_read(self):
        with self.assertRaises(mss.ToolFailure) as caught:
            self.run_action(self.args(app_id='app_' + 'b' * 32))
        self.assertEqual(caught.exception.code, 'UNKNOWN_APP')
        self.assertEqual(self.peer.calls, [])

    def test_neighbor_activity_cannot_satisfy_this_apps_guard(self):
        neighbor = mss.App('todo', 'app_' + 'b' * 32, self.app.directory / 'neighbor')
        neighbor.peer, neighbor.state = Peer(), 'READY'
        neighbor.peer.activity = mss.result_json({'user_seq': 999999})
        self.router.apps[neighbor.app_id] = neighbor
        self.assert_refused(self.run_action(self.args(if_user_seq=999999)), 'REFUSED_STALE_USER_SEQ')
        self.assertEqual(neighbor.peer.calls, [])
        self.assertEqual(neighbor.state, 'READY')

    def test_stale_process_identity_is_refused_before_activity(self):
        self.identity_check.side_effect = OSError('fixture replaced process')
        with self.assertRaises(mss.ToolFailure) as caught:
            self.run_action()
        self.assertEqual(caught.exception.code, 'IDENTITY_UNVERIFIED')
        self.assertEqual(self.peer.calls, [])

    def test_wrong_window_is_refused_before_activity(self):
        with self.assertRaises(mss.ToolFailure) as caught:
            self.run_action(self.args(w='2:0'))
        self.assertEqual(caught.exception.code, 'UNKNOWN_NODE')
        self.assertEqual([name for name, _ in self.peer.calls], ['ui__ui'])

    def test_read_only_profile_cannot_gain_dispatch_authority(self):
        self.app.plan.access = 'read-only'
        with self.assertRaises(mss.ToolFailure) as caught:
            self.run_action()
        self.assertEqual(caught.exception.code, 'READ_ONLY_PROFILE')
        self.assertEqual(self.peer.calls, [])

    def test_invalid_requested_sequence_rejected_by_public_validation(self):
        for value in (-1, True, '7', 1.5):
            with self.subTest(requested=value), self.assertRaises(mss.ToolFailure) as caught:
                self.run_action(self.args(if_user_seq=value))
            self.assertEqual(caught.exception.code, 'INVALID_ARGUMENT')
        self.assertEqual(self.peer.calls, [])

    def test_semantic_type_keeps_replace_text_and_guard(self):
        args = {'app_id': APP_ID, 'node': 'node', 'w': '1:0', 't': 'text', 'if_user_seq': 7}
        self.assertFalse(self.run_action(args, 'mss_ui_type')['isError'])
        sent = self.native_mutations()[0][1]
        self.assertEqual((sent['action'], sent['if_user_seq'], sent['t']), ('replace_text', 7, 'text'))

    def test_raw_key_mouse_and_drop_keep_guard_and_clipboard_policy(self):
        self.peer.action_result = mss.result_json({'ok': 1})
        self.app.artifacts.mkdir()
        (self.app.artifacts / 'fixture.txt').write_text('fixture', encoding='utf-8')
        for name, args in (
            ('mss_ui_key', {'w': 0, 'c': 'Tab'}),
            ('mss_ui_mouse', {'w': 0, 'k': 'click', 'x': 1, 'y': 1}),
            ('mss_ui_drop', {'w': 0, 'x': 1, 'y': 1, 'file': 'fixture.txt'}),
        ):
            with self.subTest(tool=name):
                self.peer.calls.clear()
                self.assertFalse(self.run_action(args | {'app_id': APP_ID, 'if_user_seq': 7}, name)['isError'])
                self.assertEqual(len(self.native_mutations()), 1)
                self.assertEqual(self.native_mutations()[0][1]['if_user_seq'], 7)
        self.peer.calls.clear()
        with self.assertRaises(mss.ToolFailure) as caught:
            self.run_action({'app_id': APP_ID, 'w': 0, 'c': 'KeyV', 'ctrl': True, 'if_user_seq': 7}, 'mss_ui_key')
        self.assertEqual(caught.exception.code, 'SHARED_CLIPBOARD')
        self.assertEqual(self.peer.calls, [])

    def test_race_error_after_matching_preflight_stays_unknown_and_never_replayed(self):
        self.peer.action_result = NATIVE_ERROR
        result = self.run_action()
        self.assertEqual(result['structuredContent']['code'], 'OUTCOME_UNKNOWN')
        self.assertEqual(self.app.state, 'OUTCOME_UNKNOWN')
        self.assertEqual(len(self.native_mutations()), 1)
        with self.assertRaises(mss.ToolFailure):
            self.run_action()
        self.assertEqual(len(self.native_mutations()), 1)

    def test_timeout_after_dispatch_is_unknown_without_replay(self):
        self.peer.action_result = mss.TransportFailure('fixture timeout')
        with self.assertRaises(mss.ToolFailure) as caught:
            self.run_action()
        self.assertEqual(caught.exception.code, 'OUTCOME_UNKNOWN')
        self.assertEqual(self.app.state, 'OUTCOME_UNKNOWN')
        self.assertEqual(len(self.native_mutations()), 1)

    def test_native_error_after_applied_action_stays_unknown(self):
        self.peer.action_result = {'content': [{'type': 'text', 'text':
            'failed: {"err":"user_intervened: inspect before retrying an applied action"}'}], 'isError': True}
        result = self.run_action()
        self.assertEqual(result['structuredContent']['code'], 'OUTCOME_UNKNOWN')
        self.assertIsNot(result['structuredContent'].get('action_dispatched'), False)
        self.assertEqual(self.app.state, 'OUTCOME_UNKNOWN')
        self.assertEqual(len(self.native_mutations()), 1)

    def test_select_fallback_after_dispatch_is_still_unknown(self):
        self.peer.action_result = mss.result_json({'result': 'fallback'})
        result = self.run_action()
        self.assertEqual(result['structuredContent']['code'], 'OUTCOME_UNKNOWN')
        self.assertEqual(len(self.native_mutations()), 1)

    def test_queued_preflight_runs_after_turn_and_records_failed_not_unknown(self):
        queue = self.router.shared = Queue(self.app)
        queue.on_turn = lambda: setattr(self.peer, 'activity', mss.result_json({'user_seq': 8}))
        self.assert_refused(self.run_action(), 'REFUSED_STALE_USER_SEQ')
        self.assertEqual(queue.finished, [('FAILED', 'REFUSED_STALE_USER_SEQ', 'NOT_VERIFIED')])

    def test_revoked_permission_is_refused_before_activity(self):
        queue = self.router.shared = Queue(self.app)
        queue.allowed = False
        with self.assertRaises(mss.SharedError):
            self.run_action()
        self.assertEqual(self.peer.calls, [])

    def test_permission_revoked_while_waiting_is_rechecked_before_activity(self):
        queue = self.router.shared = Queue(self.app)
        queue.on_turn = lambda: setattr(queue, 'allowed', False)
        result = self.run_action()
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent']['code'], 'ACCESS_DENIED')
        self.assertEqual(queue.finished, [('FAILED', 'ACCESS_DENIED', 'NOT_VERIFIED')])
        self.assertEqual(self.peer.calls, [])

    def test_queued_postdispatch_error_marks_unknown(self):
        queue = self.router.shared = Queue(self.app)
        self.peer.action_result = NATIVE_ERROR
        result = self.run_action()
        self.assertEqual(result['structuredContent']['code'], 'OUTCOME_UNKNOWN')
        self.assertEqual(queue.finished, [('OUTCOME_UNKNOWN', 'OUTCOME_UNKNOWN', 'NOT_VERIFIED')])
        self.assertEqual(queue.row['state'], 'OUTCOME_UNKNOWN')
        self.assertEqual(len(self.native_mutations()), 1)


if __name__ == '__main__':
    unittest.main()
