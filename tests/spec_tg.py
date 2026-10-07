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
