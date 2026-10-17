"""Verify native provider requests against a fixture, not a real model/cloud."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

import workspace as app


class SearchRequestTests(unittest.TestCase):
    def test_native_requests_disable_search_only_for_ollama(self):
        calls = []

        class API(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                response = {'id': 'resp_fixture', 'object': 'response', 'created_at': 0,
                            'status': 'completed', 'output': [{
                                'id': 'msg_fixture', 'type': 'message', 'role': 'assistant',
                                'status': 'completed', 'content': [{
                                    'type': 'output_text', 'text': 'HELLO_FIXTURE', 'annotations': []}]}],
                            'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
                events = [
                    {'type': 'response.created', 'response': dict(response, status='in_progress', output=[])},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': response['output'][0]},
                    {'type': 'response.completed', 'response': response},
                ]
                body = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), API)
        server.daemon_threads = True
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        for backend in ('ollama', 'responses'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory(prefix='harbor-native-search-') as temp:
                home = Path(temp)
                (home / 'config.toml').write_text('web_search="live"\n')
                env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'HARBOR_', 'OPENAI_'))}
                env.update(CODEX_HOME=temp, OPENAI_API_KEY='synthetic-fixture-only', NO_PROXY='127.0.0.1,localhost')
                model = {'model': 'qwen-fixture', 'provider': 'harbor_fixture', 'backend': backend,
                         'provider_config': {'name': 'fixture', 'wire_api': 'responses',
                                             'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                             'requires_openai_auth': False, 'supports_websockets': False}}
                calls.clear()
                result = subprocess.run([app.CODEX, 'exec', '--skip-git-repo-check', '--json', '-C', temp,
                                         *app.model_launch_args(model), 'hey'],
                                        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn('HELLO_FIXTURE', result.stdout)
                self.assertTrue(calls, result.stdout)
                for request in calls:
                    has_search = any(t.get('type', '').startswith('web_search') for t in request.get('tools', []))
                    self.assertEqual(has_search, backend == 'responses', request.get('tools'))
