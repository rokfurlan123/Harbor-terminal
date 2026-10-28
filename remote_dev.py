"""Whole-workspace remote development, separate from model connections."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse

if __package__:
    from . import tailscale_support
else:
    import tailscale_support


def validate(profile):
    p = dict(profile)
    if set(p) - {'id', 'kind', 'ssh', 'root', 'tailscale_socket'}:
        raise ValueError('Unsupported development host fields; do not store credentials.')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', p.get('id', '')):
        raise ValueError('Host ID must start with a lowercase letter; use letters, digits, - or _.')
    if p.get('kind') not in ('tailscale', 'ssh'):
        raise ValueError('Development transport must be tailscale or ssh.')
    if not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*', p.get('ssh', '')):
        raise ValueError('SSH target must be user@hostname or user@IPv4.')
    root = p.get('root', '~/projects')
    if not isinstance(root, str) or not (root.startswith('/') or root.startswith('~/')) or any(ord(c) < 32 for c in root):
        raise ValueError('Projects root must be an absolute Linux path or ~/path.')
    if root == '/mnt' or root.startswith('/mnt/') or '..' in Path(root).parts:
        raise ValueError('Use a Linux projects root, without parent traversal or Windows mounts.')
    p['root'] = root
    if p.get('tailscale_socket'):
        value = p['tailscale_socket']
        if p['kind'] != 'tailscale' or not isinstance(value, str) or not value.startswith('/') or any(ord(c) < 32 for c in value):
            raise ValueError('Tailscale socket must be an absolute Linux path.')
    return p


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'development-hosts.json'

    def all(self):
        if not self.path.exists():
            return []
        try:
            items = json.loads(self.path.read_text())
            if not isinstance(items, list):
                raise ValueError()
            items = [validate(p) for p in items]
            if len({p['id'] for p in items}) != len(items):
                raise ValueError()
            return items
        except (ValueError, TypeError, AttributeError):
            raise RuntimeError('Invalid development-hosts.json; repair it before changing hosts.') from None

    def get(self, name):
        for p in self.all():
            if p['id'] == name:
                return p
        raise ValueError('Unknown development host: ' + name)

    def change(self, name, profile=None, replace=False):
        checked = validate(profile) if profile is not None else None
        if checked and checked['id'] != name:
            raise ValueError('Host IDs do not match.')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / 'development-hosts.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.all()
            if checked and not replace and any(p['id'] == name for p in current):
                raise ValueError('Host exists; use --replace to change it.')
            items = [p for p in current if p['id'] != name]
            if checked:
                items.append(checked)
            temp = self.path.with_suffix('.tmp')
            fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as out:
                json.dump(items, out, indent=2)
                out.write('\n')
            temp.replace(self.path)


# Runs on the destination. Only remote PATH is extended; no client credentials,
# environment, home or sessions are sent. The application must be installed there.
BOOTSTRAP = """
import os, pathlib, shutil, sys
home = pathlib.Path.home()
paths = [home/'.local/bin', home/'bin']
paths += sorted((home/'.nvm/versions/node').glob('*/bin'), key=lambda p: p.stat().st_mtime, reverse=True)
os.environ['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin')
harbor = shutil.which('harbor')
if not harbor:
    sys.exit('Harbor is missing on the destination. Install/update Harbor there first.')
os.execv(harbor, [harbor, 'remote-worker', *sys.argv[1:]])
"""


def ssh_command(profile, args, interactive=False):
    p = validate(profile)
    options = ['-tt' if interactive else '-T', '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
               '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes']
    remote = shlex.join(['python3', '-c', BOOTSTRAP, *args])
    if p['kind'] == 'tailscale':
        return tailscale_support.prepare(p) + options + [remote]
    return ['ssh', *options, p['ssh'], remote]


def check(profile):
    result = subprocess.run(ssh_command(profile, ['check', '--root', profile['root']]),
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Remote development check failed (no local fallback): ' +
                           (result.stderr or result.stdout).strip()[-2000:])
    try:
        report = json.loads(result.stdout)
        if report.get('protocol') != 1:
            raise ValueError()
        return report
    except (ValueError, AttributeError):
        raise RuntimeError('Destination needs a compatible Harbor update (remote development protocol 1).') from None


def open_remote(profile, project=None, repo=None, instance=None, detached=False):
    check(profile)
    args = ['open', '--root', profile['root'], '--label', profile['id']]
    for flag, value in (('--project', project), ('--repo', repo), ('--instance', instance)):
        if value:
            args += [flag, value]
    if detached:
        args.append('--detached')
    elif not sys.stdin.isatty():
        raise ValueError('Open remote development in an interactive terminal, or use --detached.')
    print('REMOTE DEVELOPMENT: ' + profile['ssh'] + ' — files, commands and tests run there.', flush=True)
    result = subprocess.run(ssh_command(profile, args, interactive=not detached))
    if result.returncode:
        raise RuntimeError('Remote workspace disconnected or failed. Reopen the same host to reconnect; nothing was started locally.')


def cli(argv, directory):
    parser = argparse.ArgumentParser(prog='harbor remote', description='Develop entirely on a Linux SSH host, not just remote inference.')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    setup = sub.add_parser('setup')
    setup.add_argument('name')
    setup.add_argument('--host', required=True)
    setup.add_argument('--user', required=True)
    setup.add_argument('--kind', choices=['tailscale', 'ssh'], default='tailscale')
    setup.add_argument('--root', default='~/projects')
    setup.add_argument('--tailscale-socket')
    setup.add_argument('--replace', action='store_true')
    for action in ('test', 'remove', 'open'):
        p = sub.add_parser(action)
        p.add_argument('name')
        if action == 'open':
            p.add_argument('--project')
            p.add_argument('--repo', help='Git URL or GitHub owner/repo; clone only if absent')
            p.add_argument('--instance')
            p.add_argument('--detached', action='store_true')
    args = parser.parse_args(argv)
    store = Store(directory)
    if args.action == 'list':
        for p in store.all():
            print(p['id'], p['ssh'], p['root'], '(remote execution)')
    elif args.action == 'setup':
        p = validate(dict(id=args.name, kind=args.kind, ssh=args.user+'@'+args.host, root=args.root,
                          **({'tailscale_socket': args.tailscale_socket} if args.tailscale_socket else {})))
        if not args.replace and any(v['id'] == args.name for v in store.all()):
            raise ValueError('Host exists; use --replace to change it.')
        report = check(p)
        store.change(args.name, p, replace=args.replace)
        print('Saved remote development host:', args.name, json.dumps(report, sort_keys=True))
    elif args.action == 'test':
        print(json.dumps(check(store.get(args.name)), indent=2))
    elif args.action == 'remove':
        store.get(args.name)
        store.change(args.name)
        print('Removed profile only; remote files and sessions are unchanged.')
    else:
        open_remote(store.get(args.name), args.project, args.repo, args.instance, args.detached)


def repository_url(value):
    if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        value = 'git@github.com:' + value.removesuffix('.git') + '.git'
    if re.fullmatch(r'git@[A-Za-z0-9][A-Za-z0-9.-]*:[A-Za-z0-9_./-]+', value):
        path = value.split(':', 1)[1]
    else:
        url = urllib.parse.urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
                or any(c.isspace() for c in value)):
            raise ValueError('Use an HTTPS/SSH Git URL without credentials, or GitHub owner/repo.')
        path = url.path
    if '..' in path.split('/') or not path.strip('/'):
        raise ValueError('Invalid repository path.')
    return value


def repository_identity(value):
    value = repository_url(value).rstrip('/').removesuffix('.git')
    if value.startswith('git@'):
        host, path = value[4:].split(':', 1)
        return host.lower() + '/' + path
    url = urllib.parse.urlsplit(value)
    return url.netloc.lower() + url.path


def project_directory(root, project=None, repo=None):
    """Only explicit open can clone. Never overwrite, reset or auto-pull."""
    if repo:
        repo = repository_url(repo)
        project = project or repo.rstrip('/').split('/')[-1].split(':')[-1].removesuffix('.git')
    if not project:
        return None
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', project) or project in ('.', '..'):
        raise ValueError('Project must be one folder name, not a path.')
    dest = root / project
    if dest.is_symlink() or not dest.resolve().is_relative_to(root.resolve()):
        raise ValueError('Refusing a project symlink outside the remote projects root.')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('Project destination is not a directory.')
        if repo:
            top = subprocess.run(['git', '-C', str(dest), 'rev-parse', '--show-toplevel'],
                                 text=True, capture_output=True, timeout=10)
            if top.returncode or Path(top.stdout.strip()).resolve() != dest.resolve():
                raise ValueError('Existing directory has a different/missing origin or is not a repository root; left unchanged.')
            result = subprocess.run(['git', '-C', str(dest), 'remote', 'get-url', 'origin'],
                                    text=True, capture_output=True, timeout=10)
            if result.returncode or repository_identity(result.stdout.strip()) != repository_identity(repo):
                raise ValueError('Existing directory has a different/missing origin; left unchanged.')
    elif repo:
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--', repo, str(dest)], check=True)
    else:
        raise ValueError('Project not found on the remote host. Supply --repo to clone it.')
    return dest


def worker(argv, app):
    parser = argparse.ArgumentParser(prog='harbor remote-worker')
    parser.add_argument('action', choices=['check', 'open'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--label', default='remote')
    parser.add_argument('--project')
    parser.add_argument('--repo')
    parser.add_argument('--instance')
    parser.add_argument('--detached', action='store_true')
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        raise ValueError('Remote development requires Linux/WSL.')
    validate({'id': args.label, 'kind': 'ssh', 'ssh': 'user@remote', 'root': args.root})
    root = Path(args.root).expanduser().resolve()
    if root == Path('/mnt') or Path('/mnt') in root.parents:
        raise ValueError('Remote projects root resolves onto a Windows mount.')
    for tool in ('git', 'tmux', app.CODEX):
        if not shutil.which(tool):
            raise ValueError('Missing remote Linux tool: ' + tool)
    if args.action == 'check':
        version = subprocess.run([app.CODEX, '--version'], capture_output=True, text=True, timeout=10, check=True)
        login = subprocess.run([app.CODEX, 'login', 'status'], capture_output=True, text=True, timeout=10)
        print(json.dumps({'protocol': 1, 'hostname': os.uname().nodename, 'root': str(root),
                          'codex': version.stdout.strip(), 'signed_in': login.returncode == 0,
                          'github_cli': bool(shutil.which('gh'))}))
        return
    dest = project_directory(root, args.project, args.repo)
    root.mkdir(parents=True, exist_ok=True)
    name = args.instance or 'r-' + hashlib.sha256((args.label+str(root)).encode()).hexdigest()[:12]
    os.environ['CODEX_WORKSPACE_REMOTE_HOST'] = args.label
    os.environ['CODEX_WORKSPACE_REMOTE_ROOT'] = str(root)
    os.environ['CODEX_WORKSPACE_PROJECTS_ROOT'] = str(root)
    app.select_instance(name)
    app.initialize_projects()
    if dest:
        projects = list(app.preferences().get('projects', []))
        if str(dest) not in projects:
            app.save_preferences(projects=[*projects, str(dest)])
        app.start(detached=True)
        rpc = app.Rpc()
        try:
            manager = app.Workspace()
            thread = rpc.create_or_reuse('New session', str(dest), 'project',
                                         {p['thread'] for p in manager.panes() if p['dead'] != '1'})
            manager.open(thread)
        finally:
            rpc.close()
    app.start(detached=args.detached)


def facts():
    label = os.environ.get('CODEX_WORKSPACE_REMOTE_HOST')
    if not label:
        return ''
    root = os.environ.get('CODEX_WORKSPACE_REMOTE_ROOT', str(Path.home()/'projects'))
    return ('\n\n[Remote development]\nExecution host: ' + label + '. This Harbor workspace, shell, files, Git, builds and tests run on this Linux host. '
            'For authorized project work, find the repository here under ' + root +
            '; if missing, clone the intended Git repository here using this host’s authenticated Git access. '
            'Do not overwrite an existing checkout or copy client credentials. If the repository is ambiguous, ask for its URL. '
            'Read its AGENTS.md and follow its workflow. Discussion alone does not authorize cloning or edits. '
            'Do not move execution to the client or claim that client-only files are present here. '
            'Model inference location is separate from development execution.\n')
