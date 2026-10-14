import base64
import hashlib
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from bridge import bridge
from workspace import mode_transform


def frame(data, opcode=1, final=True):
    payload = json.dumps(data).encode() if isinstance(data,dict) else data
    head = bytes([(128 if final else 0) | opcode])
    return head + (bytes([len(payload)]) if len(payload)<126 else b'\x7e'+struct.pack('!H',len(payload))) + payload


def receive(reader):
    head = reader.read(2)
    size = head[1] & 127
    if size == 126:
        size = struct.unpack('!H',reader.read(2))[0]
    elif size == 127:
        size = struct.unpack('!Q',reader.read(8))[0]
    mask = reader.read(4) if head[1] & 128 else b''
    payload = reader.read(size)
    return bytes(v ^ mask[i % 4] for i, v in enumerate(payload)) if mask else payload


class BridgeTests(unittest.TestCase):
    def test_only_matching_start_response_binds_draft(self):
        self.exercise()

    def test_mode_instructions_on_fragmented_start_and_resume(self):
        self.exercise(mode_transform('conversation', 'Keep baseline rules.'))

    def exercise(self, transform=None):
        with tempfile.TemporaryDirectory(prefix='workspace-bridge-') as temp:
            upstream = socket.socket(socket.AF_UNIX)
            upstream.bind(str(Path(temp)/'upstream'))
            upstream.listen(1)
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(Path(temp)/'native'))
            listener.listen(1)
            bound, errors = [], []
            def forward():
                try:
                    bridge(listener,Path(temp)/'upstream',bound.append,transform)
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=forward)
            worker.start()
            client = socket.socket(socket.AF_UNIX)
            client.settimeout(5)
            client.connect(str(Path(temp)/'native'))
            key = base64.b64encode(b'0123456789abcdef').decode()
            client.sendall(f'GET / HTTP/1.1\r\nSec-WebSocket-Key: {key}\r\n\r\n'.encode())
            server,_ = upstream.accept()
            server.settimeout(5)
            reader = server.makefile('rb')
            while reader.readline() != b'\r\n':
                pass
            accept = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            server.sendall(f'HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: {accept}\r\n\r\n'.encode())
            output = client.makefile('rb')
            while output.readline() != b'\r\n':
                pass
            for request in ({'id':1,'method':'thread/read'}, {'id':2,'method':'thread/start'},
                            {'id':3,'method':'thread/resume','params':{'threadId':'abc','developerInstructions':'Keep explicit rules.'}}):
                payload = json.dumps(request).encode()
                client.sendall(frame(payload[:10], final=False) + frame(payload[10:], opcode=0))
                rewritten = transform and request['method'] in ('thread/start', 'thread/resume')
                result = json.loads(receive(reader) if rewritten else receive(reader) + receive(reader))
                if transform and request['method'] in ('thread/start', 'thread/resume'):
                    instruction = result['params'].pop('developerInstructions')
                    self.assertIn('Workspace mode: Conversation', instruction)
                    self.assertTrue(instruction.startswith('Keep explicit rules.' if request['id'] == 3 else 'Keep baseline rules.'))
                    expected = dict(request)
                    expected['params'] = dict(request.get('params', {}))
                    expected['params'].pop('developerInstructions', None)
                    self.assertEqual(result, expected)
                else:
                    self.assertEqual(result, request)
            unrelated = {'id':1,'result':{'thread':{'id':'existing'}}}
            server.sendall(frame(unrelated))
            self.assertEqual(json.loads(receive(output)),unrelated)
            self.assertEqual(bound,[])
            created = {'id':2,'result':{'thread':{'id':'new'}}}
            payload = json.dumps(created).encode()
            server.sendall(frame(payload[:10],final=False)+frame(payload[10:],opcode=0))
            self.assertEqual(json.loads(receive(output)+receive(output)),created)
            self.assertEqual(bound,[{'id':'new'}])
            client.shutdown(socket.SHUT_RDWR)
            output.close()
            client.close()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            reader.close()
            server.close()
            upstream.close()
            listener.close()
            self.assertEqual(errors,[])
