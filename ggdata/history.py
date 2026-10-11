# Public market history for rehearsals (H7): Bybit's candles and funding
# rates and Hyperliquid's funding, fetched once and cached under
# logs/research/ by coin, interval and day span. No key. The engine's
# rehearsal reads here; the research harnesses in research/ import it
# too — the engine never imports research (the 2026-10-08 audit).
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'logs' / 'research'
BYBIT = 'https://api.bybit.com'
HL_INFO = 'https://api.hyperliquid.xyz/info'
H = 3_600_000


def _dedupe(rows, key='t'):
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x[key]):
        if x[key] not in seen:
            seen.add(x[key])
            out.append(x)
    return out


def _cached(name, make):
    STORE.mkdir(parents=True, exist_ok=True)
    cache = STORE / name
    if cache.exists():
        return json.loads(cache.read_text())
    out = make()
    cache.write_text(json.dumps(out))
    return out


def fetch_klines(symbol, minutes, start_ms, end_ms):
    """Bybit linear candles with volume, oldest first, cached (ggdata, D91)."""
    from ggdata.candles import candles
    return _cached(f'{symbol}-{minutes}m-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json',
                   lambda: candles('bybit', 'linear', symbol, minutes, start_ms, end_ms))


def fetch_funding(category, symbol, start_ms, end_ms):
    """Bybit funding rates [{'t', 'rate'}], oldest first, cached (ggdata, D91)."""
    from ggdata.funding import bybit_funding
    return _cached(f'funding-{symbol}-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json',
                   lambda: bybit_funding(category, symbol, start_ms, end_ms))


def fetch_hl_funding(coin, start_ms, end_ms):
    """Hyperliquid's hourly funding [{'t', 'rate'}], oldest first, cached (ggdata, D91)."""
    from ggdata.funding import hl_funding
    return _cached(f'funding-HL-{coin}-{start_ms // 86_400_000}-{end_ms // 86_400_000}.json',
                   lambda: hl_funding(coin, start_ms, end_ms, network='mainnet'))


def hl_8h(rows):
    """Hyperliquid pays hourly; a rehearsal's clock is 8h — sum each bucket."""
    out = {}
    for x in rows:
        b = x['t'] // (8 * H)
        out[b] = out.get(b, 0.0) + x['rate']
    return [{'t': b * 8 * H, 'rate': r} for b, r in sorted(out.items())]
