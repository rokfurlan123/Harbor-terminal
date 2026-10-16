import curses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import workspace as app


class TopicTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(app, 'DATA', Path(temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.side = app.Sidebar(Mock())
        self.addCleanup(self.side.pool.shutdown)
        self.rpc = object.__new__(app.Rpc)
        self.rpc.call = Mock(return_value={'data': [], 'nextCursor': None})

    def test_nested_tree_search_and_parent_navigation_preserve_session(self):
        thread = {'id': 'qwen', 'name': 'Install model', 'cwd': '/original',
                  'workspaceMode': 'project', 'workspaceProject': '/assigned',
                  'workspaceTopic': 'misc/local-models/qwen'}
        self.side.items = [thread]
        self.side.select_thread(thread)
        self.assertEqual(self.side.selected_row()['parent'], 'misc/local-models/qwen')
        self.assertEqual(self.side.selected_row()['depth'], 3)
        self.assertEqual(sum('thread' in r for r in self.side.rows()), 1)
        self.assertFalse(any(r['key'] == 'project:/assigned' for r in self.side.rows()))
        self.side.action(curses.KEY_LEFT)
        self.side.action(curses.KEY_LEFT)  # collapse Qwen
        self.side.action(curses.KEY_LEFT)  # parent Local models
        self.assertEqual(self.side.selected_row()['key'], 'misc/local-models')
        self.side.expanded.clear()
        self.side.query = 'local models'
        self.assertEqual(self.side.filtered(), [thread])
        self.assertEqual(sum('thread' in r for r in self.side.rows()), 1)
        self.assertEqual(thread['cwd'], '/original')
        self.assertEqual(thread['workspaceMode'], 'project')

    def test_assignment_survives_archive_and_restore_then_delete(self):
        thread = self.rpc.create('Model setup', str(Path.home()))
        app.set_session_topic(thread['id'], 'misc/local-models/qwen')
        self.rpc.change('archive', thread['id'])
        self.assertEqual(app.topic_for(self.rpc.threads(True)[0]), 'misc/local-models/qwen')
        self.rpc.change('unarchive', thread['id'])
        self.assertEqual(app.topic_for(self.rpc.threads()[0]), 'misc/local-models/qwen')
        self.rpc.change('delete', thread['id'])
        with app.drafts() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM session_topics').fetchone()[0], 0)

    def test_quick_new_reuses_only_same_topic_and_blank_stays_trivia(self):
        self.side.expanded = {'misc'}
        self.side.index = next(i for i, r in enumerate(self.side.rows()) if r['key'] == 'misc/tailscale')
        self.side.submit = Mock()
        self.side.workspace = Mock()
        self.side.workspace.panes.return_value = []
        self.side.connection = Mock(return_value=self.rpc)
        self.side.action('+')
        create, opened = self.side.submit.call_args.args[:2]
        first = create()
        opened(first)
        self.assertEqual(app.topic_for(first), 'misc/tailscale')
        self.assertEqual(first['workspaceMode'], 'auto')
        self.side.workspace.panes.return_value = [{'thread': first['id'], 'dead': '0'}]
        self.assertEqual(create()['id'], first['id'])
        other = self.rpc.create_or_reuse('New session', str(Path.home()), 'auto', {first['id']}, topic='misc/local-models/qwen')
        self.assertNotEqual(other['id'], first['id'])
        blank = self.rpc.create_or_reuse('New session', str(Path.home()), 'auto', {first['id'], other['id']})
        self.assertIsNone(app.topic_for(blank))
        self.assertNotIn(blank['id'], {first['id'], other['id']})

    def test_move_open_conversation_and_restore_without_restart(self):
        thread = {'id': 'saved', 'name': 'Setup', 'cwd': '/tmp', 'workspaceMode': 'project'}
        self.side.items = [thread]
        self.side.select_thread(thread)
        self.side.prompt = Mock(return_value='t')
        self.side.workspace = Mock()
        self.side.action('g')
        self.assertEqual(self.side.selected_row()['parent'], 'misc/tailscale')
        self.side.workspace.assert_not_called()
        self.assertEqual(self.side.workspace.mock_calls, [])
        self.side.prompt.return_value = 'r'
        self.side.action('g')
        self.assertEqual(self.side.selected_row()['parent'], 'project:/tmp')
        self.assertEqual(thread['workspaceMode'], 'project')

    def test_named_conversation_in_topic_defaults_to_auto(self):
        self.side.expanded = {'misc', 'misc/local-models'}
        self.side.index = next(i for i, r in enumerate(self.side.rows()) if r['key'] == 'misc/local-models/qwen')
        self.side.prompt = Mock(return_value='Qwen tuning')
        self.side.choose_mode = Mock(return_value='auto')
        self.side.submit = Mock()
        self.side.workspace = Mock()
        self.side.workspace.panes.return_value = []
        self.side.connection = Mock(return_value=self.rpc)
        self.side.action('n')
        self.side.choose_mode.assert_called_once_with('auto')
        thread = self.side.submit.call_args.args[0]()
        self.assertEqual(app.topic_for(thread), 'misc/local-models/qwen')
        self.assertEqual(thread['cwd'], str(Path.home()))


if __name__ == '__main__':
    unittest.main()
