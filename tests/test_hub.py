import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import hub
import remote_dev
import workspace as app


class HubTests(unittest.TestCase):
    def codex(self, signed_in=True):
        return {'id': 'codex', 'adapter': 'codex', 'models': ['model-a', 'model-b'], 'signed_in': signed_in}

    def test_catalog_pages_account_and_cleanup_without_turns(self):
        rpc = Mock()
        rpc.call.side_effect = [{'account': {'type': 'chatgpt'}},
                                {'data': [{'model': 'a'}], 'nextCursor': 'page2'},
                                {'data': [{'model': 'b'}], 'nextCursor': None}]
        fake = Mock()
        fake.Rpc.return_value = rpc
        report = hub.CodexAdapter().catalog(fake)
        self.assertEqual(report['models'], ['a', 'b'])
        self.assertTrue(report['signed_in'])
        self.assertEqual([c.args[0] for c in rpc.call.call_args_list], ['account/read', 'model/list', 'model/list'])
        rpc.close.assert_called_once()
        rpc.reset_mock()
        rpc.call.side_effect = RuntimeError('disconnected')
        with self.assertRaises(RuntimeError):
            hub.CodexAdapter().catalog(fake)
        rpc.close.assert_called_once()

    def test_selection_fails_closed_on_bad_model_backend_auth(self):
        report = {'backends': [self.codex()], 'errors': [{'backend': 'connection:bad', 'error': 'offline'}]}
        self.assertEqual(hub.selection(report, 'codex', 'model-a'), {'provider': 'openai', 'model': 'model-a'})
        self.assertEqual(hub.selection(report, 'codex', None), {})
        for backend, model in [('codex', 'invented'), ('connection:bad', None), ('missing', 'a')]:
            with self.subTest(backend=backend), self.assertRaises(ValueError):
                hub.selection(report, backend, model)
        with self.assertRaisesRegex(ValueError, 'not signed in'):
            hub.selection({'backends': [self.codex(False)]}, 'codex', None)
        b = {'id': 'connection:studio', 'adapter': 'responses', 'connection': 'studio', 'models': ['paid-model']}
        self.assertEqual(hub.selection({'backends': [b]}, b['id'], 'paid-model'),
                         {'provider': 'harbor_studio', 'connection': 'studio', 'model': 'paid-model'})
        with self.assertRaises(ValueError):
            hub.selection({'backends': [b]}, b['id'], None)

    def test_local_execution_host_is_reserved(self):
        with self.assertRaisesRegex(ValueError, 'reserved'):
            remote_dev.validate({'id': 'local', 'kind': 'ssh', 'ssh': 'user@other', 'root': '~/projects'})

    def test_n_hosts_without_credential_duplication(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CODEX_WORKSPACE_BASE_DATA': tmp}):
            store = remote_dev.Store(tmp)
            for n in range(50):
                store.change('host-' + str(n), {'id': 'host-' + str(n), 'kind': 'ssh', 'ssh': 'user@host-'+str(n), 'root': '~/projects'})
            self.assertEqual(len(hub.hosts(app)), 51)
            self.assertFalse((Path(tmp)/'backends.json').exists())
            with patch.object(remote_dev, 'request', return_value={'protocol': 1, 'hub_protocol': 1, 'backends': []}) as request:
                self.assertEqual(hub.catalog(app, 'host-49')['host'], 'host-49')
                self.assertIn('catalog', request.call_args.args[1])
            with patch.object(remote_dev, 'request', return_value={'protocol': 1}):
                with self.assertRaisesRegex(RuntimeError, 'Update Harbor'):
                    hub.catalog(app, 'host-1')

    def test_open_remote_routes_and_never_starts_local(self):
        with patch.object(remote_dev, 'Store') as store, patch.object(remote_dev, 'open_remote') as launch, patch.object(app, 'start') as local:
            hub.open_workspace(app, 'laptop', model='remote-model', instance='example', detached=True)
            launch.assert_called_once_with(store.return_value.get.return_value, None, None, 'example', True, backend='codex', model='remote-model')
            local.assert_not_called()
            launch.side_effect = RuntimeError('offline')
            with self.assertRaises(RuntimeError):
                hub.open_workspace(app, 'laptop')
            local.assert_not_called()

    def test_local_scope_and_no_mutation_on_failed_selection(self):
        with patch.object(hub, 'local_catalog', return_value={'backends': [self.codex()]}), \
                patch.object(app, 'select_instance') as instance, patch.object(app, 'save_preferences') as save, patch.object(app, 'start') as start:
            with self.assertRaises(ValueError):
                hub.open_workspace(app, 'local', model='missing')
            instance.assert_not_called()
            save.assert_not_called()
            hub.open_workspace(app, 'local', model='model-a', detached=True)
            instance.assert_called_once_with('hub-local')
            save.assert_called_once_with(new_session_model={'provider': 'openai', 'model': 'model-a'})
            start.assert_called_once_with(detached=True)

    def test_discovery_keeps_healthy_backends_and_reports_failures(self):
        fake = Mock()
        fake.connection_store.return_value.get.return_value = {'id': 'local', 'kind': 'ollama'}
        fake.connection_store.return_value.all.return_value = [{'id': 'paid', 'kind': 'responses', 'models': ['configured']}]
        with patch.object(hub.ADAPTERS['codex'], 'catalog', side_effect=RuntimeError('auth needed')), \
                patch.object(hub.ADAPTERS['ollama'], 'catalog', side_effect=RuntimeError('offline')), \
                patch.object(hub.ADAPTERS['responses'], 'catalog', return_value={'id': 'connection:paid'}):
            report = hub.local_catalog(fake)
        self.assertEqual(report['backends'], [{'id': 'connection:paid'}])
        self.assertEqual(len(report['errors']), 2)

    def test_cli_all_reports_offline_hosts_without_fallback(self):
        with patch.object(hub, 'hosts', return_value=[{'id': 'local'}, {'id': 'offline'}]), \
                patch.object(hub, 'catalog', side_effect=[{'host': 'local'}, RuntimeError('offline')]), contextlib.redirect_stdout(io.StringIO()) as output:
            hub.cli(['models', '--all'], app)
            self.assertEqual(json.loads(output.getvalue()), [{'host': 'local'}, {'host': 'offline', 'error': 'offline'}])

    def test_remote_worker_validates_before_mutating(self):
        fake = Mock(CODEX='codex')
        fake.hub.selection.side_effect = ValueError('unavailable')
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote_dev.shutil, 'which', return_value='/tool'):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                remote_dev.worker(['open', '--root', tmp, '--backend', 'codex', '--model', 'missing'], fake)
        fake.select_instance.assert_not_called()
        fake.save_preferences.assert_not_called()
        fake.start.assert_not_called()

    def test_remote_open_forwards_backend_model_without_shell_interpolation(self):
        profile = {'id': 'office', 'kind': 'ssh', 'ssh': 'user@office', 'root': '~/projects'}
        with patch.object(remote_dev, 'check'), patch.object(remote_dev.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            remote_dev.open_remote(profile, detached=True, backend='codex', model='model; not-a-command')
            import shlex
            args = shlex.split(run.call_args.args[0][-1])[3:]
            self.assertEqual(args[-5:], ['--backend', 'codex', '--model', 'model; not-a-command', '--detached'])

    def test_worker_success_sets_selection_after_instance_before_start(self):
        fake = Mock(CODEX='codex')
        fake.hub.selection.return_value = {'provider': 'openai', 'model': 'model-a'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote_dev.shutil, 'which', return_value='/tool'), patch.dict(os.environ, {}):
            remote_dev.worker(['open', '--root', tmp, '--backend', 'codex', '--model', 'model-a', '--detached'], fake)
        names = [c[0] for c in fake.mock_calls]
        self.assertLess(names.index('select_instance'), names.index('save_preferences'))
        self.assertLess(names.index('save_preferences'), names.index('start'))
        fake.save_preferences.assert_called_once_with(new_session_model={'provider': 'openai', 'model': 'model-a'})

    def test_remote_worker_catalog_does_not_open_or_clone(self):
        fake = Mock(CODEX='codex')
        fake.hub.local_catalog.return_value = {'protocol': 1, 'backends': []}
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote_dev.shutil, 'which', return_value='/tool'), contextlib.redirect_stdout(io.StringIO()) as output:
            remote_dev.worker(['catalog', '--root', tmp], fake)
            self.assertEqual(json.loads(output.getvalue())['hub_protocol'], 1)
        fake.start.assert_not_called()
        fake.select_instance.assert_not_called()
        fake.save_preferences.assert_not_called()

    def test_sidebar_cancel_and_local_selection_do_not_touch_running_sessions(self):
        side = app.Sidebar(Mock())
        self.addCleanup(side.pool.shutdown)
        side.prompt = Mock(return_value=None)
        with patch.object(hub, 'hosts', return_value=[{'id': 'local'}]), patch.object(hub, 'catalog') as catalog:
            side.open_hub()
            catalog.assert_not_called()
        side.prompt = Mock(side_effect=['local', 'codex'])
        side.choose_model = Mock(return_value={'model': 'model-a'})
        side.confirm = Mock(return_value=True)
        side.submit = lambda job, done, message: done(job())
        with patch.object(hub, 'hosts', return_value=[{'id': 'local'}]), \
                patch.object(hub, 'catalog', return_value={'backends': [self.codex()]}), \
                patch.object(app, 'save_preferences') as save, patch.object(app.subprocess, 'run') as launch:
            side.open_hub()
            save.assert_called_once_with(new_session_model={'provider': 'openai', 'model': 'model-a'})
            launch.assert_not_called()
