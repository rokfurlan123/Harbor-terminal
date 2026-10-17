import os, pty, select, struct, subprocess, tempfile, time, fcntl, termios
import unittest
from pathlib import Path
root = str(Path(__file__).resolve().parents[1])
class AttachedToolbarTests(unittest.TestCase):
    def test_attached_f5_and_top_bar_click_cancel_preserve_child_pids(self):
        with tempfile.TemporaryDirectory(prefix='harbor-toolbar-smoke-') as temp:
            sock = 'harbor-toolbar-smoke-' + str(os.getpid())
            env = dict(os.environ, TERM='xterm-256color', CODEX_HOME=temp+'/codex',
                       CODEX_WORKSPACE_DATA=temp+'/data', CODEX_WORKSPACE_BASE_DATA=temp+'/data',
                       CODEX_WORKSPACE_PROJECTS_ROOT=temp, CODEX_WORKSPACE_SOCKET=sock)
            for key in list(env):
                if key.startswith('HARBOR_') or key in ('TMUX', 'TMUX_PANE'):
                    env.pop(key)
            Path(env['CODEX_HOME']).mkdir()
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',40,140,0,0))
            client = None
            output = b''
            def read_until(token, timeout=20):
                nonlocal output
                deadline = time.monotonic()+timeout
                while time.monotonic() < deadline:
                    if select.select([master],[],[],.2)[0]:
                        output += os.read(master,65536)
                        if token in output:
                            return
                raise AssertionError((token,output[-5000:]))
            def tmux(*args):
                return subprocess.check_output(['tmux','-L',sock,*args],text=True).strip()
            try:
                subprocess.run(['python3',root+'/workspace.py','--detached'],env=env,check=True,capture_output=True,timeout=30)
                before=tmux('list-panes','-s','-F','#{pane_id}:#{pane_pid}:#{@workspace_thread}')
                client=subprocess.Popen(['tmux','-L',sock,'attach-session','-t','workspace'],env=env,stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
                os.close(slave)
                read_until(b'HARBOR')
                time.sleep(.5)
                os.write(master,b'\x1b[15~')
                read_until(b'CHOOSE MODEL')
                output=b''
                os.write(master,b'\x1b')
                read_until(b'F5 Model')
                output=b''
                os.write(master,b'\x1b[<0;15;1M')
                time.sleep(.12)
                os.write(master,b'\x1b[<0;15;1m')
                read_until(b'CHOOSE MODEL')
                os.write(master,b'\x1b')
                time.sleep(.5)
                after=tmux('list-panes','-s','-F','#{pane_id}:#{pane_pid}:#{@workspace_thread}')
                assert before==after,(before,after)
                assert tmux('show-options','-v','-t','workspace','status-position')=='top'
                assert 'model-picker' in tmux('list-keys','-T','root','MouseUp1StatusLeft')
                assert 'model-picker' in tmux('list-keys','-T','root','MouseUp1StatusDefault')
            finally:
                subprocess.run(['tmux','-L',sock,'kill-server'],capture_output=True)
                if client:
                    client.wait(timeout=5)
                os.close(master)
