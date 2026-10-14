"""Minimal WebSocket-over-Unix transport for Codex JSON-RPC."""
import base64
import hashlib
import os
import socket
import struct
import sys
import threading


def proxy(path):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(10)
    sock.connect(path)
    stream = sock.makefile('rb')
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
    status = stream.readline()
    headers = {}
    while True:
        line = stream.readline()
        if line in (b'\r\n', b''):
            break
        name, value = line.decode().split(':', 1)
        headers[name.lower()] = value.strip()
    expected = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    if b' 101 ' not in status or headers.get('sec-websocket-accept') != expected:
        raise RuntimeError('Codex socket WebSocket handshake failed')
    sock.settimeout(None)
    lock = threading.Lock()

    def send(payload, opcode=1):
        mask = os.urandom(4)
        size = len(payload)
        head = bytes([128 | opcode])
        head += bytes([128 | size]) if size < 126 else (bytes([254])+struct.pack('!H', size) if size < 65536 else bytes([255])+struct.pack('!Q', size))
        body = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
        with lock:
            sock.sendall(head+mask+body)

    def upload():
        try:
            for line in sys.stdin.buffer:
                if line.strip():
                    send(line.strip())
        except OSError:
            pass
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def read(size):
        data = stream.read(size)
        if len(data) != size:
            raise EOFError
        return data

    threading.Thread(target=upload, daemon=True).start()
    message = bytearray()
    try:
        while True:
            first, second = read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack('!H', read(2))[0]
            elif size == 127:
                size = struct.unpack('!Q', read(8))[0]
            if size > 64 * 1024 * 1024:
                raise RuntimeError('Codex socket frame exceeds 64 MiB')
            mask = read(4) if second & 128 else None
            payload = read(size)
            if mask:
                payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
            opcode = first & 15
            if opcode == 8:
                break
            if opcode == 9:
                send(payload, 10)
            elif opcode in (0, 1, 2):
                message.extend(payload)
                if len(message) > 64 * 1024 * 1024:
                    raise RuntimeError('Codex socket message exceeds 64 MiB')
                if first & 128:
                    sys.stdout.buffer.write(message+b'\n')
                    sys.stdout.buffer.flush()
                    message.clear()
    except EOFError:
        pass
    finally:
        stream.close()
        sock.close()
