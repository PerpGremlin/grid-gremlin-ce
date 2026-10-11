"""The showcase's server (D86): its own process on its own port, GET only,
two paths — the page and the data behind it — no token, no cookie, no
form, no script, nothing in the desk reachable. It reads two files: what
the private side allowed to be shown (logs/show/show.json) and the newest
market reading (ggdata). It binds 127.0.0.1 unless told otherwise; putting
it in front of the internet is the owner's step (a proxy or tunnel), and
the live panel is never what is exposed.

  python3 -m showcase.server [--port 41950] [--bind 127.0.0.1]
"""
import http.server
import json
import sys
from pathlib import Path

from ggdata.market import latest
from .page import page

ROOT = Path(__file__).resolve().parents[1]
SHOW = ROOT / 'logs' / 'show' / 'show.json'
MARKET = ROOT / 'logs' / 'market.jsonl'
PUBLIC_KEYS = ('generated_ms', 'amounts', 'accounts')
MAX_CONNECTIONS = 64      # beyond this a new connection is closed at once (the review)
HEADERS = {'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; "
                                      "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
           'X-Content-Type-Options': 'nosniff',
           'Referrer-Policy': 'no-referrer',
           'Cache-Control': 'no-store'}


def read_show(path=SHOW):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


class Showcase(http.server.BaseHTTPRequestHandler):
    show_path, market_path = SHOW, MARKET
    server_version = 'showcase'
    sys_version = ''
    timeout = 10              # a half-sent request releases its thread (the review)

    def log_message(self, *a):
        pass

    def _send(self, code, body, kind='text/html; charset=utf-8'):
        data = body.encode()
        try:
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            for k, v in HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass                              # the reader hung up: nothing to say

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            try:
                body = page(read_show(self.show_path), latest(self.market_path))
            except Exception as e:                       # noqa: BLE001
                # a malformed file must not take the page down (the review)
                print(f'showcase: page failed: {type(e).__name__}: {e}', flush=True)
                body = page(None, None)
            return self._send(200, body)
        if path == '/show.json':
            # by allowlist too (the review, 2026-10-11): the file's refused
            # list names accounts the page never shows
            show = read_show(self.show_path) or {}
            return self._send(200, json.dumps({k: show.get(k) for k in PUBLIC_KEYS}),
                              'application/json')
        return self._send(404, 'not here')

    do_HEAD = do_GET

    def _refuse(self):
        self._send(405, 'read-only')

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse


class BoundedServer(http.server.ThreadingHTTPServer):
    """At most MAX_CONNECTIONS handled at once; one more is closed on
    arrival, so a crowd of idle sockets cannot starve the box the fleets
    run on (the review, 2026-10-11)."""
    daemon_threads = True

    def __init__(self, *a, **k):
        import threading
        super().__init__(*a, **k)
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def main(argv):
    port = int(argv[argv.index('--port') + 1]) if '--port' in argv else 41950
    bind = argv[argv.index('--bind') + 1] if '--bind' in argv else '127.0.0.1'
    srv = BoundedServer((bind, port), Showcase)
    print(f'showcase: http://{bind}:{port}/ (read-only)', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
