import json
import socket
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import local_runtime
import web_tools as web
import workspace as app


class WebTests(unittest.TestCase):
    def test_rejects_private_addresses_and_non_web_urls(self):
        for url in ('file:///etc/passwd', 'https://user:password@example.com', 'http://example.com:8080',
                    'http://127.0.0.1/', 'http://169.254.169.254/', 'http://100.124.226.26/',
                    'http://[::1]/', 'http://224.0.0.1/', 'https://example.com/\nsecret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                web.public_target(url)
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
        with patch.object(web.socket, 'getaddrinfo', return_value=records), self.assertRaises(ValueError):
            web.public_target('http://attacker.example/')

    def test_redirect_rechecked_and_connection_pins_validated_dns(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
        response = Mock(status=302)
        response.getheader.return_value = 'http://127.0.0.1/secret'
        connection = Mock()
        connection.getresponse.return_value = response
        sock = Mock()
        with patch.object(web.socket, 'getaddrinfo', side_effect=[records, [(2, 1, 6, '', ('127.0.0.1', 80))]]) as dns, \
                patch.object(web.socket, 'socket', return_value=sock), \
                patch.object(web.http.client, 'HTTPConnection', return_value=connection), \
                self.assertRaises(ValueError):
            web.read_public('http://public.example/')
        sock.connect.assert_called_once_with(('93.184.216.34', 80))
        self.assertEqual(dns.call_count, 2)
        connection.close.assert_called_once()

    def test_text_extraction_limits_and_search_results(self):
        with patch.object(web, 'read_public', return_value=('https://example.com', 'text/html',
                               '<h1>Title</h1><script>ignore me</script><p>Answer &amp; evidence</p>')):
            result = web.fetch('https://example.com')
        self.assertIn('Answer & evidence', result['text'])
        self.assertNotIn('ignore me', result['text'])
        with patch.object(web, 'read_public', return_value=('https://example.com', 'text/plain', 'x' * 7000)):
            self.assertTrue(web.fetch('https://example.com')['truncated'])
            self.assertEqual(len(web.fetch('https://example.com')['text']), 6000)
        xml = '<rss><channel><item><title>Source</title><link>https://example.com</link><description>Evidence</description></item></channel></rss>'
        with patch.object(web, 'read_public', return_value=('https://www.bing.com', 'application/xml', xml)):
            self.assertEqual(web.search('test')['results'][0]['url'], 'https://example.com')
        for query in ('', 'x' * 401, None):
            with self.assertRaises(ValueError):
                web.search(query)

    def test_download_size_and_binary_limits(self):
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))]
        for mime, expected in (('application/octet-stream', 'Only text'), ('text/plain', '1 MiB')):
            with self.subTest(mime=mime):
                response = Mock(status=200)
                response.getheader.side_effect = lambda name, default=None: {'Content-Type': mime, 'Content-Encoding': 'identity'}.get(name, default)
                response.read1.return_value = b'x' * (web.MAX_BYTES + 1)
                connection = Mock()
                connection.getresponse.return_value = response
                with patch.object(web.socket, 'getaddrinfo', return_value=records), \
                        patch.object(web.socket, 'socket'), \
                        patch.object(web.http.client, 'HTTPConnection', return_value=connection), \
                        self.assertRaisesRegex(ValueError, expected):
                    web.read_public('http://public.example')
                connection.close.assert_called_once()

    def test_mcp_protocol_and_honest_errors(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'fetch', 'arguments': {'url': 'file:///etc/passwd'}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'shell', 'arguments': {}}},
        ]
        result = subprocess.run([sys.executable, str(Path(web.__file__))], text=True, capture_output=True,
                                input=''.join(json.dumps(m) + '\n' for m in messages), timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), 4)
        self.assertEqual([t['name'] for t in replies[1]['result']['tools']], ['search', 'fetch'])
        self.assertTrue(replies[2]['result']['isError'])
        self.assertTrue(replies[3]['result']['isError'])


class RuntimeTests(unittest.TestCase):
    def test_local_runtime_compact_tools_and_facts_do_not_change_hosted_models(self):
        import tomllib
        local = {'provider': 'harbor_laptop', 'backend': 'ollama', 'model': 'qwen',
                 'inference': 'Ollama on laptop; encrypted SSH'}
        config = app.model_config(local)
        self.assertFalse(config['features.goals'])
        self.assertFalse(config['features.apps'])
        self.assertEqual(config['model_context_window'], 8192)
        self.assertEqual(config['mcp_servers.harbor_web']['enabled_tools'], ['search', 'fetch'])
        for value in config.values():
            self.assertEqual(tomllib.loads('v=' + local_runtime.toml(value))['v'], value)
        params = app.mode_transform('conversation', 'Keep baseline', local)({'method': 'thread/resume'})['params']
        self.assertIn('Ollama on laptop; encrypted SSH', params['developerInstructions'])
        self.assertTrue(params['developerInstructions'].startswith('Keep baseline'))
        params = app.mode_transform('conversation', model=local)({'method': 'thread/resume', 'params': params})['params']
        self.assertEqual(params['developerInstructions'].count('[Verified local runtime facts]'), 1)
        for provider in ('openai', 'harbor_api'):
            self.assertEqual(app.model_config({'model': 'qwen', 'provider': provider, 'backend': 'responses'}), {})
        with patch.dict('os.environ', {'HARBOR_OLLAMA_WEB': '0'}):
            self.assertNotIn('mcp_servers.harbor_web', app.model_config(local))
            self.assertIn('"public_web_tools": false', local_runtime.facts(local))
