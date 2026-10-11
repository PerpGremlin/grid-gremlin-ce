"""A small websocket client, stdlib only (RFC 6455) — for the venues' public
streams (D84: the liquidations Bybit and Binance publish only as a stream).
Text frames only; the client masks what it sends, as the standard requires;
a ping is answered with a pong; fragmented messages are joined; a close is
answered and ends the connection. No compression, no extensions.

  ws = WebSocket.connect('wss://stream.bybit.com/v5/public/linear')
  ws.send_text('{"op":"ping"}'); msg = ws.recv_text(timeout=30)
"""
import base64
import hashlib
import os
import socket
import ssl
import struct
import time
from urllib.parse import urlparse

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 8 * 1024 * 1024          # a venue message past 8 MB is refused, not buffered


class WebSocketError(OSError):
    pass


class Closed(WebSocketError):
    """The server closed the connection (or the socket ended)."""


def accept_key(key):
    """The handshake's proof: base64(sha1(key + GUID))."""
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def frame(opcode, payload, mask=True, fin=True):
    """One frame, as a client sends it: masked with a fresh 4-byte key."""
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    m = 0x80 if mask else 0
    if n < 126:
        head += bytes([m | n])
    elif n < 1 << 16:
        head += bytes([m | 126]) + struct.pack('!H', n)
    else:
        head += bytes([m | 127]) + struct.pack('!Q', n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


class WebSocket:
    def __init__(self, sock):
        self.sock = sock
        self._buf = b''

    @classmethod
    def connect(cls, url, timeout=15, headers=None):
        u = urlparse(url)
        secure = u.scheme == 'wss'
        port = u.port or (443 if secure else 80)
        raw = socket.create_connection((u.hostname, port), timeout=timeout)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname) if secure else raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or '/') + (f'?{u.query}' if u.query else '')
        lines = [f'GET {path} HTTP/1.1', f'Host: {u.hostname}', 'Upgrade: websocket', 'Connection: Upgrade',
                 f'Sec-WebSocket-Key: {key}', 'Sec-WebSocket-Version: 13', 'User-Agent: grid-gremlin']
        lines += [f'{k}: {v}' for k, v in (headers or {}).items()]
        sock.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode())
        ws = cls(sock)
        head = ws._read_until(b'\r\n\r\n', timeout)
        status = head.split(b'\r\n', 1)[0].decode(errors='replace')
        if ' 101 ' not in status + ' ':
            sock.close()
            raise WebSocketError(f'handshake refused: {status}')
        fields = {}
        for line in head.split(b'\r\n')[1:]:
            if b':' in line:
                k, v = line.split(b':', 1)
                fields[k.strip().lower().decode()] = v.strip().decode()
        if fields.get('sec-websocket-accept') != accept_key(key):
            sock.close()
            raise WebSocketError('handshake: the server did not prove the key')
        return ws

    def _read_until(self, marker, timeout):
        self.sock.settimeout(timeout)
        while marker not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise Closed('the connection ended during the handshake')
            self._buf += chunk
        head, self._buf = self._buf.split(marker, 1)
        return head

    def _frame_in_buffer(self):
        """A whole frame from the buffer, consumed, or None while it is not
        all there yet — so a timeout mid-frame never loses its header."""
        b = self._buf
        if len(b) < 2:
            return None
        fin, opcode = bool(b[0] & 0x80), b[0] & 0x0F
        masked, n = bool(b[1] & 0x80), b[1] & 0x7F
        at = 2
        if n == 126:
            if len(b) < 4:
                return None
            n, at = struct.unpack('!H', b[2:4])[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, at = struct.unpack('!Q', b[2:10])[0], 10
        if n > MAX_MESSAGE:
            raise WebSocketError(f'a frame of {n} bytes — refused')
        key = None
        if masked:
            if len(b) < at + 4:
                return None
            key, at = b[at:at + 4], at + 4
        if len(b) < at + n:
            return None
        data, self._buf = b[at:at + n], b[at + n:]
        if key:
            data = bytes(x ^ key[i % 4] for i, x in enumerate(data))
        return fin, opcode, data

    def _read_frame(self):
        while True:
            f = self._frame_in_buffer()
            if f is not None:
                return f
            chunk = self.sock.recv(65536)
            if not chunk:
                raise Closed('the connection ended')
            self._buf += chunk

    def send_text(self, text):
        self.sock.sendall(frame(OP_TEXT, text.encode()))

    def recv_text(self, timeout=None):
        """The next text message, or None when `timeout` passes with none.
        Pings are answered on the way; a close ends with Closed."""
        self.sock.settimeout(timeout)
        parts, size = [], 0
        try:
            while True:
                fin, opcode, data = self._read_frame()
                if opcode == OP_PING:
                    self.sock.sendall(frame(OP_PONG, data))
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_CLOSE:
                    try:
                        self.sock.sendall(frame(OP_CLOSE, data[:2]))
                    except OSError:
                        pass
                    raise Closed(f'closed by the server ({struct.unpack("!H", data[:2])[0] if len(data) >= 2 else "no code"})')
                if opcode in (OP_TEXT, OP_BIN, OP_CONT):
                    parts.append(data)
                    size += len(data)
                    if size > MAX_MESSAGE:
                        raise WebSocketError('a message past 8 MB — refused')
                    if fin:
                        return b''.join(parts).decode('utf-8', errors='replace')
        except socket.timeout:
            if parts:
                raise WebSocketError('a message cut off mid-frame')
            return None

    def close(self):
        try:
            self.sock.sendall(frame(OP_CLOSE, struct.pack('!H', 1000)))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
