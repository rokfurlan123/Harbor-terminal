"""Host/backend routing. Profiles and secrets remain owned by their native stores."""
import argparse
import json

if __package__:
    from . import connections, remote_dev
else:
    import connections, remote_dev


class CodexAdapter:
    id = 'codex'

    def catalog(self, app):
        rpc = app.Rpc(standalone=True)
        try:
            account = rpc.call('account/read', {'refreshToken': False})
            models, cursor = [], None
            while True:
                page = rpc.call('model/list', {'cursor': cursor})
                models.extend(m['model'] for m in page['data'])
                cursor = page.get('nextCursor')
                if not cursor:
                    break
            return {'id': self.id, 'adapter': self.id, 'models': models,
                    'signed_in': bool(account.get('account')),
                    'verification': 'catalog only; inference access is not verified'}
        finally:
            rpc.close()

    def selection(self, backend, model):
        if not backend.get('signed_in'):
            raise ValueError('Codex is not signed in on the selected host. Run codex login there; do not copy credentials.')
        return {'provider': 'openai', 'model': model} if model else {}


class ConnectionAdapter:
    def __init__(self, kind):
        self.id = kind

    def catalog(self, profile):
        with connections.connect(profile) as endpoint:
            return {'id': 'connection:' + profile['id'], 'adapter': self.id,
                    'models': endpoint.models(), 'connection': profile['id'],
                    'verification': ('configured catalog only' if profile['kind'] == 'responses' and profile.get('models')
                                     else 'live catalog only; inference is not verified')}

    def selection(self, backend, model):
        if not model:
            raise ValueError('Choose an explicit model for this backend.')
        name = backend['connection']
        return {'provider': 'ollama', 'model': model} if name == 'local' else {
            'provider': 'harbor_' + name, 'connection': name, 'model': model}


# Extend adapters here, not with machine/model-specific branches in the UI.
# Subscription providers require a real supported adapter, not an API-key workaround.
ADAPTERS = {'codex': CodexAdapter(), **{kind: ConnectionAdapter(kind) for kind in ('ollama', 'ssh', 'tailscale', 'responses')}}


def directory(app):
    return app.os.environ.get('CODEX_WORKSPACE_BASE_DATA', str(app.DATA))


def hosts(app):
    return [{'id': 'local', 'execution': 'this Linux computer'},
            *[dict(p, execution='remote Linux computer') for p in remote_dev.Store(directory(app)).all()]]


def local_catalog(app):
    backends, errors = [], []
    try:
        backends.append(ADAPTERS['codex'].catalog(app))
    except (RuntimeError, OSError, ValueError) as exc:
        errors.append({'backend': 'codex', 'error': str(exc)})
    store = app.connection_store()
    for profile in [store.get('local'), *store.all()]:
        try:
            backends.append(ADAPTERS[profile['kind']].catalog(profile))
        except (RuntimeError, OSError, ValueError) as exc:
            errors.append({'backend': 'connection:' + profile['id'], 'error': str(exc)})
    return {'protocol': 1, 'backends': backends, 'errors': errors}


def catalog(app, host):
    if host == 'local':
        return dict(local_catalog(app), host=host)
    p = remote_dev.Store(directory(app)).get(host)
    result = remote_dev.request(p, ['catalog', '--root', p['root']], timeout=120)
    if result.get('hub_protocol') != 1:
        raise RuntimeError('Update Harbor on the selected host; hub protocol 1 is required.')
    return dict(result, host=host)


def selection(report, backend_id, model):
    backend = next((b for b in report['backends'] if b['id'] == backend_id), None)
    if backend is None:
        detail = next((e['error'] for e in report.get('errors', []) if e['backend'] == backend_id), 'backend not found')
        raise ValueError('Selected backend unavailable (no fallback): ' + detail)
    if model and model not in backend['models']:
        raise ValueError('Model is not in the selected host/backend catalog; no fallback.')
    return ADAPTERS[backend['adapter']].selection(backend, model)


def open_workspace(app, host, backend='codex', model=None, project=None, repo=None, instance=None, detached=False):
    if host != 'local':
        # Validate on the destination immediately before selecting its scoped preference.
        p = remote_dev.Store(directory(app)).get(host)
        return remote_dev.open_remote(p, project, repo, instance, detached, backend=backend, model=model)
    selected = selection(local_catalog(app), backend, model)
    if project or repo:
        raise ValueError('Local hub opens a workspace; choose local projects in its sidebar.')
    app.select_instance(instance or 'hub-local')
    app.save_preferences(new_session_model=selected)
    app.start(detached=detached)


def cli(argv, app):
    parser = argparse.ArgumentParser(prog='harbor hub', description='Choose an execution host, backend and model. No credential sync or silent fallback.')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('hosts')
    models = sub.add_parser('models')
    models.add_argument('--host', default='local')
    models.add_argument('--all', action='store_true', help='Query every saved execution host; report offline hosts separately')
    launch = sub.add_parser('open')
    launch.add_argument('--host', default='local')
    launch.add_argument('--backend', default='codex', help='codex or connection:PROFILE')
    launch.add_argument('--model', help='Exact model from the selected backend catalog; omitted means native Codex default')
    launch.add_argument('--project')
    launch.add_argument('--repo')
    launch.add_argument('--instance')
    launch.add_argument('--detached', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'hosts':
        print(json.dumps(hosts(app), indent=2))
    elif args.action == 'models':
        if args.all:
            reports = []
            for host in hosts(app):
                try:
                    reports.append(catalog(app, host['id']))
                except (RuntimeError, OSError, ValueError) as exc:
                    reports.append({'host': host['id'], 'error': str(exc)})
            print(json.dumps(reports, indent=2))
        else:
            print(json.dumps(catalog(app, args.host), indent=2))
    else:
        return open_workspace(app, args.host, args.backend, args.model, args.project, args.repo, args.instance, args.detached)
