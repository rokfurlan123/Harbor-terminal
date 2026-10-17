#!/usr/bin/env python3
"""Install a local counterpart to the existing PC's Qwen-over-SSH launcher."""
import os
from pathlib import Path


LAUNCHER = '''#!/bin/sh
# Local Qwen launcher installed by Harbor's install_local_qwen.py.
set -eu
if [ "$#" -gt 0 ]; then
    exec "$HOME/.local/bin/ollama" run local-qwen --think=false "$*"
fi
exec "$HOME/.local/bin/ollama" run local-qwen --think=false
'''


def install(home):
    directory = Path(home) / '.local/bin'
    ollama = directory / 'ollama'
    if not os.access(ollama, os.X_OK):
        raise RuntimeError(f'Expected existing local Ollama executable: {ollama}')
    path = directory / 'qwen'
    if path.is_symlink():
        raise RuntimeError(f'Refusing to replace a symlink: {path}')
    if path.exists():
        if path.read_text() != LAUNCHER:
            raise RuntimeError(f'Refusing to overwrite an existing launcher: {path}')
        return path
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, 'w') as stream:
        stream.write(LAUNCHER)
    return path


if __name__ == '__main__':
    try:
        print('Local Qwen launcher ready:', install(Path.home()))
    except (OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
