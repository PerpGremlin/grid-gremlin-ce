# D143: a portfolio row's leverage from the panel — the spot's and the
# perps' — reviewed, typed for, written; the engine applies it live (F12).

import json

PFO = {'strategy': 'portfolio', 'name': 'carry', 'capital': 1000,
       'assets': [{'coin': 'BTC', 'weight': 0.4}, {'coin': 'ETH', 'weight': 0.3},
                  {'coin': 'SOL', 'weight': 0.3}],
       'hedge': {'product': 'inverse', 'ratio': 1.0}}


def spec_U99_the_new_row_keeps_shares_and_signs_and_validates():
    """The owner (2026-10-18): "a way to adjust the leverage of the
    derivativers positions and the spot positions for the carry accounts"."""
    from gridgremlin.config import validate_config
    from panel.lever import lever_row, said
    new = lever_row(PFO, 10, 5)
    assert [a['weight'] for a in new['assets']] == [4.0, 3.0, 3.0], new['assets']
    assert new['margin'] == {'borrow_apr_max': 0.08, 'spot_leverage': 10} and new['spot_borrow'] is True
    assert new['risk']['max_weight'] == 5.0 and new['perp_leverage'] == 5      # the cap follows the weights
    cfg = validate_config(json.loads(json.dumps(new)))
    assert cfg['margin']['spot_leverage'] == 10.0 and cfg['perp_leverage'] == 5.0
    assert PFO['assets'][0]['weight'] == 0.4 and 'margin' not in PFO           # the old row untouched
    back = lever_row(new, 1, None)
    assert [a['weight'] for a in back['assets']] == [0.4, 0.3, 0.3]
    assert back['margin']['spot_leverage'] == 1 and back['perp_leverage'] == 5   # the loan's block stays; blank keeps
    validate_config(json.loads(json.dumps(back)))
    odd = lever_row(dict(PFO, assets=[{'coin': 'BTC', 'weight': 1 / 3}, {'coin': 'ETH', 'weight': 1 / 3},
                                      {'coin': 'SOL', 'weight': 1 / 3}]), 7, None)
    validate_config(json.loads(json.dumps(odd)))                                # rounded, still sums exactly
    short = lever_row(dict(PFO, assets=[{'coin': 'BTC', 'weight': 0.5}, {'coin': 'ETH', 'weight': -0.5}]), 2, None)
    assert [a['weight'] for a in short['assets']] == [1.0, -1.0]
    for bad in ((0.5, None), (11, None), (2, 0.5), (2, 126)):
        try:
            lever_row(PFO, *bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad} passed')
    words = ' '.join(said(PFO, new))
    assert 'from 1× to 10×' in words and 'has not borrowed before' in words
    assert "from what the exchange holds to 5×" in words and 'not when the account is liquidated' in words


def spec_U99_the_panel_reviews_asks_for_the_name_and_writes_onto_what_it_read():
    from spec_setup import _call, _served_fleet
    base, d, close = _served_fleet()
    try:
        f = d / 'f.json'
        fleet = json.loads(f.read_text())
        fleet['bots'].append(PFO)
        f.write_text(json.dumps(fleet))
        door = _call(base, '/edit?fleet=0&bot=pfocarry')
        assert 'action="/lever"' in door and 'name="spot"' in door and 'value="1"' in door
        form = {'fleet': '0', 'orig': 'pfocarry', 'spot': '3', 'perp': '4'}
        review = _call(base, '/lever', form)
        assert 'from 1× to 3×' in review and 'name="confirm"' in review
        assert json.loads(f.read_text()) == fleet                      # a review writes nothing
        seen = review.split('name="seen" value="')[1].split('"')[0].replace('&quot;', '"')
        wrong = _call(base, '/lever', dict(form, seen=seen, confirm='pfoother'))
        assert 'not applied' in wrong and json.loads(f.read_text()) == fleet
        ok = _call(base, '/lever', dict(form, seen=seen, confirm='PFOcarry'))
        assert 'pfocarry: written' in ok
        row = json.loads(f.read_text())['bots'][1]
        assert row['margin']['spot_leverage'] == 3 and row['perp_leverage'] == 4
        assert sum(a['weight'] for a in row['assets']) == 3
        again = _call(base, '/lever', dict(form, seen=seen, confirm='pfocarry'))   # the file moved since
        assert 'the file changed since you reviewed it' in again
        assert 'type the leverage as a number' in _call(base, '/lever', dict(form, spot='lots'))
        assert 'from 1 to 10' in _call(base, '/lever', dict(form, spot='12'))
        assert 'no portfolio row' in _call(base, '/lever', dict(form, orig=fleet['bots'][0].get('symbol', 'x')))
        f.write_text(json.dumps(dict(json.loads(f.read_text()), allow_mainnet=True)))
        assert 'by hand (D64)' in _call(base, '/lever', form)
    finally:
        close()
