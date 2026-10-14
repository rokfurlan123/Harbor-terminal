import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

import workspace as app


class InstanceTests(unittest.TestCase):
    def test_default_launches_are_independent_and_named_launch_reconnects(self):
        with tempfile.TemporaryDirectory(prefix='cw-instances-') as temp:
            env = dict(os.environ, CODEX_HOME=temp, CODEX_WORKSPACE_DATA=temp + '/data',
                       CODEX_WORKSPACE_PROJECTS_ROOT=temp)
            env.pop('CODEX_WORKSPACE_SOCKET', None)
            env.pop('CODEX_WORKSPACE_BASE_DATA', None)
            env.pop('CODEX_WORKSPACE_INSTANCE', None)
            base = Path(temp) / 'data'
            with patch.object(app, 'DATA', base):
                rpc = object.__new__(app.Rpc)
                rpc.call = Mock(return_value={'data': [], 'nextCursor': None})
                original = rpc.create('Original unused session', temp, 'conversation', temporary=True)
                app.save_preferences(projects=[temp])
            sockets = []

            def launch(*args):
                return subprocess.check_output(
                    [sys.executable, str(app.ROOT / 'workspace.py'), '--detached', *args],
                    env=env, text=True, stderr=subprocess.STDOUT, timeout=45)

            def tmux(sock, *args):
                return subprocess.check_output(['tmux', '-L', sock, *args], text=True).strip()

            try:
                for _ in range(2):
                    output = launch()
                    name = output.split('Workspace instance: ')[1].split('.')[0]
                    sockets.append('codex-workspace-' + name)
                self.assertNotEqual(*sockets)
                first, second = sockets
                before = tmux(second, 'list-panes', '-t', 'workspace', '-F', '#{pane_id}:#{pane_current_command}')
                pane = tmux(first, 'split-window', '-d', '-t', 'workspace', '-P', '-F', '#{pane_id}', 'sleep 60')
                self.assertEqual(before, tmux(second, 'list-panes', '-t', 'workspace', '-F', '#{pane_id}:#{pane_current_command}'))
                name = first.removeprefix('codex-workspace-')
                launch('--instance', name)
                self.assertIn(pane, tmux(first, 'list-panes', '-t', 'workspace', '-F', '#{pane_id}').splitlines())
                roots = list((Path(temp) / 'data' / 'instances').iterdir())
                self.assertEqual(len(roots), 2)
                self.assertTrue(all((root / 'server.sock').exists() for root in roots))
                for root in roots:
                    with patch.object(app, 'DATA', root):
                        self.assertEqual(app.session_mode(original['id']), 'conversation')
                        self.assertEqual(app.preferences()['projects'], [temp])
                        with app.drafts() as db:
                            self.assertEqual(db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0], 0)
                with patch.object(app, 'DATA', base), app.drafts() as db:
                    self.assertEqual(db.execute('SELECT id FROM drafts').fetchone()[0], original['id'])
            finally:
                for sock in sockets:
                    subprocess.run(['tmux', '-L', sock, 'kill-server'], capture_output=True)
                time.sleep(1)
