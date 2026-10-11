"""The websocket client (D84's streams), against a local server: the
handshake and its proof, pings answered, fragments joined, a frame split by
a timeout read whole afterwards, a close."""
import socket
import struct
import threading
import time

from ggdata.ws import (OP_CLOSE, OP_CONT, OP_PING, OP_PONG, OP_TEXT, Closed, WebSocket,
                            WebSocketError, accept_key, frame)


def _server(script, prove=True):
    """A one-connection websocket server on loopback running `script(conn,
    read_frame)` after the handshake. Returns (url, seen) — seen collects
    what the client sent."""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    seen = []

    def read_frame(conn):
        b0, b1 = conn.recv(1)[0], conn.recv(1)[0]
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack('!H', conn.recv(2))[0]
        key = conn.recv(4) if b1 & 0x80 else None
        data = b''
        while len(data) < n:
            data += conn.recv(n - len(data))
        if key:
            data = bytes(x ^ key[i % 4] for i, x in enumerate(data))
        seen.append((b0 & 0x0F, bool(b1 & 0x80), data))
        return b0 & 0x0F, data

    def run():
        conn, _ = srv.accept()
        head = b''
        while b'\r\n\r\n' not in head:
            head += conn.recv(1024)
        key = [l.split(b':', 1)[1].strip().decode() for l in head.split(b'\r\n')
               if l.lower().startswith(b'sec-websocket-key')][0]
        proof = accept_key(key) if prove else 'forged'
        conn.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                      f'Sec-WebSocket-Accept: {proof}\r\n\r\n').encode())
        try:
            script(conn, lambda: read_frame(conn))
        finally:
            conn.close()
            srv.close()
    threading.Thread(target=run, daemon=True).start()
    return f'ws://127.0.0.1:{port}/stream', seen


def spec_D84_the_websocket_client_speaks_the_standard():
    """Python has no websocket client; this one (stdlib) is what the
    liquidation streams ride. Handshake proven; a forged proof refused;
    client frames masked; a ping answered with its pong; a fragmented
    message joined; a frame split across a timeout read whole after it; a
    close ends with Closed."""
    def script(conn, read):
        op, data = read()                                       # the client's text
        assert op == OP_TEXT and data == b'hello'
        conn.sendall(frame(OP_PING, b'beat', mask=False))
        op, data = read()                                       # its pong
        assert op == OP_PONG and data == b'beat'
        conn.sendall(frame(OP_TEXT, b'{"part":', mask=False, fin=False)
                     + frame(OP_CONT, b'1}', mask=False))         # fragmented
        whole = frame(OP_TEXT, b'{"split":true}', mask=False)
        conn.sendall(whole[:5])                                 # half a frame …
        time.sleep(0.6)
        conn.sendall(whole[5:])                                 # … then the rest
        time.sleep(0.2)
        conn.sendall(frame(OP_CLOSE, struct.pack('!H', 1000), mask=False))
        time.sleep(0.3)
    url, seen = _server(script)
    ws = WebSocket.connect(url, timeout=5)
    ws.send_text('hello')
    assert ws.recv_text(timeout=5) == '{"part":1}'              # the ping answered on the way
    assert ws.recv_text(timeout=0.3) is None                    # the timeout falls mid-frame
    assert ws.recv_text(timeout=5) == '{"split":true}'          # read whole, nothing lost
    try:
        ws.recv_text(timeout=5)
        raise AssertionError('no close')
    except Closed:
        pass
    assert all(masked for op, masked, _ in seen)                # every client frame masked
    assert (OP_PONG, True, b'beat') in seen                     # the ping's pong, masked, its payload back
    url2, _ = _server(lambda conn, read: time.sleep(0.2), prove=False)
    try:
        WebSocket.connect(url2, timeout=5)
        raise AssertionError('a forged proof was accepted')
    except WebSocketError as e:
        assert 'did not prove the key' in str(e)
    assert accept_key('dGhlIHNhbXBsZSBub25jZQ==') == 's3pPLMBiTxaQ9kYGzzhZRbK+xOo='   # RFC 6455's own example
