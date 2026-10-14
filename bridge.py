"""Forward a native TUI connection and record its newly started thread."""
import json
import os
import socket
import struct
import threading


def encode_message(payload):
    """Client-to-server WebSocket messages must be masked."""
    size = len(payload)
    header = b'\x81' + (bytes([128 | size]) if size < 126 else
                         b'\xfe' + struct.pack('!H', size) if size < 65536 else
                         b'\xff' + struct.pack('!Q', size))
    mask = os.urandom(4)
    return header + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(payload))


def bridge(listener, upstream_path, on_thread, transform=None):
    client, _ = listener.accept()
    upstream = socket.socket(socket.AF_UNIX)
    upstream.connect(str(upstream_path))
    client.settimeout(10)
    upstream.settimeout(10)
    reader = upstream.makefile('rb')
    try:
        # Forward the native WebSocket handshake unchanged.
        request = bytearray()
        while not request.endswith(b'\r\n\r\n'):
            chunk = client.recv(1)
            if not chunk or len(request) >= 65536:
                raise RuntimeError('Invalid native WebSocket handshake')
            request.extend(chunk)
        upstream.sendall(request)
        response = bytearray()
        while not response.endswith(b'\r\n\r\n'):
            chunk = reader.read(1)
            if not chunk or len(response) >= 65536:
                raise RuntimeError('Invalid service WebSocket handshake')
            response.extend(chunk)
        client.sendall(response)
        client.settimeout(None)
        upstream.settimeout(None)

        start_ids = set()

        def frame(stream):
            header = stream.read(2)
            if len(header) != 2:
                raise EOFError
            first, second = header
            size = second & 127
            extra = b''
            if size in (126, 127):
                extra = stream.read(2 if size == 126 else 8)
                size = struct.unpack('!H' if size == 126 else '!Q', extra)[0]
            if size > 64 * 1024 * 1024:
                raise RuntimeError('Socket frame exceeds 64 MiB')
            mask = stream.read(4) if second & 128 else b''
            payload = stream.read(size)
            if len(payload) != size:
                raise EOFError
            decoded = bytes(v ^ mask[i % 4] for i, v in enumerate(payload)) if mask else payload
            return first, decoded, header+extra+mask+payload

        def upload():
            incoming = client.makefile('rb')
            message = bytearray()
            original = bytearray()
            try:
                while True:
                    first, payload, raw = frame(incoming)
                    if first & 15 in (0, 1, 2):
                        message.extend(payload)
                        if transform:
                            original.extend(raw)
                        if len(message) > 64 * 1024 * 1024:
                            raise RuntimeError('Native message exceeds 64 MiB')
                        if first & 128:
                            data = json.loads(message)
                            if data.get('method') == 'thread/start':
                                start_ids.add(data['id'])
                            if transform:
                                changed = transform(data)
                                upstream.sendall(encode_message(json.dumps(changed).encode())
                                                 if changed is not None else original)
                                original.clear()
                            message.clear()
                        if transform:
                            continue
                    upstream.sendall(raw)
            except (OSError, EOFError):
                pass
            finally:
                incoming.close()
                try:
                    upstream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        threading.Thread(target=upload, daemon=True).start()
        message = bytearray()
        bound = False
        while True:
            try:
                first, payload, raw = frame(reader)
            except EOFError:
                break
            if first & 15 in (0, 1, 2) and not bound:
                message.extend(payload)
                if len(message) > 64 * 1024 * 1024:
                    raise RuntimeError('Service message exceeds 64 MiB')
                if first & 128:
                    data = json.loads(message)
                    thread = data.get('result', {}).get('thread')
                    if thread and data.get('id') in start_ids and on_thread:
                        on_thread(thread)
                        bound = True
                    message.clear()
            client.sendall(raw)
            if first & 15 == 8:
                break
    finally:
        reader.close()
        upstream.close()
        client.close()
