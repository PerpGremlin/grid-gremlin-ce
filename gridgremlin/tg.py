"""F20: a Telegram message carries its heading in bold.

Telegram renders bold only under a parse mode; HTML is the one whose
escaping is plain (&, <, >). Every sender builds its request here, so the
rule is one: a line's label — up to its first ': ', or the whole line when
it has none — is bold; everything else is escaped verbatim. The first line
of a page, a digest or a reply; every line of the engine's coalesced events.
"""
import html
import re

LABEL = re.compile(r'^(.{1,70}?): ')


def bold_headings(text, every_line=False):
    out = []
    for i, line in enumerate(str(text).split('\n')):
        if (i == 0 or every_line) and line.strip():
            m = LABEL.match(line)
            if m:
                line = f'<b>{html.escape(m.group(1))}</b>: {html.escape(line[m.end():])}'
            else:
                line = f'<b>{html.escape(line)}</b>'
        else:
            line = html.escape(line)
        out.append(line)
    return '\n'.join(out)


def redact(text, token):
    """P3: a Telegram bot token travels in the request URL; an error that
    quotes the URL would carry it into a log. Every sender passes what it
    raises through here."""
    text = str(text)
    return text.replace(token, '<token>') if token else text


def payload(chat_id, text, every_line=False):
    """The sendMessage body every sender uses."""
    return {'chat_id': chat_id, 'text': bold_headings(text, every_line),
            'parse_mode': 'HTML'}
