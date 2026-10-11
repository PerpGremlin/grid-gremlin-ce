"""The one GET-JSON helper for public endpoints (D91: one of each). Keyed and
signed requests stay with the engine's venue clients."""
import json
import urllib.request

USER_AGENT = 'grid-gremlin'


def get_json(url, timeout=15):
    """A URL (or a prepared Request) fetched and parsed as JSON."""
    req = (url if isinstance(url, urllib.request.Request)
           else urllib.request.Request(url, headers={'User-Agent': USER_AGENT}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())
