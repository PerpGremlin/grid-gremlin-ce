# One kept HTTPS connection per host for the venue READS (SPEC E10).
# Measured on the box 2026-10-06: a Bybit truth read is five requests and
# 71 ms of CPU, 84% of it opening connections (TLS handshake, DNS, connect);
# a request on a kept connection costs about 1 ms. Writes keep urlopen: a
# write is never re-sent on a fresh connection.
import http.client
import io
import ssl
import urllib.error
import urllib.parse

# the server closed an idle kept connection: the request never reached it
STALE = (http.client.RemoteDisconnected, ConnectionResetError,
         BrokenPipeError, ConnectionAbortedError)


class KeepAlive:
    def __init__(self, timeout=15, connect=None):
        self.timeout = timeout
        self._ctx = None
        self._connect = connect or self._https
        self._conns = {}

    def _https(self, host):
        if self._ctx is None:                 # one context, built once
            self._ctx = ssl.create_default_context()
        return http.client.HTTPSConnection(host, timeout=self.timeout,
                                           context=self._ctx)

    def _drop(self, host):
        conn = self._conns.pop(host, None)
        if conn is not None:
            conn.close()

    def request(self, method, url, headers, body=None):
        """-> (headers, raw bytes). A 4xx/5xx raises urllib's HTTPError, as
        urlopen did. Only a STALE failure on a REUSED connection is sent
        again, once, fresh — every caller here is a read; a timeout or a
        fresh connection's failure raises as before."""
        parts = urllib.parse.urlsplit(url)
        path = parts.path + ('?' + parts.query if parts.query else '')
        for attempt in (1, 2):
            conn = self._conns.get(parts.netloc)
            reused = conn is not None
            if not reused:
                conn = self._conns[parts.netloc] = self._connect(parts.netloc)
            try:
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
            except STALE:
                self._drop(parts.netloc)
                if reused and attempt == 1:
                    continue
                raise
            except BaseException:
                self._drop(parts.netloc)
                raise
            if resp.will_close:
                self._drop(parts.netloc)
            if resp.status >= 400:
                raise urllib.error.HTTPError(url, resp.status, resp.reason,
                                             resp.headers, io.BytesIO(raw))
            return resp.headers, raw
