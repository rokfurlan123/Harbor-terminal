import curses
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workspace as app


class MenuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(app, 'DATA', Path(temporary.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def sidebar(self):
        screen = Mock()
        screen.getmaxyx.return_value = (24, 38)
        sidebar = app.Sidebar(screen)
        self.addCleanup(sidebar.pool.shutdown)
        sidebar.items = [{'id': 'first', 'cwd': '/tmp'}, {'id': 'second', 'cwd': '/tmp'}]
        sidebar.select_thread(sidebar.items[0])
        return sidebar

    def test_right_click_selects_clicked_session_without_opening(self):
        sidebar = self.sidebar()
        sidebar.context_menu = Mock()
        sidebar.submit = Mock()
        with patch.object(curses, 'getmouse', return_value=(0, 3, 12, 0, curses.BUTTON3_PRESSED)):
            sidebar.action(curses.KEY_MOUSE)
        self.assertEqual(sidebar.selected()['id'], 'second')
        sidebar.context_menu.assert_called_once()
        sidebar.submit.assert_not_called()

    def test_click_empty_area_keeps_selection(self):
        sidebar = self.sidebar()
        sidebar.context_menu = Mock()
        with patch.object(curses, 'getmouse', return_value=(0, 3, 20, 0, curses.BUTTON3_PRESSED)):
            sidebar.action(curses.KEY_MOUSE)
        self.assertEqual(sidebar.selected()['id'], 'first')

    def test_menu_delete_uses_existing_confirmation(self):
        sidebar = self.sidebar()
        sidebar.archived = True
        sidebar.confirm = Mock(return_value=False)
        sidebar.submit = Mock()
        sidebar.screen.get_wch.side_effect = ['j'] * 8 + ['\n']
        sidebar.context_menu()
        sidebar.confirm.assert_called_once()
        sidebar.submit.assert_not_called()

    def test_small_menu_scrolls_to_copy_resume(self):
        sidebar = self.sidebar()
        sidebar.screen.getmaxyx.return_value = (10, 38)
        sidebar.screen.get_wch.side_effect = ['k', '\n']
        sidebar.action = Mock()
        sidebar.context_menu()
        sidebar.action.assert_called_once_with('copy:resume')

    def test_escape_does_nothing(self):
        sidebar = self.sidebar()
        sidebar.screen.get_wch.return_value = '\x1b'
        sidebar.action = Mock()
        sidebar.context_menu()
        sidebar.action.assert_not_called()

    def test_copy_unicode_reference_via_stdin(self):
        sidebar = self.sidebar()
        sidebar.items[0]['name'] = 'Učenje'
        with patch.object(app, 'run') as run:
            sidebar.action('copy:reference')
        self.assertEqual(run.call_args.kwargs['input'], 'Učenje\nSession: first\nProject: /tmp')
        self.assertEqual(run.call_args.args[0][-3:], ['load-buffer', '-w', '-'])

    def test_resume_quotes_path_and_refuses_drafts(self):
        import shlex
        thread = {'id': 'abc', 'cwd': "/tmp/a b'$(test)", 'path': '/tmp/history'}
        result = app.session_copy(thread, 'resume')
        self.assertEqual(shlex.split(result), ['cd', thread['cwd'], '&&', app.CODEX, 'resume', 'abc'])
        thread['draft'] = True
        with self.assertRaises(RuntimeError):
            app.session_copy(thread, 'resume')
