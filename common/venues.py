"""How a venue is named on a page and on the phone (D91: one of each)."""

VENUE_WORD = {'bybit': 'Bybit', 'binance': 'Binance', 'okx': 'OKX', 'hyperliquid': 'Hyperliquid',
              'coinbase': 'Coinbase', 'kraken': 'Kraken'}
VENUE_SHORT = dict(VENUE_WORD, hyperliquid='HL')          # where a line is tight: the phone's report


def venue_word(venue, short=False):
    """The venue's name, or the key itself when it is not one we name."""
    return (VENUE_SHORT if short else VENUE_WORD).get(venue, venue)
