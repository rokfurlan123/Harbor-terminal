import os
from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workspace as app


class TitleTests(unittest.TestCase):
    def test_reattach_sets_harbor_terminal_title_without_restarting_panes(self):
        with patch.object(app, 'tmux') as tmux, \
                patch.object(app, 'initialize_projects'), \
                patch.object(app, 'configure_mouse'), \
                patch.object(app, 'configure_keys'), \
                patch.object(app.shutil, 'which', return_value='/usr/bin/tool'), \
                patch.object(app, 'Workspace') as workspace:
            workspace.return_value.panes.return_value = [{'thread': 'sidebar', 'pane': '%2'}]
            app.start(detached=True)
            tmux.assert_any_call('set-option', '-t', app.SESSION, 'set-titles-string', 'Harbor')
            tmux.assert_any_call('set-option', '-t', app.SESSION, 'set-titles', 'on')
            self.assertFalse(any(call.args[0] in ('kill-pane', 'respawn-pane', 'kill-session')
                                 for call in tmux.call_args_list))


class PersistenceTests(unittest.TestCase):
    """Real Codex RPC, with an isolated home and no model generation."""

    def test_saved_conversation_survives_server_restart_and_archive_restore(self):
        with tempfile.TemporaryDirectory(prefix="workspace-history-") as temp:
            home = Path(temp)
            with patch.dict(os.environ, {"CODEX_HOME": temp}), patch.object(app, "DATA", home / "workspace"):
                rpc = app.Rpc(standalone=True)
                try:
                    thread = rpc.create("Persistence test", temp)
                    tid = thread["id"]
                    self.assertTrue(any(t["id"] == tid for t in rpc.threads()))
                finally:
                    rpc.close()
                rpc = app.Rpc(standalone=True)
                try:
                    saved = next(t for t in rpc.threads() if t["id"] == tid)
                    self.assertEqual(saved["name"], "Persistence test")
                    self.assertEqual(saved["cwd"], temp)
                    saved = rpc.ensure(saved)
                    tid = saved["id"]
                    rpc.change("name/set", tid, "Renamed empty conversation")
                    self.assertEqual(next(t for t in rpc.threads() if t["id"] == tid)["name"], "Renamed empty conversation")
                    rpc.change("archive", tid)
                    self.assertFalse(any(t["id"] == tid for t in rpc.threads()))
                    self.assertTrue(any(t["id"] == tid for t in rpc.threads(True)))
                    rpc.change("unarchive", tid)
                    self.assertTrue(any(t["id"] == tid for t in rpc.threads()))
                    rpc.change("archive", tid)
                    rpc.change("delete", tid)
                    self.assertFalse(any(t["id"] == tid for t in rpc.threads(True)))
                finally:
                    rpc.close()


class PaneTests(unittest.TestCase):
    def test_switch_close_reopen_preserves_other_terminal(self):
        with tempfile.TemporaryDirectory(prefix="workspace-panes-") as temp:
            fake = Path(temp) / "fake-codex"
            fake.write_text("#!/bin/sh\nprintf 'TEST CONVERSATION %s\\n' \"$2\"\nexec sleep 120\n")
            fake.chmod(0o700)
            socket = f"workspace-test-{os.getpid()}"
            env = {"CODEX_WORKSPACE_CODEX": str(fake), "CODEX_WORKSPACE_SOCKET": socket,
                   "CODEX_WORKSPACE_DATA": temp}
            with patch.dict(os.environ, env), patch.object(app, "SOCKET", socket), patch.object(app, "DATA", Path(temp)), patch.object(app, "command", side_effect=lambda *args: shlex.join([str(fake), *args])):
                try:
                    app.tmux("-f", "/dev/null", "new-session", "-d", "-s", app.SESSION,
                             "-x", "140", "-y", "40", "sleep 120")
                    main = app.tmux("display-message", "-p", "-t", app.SESSION, "#{pane_id}")
                    window = app.tmux("display-message", "-p", "-t", app.SESSION, "#{window_id}")
                    app.tmux("set-option", "-t", app.SESSION, "@workspace_window", window)
                    app.tmux("set-option", "-p", "-t", main, "@workspace_thread", "home")
                    sidebar = app.tmux("split-window", "-h", "-d", "-l", "38", "-t", main,
                                       "-P", "-F", "#{pane_id}", "sleep 120")
                    app.tmux("set-option", "-p", "-t", sidebar, "@workspace_thread", "sidebar")
                    manager = app.Workspace()
                    a = {"id": "session-a", "cwd": temp}
                    b = {"id": "session-b", "cwd": temp}
                    manager.open(a)
                    first_pane = manager.main()["pane"]
                    manager.open(b)
                    self.assertEqual(manager.main()["thread"], "session-b")
                    manager.open(a)
                    self.assertEqual(manager.main()["pane"], first_pane)
                    self.assertEqual(len(manager.panes()), 4)
                    manager.close("session-a")
                    self.assertEqual(manager.main()["thread"], "home")
                    self.assertTrue(any(p["thread"] == "session-b" for p in manager.panes()))
                    manager.open(a)
                    self.assertNotEqual(manager.main()["pane"], first_pane)
                    self.assertEqual(app.preferences()["last_session"], "session-a")
                    manager.close("session-b")
                    self.assertEqual(manager.main()["thread"], "session-a")
                finally:
                    try:
                        app.tmux("kill-server")
                    except RuntimeError:
                        pass

class RecordedHistoryTests(unittest.TestCase):
    def test_recorded_history_resume_archive_restore_delete(self):
        """Synthetic rollout fixture, isolated from all real user history."""
        import datetime
        import json
        import uuid
        with tempfile.TemporaryDirectory(prefix='workspace-recorded-') as temp:
            home = Path(temp)
            tid = str(uuid.uuid4())
            now = datetime.datetime.now(datetime.timezone.utc)
            stamp = now.isoformat().replace('+00:00','Z')
            folder = home/'sessions'/now.strftime('%Y/%m/%d')
            folder.mkdir(parents=True)
            path = folder/f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{tid}.jsonl"
            rows = [
                {'type':'session_meta','payload':{'id':tid,'timestamp':stamp,'cwd':temp,
                    'originator':'codex_cli_rs','cli_version':'0.155.1','source':'cli','model_provider':'openai'}},
                {'type':'event_msg','payload':{'type':'user_message','message':'Isolated fixture message','images':[]}},
                {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Isolated fixture message'}]}},
            ]
            path.write_text(''.join(json.dumps({'timestamp':stamp,**r})+'\n' for r in rows))
            with patch.dict(os.environ,{'CODEX_HOME':temp}), patch.object(app,'DATA',home/'workspace'):
                rpc = app.Rpc(standalone=True)
                try:
                    result = rpc.call('thread/resume',{'threadId':tid})
                    self.assertEqual(result['thread']['id'],tid)
                    rpc.change('name/set',tid,'Recorded fixture')
                finally:
                    rpc.close()
                rpc = app.Rpc(standalone=True)
                try:
                    result = rpc.call('thread/resume',{'threadId':tid})
                    self.assertEqual(result['thread']['name'],'Recorded fixture')
                    rpc.change('archive',tid)
                    self.assertTrue(any(t['id']==tid for t in rpc.threads(True)))
                    rpc.change('unarchive',tid)
                    self.assertTrue(any(t['id']==tid for t in rpc.threads()))
                    rpc.change('archive',tid)
                    rpc.change('delete',tid)
                    self.assertFalse(any(t['id']==tid for t in rpc.threads(True)))
                finally:
                    rpc.close()


if __name__ == "__main__":
    unittest.main()
