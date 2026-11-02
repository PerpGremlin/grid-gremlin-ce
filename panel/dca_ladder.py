"""D168: the DCA creators do the ladder's arithmetic. The person states the
investment, the leverage, how many add-ons and a shape; the first order and
the add-ons come out of those, in the row's own keys, so the engine and the
file never know a shape existed. Pure: no venue, no page."""

# name -> (each add-on is this many times the last, each gap this many times
# the last). The engine's own keys, order_size_multiplier and
# deviation_step_multiplier; nothing else differs between them.
SHAPES = {'even': (1.0, 1.0), 'gentle': (1.25, 1.2), 'steep': (1.5, 1.4)}
OWN = 'own'
TYPED_KEYS = ('base_order_size', 'safety_order_size', 'order_size_multiplier',
              'deviation_step_multiplier')
DEFAULT_SHAPE = 'gentle'
SHAPE_WORDS = {'even': 'Even: same size, same gaps',     # short: a select is narrow
               'gentle': 'Gentle: a little bigger, a little wider',
               'steep': 'Steep: much bigger, much wider',
               OWN: 'My own orders'}
# What the ladder may use of investment x leverage; the rest pays the orders'
# own fees. The quick setup's figure since it was written (M2): spent to the
# cent, the last order is refused by the fees of the ones before it.
LADDER_SHARE = 0.98
FIT_SLACK = 0.97                  # under this share the ladder leaves money idle


def order_unit(money, leverage, n, k):
    """The first order and the first add-on, one size: base + every add-on
    fits inside money x leverage (M2)."""
    room = money * leverage * LADDER_SHARE
    return float(f'{room / (1.0 + sum(k ** i for i in range(n))):.4g}')


def _read(text):
    return float(str(text).replace(',', '').strip())


def shape_asked(form):
    """The shape this form asks to have worked out, or None: its orders are
    then its own. Sizes in coins have no price to divide by here (D89)."""
    shape = form.get('ladder_shape')
    if shape not in SHAPES or form.get('strategy') != 'martingale':
        return None
    return None if form.get('size_in') == 'coin' else shape


def _form_leverage(form):
    if form.get('market_type') == 'spot':            # D59: one key per market
        raw = form.get('spot_leverage') if form.get('spot_borrow') == '1' else None
    else:
        raw = form.get('leverage')
    return _read(raw) if str(raw or '').strip() else 1.0


def resolve_ladder(form):
    """The form with its orders worked out, when it asks for a shape: what
    was in those boxes gives way. The growth is set at once; the sizes when
    the investment and the add-ons can be read, or left blank for the same
    refusal a blank has always had. A new form; never the typed one."""
    shape = shape_asked(form)
    if shape is None:
        return form
    k, step = SHAPES[shape]
    out = dict(form, order_size_multiplier=f'{k:g}',
               deviation_step_multiplier=f'{step:g}',
               base_order_size='', safety_order_size='')
    try:
        money, n = _read(form.get('capital')), int(_read(form.get('max_averaging_orders')))
        lev = _form_leverage(form)
    except (TypeError, ValueError):
        return out
    if money > 0 and n >= 1 and lev > 0:
        out['base_order_size'] = out['safety_order_size'] = f'{order_unit(money, lev, n, k):.10g}'
    return out


def _row_leverage(row):
    if row.get('market_type') == 'spot':
        return float((row.get('spot_leverage') if row.get('spot_borrow') else None) or 1.0)
    return float(row.get('leverage') or 1.0)


def inferred_shape(row):
    """The shape a row's orders are exactly, or None. The file holds no shape,
    so a form reopened from a row, and the review, read it back from here."""
    if row.get('size_in') == 'coin':
        return None
    try:
        k = float(row.get('order_size_multiplier') or 1.0)
        step = float(row.get('deviation_step_multiplier') or 1.0)
        n = int(float(row['max_averaging_orders']))
        base, safety = float(row['base_order_size']), float(row['safety_order_size'])
        unit = order_unit(float(row['capital']), _row_leverage(row), n, k)
    except (KeyError, TypeError, ValueError):
        return None
    if base != safety or abs(base - unit) > 1e-9 * max(unit, 1.0):
        return None
    return next((s for s, grow in SHAPES.items() if grow == (k, step)), None)


def shape_of(values, edit=False):
    """What the form's shape choice shows. Asked for, it stays. A blank new
    form starts on the default; a form holding orders keeps them unless they
    are exactly a shape. An edit stays with its orders: a running bot's sizes
    change only when the person chooses a shape on the page."""
    asked = values.get('ladder_shape')
    if asked in SHAPES or asked == OWN:
        return asked
    if edit:
        return OWN
    if not str(values.get('base_order_size') or values.get('safety_order_size') or '').strip():
        return DEFAULT_SHAPE
    row = {k: v for k, v in values.items() if str(v or '').strip()}
    row['spot_borrow'] = values.get('spot_borrow') == '1'
    return inferred_shape(row) or OWN


def ladder_total(row):
    """Base + every add-on, in money; the row's own series (M2)."""
    k = float(row.get('order_size_multiplier') or 1.0)
    return float(row['base_order_size']) + sum(
        float(row['safety_order_size']) * k ** i for i in range(int(row['max_averaging_orders'])))


def fit_words(row):
    """The ladder against the money, in words: worked out, too much for it,
    or leaving much of it idle. None when typed orders use about all of it, or
    when it cannot be said (coin sizes have no price here, D89)."""
    if row.get('size_in') == 'coin':
        return None
    try:
        total = ladder_total(row)
        room = float(row['capital']) * _row_leverage(row)
    except (KeyError, TypeError, ValueError):
        return None
    shape = inferred_shape(row)
    if shape:
        return (f'Worked out for you ({shape}). The orders use {total:,.6g} of the '
                f'{room:,.6g} your investment and leverage allow; the rest pays their fees.')
    if total > room * (1.0 + 1e-9):
        return (f'These orders add up to {total:,.6g}, but your investment and leverage allow '
                f'{room:,.6g}: {total - room:,.6g} too much. Lower them, raise the investment, '
                'or pick a ladder shape to have them worked out.')
    if total < room * FIT_SLACK:
        return (f'These orders add up to {total:,.6g} of the {room:,.6g} your investment and '
                f'leverage allow: {room - total:,.6g} would sit unused. Fine if you meant it; '
                'a ladder shape spends it all.')
    return None
