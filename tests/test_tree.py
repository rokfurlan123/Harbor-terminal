import curses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import workspace as app


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(app, 'DATA', Path(self.temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.side = app.Sidebar(Mock())
        self.side.expanded = {'trivia', 'projects'}
        self.addCleanup(self.side.pool.shutdown)
        self.side.items = [
            {'id': 'chat', 'cwd': '/tmp/elsewhere', 'name': 'Trivia', 'workspaceMode': 'conversation'},
            {'id': 'legacy', 'cwd': str(Path.home()), 'name': 'General'},
            {'id': 'work', 'cwd': '/tmp/project', 'name': 'Implement menu', 'workspaceMode': 'project'},
            {'id': 'other', 'cwd': '/tmp/other', 'name': 'Another project', 'workspaceMode': 'auto'},
        ]

    def test_groups_trivia_and_projects_without_rewriting_sessions(self):
        rows = self.side.rows()
        self.assertEqual(rows[0]['label'], 'Trivia (2)')
        self.assertEqual([r['thread']['id'] for r in rows if 'thread' in r], ['chat', 'legacy'])
        self.assertEqual([r['cwd'] for r in rows if r['key'].startswith('project:')], ['/tmp/other', '/tmp/project'])
        self.assertEqual(len(self.side.items), 4)

    def test_expand_collapse_and_parent_navigation_persist(self):
        self.side.index = next(i for i, r in enumerate(self.side.rows()) if r['key'] == 'project:/tmp/project')
        self.side.action('\n')
        self.side.action(curses.KEY_DOWN)
        self.assertEqual(self.side.selected()['id'], 'work')
        self.side.action(curses.KEY_LEFT)
        self.assertEqual(self.side.selected_row()['key'], 'project:/tmp/project')
        self.side.action(curses.KEY_LEFT)
        self.assertNotIn('project:/tmp/project', app.preferences()['tree_expanded'])
        self.assertNotIn('work', [r.get('thread', {}).get('id') for r in self.side.rows()])

    def test_search_reveals_matches_in_collapsed_projects(self):
        self.side.expanded.clear()
        self.side.query = 'menu'
        rows = self.side.rows()
        self.assertEqual([r['thread']['id'] for r in rows if 'thread' in r], ['work'])
        self.assertTrue(next(r for r in rows if r['key'] == 'project:/tmp/project')['opened'])
        self.side.query = ''
        self.assertEqual([r['key'] for r in self.side.rows()], ['trivia', 'projects'])

    def test_refresh_preserves_selected_folder(self):
        self.side.index = next(i for i, r in enumerate(self.side.rows()) if r['key'] == 'projects')
        self.side.submit = Mock()
        self.side.refresh()
        loaded = self.side.submit.call_args.args[1]
        loaded(self.side.items + [{'id': 'new', 'cwd': str(Path.home()), 'name': 'Extra'}])
        self.assertEqual(self.side.selected_row()['key'], 'projects')

    def test_new_in_project_defaults_to_project_and_selected_folder(self):
        self.side.select_thread(self.side.items[2])
        self.side.prompt = Mock(side_effect=['New task', '/tmp'])
        self.side.choose_mode = Mock(return_value='project')
        self.side.submit = Mock()
        self.side.action('n')
        self.side.choose_mode.assert_called_once_with('project')
        self.assertEqual(self.side.prompt.call_args.args[1], '/tmp/project')

    def test_blank_session_skips_setup_and_opens_outside_selected_project(self):
        self.side.select_thread(self.side.items[2])
        self.side.archived = True
        self.side.query = 'menu'
        self.side.prompt = Mock(side_effect=AssertionError('Unexpected setup prompt'))
        self.side.choose_mode = Mock(side_effect=AssertionError('Unexpected mode prompt'))
        self.side.submit = Mock()
        self.side.workspace = Mock()
        self.side.workspace.panes.return_value = []
        # Exercise real local draft creation without connecting to user history.
        rpc = object.__new__(app.Rpc)
        rpc.call = Mock(return_value={'data': [], 'nextCursor': None})
        self.side.connection = Mock(return_value=rpc)
        self.side.action('b')
        create, opened = self.side.submit.call_args.args[:2]
        thread = create()
        opened(thread)
        self.assertEqual(thread['cwd'], str(Path.home()))
        self.assertEqual(thread['workspaceMode'], 'auto')
        self.assertTrue(thread['draft'])
        self.assertIsNone(thread['path'])
        self.side.workspace.open.assert_called_once_with(thread)
        self.assertFalse(self.side.archived)
        self.assertEqual(self.side.query, '')
        self.assertEqual(self.side.selected()['id'], thread['id'])
        self.assertEqual(self.side.selected_row()['parent'], 'trivia')

    def test_blank_button_click_and_busy_guard(self):
        self.side.submit = Mock()
        with patch.object(curses, 'getmouse', return_value=(0, 8, 3, 0, curses.BUTTON1_RELEASED)):
            self.side.action(curses.KEY_MOUSE)
        self.side.submit.assert_called_once()
        self.side.submit.reset_mock()
        self.side.future = Mock()
        self.side.action('b')
        self.side.submit.assert_not_called()

    def test_folder_copy_does_not_copy_a_neighboring_session(self):
        self.side.index = next(i for i, r in enumerate(self.side.rows()) if r['key'] == 'project:/tmp/project')
        with patch.object(app, 'copy_text') as copy:
            self.side.action('copy:path')
        copy.assert_called_once_with('/tmp/project')
        self.assertIsNone(self.side.selected())

    def test_registered_projects_appear_without_sessions(self):
        self.side.projects = ['/tmp/empty-project']
        row = next(r for r in self.side.rows() if r['key'] == 'project:/tmp/empty-project')
        self.assertEqual(row['label'], 'empty-project (0)')
        self.side.query = 'empty-project'
        self.assertTrue(any(r['key'] == row['key'] for r in self.side.rows()))

    def test_first_launch_discovers_project_folders_and_keeps_registry(self):
        root = Path(self.temp.name) / 'projects'
        root.mkdir()
        project = root / 'example'
        project.mkdir()
        (project / 'README.md').write_text('Example')
        (root / 'unrelated').mkdir()
        with patch.dict('os.environ', {'CODEX_WORKSPACE_PROJECTS_ROOT': str(root)}):
            app.initialize_projects()
            self.assertEqual(app.preferences()['projects'], [str(project)])
            app.save_preferences(projects=['/registered/elsewhere'])
            app.initialize_projects()
            self.assertEqual(app.preferences()['projects'], ['/registered/elsewhere'])

    def test_content_assignment_overrides_home_folder_and_mode(self):
        thread = {'id': 'classified', 'cwd': str(Path.home()), 'workspaceMode': 'auto',
                  'workspaceProject': '/tmp/project', 'name': 'Old misleading title'}
        self.side.items = [thread]
        self.side.select_thread(thread)
        self.assertEqual(self.side.selected_row()['parent'], 'project:/tmp/project')
        self.assertEqual(thread['cwd'], str(Path.home()))
        self.side.query = '/tmp/project'
        self.assertEqual(self.side.filtered(), [thread])
        thread['workspaceProject'] = ''
        self.side.query = ''
        self.side.select_thread(thread)
        self.assertEqual(self.side.selected_row()['parent'], 'trivia')

    def test_assignment_persists_through_archive_and_is_removed_on_delete(self):
        rpc = object.__new__(app.Rpc)
        rpc.call = Mock(return_value={'data': [], 'nextCursor': None})
        thread = rpc.create('Existing session', str(Path.home()))
        app.set_session_project(thread['id'], self.temp.name)
        rpc.change('archive', thread['id'])
        saved = rpc.threads(True)[0]
        self.assertEqual(saved['workspaceProject'], self.temp.name)
        self.assertEqual(saved['cwd'], str(Path.home()))
        self.assertEqual(saved['workspaceMode'], 'auto')
        rpc.change('delete', thread['id'])
        with app.drafts() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM session_projects').fetchone()[0], 0)

    def test_project_copy_and_resume_use_their_respective_folders(self):
        thread = {'id': 'existing', 'cwd': str(Path.home()), 'path': '/recorded',
                  'workspaceProject': self.temp.name}
        self.assertEqual(app.session_copy(thread, 'path'), self.temp.name)
        self.assertIn('Working folder: ' + str(Path.home()), app.session_copy(thread, 'reference'))
        import shlex
        self.assertEqual(shlex.split(app.session_copy(thread, 'resume'))[1], str(Path.home()))
