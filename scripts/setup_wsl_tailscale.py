#!/usr/bin/env python3
"""Restore an existing Tailscale installation in non-systemd Ubuntu/WSL."""
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


HELPER = Path('/usr/local/sbin/harbor-tailscale-start')
STARTER = '''#!/bin/sh
# Managed by Harbor's scripts/setup_wsl_tailscale.py.
set -eu
mkdir -p /run/tailscale
exec /usr/sbin/start-stop-daemon --start --background --oknodo \\
    --exec /usr/sbin/tailscaled --output /var/log/harbor-tailscaled.log -- \\
    --state=/var/lib/tailscale/tailscaled.state \\
    --socket=/run/tailscale/tailscaled.sock
'''


def boot_config(original):
    """Preserve existing settings/comments; refuse to replace a different hook."""
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.read_string(original)
    if config.get('boot', 'systemd', fallback='false').lower() == 'true':
        raise ValueError('This distro enables systemd; use sudo systemctl enable --now tailscaled instead.')
    command = config.get('boot', 'command', fallback='').strip().strip('"')
    if command:
        if command == str(HELPER):
            return original
        raise ValueError('An existing [boot] command must be preserved; integrate Tailscale with it manually.')
    lines = original.splitlines(keepends=True)
    if original and not original.endswith('\n'):
        lines[-1] += '\n'
    # An empty command still counts as an existing setting: replace only it.
    in_boot = False
    boot_end = None
    for i, line in enumerate(lines):
        section = re.match(r'\s*\[([^]]+)\]', line)
        if section:
            if in_boot:
                boot_end = i
                break
            in_boot = section[1] == 'boot'
        elif in_boot and re.match(r'\s*command\s*[=:]', line, re.I):
            lines[i] = f'command={HELPER}\n'
            return ''.join(lines)
    if config.has_section('boot'):
        lines.insert(boot_end if boot_end is not None else len(lines), f'command={HELPER}\n')
    else:
        lines.extend(['\n[boot]\n', f'command={HELPER}\n'])
    return ''.join(lines)


def atomic_write(path, content, mode):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run: sudo python3 scripts/setup_wsl_tailscale.py')
    if 'microsoft' not in Path('/proc/sys/kernel/osrelease').read_text().lower():
        raise SystemExit('This helper is for WSL only.')
    for binary in ('/usr/sbin/tailscaled', '/usr/sbin/start-stop-daemon', '/usr/bin/tailscale'):
        if not os.access(binary, os.X_OK):
            raise SystemExit('Missing prerequisite: ' + binary)
    path = Path('/etc/wsl.conf')
    original = path.read_text() if path.exists() else ''
    try:
        updated = boot_config(original)
    except (ValueError, configparser.Error) as exc:
        raise SystemExit(str(exc)) from None
    if HELPER.exists() and HELPER.read_text() != STARTER:
        raise SystemExit(f'Refusing to overwrite unrelated helper: {HELPER}')
    if path.is_symlink() or HELPER.is_symlink():
        raise SystemExit('Refusing to replace a symlink.')
    if updated != original and path.exists():
        backup = path.with_name(f'wsl.conf.pre-harbor-{time.time_ns()}')
        shutil.copy2(path, backup)
        print('Backup:', backup, flush=True)
    atomic_write(HELPER, STARTER, 0o755)
    if updated != original:
        atomic_write(path, updated, path.stat().st_mode & 0o777 if path.exists() else 0o644)
    subprocess.run([str(HELPER)], check=True)
    print('Detached Tailscale startup configured now and for future WSL boots. No restart performed.', flush=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(['/usr/bin/tailscale', 'status', '--json'],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and json.loads(result.stdout).get('BackendState') == 'Running':
                print('Tailscale is Running.')
                return
        except (subprocess.TimeoutExpired, ValueError, AttributeError):
            pass
        time.sleep(1)
    raise SystemExit('Startup configured, but Tailscale is not ready. Check /var/log/harbor-tailscaled.log and tailscale status.')


if __name__ == '__main__':
    main()
