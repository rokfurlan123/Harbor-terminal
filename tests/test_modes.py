import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import workspace as app


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(app, 'DATA', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unknown_sessions_default_auto_and_invalid_modes_rejected(self):
        self.assertEqual(app.session_mode('existing'), 'auto')
        with self.assertRaises(ValueError):
            app.set_session_mode('existing', '../invalid')
        self.assertEqual(app.session_mode('existing'), 'auto')

    def test_draft_mode_survives_archive_refresh_and_is_removed_on_delete(self):
        rpc = object.__new__(app.Rpc)
        rpc.call = Mock(return_value={'data': [], 'nextCursor': None})
        thread = rpc.create('Learning', self.temp.name, 'conversation')
        tid = thread['id']
        self.assertEqual(rpc.threads()[0]['workspaceMode'], 'conversation')
        app.set_session_mode(tid, 'project')
        rpc.change('archive', tid)
        self.assertEqual(rpc.threads(True)[0]['workspaceMode'], 'project')
        rpc.change('delete', tid)
        self.assertEqual(app.session_mode(tid), 'auto')

    def test_mode_survives_draft_replaced_by_recorded_history(self):
        rpc = object.__new__(app.Rpc)
        thread = rpc.create('Work', self.temp.name, 'project')
        rpc.call = Mock(return_value={'data': [{'id': thread['id'], 'cwd': self.temp.name}], 'nextCursor': None})
        self.assertEqual(rpc.threads()[0]['workspaceMode'], 'project')
        with app.drafts() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0], 0)
        self.assertEqual(app.session_mode(thread['id']), 'project')

    def test_preserves_native_configuration_and_replaces_previous_mode(self):
        request = {'id': 1, 'method': 'thread/resume', 'params': {
            'threadId': 'abc', 'approvalPolicy': 'on-request', 'config': {'developer_instructions': 'Existing rules'}}}
        original = copy.deepcopy(request)
        result = app.mode_transform('auto')(request)
        self.assertTrue(result['params']['developerInstructions'].startswith('Existing rules'))
        result = app.mode_transform('project')(result)
        self.assertEqual(result['params']['developerInstructions'].count(app.MODE_MARKER), 1)
        self.assertIn('Workspace mode: Project work', result['params']['developerInstructions'])
        del result['params']['developerInstructions']
        self.assertEqual(result, original)
        untouched = {'id': 2, 'method': 'turn/start', 'params': {'input': []}}
        self.assertIsNone(app.mode_transform('auto')(untouched))
        self.assertEqual(untouched, {'id': 2, 'method': 'turn/start', 'params': {'input': []}})

    def test_open_session_cannot_change_mode(self):
        sidebar = app.Sidebar(Mock())
        self.addCleanup(sidebar.pool.shutdown)
        sidebar.items = [{'id': 'live'}]
        sidebar.select_thread(sidebar.items[0])
        sidebar.workspace = Mock()
        sidebar.workspace.panes.return_value = [{'thread': 'live', 'dead': '0'}]
        sidebar.choose_mode = Mock(return_value='project')
        sidebar.action('m')
        sidebar.choose_mode.assert_not_called()
        self.assertEqual(app.session_mode('live'), 'auto')
        self.assertIn('Close terminal', sidebar.message)

    def test_closed_session_mode_change_and_cancel(self):
        sidebar = app.Sidebar(Mock())
        self.addCleanup(sidebar.pool.shutdown)
        sidebar.items = [{'id': 'saved'}]
        sidebar.select_thread(sidebar.items[0])
        sidebar.workspace = Mock()
        sidebar.workspace.panes.return_value = []
        sidebar.choose_mode = Mock(side_effect=['conversation', None])
        sidebar.action('m')
        sidebar.action('m')
        self.assertEqual(app.session_mode('saved'), 'conversation')
        self.assertEqual(sidebar.selected()['workspaceMode'], 'conversation')

    def test_new_conversation_skips_project_prompt(self):
        sidebar = app.Sidebar(Mock())
        self.addCleanup(sidebar.pool.shutdown)
        sidebar.prompt = Mock(return_value='Learning')
        sidebar.choose_mode = Mock(return_value='conversation')
        sidebar.submit = Mock()
        sidebar.action('n')
        sidebar.prompt.assert_called_once_with('Conversation name')
        with patch.object(sidebar, 'connection') as connection, patch.object(sidebar, 'live_ids', return_value=set()):
            sidebar.submit.call_args.args[0]()
        connection.return_value.create_or_reuse.assert_called_once_with('Learning', str(Path.home()), 'conversation', set())
        self.assertNotIn('project', app.preferences())
