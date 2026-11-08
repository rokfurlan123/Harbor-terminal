import datetime
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
import workspace as app

class LaunchTests(unittest.TestCase):
    def test_saved_terminal_resumes_with_configured_permissions_and_recovers_dead_pane(self):
        """Real remote TUI, isolated recorded history, no model generation."""
        with tempfile.TemporaryDirectory(prefix='harbor-resume-') as temp:
            home = Path(temp)
            data = home / 'workspace'
            name = 'harbor-resume-' + uuid.uuid4().hex[:12]
            tid = str(uuid.uuid4())
            now = datetime.datetime.now(datetime.timezone.utc)
            stamp = now.isoformat().replace('+00:00', 'Z')
            folder = home / 'sessions' / now.strftime('%Y/%m/%d')
            folder.mkdir(parents=True)
            path = folder / f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{tid}.jsonl"
            message = 'SAVED_RESUME_FIXTURE'
            rows = [
                {'type': 'session_meta', 'payload': {'id': tid, 'timestamp': stamp,
                    'cwd': temp, 'originator': 'codex_cli_rs', 'cli_version': '0.167.0',
                    'source': 'cli', 'model_provider': 'openai'}},
                {'type': 'event_msg', 'payload': {'type': 'user_message',
                    'message': message, 'images': []}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': message}]}},
            ]
            path.write_text(''.join(json.dumps({'timestamp': stamp, **r}) + '\n' for r in rows))
            (home / 'config.toml').write_text(
                'model="gpt-6.1-sol"\nmodel_reasoning_effort="medium"\n'
                'sandbox_mode="danger-full-access"\napproval_policy="never"\n'
                f'[projects.{json.dumps(temp)}]\ntrust_level="trusted"\n')
            # Synthetic auth skips onboarding without user credentials; no turn is sent.
            (home / 'auth.json').write_text(json.dumps({'auth_mode': 'apikey',
                'OPENAI_API_KEY': 'synthetic-fixture-only'}))
            env = {'CODEX_HOME': temp, 'CODEX_WORKSPACE_DATA': str(data),
                   'CODEX_WORKSPACE_SOCKET': name, 'CODEX_WORKSPACE_PROJECTS_ROOT': temp}
            with patch.dict(os.environ, env), patch.object(app, 'DATA', data), patch.object(app, 'SOCKET', name):
                rpc = None
                try:
                    app.start(detached=True)
                    rpc = app.Rpc()
                    thread = rpc.call('thread/resume', {'threadId': tid})['thread']
                    manager = app.Workspace()

                    def wait_for_history():
                        deadline = time.monotonic() + 20
                        while True:
                            pane = manager.main()
                            capture = app.tmux('capture-pane', '-p', '-t', pane['pane'])
                            self.assertEqual(pane['dead'], '0', capture)
                            self.assertNotIn('Permission overrides are not supported', capture)
                            if message in capture:
                                return pane['pane']
                            self.assertLess(time.monotonic(), deadline, capture)
                            time.sleep(.1)

                    manager.open(thread)
                    first = wait_for_history()
                    manager.close(tid)
                    manager.open(thread)
                    reopened = wait_for_history()
                    self.assertNotEqual(first, reopened)
                    # Recover a failed terminal without duplicating its saved entry.
                    app.tmux('respawn-pane', '-k', '-t', reopened, 'exit 7')
                    deadline = time.monotonic() + 5
                    while manager.main()['dead'] != '1':
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.05)
                    manager.open(thread)
                    self.assertEqual(wait_for_history(), reopened)
                    self.assertEqual(sum(p['thread'] == tid for p in manager.panes()), 1)
                finally:
                    if rpc:
                        rpc.close()
                    try:
                        app.tmux('kill-server')
                    except RuntimeError:
                        pass
                    time.sleep(1)

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
                    # Wait for the catalog before navigating; actions during a
                    # background refresh are intentionally ignored. The outer
                    # toolbar also resizes the child once during startup.
                    deadline = time.monotonic() + 10
                    while True:
                        capture = app.tmux('capture-pane', '-p', '-t', side['pane'])
                        if '1 saved conversations' in capture:
                            break
                        self.assertLess(time.monotonic(), deadline, capture)
                        time.sleep(.05)
                    for key in ('Down', 'Down', 'Enter', 'Down'):
                        app.tmux('send-keys', '-t', side['pane'], key)
                        time.sleep(.15)
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
