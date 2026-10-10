# The event vocabulary. Order mechanics are logged, not shipped, unless asked.
ORDER_KINDS = ('placed', 'cancel', 'amend', 'skip')
LOG_ONLY_KINDS = ('net',)    # network weather: the terminal's business, never the phone's
# D60: what reaches the phone. These kinds always do — a stand-down, the
# venue refusing for margin, growth halted, the fleet's own lines. Any other
# event does only when its call site marks it urgent (needs the owner now,
# or can cost money), while the fleet is starting, or when a warning keeps
# repeating. Everything still prints: the log is the whole record.
PHONE_KINDS = ('kill', 'margin', 'backoff', 'fleet')
PERSIST_COUNT = 5            # the same bot's same warning this many times...
PERSIST_WINDOW = 900.0       # ...inside this many seconds is persisting
PERSIST_REPEAT = 3600.0      # and is said again at most this often
REFUSAL_REPEAT = 3600.0      # D82: a margin refusal or backoff that recurs:
                             # said first, then hourly with its count (the
                             # owner, 2026-10-11: a tier cap paged ~6/hour)
URGENT_REPEAT = 900.0        # an urgent line that recurs: said first, then
                             # at most this often (the SUI refusal, every
                             # cycle for 286 cycles, 2026-10-05)


def stamped_print(line):
    """R23: the fleet's own log line, with its UTC time at the END — every
    reader keys on the line's start ('[ship] kill …'), so the start stays
    as it was. The fleet's log carried no clock until 2026-10-11, and a lag
    it said could not be measured."""
    from .fmt import utc_stamp
    print(f'{line} @{utc_stamp()}', flush=True)


class Notifier:
    def __init__(self, ship_orders=False, sink=None):
        self.ship_orders = ship_orders
        self.sink = sink or (lambda line: print(line, flush=True))

    def event(self, kind, botid, text, icon='', urgent=False):
        # the terminal stays clean ASCII — it is the audit trail tools grep;
        # the icon is the PHONE's affordance only (TelegramNotifier)
        route = 'log' if ((kind in ORDER_KINDS and not self.ship_orders)
                          or kind in LOG_ONLY_KINDS) else 'ship'
        label = kind if botid == kind else f'{kind} {botid}'   # no "fleet fleet"
        self.sink(f'[{route}] {label}: {text}')


class TelegramNotifier(Notifier):
    """Shipped events go to Telegram, coalesced, never faster than
    MIN_INTERVAL; order mechanics stay in the log. Everything still prints —
    the terminal is the audit trail, the phone is the alert channel."""

    MIN_INTERVAL = 3.0
    HARD_LIMIT = 3900        # Telegram rejects > 4096; keep headroom

    def __init__(self, token, chat_id, ship_orders=False, transport=None,
                 clock=None, sink=None):
        super().__init__(ship_orders=ship_orders, sink=sink)
        self.token = token
        self.chat_id = chat_id
        self._transport = transport or self._http
        self._clock = clock or __import__('time').time
        self._buffer = []
        self._last_send = 0.0
        self.startup = True          # D60: the fleet's start reaches the phone
        self._seen = {}              # D60: (botid, shape) -> [times]
        self._said = {}              # D60: (botid, shape) -> last escalation
        self._urgent = {}            # D60: (botid, shape) -> [last said, held]

    def _http(self, text):
        import json
        import urllib.request
        from .tg import payload                       # F20: labels in bold
        from .tg import redact                        # P3: never the token
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{self.token}/sendMessage',
            data=json.dumps(payload(self.chat_id, text, every_line=True)).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except OSError as e:
            raise OSError(redact(f'telegram: {e} {getattr(e, "url", "") or ""}',
                                 self.token)) from None

    def event(self, kind, botid, text, icon='', urgent=False):
        super().event(kind, botid, text)
        if (kind in ORDER_KINDS and not self.ship_orders) \
                or kind in LOG_ONLY_KINDS:
            return
        if not (kind in PHONE_KINDS or urgent or self.startup):
            if kind != 'warn':
                return                       # D60: the log's, not the phone's
            text = self._persisting(botid, text)
            if text is None:
                return
        elif urgent and not self.startup and kind not in PHONE_KINDS:
            text = self._recurring(botid, text)
            if text is None:
                return
        elif kind in ('margin', 'backoff') and not self.startup:      # D82
            text = self._recurring(botid, f'{kind}: {text}', REFUSAL_REPEAT)
            if text is None:
                return
            text = text.replace(f'{kind}: ', '', 1)
        prefix = f'{icon} ' if icon else ''
        label = kind if botid == kind else f'{kind} {botid}'   # phone too:
        self._buffer.append(f'{prefix}{label}: {text}')        # no "fleet fleet"
        # a kill page must not sit in the buffer until some later event
        # arrives (the audit's M6) — it flushes NOW, rate limit or not
        self._maybe_flush(force=(kind == 'kill'))

    def _recurring(self, botid, text, every=URGENT_REPEAT):
        """D60: an urgent line is said the first time; the same bot's same
        line (its numbers aside) is then held and said again at most every
        `every` (URGENT_REPEAT; REFUSAL_REPEAT for margin and backoff, D82),
        with how often it came meanwhile."""
        import re
        now = self._clock()
        key = (botid, re.sub(r'[0-9.]+', '#', text))
        last = self._urgent.get(key)
        if last is None or now - last[0] >= every:
            held = 0 if last is None else last[1]
            self._urgent[key] = [now, 0]
            if len(self._urgent) > 500:
                self._urgent = {k: v for k, v in self._urgent.items()
                                if now - v[0] < REFUSAL_REPEAT}
            if held:
                return (f'still ({held + 1}x in {(now - last[0]) / 60:.0f} '
                        f'min): {text}')
            return text
        last[1] += 1
        return None

    def _persisting(self, botid, text):
        """D60: a warning the call site did not mark urgent reaches the
        phone only when it keeps coming — the same bot, the same message
        shape (its numbers aside), PERSIST_COUNT times in PERSIST_WINDOW;
        then at most once per PERSIST_REPEAT while it lasts. Returns the
        line to send, or None."""
        import re
        now = self._clock()
        key = (botid, re.sub(r'[0-9.]+', '#', text))
        times = [t for t in self._seen.get(key, ()) if now - t <= PERSIST_WINDOW]
        times.append(now)
        self._seen[key] = times
        if len(self._seen) > 500:            # bounded: forget the quiet ones
            self._seen = {k: v for k, v in self._seen.items()
                          if now - v[-1] <= PERSIST_WINDOW}
        if len(times) < PERSIST_COUNT:
            return None
        if now - self._said.get(key, -PERSIST_REPEAT) < PERSIST_REPEAT:
            return None
        self._said[key] = now
        return (f'persisting ({len(times)}x in {(now - times[0]) / 60:.0f} '
                f'min): {text}')

    def _maybe_flush(self, force=False):
        if not self._buffer:
            return
        now = self._clock()
        if not force and now - self._last_send < self.MIN_INTERVAL:
            return
        payload = '\n'.join(self._buffer)
        if len(payload) > self.HARD_LIMIT:
            # the venue rejects oversize payloads outright — an unbounded
            # buffer would then fail forever, silently losing every later
            # page including kills. Send the NEWEST, say what was dropped.
            keep, size = [], 0
            for line in reversed(self._buffer):
                if size + len(line) + 1 > self.HARD_LIMIT - 80:
                    break
                keep.append(line)
                size += len(line) + 1
            dropped = len(self._buffer) - len(keep)
            payload = ('\n'.join(reversed(keep))
                       + f'\n[{dropped} earlier line(s) dropped — see the log]')
        try:
            self._transport(payload)
            self._buffer = []
            self._last_send = now
        except OSError:
            if len(payload) >= self.HARD_LIMIT - 200 or len(self._buffer) > 200:
                # never wedge the channel on one bad payload — but a kill
                # page is the one line this channel exists for: it survives
                # the drop and rides the next flush (audit 2026-08-07 H4)
                self._buffer = [ln for ln in self._buffer
                                if 'kill' in ln][-10:]
            self._last_send = now   # and respect the interval before retrying

    def close(self):
        self._maybe_flush(force=True)


class VenueNotifier:
    """The seam that colours a bot's phone events at a glance (owner ask,
    2026-08-05) — wraps once at construction, zero call-site changes. Takes
    the ICON, not the venue name: this module stays venue-blind (A6)."""

    def __init__(self, inner, icon):
        self._inner = inner
        self._icon = icon

    def event(self, kind, botid, text, urgent=False):
        self._inner.event(kind, botid, text, icon=self._icon, urgent=urgent)
