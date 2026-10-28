import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import remote_dev as remote
import workspace as app


PROFILE = {'id': 'laptop', 'kind': 'ssh', 'ssh': 'user@laptop', 'root': '~/projects'}


class RemoteTests(unittest.TestCase):
    def test_private_profiles_persist_replace_remove_and_reject_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = remote.Store(tmp)
            store.change('laptop', PROFILE)
            self.assertEqual(remote.Store(tmp).get('laptop'), PROFILE)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                store.change('laptop', dict(PROFILE, root='/home/elsewhere'))
            self.assertEqual(store.get('laptop'), PROFILE)
            store.change('laptop', dict(PROFILE, root='/home/elsewhere'), replace=True)
            self.assertEqual(store.get('laptop')['root'], '/home/elsewhere')
            with self.assertRaises(ValueError):
                store.change('laptop', dict(PROFILE, password='secret'), replace=True)
            store.change('laptop')
            self.assertEqual(store.all(), [])
            store.path.write_text('{}')
            with self.assertRaises(RuntimeError):
                store.change('laptop', PROFILE)
            self.assertEqual(store.path.read_text(), '{}')

    def test_bad_profiles_and_windows_mounts(self):
        for values in ({'id': '-option'}, {'ssh': 'user@host;id'}, {'ssh': '-oProxyCommand=x'},
                       {'root': '/mnt/c/private'}, {'root': '~/../bad'}, {'root': 'relative'},
                       {'root': '/mnt/c/projects'}, {'root': '/tmp/line\nbreak'}, {'kind': 'ollama'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                remote.validate(dict(PROFILE, **values))

    def test_ssh_quoting_no_agent_forwarding_and_no_fallback(self):
        args = ['open', '--root', "/home/user/project'; touch /tmp/evil; '"]
        cmd = remote.ssh_command(PROFILE, args, interactive=True)
        self.assertEqual(shlex.split(cmd[-1]), ['python3', '-c', remote.BOOTSTRAP, *args])
        self.assertIn('-tt', cmd)
        for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'ForwardAgent=no', 'ClearAllForwardings=yes'):
            self.assertIn(option, cmd)
        p = dict(PROFILE, kind='tailscale')
        with patch.object(remote.tailscale_support, 'prepare', return_value=['tailscale', 'ssh', 'user@100.1.2.3']):
            self.assertEqual(remote.ssh_command(p, args)[:3], ['tailscale', 'ssh', 'user@100.1.2.3'])
        with patch.object(remote.tailscale_support, 'prepare', side_effect=RuntimeError('offline')), patch.object(remote.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                remote.open_remote(p, detached=True)
            run.assert_not_called()

    def test_check_never_saves_on_failure_and_no_local_launch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote, 'check', side_effect=RuntimeError('offline')), patch.object(app, 'start') as local:
            with self.assertRaises(RuntimeError):
                remote.cli(['setup', 'laptop', '--host', 'host', '--user', 'user'], tmp)
            self.assertFalse(remote.Store(tmp).path.exists())
            local.assert_not_called()
        with patch.object(remote.subprocess, 'run', return_value=Mock(returncode=1, stderr='denied', stdout='')):
            with self.assertRaisesRegex(RuntimeError, 'no local fallback'):
                remote.check(PROFILE)
        with patch.object(remote.subprocess, 'run', return_value=Mock(returncode=0, stderr='', stdout='not protocol JSON')):
            with self.assertRaisesRegex(RuntimeError, 'compatible Harbor'):
                remote.check(PROFILE)

    def test_open_uses_remote_only_and_forwards_exact_options(self):
        with patch.object(remote, 'check'), patch.object(remote.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            remote.open_remote(PROFILE, 'demo', 'owner/demo', instance='test', detached=True)
            args = shlex.split(run.call_args.args[0][-1])
            self.assertEqual(args[3:], ['open', '--root', '~/projects', '--label', 'laptop', '--project', 'demo', '--repo', 'owner/demo', '--instance', 'test', '--detached'])
        with patch.object(remote, 'check'), patch.object(remote.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactive terminal'):
                remote.open_remote(PROFILE)

    def test_repository_urls_and_existing_checkout_safety(self):
        self.assertEqual(remote.repository_url('owner/demo'), 'git@github.com:owner/demo.git')
        self.assertEqual(remote.repository_identity('git@github.com:owner/demo.git'), remote.repository_identity('https://github.com/owner/demo'))
        for value in ('--upload-pack=evil', 'file:///tmp/repo', 'https://secret@github.com/a/b', 'ext::evil', 'https://host/a/../b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                remote.repository_url(value)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'not found'):
                remote.project_directory(root, 'missing')
            for name in ('../outside', '/tmp/outside', '-option', 'a/b'):
                with self.assertRaises(ValueError):
                    remote.project_directory(root, name)
            (root/'link').symlink_to('/tmp')
            with self.assertRaises(ValueError):
                remote.project_directory(root, 'link')
            dest = root/'demo'
            dest.mkdir()
            marker = dest/'user-work'
            marker.write_text('keep')
            with patch.object(remote.subprocess, 'run', side_effect=[Mock(returncode=0, stdout=str(dest)), Mock(returncode=0, stdout='git@github.com:other/repo.git\n')]) as run:
                with self.assertRaisesRegex(ValueError, 'different/missing origin'):
                    remote.project_directory(root, 'demo', 'owner/demo')
                self.assertEqual(run.call_count, 2)
            # A parent repository must not make an ordinary child look like a clone.
            with patch.object(remote.subprocess, 'run', return_value=Mock(returncode=0, stdout=str(root))):
                with self.assertRaisesRegex(ValueError, 'repository root'):
                    remote.project_directory(root, 'demo', 'owner/demo')
            self.assertEqual(marker.read_text(), 'keep')
            self.assertEqual(remote.project_directory(root, 'demo'), dest)

    def test_clone_only_if_missing_reuse_dirty_matching_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(remote.subprocess, 'run') as run:
                self.assertEqual(remote.project_directory(root, repo='owner/demo'), root/'demo')
                self.assertEqual(run.call_args.args[0], ['git', 'clone', '--', 'git@github.com:owner/demo.git', str(root/'demo')])
            (root/'demo').mkdir()
            (root/'demo/dirty').write_text('keep')
            with patch.object(remote.subprocess, 'run', side_effect=[Mock(returncode=0, stdout=str(root/'demo')), Mock(returncode=0, stdout='https://github.com/owner/demo.git\n')]) as run:
                remote.project_directory(root, repo='owner/demo')
                self.assertEqual(run.call_count, 2)
                self.assertNotIn('pull', run.call_args.args[0])
                self.assertEqual((root/'demo/dirty').read_text(), 'keep')

    def test_remote_facts_preserve_native_approvals_and_local_mode(self):
        with patch.dict(os.environ, {'CODEX_WORKSPACE_REMOTE_HOST': 'laptop', 'CODEX_WORKSPACE_REMOTE_ROOT': '/home/user/projects'}):
            request = {'method': 'thread/start', 'params': {'developerInstructions': 'Existing rules', 'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'}}
            for _ in range(2):
                request = app.mode_transform('project')(request)
            params = request['params']
            self.assertEqual(params['developerInstructions'].count('[Remote development]'), 1)
            self.assertIn('Existing rules', params['developerInstructions'])
            self.assertIn('/home/user/projects', params['developerInstructions'])
            self.assertEqual(params['approvalPolicy'], 'on-request')
            self.assertEqual(params['sandbox'], 'workspace-write')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(remote.facts(), '')

    def test_sidebar_cancel_and_popup_preserve_local_panes(self):
        side = app.Sidebar(Mock())
        self.addCleanup(side.pool.shutdown)
        with patch.object(app.remote_dev, 'Store') as store, patch.object(app.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            store.return_value.all.return_value = [PROFILE]
            side.prompt = Mock(side_effect=[None])
            side.remote_development()
            run.assert_not_called()
            side.prompt = Mock(side_effect=['laptop', 'demo', 'owner/demo'])
            side.remote_development()
            cmd = run.call_args.args[0]
            self.assertIn('display-popup', cmd)
            self.assertIn('remote open laptop --project demo --repo owner/demo', cmd[-1])
            self.assertIn('remote sessions remain', side.message)
            self.assertIn('Press Enter', cmd[-1])
            run.return_value.returncode = 1
            side.prompt = Mock(side_effect=['laptop', '', ''])
            side.remote_development()
            self.assertIn('no local fallback', side.message)

    def test_worker_check_read_only_and_stable_remote_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp)/'new-projects')
            fake = Mock(CODEX='codex')
            fake.preferences.return_value = {'projects': []}
            with patch.object(remote.shutil, 'which', return_value='/tool'), patch.object(remote.subprocess, 'run', return_value=Mock(returncode=0, stdout='codex-cli test')):
                remote.worker(['check', '--root', root], fake)
                self.assertFalse(Path(root).exists())
                fake.start.assert_not_called()
                with patch.dict(os.environ, {}):
                    remote.worker(['open', '--root', root, '--label', 'laptop', '--detached'], fake)
                    name = fake.select_instance.call_args.args[0]
                    self.assertTrue(name.startswith('r-'))
                    self.assertLessEqual(len(name), 16)
                    self.assertEqual(os.environ['CODEX_WORKSPACE_REMOTE_HOST'], 'laptop')
                    remote.worker(['open', '--root', root, '--label', 'laptop', '--detached'], fake)
                    self.assertEqual(fake.select_instance.call_args.args[0], name)
                    fake.start.assert_called_with(detached=True)
