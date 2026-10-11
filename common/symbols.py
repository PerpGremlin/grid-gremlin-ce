"""The coin a market trades, from the venue's own symbol (D91: one of each)."""
import re

QUOTES = ('USDT', 'USDC', 'PERP', 'USD')
_DATED = re.compile(r'^([A-Z0-9]+?)(USDT|USDC|USD)[A-Z]\d{2}$')   # a dated future: ETHUSDH26


def coin_of(symbol):
    """BTCUSDT, BTCUSDC, BTCPERP, BTCUSD -> BTC; a dated future ETHUSDH26 ->
    ETH; Hyperliquid's bare BTC -> BTC; USDCUSDT -> USDC (the quote at the
    end, not the first one found). '' for nothing."""
    s = str(symbol or '')
    for q in QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return s[:-len(q)]
    m = _DATED.match(s)
    return m.group(1) if m else s
