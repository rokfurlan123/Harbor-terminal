import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import workspace as app


class ToolbarTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        data = patch.object(app, 'DATA', Path(temp.name))
        data.start()
        self.addCleanup(data.stop)
        self.workspace = Mock()
        self.pane = {'thread': 'current', 'pane': '%1', 'dead': '0'}
        self.workspace.main.return_value = self.pane
        self.workspace.panes.return_value = [self.pane]
        self.rpc = Mock()
        self.current = {'id': 'current', 'cwd': temp.name, 'workspaceMode': 'project'}
        self.rpc.threads.return_value = [self.current]
        self.model = {'provider': 'ollama', 'model': 'qwen3:8b'}

    def test_top_bar_click_and_f5_open_the_same_harbor_popup(self):
        with patch.object(app, 'tmux') as tmux, patch.object(app, 'refresh_toolbar'):
            app.configure_toolbar()
        tmux.assert_any_call('set-option', '-t', app.SESSION, 'status-position', 'top')
        bindings = [c.args for c in tmux.call_args_list if c.args[0] == 'bind-key']
        self.assertEqual({c[2] for c in bindings}, {'F5', 'MouseUp1StatusLeft', 'MouseUp1StatusDefault'})
        self.assertEqual(bindings[0][3:], bindings[1][3:])
        self.assertIn('model-picker', bindings[0][-1])
        self.assertFalse(any(c.args[0] in ('kill-pane', 'respawn-pane', 'send-keys')
                             for c in tmux.call_args_list))

    def test_other_model_opens_child_in_same_project_without_closing_current(self):
        child = {'id': 'other'}
        self.rpc.create_or_reuse.return_value = child
        with patch.object(app, 'active_child_model', return_value={}):
            self.assertEqual(app.open_model_child(self.workspace, self.rpc, self.model), child)
        self.assertEqual(app.preferences()['new_session_model'], self.model)
        self.rpc.create_or_reuse.assert_called_once_with(
            'New session', self.current['cwd'], 'project', {'current'}, topic=None)
        self.workspace.open.assert_called_once_with(child)
        self.workspace.close.assert_not_called()
        self.rpc.change.assert_not_called()

    def test_same_running_model_keeps_child_and_does_not_create_duplicate(self):
        with patch.object(app, 'active_child_model', return_value=self.model):
            result = app.open_model_child(self.workspace, self.rpc, self.model)
        self.assertEqual(result, self.current)
        self.workspace.focus.assert_called_once()
        self.rpc.create_or_reuse.assert_not_called()
        self.workspace.open.assert_not_called()

    def test_explicit_codex_default_keeps_existing_default_child(self):
        with patch.object(app, 'active_child_model', return_value={'default': True}):
            self.assertEqual(app.open_model_child(self.workspace, self.rpc, {}), self.current)
        self.rpc.create_or_reuse.assert_not_called()
        self.workspace.focus.assert_called_once()

    def test_home_uses_default_context_and_existing_unused_child_is_reused(self):
        self.rpc.threads.return_value = []
        self.rpc.create_or_reuse.return_value = {'id': 'unused'}
        app.open_model_child(self.workspace, self.rpc, {})
        self.rpc.create_or_reuse.assert_called_once_with(
            'New session', str(Path.home()), 'auto', {'current'}, topic=None)
        self.workspace.open.assert_called_once_with({'id': 'unused'})

    def test_cancel_picker_does_not_change_preferences_or_child(self):
        screen = Mock()
        with patch.object(app, 'Sidebar') as sidebar, \
                patch.object(app.curses, 'curs_set'), \
                patch.object(app.curses, 'use_default_colors'), \
                patch.object(app.curses, 'mousemask'), \
                patch.object(app, 'active_child_model', return_value={}), \
                patch.object(app, 'available_models', return_value=([{}], '')), \
                patch.object(app, 'open_model_child') as opened:
            sidebar.return_value.choose_model.return_value = None
            app.model_picker(screen)
            opened.assert_not_called()
            sidebar.return_value.rpc.close.assert_called_once()
            sidebar.return_value.pool.shutdown.assert_called_once_with(wait=True)
        self.assertNotIn('new_session_model', app.preferences())

    def test_toolbar_uses_launch_model_not_pending_preference_and_escapes_formats(self):
        original = {'provider': 'openai', 'model': 'model#[bg=red]'}
        app.set_session_model('current', self.model)
        with patch.object(app, 'tmux', return_value=json.dumps(original)):
            self.assertEqual(app.active_child_model(self.workspace), original)
        with patch.object(app, 'active_child_model', return_value=original), \
                patch.object(app, 'tmux') as tmux:
            app.refresh_toolbar()
        tmux.assert_called_once_with('set-option', '-t', app.SESSION,
                                     '@harbor_model', 'model##[bg=red]')

    def test_closed_same_model_still_opens_child(self):
        self.pane['dead'] = '1'
        with patch.object(app, 'active_child_model', return_value=self.model):
            app.open_model_child(self.workspace, self.rpc, self.model)
        self.workspace.open.assert_called_once()
        self.workspace.focus.assert_not_called()
