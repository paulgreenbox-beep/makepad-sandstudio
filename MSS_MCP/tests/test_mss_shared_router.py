"""Focused connector races; no applications or OS input are involved."""
from pathlib import Path
import sys
from threading import Event, Thread
from threading import RLock
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from mss_universal import App, Router, ToolFailure
from mss_shared import SharedError


class Client:
    def __init__(self):
        self.closed = 0
    def close(self):
        self.closed += 1


class SharedRouterTests(unittest.TestCase):
    def activation_fixture(self, *, mode='private', verified=3, running=False, unknown=False):
        router = Router.__new__(Router)
        self.activations = []
        app = SimpleNamespace(app_id='app_candidate', read_lock=RLock(),
                              build_postcondition={'operation_sequence': verified},
                              activation_evidence=lambda *a: {'verified': True})
        def permission(app_id, *, control=False, owner=False):
            self.assertTrue(owner)
            self.assertTrue(control)
            if unknown:
                raise SharedError('OUTCOME_UNKNOWN', 'Unknown')
        row = {'state': 'READY', 'share_mode': mode}
        router.shared = SimpleNamespace(permission=permission, app=lambda _: row,
            operations=lambda _: [{'tool': 'mss_ui_type', 'sequence': 3, 'state': 'RUNNING' if running else 'APPLIED'}])
        router.apps = {app.app_id: app}
        registry = SimpleNamespace(activate=lambda *a: self.activations.append(a) or {'active': 'candidate'})
        router.catalog = SimpleNamespace(build_registry=lambda _: registry)
        router.queued = lambda app, name, args, dispatch: dispatch()
        arguments = {'app_id': app.app_id, 'profile': 'rudraoffice', 'build_id': 'candidate',
                     'expected_active': 'baseline', 'verification': 'Observed exact postcondition'}
        return router, arguments

    def test_shared_candidate_cannot_activate(self):
        router, args = self.activation_fixture(mode='control')
        with self.assertRaises(ToolFailure) as caught:
            router.run_tool('mss_activate_build', args)
        self.assertEqual(caught.exception.code, 'VERIFICATION_REQUIRED')
        self.assertEqual(self.activations, [])

    def test_participant_mutation_invalidates_owner_verification(self):
        router, args = self.activation_fixture(verified=2)
        with self.assertRaises(ToolFailure):
            router.run_tool('mss_activate_build', args)
        self.assertEqual(self.activations, [])

    def test_unknown_shared_outcome_blocks_owner_activation(self):
        router, args = self.activation_fixture(unknown=True)
        with self.assertRaises(SharedError) as caught:
            router.run_tool('mss_activate_build', args)
        self.assertEqual(caught.exception.code, 'OUTCOME_UNKNOWN')
        self.assertEqual(self.activations, [])

    def test_running_mutation_cannot_be_claimed_as_verified(self):
        router, args = self.activation_fixture(running=True)
        with self.assertRaises(ToolFailure):
            router.run_tool('mss_activate_build', args)
        self.assertEqual(self.activations, [])

    def test_private_candidate_fresh_verification_preserves_activation_contract(self):
        router, args = self.activation_fixture()
        self.assertFalse(router.run_tool('mss_activate_build', args)['isError'])
        self.assertEqual(len(self.activations), 1)

    def test_sharing_transition_clears_candidate_evidence(self):
        router, app = self.fixture(lambda _: None)
        app.build_tree_observed, app.build_png, app.build_action_dispatched = True, ('png', 'sha'), True
        app.build_postcondition = {'operation_sequence': 1}
        router.store = lambda: SimpleNamespace(share=lambda *a: {
            'app_id': app.app_id, 'owner_connection_id': 'owner', 'share_mode': 'private'})
        router.run_tool('mss_share_app', {'app_id': app.app_id, 'mode': 'private'})
        self.assertFalse(app.build_tree_observed)
        self.assertFalse(app.build_action_dispatched)
        self.assertIsNone(app.build_png)
        self.assertIsNone(app.build_postcondition)

    def fixture(self, detach):
        router = Router.__new__(Router)
        router.store = lambda: SimpleNamespace(detach=detach)
        app = App('todo', 'app_fixture', Path('unused'))
        app.participant, app.state, app.peer = True, 'READY', Client()
        router.apps = {app.app_id: app}
        return router, app

    def test_detach_serializes_with_lazy_read_client_creation(self):
        router, app = self.fixture(lambda app_id: None)
        creating, release, done = Event(), Event(), Event()
        reader_client = Client()
        app.ensure_ready = lambda **kwargs: None
        def create(directory):
            creating.set()
            self.assertTrue(release.wait(2))
            return reader_client
        app.direct_peer = create
        app.call = lambda *args, **kwargs: {'content': []}
        read = Thread(target=app.read_call, args=('mss_ui_tree', {}))
        read.start()
        self.assertTrue(creating.wait(2))
        def detach():
            router.detach(app.app_id)
            done.set()
        detach_thread = Thread(target=detach)
        detach_thread.start()
        self.assertFalse(done.wait(.05))
        release.set()
        read.join(2)
        detach_thread.join(2)
        self.assertTrue(done.is_set())
        self.assertEqual(reader_client.closed, 1)
        self.assertEqual(app.peer.closed, 1)
        self.assertNotIn(app.app_id, router.apps)

    def test_revoked_participant_can_still_release_its_own_clients(self):
        def revoked(app_id):
            raise SharedError('NOT_ATTACHED', 'Owner already revoked')
        router, app = self.fixture(revoked)
        app.read_peer = Client()
        result = router.detach(app.app_id)
        self.assertFalse(result['isError'])
        self.assertEqual(app.peer.closed, 1)
        self.assertEqual(app.read_peer.closed, 1)
        self.assertNotIn(app.app_id, router.apps)


if __name__ == '__main__':
    unittest.main()
