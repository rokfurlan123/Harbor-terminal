import curses
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import workspace as app


class ModelTests(unittest.TestCase):
    def test_search_disabled_only_for_verified_ollama_backends(self):
        for model in ({'provider': 'ollama', 'model': 'qwen3:8b'},
                      {'provider': 'harbor_laptop', 'model': 'local-qwen', 'backend': 'ollama'}):
            with self.subTest(model=model):
                args = app.model_launch_args(model)
                self.assertIn('web_search="disabled"', args)
                for method in ('thread/start', 'thread/resume'):
                    original = {'web_search': 'live', 'unrelated': {'keep': True}}
                    request = {'method': method, 'params': {'config': original,
                               'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'}}
                    params = app.mode_transform('auto', 'Preserve this', model)(request)['params']
                    self.assertEqual(params['config']['web_search'], 'disabled')
                    self.assertEqual(params['config']['unrelated'], {'keep': True})
                    self.assertEqual(original['web_search'], 'live')
                    self.assertEqual(params['approvalPolicy'], 'on-request')
                    self.assertEqual(params['sandbox'], 'workspace-write')
                self.assertIsNone(app.mode_transform('auto', model=model)({'method': 'turn/start'}))
        for model in (None, {}, {'provider': 'openai', 'model': 'gpt-test'},
                      {'provider': 'harbor_api', 'model': 'qwen3:8b', 'backend': 'responses'}):
            with self.subTest(model=model):
                self.assertNotIn('web_search', ' '.join(app.model_launch_args(model)))
                for method in ('thread/start', 'thread/resume'):
                    request = {'method': method, 'params': {'config': {'web_search': 'live'}}}
                    params = app.mode_transform('auto', model=model)(request)['params']
                    self.assertEqual(params['config']['web_search'], 'live')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cwd = temp.name
        patcher = patch.object(app, 'DATA', Path(temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        store = patch.object(app, 'connection_store')
        store.start().return_value.all.return_value = []
        self.addCleanup(store.stop)
        self.rpc = object.__new__(app.Rpc)
        self.rpc.call = Mock(return_value={'data': [], 'nextCursor': None})
        self.model = {'provider': 'ollama', 'model': 'qwen3:8b'}

    def sidebar(self):
        screen = Mock()
        screen.getmaxyx.return_value = (30, 40)
        side = app.Sidebar(screen)
        self.addCleanup(side.pool.shutdown)
        side.workspace = Mock()
        side.workspace.panes.return_value = []
        side.connection = Mock(return_value=self.rpc)
        side.submit = Mock()
        return side

    def test_model_persistence_and_unused_reuse(self):
        app.save_preferences(new_session_model=self.model)
        first = self.rpc.create_or_reuse('New session', self.cwd, 'project', set())
        same = self.rpc.create_or_reuse('New session', self.cwd, 'project', {first['id']})
        self.assertEqual(first['id'], same['id'])
        self.assertEqual(app.session_model(first['id']), self.model)
        app.save_preferences(new_session_model={})
        other = self.rpc.create_or_reuse('New session', self.cwd, 'project', {first['id']})
        self.assertNotEqual(first['id'], other['id'])
        self.rpc.call.return_value = {'data': [{'id': first['id'], 'cwd': self.cwd}], 'nextCursor': None}
        self.assertEqual(self.rpc.threads()[0]['workspaceModel'], self.model)
        self.rpc.change('delete', first['id'])
        self.assertEqual(app.session_model(first['id']), {})

    def test_new_and_resume_select_provider_preserve_permissions(self):
        for method in ['thread/start', 'thread/resume']:
            request = {'method': method, 'params': {'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'}}
            result = app.mode_transform('project', 'Existing instructions', self.model)(request)
            self.assertEqual(result['params']['modelProvider'], 'ollama')
            self.assertEqual(result['params']['model'], 'qwen3:8b')
            self.assertEqual(result['params']['approvalPolicy'], 'on-request')
            self.assertEqual(result['params']['sandbox'], 'workspace-write')
            self.assertTrue(result['params']['developerInstructions'].startswith('Existing instructions'))
        self.assertIsNone(app.mode_transform('auto', model=self.model)({'method': 'turn/start'}))

    def test_project_plus_click_skips_prompts_and_reuses(self):
        side = self.sidebar()
        side.projects = [self.cwd]
        side.expanded = {'projects'}
        side.index = next(i for i, row in enumerate(side.rows()) if row.get('cwd') == self.cwd)
        side.prompt = Mock(side_effect=AssertionError('No setup prompts expected'))
        y = 4 + side.index * 2
        with patch.object(curses, 'getmouse', return_value=(0, 38, y, 0, curses.BUTTON1_RELEASED)):
            side.action(curses.KEY_MOUSE)
        create, opened = side.submit.call_args.args[:2]
        thread = create()
        opened(thread)
        self.assertEqual(thread['cwd'], self.cwd)
        self.assertEqual(thread['workspaceMode'], 'project')
        self.assertTrue(thread['temporary'])
        side.workspace.panes.return_value = [{'thread': thread['id'], 'dead': '0'}]
        self.assertEqual(create()['id'], thread['id'])

    def test_open_model_choice_saved_without_interrupting_and_cancel_keeps_choice(self):
        side = self.sidebar()
        thread = self.rpc.create('Test', self.cwd)
        side.items = [thread]
        side.select_thread(thread)
        side.workspace.panes.return_value = [{'thread': thread['id'], 'dead': '0'}]
        side.action('M')
        side.submit.assert_called_once()
        side.choose_model = Mock(return_value=None)
        side.apply_model_choice(thread, ([{}, self.model], ''))
        self.assertEqual(app.session_model(thread['id']), {})
        side.choose_model.return_value = self.model
        side.apply_model_choice(thread, ([{}, self.model], ''))
        self.assertEqual(app.session_model(thread['id']), self.model)
        self.assertIn('Saved for next reopen', side.message)
        side.workspace.close.assert_not_called()
        side.workspace.open.assert_not_called()
        side.choose_model.return_value = {}
        side.apply_model_choice(thread, ([{}, self.model], ''))
        self.assertEqual(app.session_model(thread['id']), {'default': True})
        side.workspace.panes.return_value = []
        side.choose_model.return_value = self.model
        side.apply_model_choice(thread, ([{}, self.model], ''))
        self.assertTrue(side.message.startswith('Session model: '))

    def test_catalog_pagination_local_discovery_and_unavailable_service(self):
        self.rpc.call.side_effect = [
            {'data': [{'model': 'cloud-one'}], 'nextCursor': 'next'},
            {'data': [{'model': 'cloud-two'}], 'nextCursor': None}]
        with patch.object(app.subprocess, 'run', return_value=Mock(returncode=0, stdout='NAME ID SIZE\nqwen3:8b abc 5GB\n')):
            choices, warning = app.available_models(self.rpc)
        self.assertEqual(choices[-1], self.model)
        self.assertEqual(len(choices), 4)
        self.assertEqual(warning, '')
        self.rpc.call.side_effect = RuntimeError('Offline')
        with patch.object(app.subprocess, 'run', side_effect=FileNotFoundError):
            choices, warning = app.available_models(self.rpc)
        self.assertEqual(choices, [{}])
        self.assertIn('Ollama unavailable', warning)

    def test_picker_scroll_click_cancel_and_small_terminal(self):
        side = self.sidebar()
        side.screen.getmaxyx.return_value = (8, 30)
        choices = [{}, *({'model': str(i), 'provider': 'openai'} for i in range(6))]
        side.screen.get_wch.side_effect = ['k', curses.KEY_MOUSE]
        with patch.object(curses, 'getmouse', return_value=(0, 2, 4, 0, curses.BUTTON1_RELEASED)):
            self.assertEqual(side.choose_model({}, (choices, '')), choices[-1])
        side.screen.get_wch.side_effect = ['\x1b']
        self.assertIsNone(side.choose_model({}, (choices, '')))
        side.screen.getmaxyx.return_value = (6, 15)
        self.assertIsNone(side.choose_model({}, (choices, '')))
