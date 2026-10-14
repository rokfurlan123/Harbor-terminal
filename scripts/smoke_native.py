"""Open and clean up only a newly-created smoke-test draft; sends no prompt."""
import sys
from pathlib import Path
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import workspace as app
rpc = app.Rpc()
thread = None
previous = app.preferences().get("last_session")
try:
    thread = rpc.create('Workspace terminal check', str(app.ROOT))
    manager = app.Workspace()
    manager.open(thread)
    pane = manager.main()['pane']
    for attempt in range(2):
        deadline = time.monotonic()+20
        while True:
            capture = app.tmux('capture-pane','-p','-t',pane)
            if 'Do you trust the contents of this directory?' in capture:
                app.tmux('send-keys','-t',pane,'Enter')
            current = next(p['thread'] for p in manager.panes() if p['pane'] == pane)
            if ('OpenAI Codex' in capture and 'Ask Codex to do anything' in capture
                    and 'loading' not in capture and current != thread['id']):
                saved = next(t for t in rpc.threads() if t['id'] == current)
                assert saved['name'] == 'Workspace terminal check'
                break
            if time.monotonic() > deadline:
                raise RuntimeError(capture)
            time.sleep(.2)
        print(f"Native {'reopen' if attempt else 'create'} and sidebar linking: OK")
        if attempt == 0:
            manager.close(current)
            thread = saved
            manager.open(thread)
            pane = manager.main()['pane']
    print(capture)

finally:
    if thread:
        current = next((p['thread'] for p in manager.panes() if p['pane'] == pane), thread['id'])
        manager.close(current)
        rpc.change('archive',current)
        rpc.change('delete',current)
    app.save_preferences(last_session=previous)
    rpc.close()
