import os
from pathlib import Path
import tempfile
import time
import subprocess
import socket
import threading
from bridge import bridge
import unittest
from unittest.mock import patch
import workspace as app

class SharedTests(unittest.TestCase):
    def test_shared_catalog_connection(self):
        with tempfile.TemporaryDirectory(prefix='workspace-shared-') as temp:
            data = Path(temp)
            with patch.dict(os.environ, {'CODEX_HOME':temp}), patch.object(app, 'DATA', data):
                server = subprocess.Popen([app.CODEX, 'app-server', '--listen', 'unix://' + str(data/'server.sock')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic()+10
                    while not (data/'server.sock').exists():
                        self.assertLess(time.monotonic(),deadline)
                        time.sleep(.05)
                    rpc = app.Rpc()
                    try:
                        thread = rpc.call('thread/start', {'cwd': temp})['thread']
                        rpc.call('thread/name/set', {'threadId':thread['id'], 'name':'Shared catalog test'})
                        other = app.Rpc()
                        try:
                            self.assertIsInstance(other.threads(),list)
                        finally:
                            other.close()
                    finally:
                        rpc.close()
                    # A real server accepts instructions delivered through the
                    # same bridge used by native new/resumed terminals.
                    bridged = data / 'bridged'
                    bridged.mkdir()
                    listener = socket.socket(socket.AF_UNIX)
                    listener.bind(str(bridged / 'server.sock'))
                    listener.listen(1)
                    bound, failures = [], []
                    def forward():
                        try:
                            bridge(listener, data / 'server.sock', bound.append,
                                   app.mode_transform('conversation', 'Preserve existing configuration.'))
                        except Exception as exc:
                            failures.append(exc)
                    worker = threading.Thread(target=forward)
                    worker.start()
                    try:
                        with patch.object(app, 'DATA', bridged):
                            native = app.Rpc()
                            try:
                                result = native.call('thread/start', {'cwd': temp})
                                self.assertEqual(bound[0]['id'], result['thread']['id'])
                            finally:
                                native.close()
                    finally:
                        listener.close()
                        worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(failures, [])
                finally:
                    server.terminate()
                    server.wait(timeout=10)
