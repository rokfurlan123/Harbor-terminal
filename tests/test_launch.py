import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import workspace as app

class LaunchTests(unittest.TestCase):
    def test_native_terminal_and_sidebar(self):
        with tempfile.TemporaryDirectory(prefix='workspace-launch-') as temp:
            data = Path(temp)/'workspace'
            name = f'workspace-launch-{os.getpid()}'
            env = {'CODEX_HOME':temp, 'CODEX_WORKSPACE_DATA':str(data), 'CODEX_WORKSPACE_SOCKET':name,
                   'CODEX_WORKSPACE_PROJECTS_ROOT': temp}
            with patch.dict(os.environ,env), patch.object(app,'DATA',data), patch.object(app,'SOCKET',name):
                rpc = None
                try:
                    app.start(detached=True)
                    bindings = app.tmux('list-keys', '-T', 'root')
                    keys = [line.split()[3] for line in bindings.splitlines()]
                    self.assertNotIn('F2', keys)
                    self.assertIn('F6', keys)
                    rpc = app.Rpc()
                    thread = rpc.create('Native empty conversation',temp)
                    manager = app.Workspace()
                    manager.open(thread)
                    pane = manager.main()['pane']
                    deadline = time.monotonic()+20
                    while True:
                        capture = app.tmux('capture-pane','-p','-t',pane)
                        if 'OpenAI Codex' in capture or 'Welcome to Codex' in capture:
                            break
                        self.assertLess(time.monotonic(),deadline,capture)
                        time.sleep(.2)
                    self.assertNotIn('no rollout found',capture)
                    manager.close(thread['id'])
                    manager.open(rpc.ensure(thread))
                    self.assertNotEqual(manager.main()['pane'],pane)
                    side = next(p for p in manager.panes() if p['thread']=='sidebar')
                    capture = app.tmux('capture-pane','-p','-t',side['pane'])
                    self.assertIn('HARBOR',capture)
                    # Expand the project branch, then select its session.
                    app.tmux('send-keys', '-t', side['pane'], 'Down', 'Down', 'Enter', 'Down')
                    deadline = time.monotonic() + 5
                    while True:
                        capture = app.tmux('capture-pane', '-p', '-t', side['pane'])
                        if 'Native empty conversation' in capture:
                            break
                        self.assertLess(time.monotonic(), deadline, capture)
                        time.sleep(.05)
                    binding = app.tmux('list-keys', '-T', 'root', 'MouseDown3Pane')
                    self.assertIn('send-keys -M', binding)
                    # tmux-256color's terminfo uses legacy X10 mouse encoding.
                    app.tmux('send-keys', '-t', side['pane'], '-l', '\x1b[M"%+\x1b[M#%+')
                    deadline = time.monotonic() + 5
                    while True:
                        capture = app.tmux('capture-pane', '-p', '-t', side['pane'])
                        if 'Copy session reference' in capture:
                            break
                        self.assertLess(time.monotonic(), deadline, capture)
                        time.sleep(.05)
                    self.assertIn('Delete permanently', capture)
                    app.tmux('send-keys', '-t', side['pane'], 'Escape')
                    # Blank sessions are reused while open and vanish on close.
                    live_ids = lambda: {p['thread'] for p in manager.panes() if p['dead'] == '0'}
                    blank = rpc.create_or_reuse('New session', str(Path.home()), 'auto', live_ids())
                    manager.open(blank)
                    blank_pane = manager.main()['pane']
                    again = rpc.create_or_reuse('New session', str(Path.home()), 'auto', live_ids())
                    manager.open(again)
                    self.assertEqual(manager.main()['pane'], blank_pane)
                    self.assertFalse(any(t['id'] == blank['id'] for t in rpc.threads()))
                    manager.close(blank['id'])
                    self.assertFalse(any(t['id'] == blank['id'] for t in rpc.threads(live_ids=live_ids())))
                    # Simulate crashed support processes and a leftover socket.
                    rpc.close()
                    rpc = None
                    for kind in ('sidebar', 'service'):
                        support = next(p for p in manager.panes() if p['thread'] == kind)
                        app.tmux('respawn-pane', '-k', '-t', support['pane'], 'exit 7')
                        deadline = time.monotonic()+5
                        while next(p for p in manager.panes() if p['pane'] == support['pane'])['dead'] != '1':
                            self.assertLess(time.monotonic(),deadline)
                            time.sleep(.05)
                    app.start(detached=True)
                    rpc = app.Rpc()
                    self.assertTrue(any(t['id'] == thread['id'] for t in rpc.threads()))
                    self.assertTrue(all(p['dead'] == '0' for p in manager.panes()
                                        if p['thread'] in ('service','sidebar')))
                finally:
                    if rpc:
                        rpc.close()
                    try:
                        app.tmux('kill-server')
                    except RuntimeError:
                        pass
                    # tmux exits before Codex finishes flushing its logs.
                    time.sleep(1)
