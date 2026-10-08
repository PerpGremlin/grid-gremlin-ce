"""F20: a Telegram message carries its heading in bold."""
import inspect
from pathlib import Path

from gridgremlin.tg import bold_headings, payload


def spec_F20_the_label_is_bold_and_the_rest_is_escaped_verbatim():
    assert bold_headings('[hl] stale: snapshot is 1240s old') == '<b>[hl] stale</b>: snapshot is 1240s old'
    assert bold_headings('🧌 daily digest · day\nsecond: line') == '<b>🧌 daily digest · day</b>\nsecond: line'
    assert bold_headings('/log <bot> [n] — a & b') == '<b>/log &lt;bot&gt; [n] — a &amp; b</b>'
    two = bold_headings('🟢 HL kill linA: x -> 0\n🟢 HL warn linB: y < z', every_line=True)
    assert two == '<b>🟢 HL kill linA</b>: x -&gt; 0\n<b>🟢 HL warn linB</b>: y &lt; z'
    assert bold_headings('') == '' and bold_headings('\nx') == '\nx'
    assert bold_headings('h\na < b & c') == '<b>h</b>\na &lt; b &amp; c'   # the body too
    long = 'a' * 80 + ': tail'                      # a label past 70 chars is not one
    assert bold_headings(long) == f'<b>{html_escape(long)}</b>'
    p = payload(5, 'h: t')
    assert p == {'chat_id': 5, 'text': '<b>h</b>: t', 'parse_mode': 'HTML'}


def html_escape(s):
    import html
    return html.escape(s)


def spec_F20_every_sender_builds_its_request_through_payload():
    from gridgremlin import events, phone, watchdog
    assert 'payload(self.chat_id, text, every_line=True)' in inspect.getsource(events.TelegramNotifier._http)
    assert 'payload(chat, text)' in inspect.getsource(watchdog.send_telegram)
    assert 'payload(chat, text)' in inspect.getsource(phone.Telegram.send)
    ops = Path(__file__).resolve().parents[1] / 'ops' / 'systemd'
    for name in ('fleet-failed.service.template', 'watchdog-failed.service.template'):
        t = (ops / name).read_text()
        assert 'parse_mode=HTML' in t and 'text="<b>{{LABEL}} v3 {{FLEET}}:' in t, name


def spec_P3_a_telegram_token_never_leaves_a_sender_in_an_error():
    """The token travels in the request URL; an error that quotes the URL
    would carry it into a log. Every sender raises a redacted OSError."""
    import urllib.error
    import urllib.request
    import gridgremlin.events as ev
    import gridgremlin.phone as ph
    import gridgremlin.watchdog as wd
    from gridgremlin.tg import redact
    token = 'SECRET-TOKEN-123'
    assert redact(f'https://api.telegram.org/bot{token}/x failed', token) == \
        'https://api.telegram.org/bot<token>/x failed'
    assert redact('plain', '') == 'plain'

    def boom(req, *a, **kw):
        url = req if isinstance(req, str) else req.full_url
        raise urllib.error.HTTPError(url, 401, f'Unauthorized at {url}', {}, None)
    saved = urllib.request.urlopen
    urllib.request.urlopen = boom
    try:
        for name, call in (
            ('events', lambda: ev.TelegramNotifier(token, '1')._http('hi')),
            ('phone', lambda: ph.Telegram(token).send('1', 'hi')),
            ('watchdog', lambda: wd.send_telegram('hi')),
        ):
            import os
            os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID'] = token, '1'
            try:
                call()
            except OSError as e:
                assert token not in str(e) and '<token>' in str(e), (name, str(e))
            else:
                raise AssertionError(f'{name}: no error raised')
    finally:
        urllib.request.urlopen = saved
        os.environ.pop('TELEGRAM_BOT_TOKEN', None)
        os.environ.pop('TELEGRAM_CHAT_ID', None)
