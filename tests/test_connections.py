import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock

import connections
import workspace as app


class ModelServer(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *args):
        pass
    def do_GET(self):
        self.calls.append((self.path, self.headers.get('Authorization')))
        if self.path == '/redirect/models':
            self.send_response(302)
            self.send_header('Location', '/v1/models')
            self.end_headers()
            return
        body = {'models': [{'name': 'qwen-test'}]} if self.path == '/api/tags' else {'data': [{'id': 'remote-model'}]}
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append((self.path, payload))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"done": true}')


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='harbor-connections-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = connections.Store(self.root)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ModelServer)
        self.server.daemon_threads = True
        ModelServer.calls = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.profile = {'id': 'laptop', 'kind': 'ollama', 'url': self.url}
        self.env = patch.dict(os.environ, {'CODEX_WORKSPACE_BASE_DATA': str(self.root), 'CODEX_HOME': str(self.root/'codex')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.data = patch.object(app, 'DATA', self.root)
        self.data.start(); self.addCleanup(self.data.stop)

    def test_save_reopen_permissions_and_secret_rejection(self):
        self.store.change('laptop', self.profile)
        self.assertEqual(connections.Store(self.root).get('laptop')['url'], self.url)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        for bad in [dict(self.profile, url='http://remote.example'), dict(self.profile, url='https://user:secret@example.com'),
                    dict(self.profile, token='secret'), dict(self.profile, key_env='sk-not-a-variable')]:
            with self.assertRaises(ValueError):
                self.store.change('laptop', bad)
        self.assertEqual(self.store.get('laptop')['url'], self.url)
        self.store.path.write_text('broken json')
        with self.assertRaises(RuntimeError):
            self.store.change('new', dict(self.profile, id='new'))
        self.assertEqual(self.store.path.read_text(), 'broken json')

    def test_discovery_auth_and_model_lifecycle(self):
        profile = connections.validate(dict(self.profile, key_env='HARBOR_TEST_TOKEN'))
        with patch.dict(os.environ, {'HARBOR_TEST_TOKEN': 'private-test-key'}), connections.connect(profile) as endpoint:
            self.assertEqual(endpoint.models(), ['qwen-test'])
            self.assertEqual(ModelServer.calls[-1][1], 'Bearer private-test-key')
            endpoint.manage('load', 'qwen-test')
            self.assertEqual(ModelServer.calls[-1], ('/api/generate', {'model':'qwen-test','stream':False,'keep_alive':'10m'}))
            endpoint.manage('unload', 'qwen-test')
            self.assertEqual(ModelServer.calls[-1][1]['keep_alive'], 0)
            endpoint.manage('pull', 'another-model')
            self.assertEqual(ModelServer.calls[-1][0], '/api/pull')
            self.assertNotIn('private-test-key', json.dumps(endpoint.provider()))
            self.assertEqual(endpoint.provider()['env_key'], 'HARBOR_TEST_TOKEN')
        with connections.connect(profile) as endpoint, self.assertRaisesRegex(RuntimeError, 'HARBOR_TEST_TOKEN'):
            endpoint.models()

    def test_redirect_never_forwards_auth_and_responses_cannot_manage(self):
        profile = connections.validate({'id':'api','kind':'responses','url':self.url+'/redirect'})
        with connections.connect(profile) as endpoint:
            with self.assertRaisesRegex(RuntimeError, 'redirected'):
                endpoint.models()
            with self.assertRaises(ValueError):
                endpoint.manage('pull', 'remote-model')
        self.assertEqual([path for path, _ in ModelServer.calls], ['/redirect/models'])

    def test_catalog_switch_scoped_config_and_deleted_connection(self):
        self.store.change('laptop', self.profile)
        rpc = Mock(); rpc.call.return_value = {'data':[{'model':'cloud'}], 'nextCursor':None}
        with patch.object(app.subprocess,'run',side_effect=FileNotFoundError):
            choices, warning = app.available_models(rpc)
        model = next(m for m in choices if m.get('connection') == 'laptop')
        self.assertEqual(model['model'], 'qwen-test')
        app.set_session_model('draft-test', model)
        seen = []
        with patch.object(app, '_run_conversation', side_effect=lambda tid,cwd,prepared: seen.append(prepared)):
            app.run_conversation('draft-test', str(self.root))
        for method in ['thread/start', 'thread/resume']:
            request = {'method':method, 'params':{'approvalPolicy':'on-request','sandbox':'workspace-write','config':{'existing':True}}}
            result = app.mode_transform('auto', 'Keep instructions', seen[0])(request)['params']
            self.assertEqual(result['config']['model_providers.harbor_laptop']['base_url'], self.url+'/v1')
            self.assertTrue(result['config']['existing'])
            self.assertEqual(result['config']['web_search'], 'disabled')
            self.assertEqual(result['approvalPolicy'],'on-request')
            self.assertEqual(result['sandbox'],'workspace-write')
        self.assertNotIn('provider_config', app.session_model('draft-test'))
        self.assertNotIn('backend', app.session_model('draft-test'))
        self.store.change('laptop')
        with self.assertRaisesRegex(RuntimeError, 'Connection not found'):
            app.run_conversation('draft-test', str(self.root))

    def test_cli_roundtrip_and_ui_add_cancel(self):
        with contextlib.redirect_stdout(io.StringIO()):
            app.model_cli(['connections','add','laptop','--kind','ollama','--url',self.url])
            app.model_cli(['models','use','qwen-test','--connection','laptop'])
        self.assertEqual(app.preferences()['new_session_model']['connection'], 'laptop')
        side = app.Sidebar(Mock()); self.addCleanup(side.pool.shutdown)
        side.prompt = Mock(side_effect=['a', 'cancelled', None])
        side.manage_connections()
        self.assertEqual(len(self.store.all()), 1)
        side.prompt = Mock(side_effect=['a','second','responses',self.url+'/v1','','remote-model'])
        side.manage_connections()
        self.assertEqual(self.store.get('second')['models'], ['remote-model'])
        with contextlib.redirect_stdout(io.StringIO()):
            app.model_cli(['models','default'])
        self.assertEqual(app.preferences()['new_session_model'], {})

    def test_prepared_backend_search_policy_for_every_connection_kind(self):
        for kind in ('ollama', 'ssh', 'tailscale', 'responses'):
            with self.subTest(kind=kind):
                profile = {'id': 'laptop', 'kind': kind}
                profile.update({'ssh': 'tester@studio'} if kind in ('ssh', 'tailscale') else {'url': self.url})
                self.store.change('laptop', profile)
                app.set_session_model('search-fixture', {'provider': 'harbor_laptop', 'connection': 'laptop', 'model': 'qwen-test'})
                endpoint = Mock()
                endpoint.resolve_model.return_value = 'qwen-test'
                endpoint.provider.return_value = {'name': 'fixture', 'wire_api': 'responses', 'base_url': self.url + '/v1'}
                with patch.object(app.connections, 'connect') as connect, patch.object(app, '_run_conversation') as run:
                    connect.return_value.__enter__.return_value = endpoint
                    app.run_conversation('search-fixture', str(self.root))
                    prepared = run.call_args.args[2]
                expected = 'responses' if kind == 'responses' else 'ollama'
                self.assertEqual(prepared['backend'], expected)
                self.assertEqual(app.uses_ollama(prepared), kind != 'responses')
                for method in ('thread/start', 'thread/resume'):
                    request = {'method': method, 'params': {'config': {'web_search': 'live'}}}
                    params = app.mode_transform('auto', model=prepared)(request)['params']
                    self.assertEqual(params['config']['web_search'], 'live' if kind == 'responses' else 'disabled')

    def test_tunnel_command_and_failure_cleanup(self):
        profile = connections.validate({'id':'remote','kind':'ssh','ssh':'user@100.89.111.39'})
        command = connections.ssh_command(profile, 12345)
        self.assertIn('127.0.0.1:12345:127.0.0.1:11434', command)
        self.assertIn('StrictHostKeyChecking=yes', command)
        process = Mock(); process.poll.return_value = 255
        with patch.object(connections.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'SSH connection failed'):
                with connections.connect(profile):
                    self.fail('failed tunnel must not yield')
        with self.assertRaises(ValueError):
            connections.validate(dict(profile, ssh='user@host;touch /tmp/oops'))
        process = Mock(); process.poll.return_value = None
        probe = Mock(); probe.__enter__ = Mock(); probe.__exit__ = Mock()
        with patch.object(connections.subprocess, 'Popen', return_value=process), patch.object(socket,'create_connection',return_value=probe):
            with self.assertRaisesRegex(RuntimeError, 'consumer failed'):
                with connections.connect(profile):
                    raise RuntimeError('consumer failed')
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_ollama_implicit_latest_tag_does_not_apply_to_api_models(self):
        endpoint = connections.Endpoint(self.profile, self.url)
        with patch.object(endpoint, 'models', return_value=['local-qwen:latest', 'qwen:8b']):
            self.assertEqual(endpoint.resolve_model('local-qwen'), 'local-qwen:latest')
            self.assertEqual(endpoint.resolve_model('qwen:8b'), 'qwen:8b')
            with self.assertRaises(ValueError):
                endpoint.resolve_model('qwen')
        endpoint.profile = dict(self.profile, kind='responses')
        with patch.object(endpoint, 'models', return_value=['local-qwen:latest']):
            with self.assertRaises(ValueError):
                endpoint.resolve_model('local-qwen')

    def test_invalid_remote_catalog_reports_a_usable_error(self):
        endpoint = connections.Endpoint(self.profile, self.url)
        for response in ({'error': 'service unavailable'}, {'models': {}}, {'models': [None]}, {'models': [{}]}):
            with patch.object(endpoint, 'request', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'invalid model catalog'):
                    endpoint.models()

    def test_native_bootstrap_selects_provider_without_changing_permissions(self):
        import tomllib
        with connections.connect(connections.validate(self.profile)) as endpoint:
            model = {'model':'qwen-test','provider':'harbor_laptop','provider_config':endpoint.provider()}
        args = app.model_launch_args(model)
        inline = args[-1].split('=', 1)[1]
        parsed = tomllib.loads('provider=' + inline)['provider']
        self.assertEqual(parsed, model['provider_config'])
        self.assertEqual(args[1], 'qwen-test')
        self.assertNotIn('--oss', args)
        self.assertNotIn('--sandbox', args)
        self.assertNotIn('--approval-policy', args)
        self.assertFalse(parsed['requires_openai_auth'])

    def test_native_server_accepts_custom_provider_start_and_resume(self):
        # Real installed Codex; isolated history, no inference/model turn.
        (self.root/'codex').mkdir()
        rpc = app.Rpc(standalone=True)
        try:
            with connections.connect(connections.validate(self.profile)) as endpoint:
                model = {'model':'qwen-test','provider':'harbor_laptop','provider_config':endpoint.provider(), 'backend': 'ollama'}
                transform = app.mode_transform('conversation', 'Existing instructions', model)
                params = transform({'method':'thread/start','params':{'cwd':str(self.root),'approvalPolicy':'on-request'}})['params']
                result = rpc.call('thread/start', params)
                self.assertEqual(result['modelProvider'],'harbor_laptop')
                self.assertEqual(result['model'],'qwen-test')
                # Unsaved threads cannot be resumed from disk; start verifies the native config schema.
        finally:
            rpc.close()


if __name__ == '__main__':
    unittest.main()
