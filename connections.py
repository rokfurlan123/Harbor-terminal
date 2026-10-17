"""Harbor model connections. Credentials stay in the environment, never in profiles."""
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def validate(profile):
    profile = dict(profile)
    name = profile.get('id', '')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', name):
        raise ValueError('Connection ID must start with a lowercase letter; use letters, digits, - or _.')
    if name == 'local':
        raise ValueError('local is reserved for this computer’s Ollama.')
    kind = profile.get('kind')
    if kind not in ('ollama', 'ssh', 'responses'):
        raise ValueError('Choose ollama, ssh, or responses.')
    allowed = {'id', 'kind', 'url', 'ssh', 'remote_port', 'key_env', 'models'}
    if set(profile) - allowed:
        raise ValueError('Unsupported connection fields; never store credentials in a profile.')
    if kind == 'ssh':
        if not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*', profile.get('ssh', '')):
            raise ValueError('SSH target must be user@hostname or user@IPv4; use SSH config for custom ports/keys.')
        port = int(profile.get('remote_port', 11434))
        if not 1 <= port <= 65535:
            raise ValueError('Remote port must be between 1 and 65535.')
        profile['remote_port'] = port
        if profile.get('url') or profile.get('key_env'):
            raise ValueError('SSH connections use encrypted forwarding to remote loopback Ollama.')
    else:
        url = profile.get('url', '').rstrip('/')
        parsed = urllib.parse.urlsplit(url)
        try:
            loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname or '').is_loopback
        except ValueError:
            loopback = False
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() for c in url) or parsed.scheme not in ('http', 'https')
                or (parsed.scheme == 'http' and not loopback)):
            raise ValueError('Use HTTPS, or loopback HTTP. No credentials, query strings, or fragments in URLs.')
        try:
            parsed.port
        except ValueError:
            raise ValueError('Invalid endpoint port.') from None
        profile['url'] = url
        if profile.get('key_env') and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', profile['key_env']):
            raise ValueError('Enter an environment variable name, not an API key.')
        if profile.get('ssh'):
            raise ValueError('SSH targets belong to ssh connections.')
    models = profile.get('models', [])
    if not isinstance(models, list) or any(not isinstance(m, str) or not m.strip() or any(ord(c) < 32 for c in m) for m in models):
        raise ValueError('Models must be a list of nonempty model IDs.')
    profile['models'] = list(dict.fromkeys(models))
    return profile


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'connections.json'

    def all(self):
        if not self.path.exists():
            return []
        try:
            items = json.loads(self.path.read_text())
            if not isinstance(items, list):
                raise ValueError()
            profiles = [validate(p) for p in items]
            if len({p['id'] for p in profiles}) != len(profiles):
                raise ValueError()
            return profiles
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError('Invalid connections.json; fix it before changing connections.') from None

    def get(self, name):
        if name == 'local':
            return {'id': 'local', 'kind': 'ollama', 'url': 'http://127.0.0.1:11434', 'models': []}
        for profile in self.all():
            if profile['id'] == name:
                return profile
        raise RuntimeError('Connection not found: ' + name + '. Re-add it or choose another model.')

    def change(self, name, profile=None):
        if name == 'local':
            raise ValueError('The built-in local connection cannot be replaced or removed.')
        checked = validate(profile) if profile is not None else None
        if checked and checked['id'] != name:
            raise ValueError('Connection IDs do not match.')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / 'connections.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            profiles = [p for p in self.all() if p['id'] != name]
            if checked:
                profiles.append(checked)
            tmp = self.path.with_suffix('.tmp')
            # Open with 0600 before writing, including when a prior temp exists.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump(profiles, f, indent=2)
                f.write('\n')
            tmp.replace(self.path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Model endpoint redirected; configure its final URL explicitly.')


class Endpoint:
    def __init__(self, profile, url):
        self.profile, self.url = profile, url.rstrip('/')

    def request(self, path, payload=None, timeout=15):
        headers = {'Content-Type': 'application/json'}
        key_env = self.profile.get('key_env')
        if key_env:
            key = os.environ.get(key_env)
            if not key:
                raise RuntimeError('Set ' + key_env + ' in the environment before starting Harbor.')
            headers['Authorization'] = 'Bearer ' + key
        request = urllib.request.Request(self.url + path, headers=headers,
                                        data=json.dumps(payload).encode() if payload is not None else None)
        # Never send local/tunnel traffic through a shell's corporate HTTP proxy.
        handlers = [NoRedirect()]
        if urllib.parse.urlsplit(self.url).hostname in ('localhost', '127.0.0.1', '::1'):
            handlers.append(urllib.request.ProxyHandler({}))
        try:
            with urllib.request.build_opener(*handlers).open(request, timeout=timeout) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise RuntimeError('Model endpoint response is too large.')
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise RuntimeError('Model endpoint returned an invalid response object.')
                return result
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'Model endpoint returned HTTP {exc.code}; check URL and authentication.') from None
        except (OSError, ValueError) as exc:
            raise RuntimeError('Model endpoint unavailable or invalid JSON (' + type(exc).__name__ + ').') from None

    def models(self):
        if self.profile['kind'] == 'responses':
            if self.profile.get('models'):
                return self.profile['models']
            result = self.request('/models')
            field, key = 'data', 'id'
        else:
            result = self.request('/api/tags')
            field, key = 'models', 'name'
        try:
            if not isinstance(result[field], list):
                raise TypeError()
            models = [m[key] for m in result[field]]
        except (KeyError, TypeError):
            raise RuntimeError('Model endpoint returned an invalid model catalog.') from None
        if any(not isinstance(m, str) or not m or any(ord(c) < 32 for c in m) for m in models):
            raise RuntimeError('Endpoint returned invalid model names.')
        return models

    def manage(self, action, model):
        if self.profile['kind'] == 'responses':
            raise ValueError('Load, unload and download apply only to Ollama connections.')
        if not model or any(ord(c) < 32 for c in model):
            raise ValueError('Enter a model name.')
        if action == 'pull':
            result = self.request('/api/pull', {'model': model, 'stream': False}, timeout=3600)
        elif action in ('load', 'unload'):
            result = self.request('/api/generate', {'model': model, 'stream': False,
                                  'keep_alive': '10m' if action == 'load' else 0}, timeout=180)
        else:
            raise ValueError('Unknown model operation.')
        if result.get('error'):
            raise RuntimeError('Ollama could not complete the operation; inspect its service log.')
        return action + ' completed: ' + model

    def resolve_model(self, name):
        models = self.models()
        if name in models:
            return name
        # Ollama accepts an omitted :latest tag; its catalog returns it explicitly.
        if self.profile['kind'] != 'responses' and ':' not in name.rsplit('/', 1)[-1]:
            canonical = name + ':latest'
            if canonical in models:
                return canonical
        raise ValueError('Model not found on ' + self.profile['id'] + '. List models or choose another model.')

    def provider(self):
        provider = {'name': 'Harbor · ' + self.profile['id'], 'wire_api': 'responses',
                    'base_url': self.url + ('' if self.profile['kind'] == 'responses' else '/v1'),
                    'requires_openai_auth': False, 'supports_websockets': False}
        if self.profile.get('key_env'):
            provider['env_key'] = self.profile['key_env']
        return provider


def ssh_command(profile, port):
    return ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-L', f'127.0.0.1:{port}:127.0.0.1:{profile["remote_port"]}', '--', profile['ssh']]


@contextmanager
def connect(profile):
    if profile['kind'] != 'ssh':
        yield Endpoint(profile, profile['url'])
        return
    # Loopback-only, per-operation forwarding. Never daemonize an orphan tunnel.
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    process = subprocess.Popen(ssh_command(profile, port), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 12
        while True:
            if process.poll() is not None:
                raise RuntimeError('SSH connection failed. Verify host key, login and forwarding with ssh ' + profile['ssh'] + '.')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('SSH tunnel timed out. Check Tailscale connectivity and SSH access.')
                time.sleep(.1)
        yield Endpoint(profile, f'http://127.0.0.1:{port}')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
