"""Tailscale setup acceptance checks with a disposable daemon/API fixture."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import connections
import tailscale_support as ts
import workspace as app

ROOT = Path(__file__).resolve().parents[1]

# Real subprocess fixture: implements discovery and owns an actual HTTP tunnel.
FAKE_CLI = r'''#!/usr/bin/env python3
import json,os,sys,socket,socketserver,select
args=sys.argv[1:]
if args and args[0].startswith('--socket='):args.pop(0)
if args==['status','--json']:
 print(os.environ['TAILSCALE_FIXTURE_STATE']);raise SystemExit(0)
if args[0]!='ssh':raise SystemExit(2)
if os.environ.get('TAILSCALE_FIXTURE_FAILURE'):
 print(os.environ['TAILSCALE_FIXTURE_FAILURE'],file=sys.stderr);raise SystemExit(255)
forward=args[args.index('-L')+1].split(':')
assert forward[0]=='127.0.0.1' and forward[2]=='127.0.0.1'
assert 'StrictHostKeyChecking=yes' in args and 'BatchMode=yes' in args
port,target=int(forward[1]),int(forward[3])
class Proxy(socketserver.BaseRequestHandler):
 def handle(self):
  with socket.create_connection(('127.0.0.1',target)) as remote:
   while True:
    ready,_,_=select.select([self.request,remote],[],[],5)
    if not ready:return
    for source in ready:
     data=source.recv(65536)
     if not data:return
     (remote if source is self.request else self.request).sendall(data)
with socketserver.ThreadingTCPServer(('127.0.0.1',port),Proxy) as server:
 server.daemon_threads=True;server.serve_forever()
'''


class API(BaseHTTPRequestHandler):
    models = ['qwen-fixture:latest', 'other-model:small']
    def log_message(self,*args): pass
    def do_GET(self):
        body=json.dumps({'models':[{'name':m} for m in self.models]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


class TailscaleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='harbor-tailscale-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.state={'BackendState':'Running','Peer':{'peer':{'HostName':'Studio','DNSName':'studio.example.ts.net.',
                    'TailscaleIPs':['100.100.1.2'],'Online':True,'OS':'linux'}}}
        self.fake=self.root/'tailscale';self.fake.write_text(FAKE_CLI);self.fake.chmod(0o700)
        self.env={k:v for k,v in os.environ.items() if not k.startswith(('HARBOR_','CODEX_WORKSPACE_'))}
        self.env.update(HARBOR_TAILSCALE=str(self.fake),TAILSCALE_FIXTURE_STATE=json.dumps(self.state),
                        CODEX_HOME=str(self.root/'codex'),CODEX_WORKSPACE_DATA=str(self.root/'data'),
                        CODEX_WORKSPACE_BASE_DATA=str(self.root/'data'),CODEX_WORKSPACE_SOCKET='harbor-tailscale-'+str(os.getpid()),
                        CODEX_WORKSPACE_PROJECTS_ROOT=str(self.root))
        (self.root/'codex').mkdir()
        self.patcher=patch.dict(os.environ,self.env,clear=True);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.store=connections.Store(self.root/'data')
        self.api=ThreadingHTTPServer(('127.0.0.1',0),API);self.api.daemon_threads=True
        threading.Thread(target=self.api.serve_forever,daemon=True).start()
        self.addCleanup(self.api.server_close);self.addCleanup(self.api.shutdown)
        self.port=self.api.server_port

    def update(self,**values):
        self.state.update(values);os.environ['TAILSCALE_FIXTURE_STATE']=json.dumps(self.state)

    def cli(self,*args):
        return subprocess.run([sys.executable,str(ROOT/'workspace.py'),'connections',*args],
                              env=dict(os.environ),capture_output=True,text=True,timeout=20)

    def test_cli_device_discovery_and_setup_with_nondefault_port_and_model(self):
        listing=self.cli('devices');self.assertEqual(listing.returncode,0,listing.stderr)
        self.assertIn('studio.example.ts.net',listing.stdout)
        result=self.cli('setup','studio','--host','STUDIO','--user','tester','--remote-port',str(self.port),'--model','qwen-fixture')
        self.assertEqual(result.returncode,0,result.stderr)
        profile=self.store.get('studio');self.assertEqual(profile['kind'],'tailscale');self.assertEqual(profile['remote_port'],self.port)
        self.assertIn('qwen-fixture:latest',result.stdout)
        prefs=json.loads((self.root/'data/preferences.json').read_text())
        self.assertEqual(prefs['new_session_model']['connection'],'studio')
        self.assertEqual(prefs['new_session_model']['model'],'qwen-fixture:latest')
        # Reopen from the saved profile and resolve another model independently.
        with connections.connect(connections.Store(self.root/'data').get('studio')) as endpoint:
            self.assertEqual(endpoint.resolve_model('other-model:small'),'other-model:small')
            forwarded=int(endpoint.url.rsplit(':',1)[1])
        with self.assertRaises(OSError):socket.create_connection(('127.0.0.1',forwarded),timeout=.2)
        self.assertEqual((self.root/'data/connections.json').stat().st_mode & 0o777,0o600)

    def test_unknown_offline_and_logged_out_devices_do_not_save(self):
        for host in ('missing','studio'):
            if host=='studio':self.state['Peer']['peer']['Online']=False;self.update()
            with self.assertRaisesRegex(RuntimeError,'not found|offline'):
                connections.setup_tailscale(self.store,'test','tester@'+host,self.port)
            self.assertEqual(self.store.all(),[])
        self.update(BackendState='NeedsLogin')
        with self.assertRaisesRegex(RuntimeError,'not connected'):ts.devices()

    def test_policy_rejection_explains_direction_and_preserves_existing_profile(self):
        previous={'id':'studio','kind':'ollama','url':'http://127.0.0.1:1234'}
        self.store.change('studio',previous)
        os.environ['TAILSCALE_FIXTURE_FAILURE']='tailscale: tailnet policy does not permit you to SSH to this node'
        with self.assertRaisesRegex(RuntimeError,'reverse direction'):
            connections.setup_tailscale(self.store,'studio','tester@studio',self.port,replace=True)
        self.assertEqual(self.store.get('studio')['kind'],'ollama')
        self.assertFalse((self.root/'data/preferences.json').exists())

    def test_unknown_model_and_empty_catalog_do_not_save(self):
        with self.assertRaisesRegex(ValueError,'Model not found'):
            connections.setup_tailscale(self.store,'studio','tester@studio',self.port,model='missing')
        with patch.object(API,'models',[]):
            with self.assertRaisesRegex(RuntimeError,'no installed models'):
                connections.setup_tailscale(self.store,'studio','tester@studio',self.port)
        self.assertEqual(self.store.all(),[])

    def test_replacement_requires_explicit_authorization(self):
        connections.setup_tailscale(self.store,'studio','tester@studio',self.port)
        with self.assertRaisesRegex(ValueError,'exists'):
            connections.setup_tailscale(self.store,'studio','tester@studio',self.port)
        self.assertEqual(len(self.store.all()),1)

    def test_concurrent_setup_cannot_overwrite_an_unconfirmed_connection(self):
        original=connections.Endpoint.models
        def racing(endpoint):
            self.store.change('studio',{'id':'studio','kind':'ollama','url':'http://127.0.0.1:4567'})
            return original(endpoint)
        with patch.object(connections.Endpoint,'models',racing):
            with self.assertRaisesRegex(ValueError,'confirm replacement'):
                connections.setup_tailscale(self.store,'studio','tester@studio',self.port)
        self.assertEqual(self.store.get('studio')['kind'],'ollama')

    def test_only_authenticated_tailnet_devices_and_safe_targets_are_used(self):
        for host in ('studio.example.ts.net','100.100.1.2','Studio'):
            command=ts.prepare({'ssh':'tester@'+host})
            self.assertIn('tester@100.100.1.2',command)
        for target in ('tester@studio;touch bad','-o@studio','tester@host/path'):
            with self.assertRaises(ValueError):connections.validate({'id':'test','kind':'tailscale','ssh':target})
        for port in (0,65536,-1):
            with self.assertRaises(ValueError):connections.validate({'id':'test','kind':'tailscale','ssh':'tester@studio','remote_port':port})
        self.state['Peer']['second']=dict(self.state['Peer']['peer'],DNSName='studio-2.example.ts.net.')
        self.update()
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):ts.prepare({'ssh':'tester@Studio'})

    def test_custom_socket_and_missing_cli_produce_useful_results(self):
        profile=connections.validate({'id':'test','kind':'tailscale','ssh':'tester@studio','tailscale_socket':'/tmp/test-tail.sock'})
        self.assertIn('--socket=/tmp/test-tail.sock',ts.prepare(profile))
        os.environ['HARBOR_TAILSCALE']='/missing/tailscale'
        with self.assertRaisesRegex(RuntimeError,'executable'):ts.devices()

    def test_first_use_uses_coordination_host_keys_and_retains_native_permissions(self):
        profile=connections.validate({'id':'test','kind':'tailscale','ssh':'tester@studio','remote_port':self.port})
        command=connections.ssh_command(profile,12345)
        self.assertEqual(command[:3],[str(self.fake),'ssh','tester@100.100.1.2'])
        self.assertIn('StrictHostKeyChecking=yes',command)
        self.assertNotIn('StrictHostKeyChecking=no',command)
        self.assertNotIn('accept-new',' '.join(command))
        with connections.connect(profile) as endpoint:
            model={'model':'qwen-fixture:latest','provider':'harbor_test','provider_config':endpoint.provider()}
            request={'method':'thread/start','params':{'approvalPolicy':'on-request','sandbox':'workspace-write'}}
            transformed=app.mode_transform('auto','Existing instructions',model)(request)
            self.assertEqual(transformed['params']['approvalPolicy'],'on-request')
            self.assertEqual(transformed['params']['sandbox'],'workspace-write')

    def test_setup_cli_rejects_missing_data_without_waiting_for_input(self):
        result=self.cli('setup')
        self.assertNotEqual(result.returncode,0);self.assertIn('--host',result.stderr)
        result=self.cli('setup','studio','--host','studio','--user','tester','--remote-port','0')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.store.path.exists())

    def test_sidebar_setup_cancel_saves_nothing_and_success_uses_async_setup(self):
        with patch.object(app,'DATA',self.root/'data'):
            side=app.Sidebar(Mock());self.addCleanup(side.pool.shutdown)
            side.prompt=Mock(side_effect=['s','studio',None]);side.manage_connections()
            self.assertEqual(self.store.all(),[])
            side.prompt=Mock(side_effect=['s','studio','studio','tester',str(self.port),'qwen-fixture'])
            side.manage_connections()
            result=side.future.result(timeout=10);side.after(result)
            self.assertEqual(self.store.get('studio')['kind'],'tailscale')
            self.assertEqual(app.preferences()['new_session_model']['model'],'qwen-fixture:latest')

    def test_real_sidebar_guided_setup_and_cancel_with_isolated_history(self):
        sock='harbor-tail-ui-'+str(os.getpid())
        env=dict(os.environ,CODEX_WORKSPACE_SOCKET=sock,TERM='xterm-256color')
        tmux=['tmux','-L',sock]
        def tm(*args):
            return subprocess.check_output([*tmux,*args],text=True).strip()
        def wait_for(check,timeout=15):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if check():return
                time.sleep(.1)
            self.fail('Sidebar condition timed out: '+tm('capture-pane','-p','-t',sidebar))
        def enter(value):
            if value:tm('send-keys','-t',sidebar,'-l',value)
            tm('send-keys','-t',sidebar,'Enter')
        def capture():return tm('capture-pane','-p','-t',sidebar)
        try:
            subprocess.run([sys.executable,str(ROOT/'workspace.py'),'--detached'],env=env,capture_output=True,check=True,timeout=30)
            panes=tm('list-panes','-s','-F','#{pane_id}:#{@workspace_thread}').splitlines()
            sidebar=next(row.split(':')[0] for row in panes if row.endswith(':sidebar'))
            wait_for(lambda:'HARBOR' in capture())
            time.sleep(.4)
            tm('send-keys','-t',sidebar,'C');wait_for(lambda:'Setup Tailscale' in capture())
            enter('s');enter('cancelled');wait_for(lambda:'Tailscale computer' in capture())
            tm('send-keys','-t',sidebar,'Escape');time.sleep(.3)
            self.assertEqual(self.store.all(),[])
            tm('send-keys','-t',sidebar,'C');wait_for(lambda:'Setup Tailscale' in capture())
            for value in ('s','studio','studio','tester',str(self.port),'qwen-fixture'):enter(value)
            wait_for(lambda:self.store.path.exists())
            self.assertEqual(self.store.get('studio')['kind'],'tailscale')
            wait_for(lambda:(self.root/'data/preferences.json').exists() and 'qwen-fixture:latest' in (self.root/'data/preferences.json').read_text())
            self.assertEqual(self.store.all()[0]['ssh'],'tester@studio')
        finally:
            subprocess.run([*tmux,'kill-server'],capture_output=True)


if __name__=='__main__':unittest.main()
