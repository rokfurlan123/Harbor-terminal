"""Session tools: isolated real tmux/RPC, synthetic drafts, no model turns."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import session_tools as tools
import workspace as app


class ProtocolTests(unittest.TestCase):
    def test_pins_instance_for_native_cli_and_start_resume(self):
        config = tools.launch_config(Path('/tmp/example'), 'test-socket')
        server = config['mcp_servers.harbor_sessions']
        self.assertEqual(server['env']['HARBOR_SOCKET'], 'test-socket')
        self.assertEqual(server['env']['CODEX_WORKSPACE_DATA'], '/tmp/example')
        self.assertEqual(server['enabled_tools'], ['search_threads', 'open_thread'])
        self.assertIn('mcp_servers.harbor_sessions=', app.native_launch_args(config)[1])
        for method in ('thread/start', 'thread/resume'):
            request = {'method': method, 'params': {'config': {'keep': 1}, 'approvalPolicy': 'on-request'}}
            result = app.mode_transform('auto', launch_config=config)(request)
            self.assertEqual(result['params']['config']['mcp_servers.harbor_sessions'], server)
            self.assertEqual(result['params']['config']['keep'], 1)
            self.assertEqual(result['params']['approvalPolicy'], 'on-request')

    def test_invalid_arguments_are_errors_without_side_effects(self):
        with patch.object(tools, 'connect') as connect:
            for tid in (None, [], '../path', '-t', str(uuid.uuid4()).upper()):
                result = tools.dispatch({'method': 'tools/call', 'params': {
                    'name': 'open_thread', 'arguments': {'threadId': tid}}})
                self.assertTrue(result['isError'], result)
            for args in ([], {'threadId': str(uuid.uuid4()), 'restore': True}):
                result = tools.dispatch({'method': 'tools/call', 'params': {'name': 'open_thread', 'arguments': args}})
                self.assertTrue(result['isError'], result)
            connect.assert_not_called()

    def test_protocol_survives_malformed_requests(self):
        messages = ['not json', '[]', json.dumps({'id': 2, 'method': 'initialize'}),
                    json.dumps({'method': 'notifications/initialized'}),
                    json.dumps({'id': 3, 'method': 'tools/list'}),
                    json.dumps({'id': 4, 'method': 'tools/call', 'params': {
                        'name': 'open_thread', 'arguments': {'threadId': 'invalid'}}})]
        proc = subprocess.run([sys.executable, tools.__file__, 'serve'], input='\n'.join(messages) + '\n',
                              text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[2]['result']['serverInfo']['name'], 'harbor_sessions')
        self.assertEqual({t['name'] for t in rows[3]['result']['tools']}, {'search_threads', 'open_thread'})
        self.assertTrue(rows[4]['result']['isError'])
        self.assertEqual(proc.stderr, '')

    def test_requires_explicit_instance(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app, 'Workspace') as manager:
            with self.assertRaisesRegex(ValueError, 'intended Harbor'):
                tools.connect()
            manager.assert_not_called()

    def test_missing_main_pane_is_a_clear_error(self):
        with patch.dict(os.environ, {'CODEX_WORKSPACE_DATA': '/tmp/unused', 'CODEX_WORKSPACE_SOCKET': 'unused'}), \
                patch.object(app, 'Workspace') as manager:
            manager.return_value.main.side_effect = StopIteration
            with self.assertRaisesRegex(RuntimeError, 'not running'):
                tools.connect()


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='harbor-navigation-')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.socket = 'harbor-navigation-' + uuid.uuid4().hex[:12]
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'HARBOR_', 'OPENAI_'))}
        env.update(CODEX_HOME=str(self.data), CODEX_WORKSPACE_DATA=str(self.data),
                   CODEX_WORKSPACE_SOCKET=self.socket)
        self.env = env
        for patcher in (patch.dict(os.environ, env, clear=True), patch.object(app, 'DATA', self.data),
                        patch.object(app, 'SOCKET', self.socket)):
            patcher.start()
            self.addCleanup(patcher.stop)
        server = subprocess.Popen([app.CODEX, 'app-server', '--listen', 'unix://' + str(self.data / 'server.sock')],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (server.terminate(), server.wait(timeout=10)))
        deadline = time.monotonic() + 10
        while not (self.data / 'server.sock').exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.05)
        app.tmux('-f', '/dev/null', 'new-session', '-d', '-s', app.SESSION, '-x', '140', '-y', '40', 'sleep 120')
        self.addCleanup(lambda: app.tmux('kill-server'))
        main = app.tmux('display-message', '-p', '-t', app.SESSION, '#{pane_id}')
        window = app.tmux('display-message', '-p', '-t', app.SESSION, '#{window_id}')
        app.tmux('set-option', '-t', app.SESSION, '@workspace_window', window)
        app.tmux('set-option', '-p', '-t', main, '@workspace_thread', 'home')
        side = app.tmux('split-window', '-h', '-d', '-l', '38', '-t', main, '-P', '-F', '#{pane_id}', 'sleep 120')
        app.tmux('set-option', '-p', '-t', side, '@workspace_thread', 'sidebar')
        self.manager = app.Workspace()
        rpc = app.Rpc()
        try:
            self.a = rpc.create('Cleaning invoice', str(self.data))
            self.b = rpc.create('Pulse metronome development', str(self.data))
            self.archived = rpc.create('Pulse old archived session', str(self.data))
            rpc.change('archive', self.archived['id'])
        finally:
            rpc.close()
        with patch.object(app, 'command', return_value='sleep 120'):
            self.manager.open(self.a)
            self.manager.open(self.b)
            self.manager.open(self.a)

    def snapshot(self):
        return app.tmux('list-panes', '-s', '-t', app.SESSION,
                        '-F', '#{pane_id}:#{pane_pid}:#{@workspace_thread}').splitlines()

    def mcp(self, name, arguments):
        request = {'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
        proc = subprocess.run([sys.executable, tools.__file__, 'serve'], input=json.dumps(request) + '\n',
                              env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)['result']

    def test_real_mcp_search_switch_reuse_and_failure_preserve_processes(self):
        before = sorted(self.snapshot())
        result = self.mcp('search_threads', {'query': 'PULSE'})
        matches = json.loads(result['content'][0]['text'])['threads']
        self.assertEqual([t['id'] for t in matches], [self.b['id']])
        pane = next(p['pane'] for p in self.manager.panes() if p['thread'] == self.b['id'])
        for _ in range(2):
            result = self.mcp('open_thread', {'threadId': self.b['id']})
            self.assertNotIn('isError', result)
            self.assertTrue(json.loads(result['content'][0]['text'])['alreadyOpen'])
            self.assertEqual(self.manager.main()['pane'], pane)
            self.assertEqual(sorted(self.snapshot()), before)
        for tid in (self.archived['id'], str(uuid.uuid4())):
            self.assertTrue(self.mcp('open_thread', {'threadId': tid})['isError'])
            self.assertEqual(self.manager.main()['pane'], pane)
            self.assertEqual(sorted(self.snapshot()), before)

    def test_cold_open_and_cli(self):
        rpc = app.Rpc()
        try:
            cold = rpc.create('Cold saved session', str(self.data))
        finally:
            rpc.close()
        before = set(self.snapshot())
        with patch.object(app, 'command', return_value='sleep 120'):
            self.assertFalse(tools.open_thread(cold['id'])['alreadyOpen'])
            self.assertTrue(tools.open_thread(cold['id'])['alreadyOpen'])
        self.assertEqual(len(self.snapshot()), len(before) + 1)
        self.assertTrue(before.issubset(set(self.snapshot())))
        proc = subprocess.run([sys.executable, app.__file__, 'sessions', 'open', self.b['id']],
                              env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['threadId'], self.b['id'])
        self.assertEqual(self.manager.main()['thread'], self.b['id'])

    def test_missing_instance_does_not_fallback(self):
        before = sorted(self.snapshot())
        with patch.object(app, 'SOCKET', self.socket + '-absent'):
            with self.assertRaises(RuntimeError):
                tools.open_thread(self.b['id'])
        self.assertEqual(sorted(self.snapshot()), before)
        self.assertEqual(self.manager.main()['thread'], self.a['id'])

    def test_native_codex_executes_mcp_switch_without_real_inference(self):
        calls, failures = [], []
        target = self.b['id']

        def tool_names(value, prefix=''):
            if isinstance(value, dict):
                if value.get('type') == 'namespace':
                    for tool in value.get('tools', []):
                        yield from tool_names(tool, value['name'] + '.')
                else:
                    if isinstance(value.get('name'), str):
                        yield prefix + value['name']
                    for nested in value.values():
                        yield from tool_names(nested, prefix)
            elif isinstance(value, list):
                for nested in value:
                    yield from tool_names(nested, prefix)

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                item = {'id': 'message_fixture', 'type': 'message', 'role': 'assistant',
                        'status': 'completed', 'content': [{'type': 'output_text',
                        'text': 'SWITCH_FIXTURE_COMPLETE', 'annotations': []}]}
                if len(calls) == 1:
                    tool = next((n for n in tool_names(calls[-1].get('tools', []))
                                 if 'harbor_sessions' in n and n.endswith('open_thread')), None)
                    if tool is None:
                        failures.append('Native tool catalog did not contain open_thread')
                    else:
                        namespace, _, name = tool.rpartition('.')
                        item = {'id': 'fc_fixture', 'type': 'function_call', 'call_id': 'call_fixture',
                                'status': 'completed', 'name': name or tool, 'namespace': namespace or None,
                                'arguments': json.dumps({'threadId': target})}
                response = {'id': 'resp_fixture', 'object': 'response', 'created_at': 0,
                            'status': 'completed', 'output': [item],
                            'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
                events = [{'type': 'response.created', 'response': dict(response, status='in_progress', output=[])},
                          {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                          {'type': 'response.completed', 'response': response}]
                body = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = tools.launch_config(self.data, self.socket)
        model = {'model': 'session-fixture', 'provider': 'harbor_fixture', 'provider_config': {
            'name': 'fixture', 'wire_api': 'responses', 'requires_openai_auth': False,
            'supports_websockets': False, 'base_url': f'http://127.0.0.1:{server.server_port}/v1'}}
        before = sorted(self.snapshot())
        result = subprocess.run([app.CODEX, 'exec', '--skip-git-repo-check', '--json', '-C', str(self.data),
                                 *app.native_launch_args(config), *app.model_launch_args(model), 'fixture only'],
                                env=dict(self.env, NO_PROXY='127.0.0.1,localhost'), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(failures, [])
        self.assertIn('SWITCH_FIXTURE_COMPLETE', result.stdout)
        self.assertGreaterEqual(len(calls), 2)
        self.assertIn('selected', json.dumps(calls[-1].get('input')))
        self.assertEqual(self.manager.main()['thread'], target)
        self.assertEqual(sorted(self.snapshot()), before)
