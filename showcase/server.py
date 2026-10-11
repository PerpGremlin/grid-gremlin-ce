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

    def log_message(self, *a):
        pass

    def _send(self, code, body, kind='text/html; charset=utf-8'):
        data = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        for k, v in HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            return self._send(200, page(read_show(self.show_path), latest(self.market_path)))
        if path == '/show.json':
            return self._send(200, json.dumps(read_show(self.show_path) or {}),
                              'application/json')
        return self._send(404, 'not here')

    do_HEAD = do_GET

    def _refuse(self):
        self._send(405, 'read-only')

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse


def main(argv):
    port = int(argv[argv.index('--port') + 1]) if '--port' in argv else 41950
    bind = argv[argv.index('--bind') + 1] if '--bind' in argv else '127.0.0.1'
    srv = http.server.ThreadingHTTPServer((bind, port), Showcase)
    print(f'showcase: http://{bind}:{port}/ (read-only)', flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
