"""The agent's one door onto the box (SPEC J1, D80): a forced command behind
a restricted ssh key. The key runs this and nothing else; the fleet file is
named by the owner in the key's own line, never by the agent. Two verbs:

  read             the agent's limits, its open trades, its intents left
                   this hour and today's loss, as JSON
  intent <json>    one trade request, checked against every limit (J3);
                   paper — logged only; live — queued as a trade (D81)

Anything else is refused by name. No shell, no file, no config, no unit, no
key: the model holds none of them.

  authorized_keys, on the box (the owner's install, ops/README):
  command="cd <repo> && python3 -m gridgremlin.agent_door configs/fleet.agent.json",
  no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA… agent
"""
import json
import os
import sys
import time

VERBS = ('read', 'intent')


def handle(fleet_path, command, now_s=None, fetch=None):
    """The door, pure but for the fleet's files: returns (exit code, text)."""
    from .agent import read_state, submit
    from .config import ConfigError, validate_fleet
    now_s = now_s or time.time()
    words = (command or '').strip().split(None, 1)
    verb = words[0] if words else ''
    if verb not in VERBS:
        return 2, json.dumps({'refused': f"the door knows {', '.join(VERBS)} — not {verb or 'nothing'!r}"})
    try:
        fleet = validate_fleet(json.loads(open(fleet_path).read()))
    except (ConfigError, OSError, ValueError) as e:
        return 1, json.dumps({'refused': f'the fleet cannot be read: {e}'})
    if not fleet.get('agent'):
        return 1, json.dumps({'refused': 'this fleet has no agent block — the owner has not opened it'})
    if verb == 'read':
        lim = fleet['agent']
        st = read_state(fleet_path, now_s, lim['paper'], fetch)
        out = {'limits': lim, 'open': st['open'],
               'intents_left_this_hour': max(0, lim['max_intents_hour'] - st['intents_last_hour']),
               'day_loss': st['day_loss'], 'paper': lim['paper'],
               'utc': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now_s))}
        if lim['paper']:
            day = int(now_s) - int(now_s) % 86_400
            out['closed_today'] = [{'id': p['id'], 'market': p['market'], 'side': p['side'],
                                    'entry': p['entry'], **p['closed']}
                                   for p in st['book'] if p['closed'] and p['closed']['t'] >= day * 1000]
        return 0, json.dumps(out, sort_keys=True)
    try:
        intent = json.loads(words[1]) if len(words) > 1 else None
    except ValueError as e:
        return 1, json.dumps({'refused': f'the intent is not JSON: {e}'})
    verdict, text = submit(fleet_path, intent, now_s, fetch)
    return ((0 if verdict in ('queued', 'paper', 'closed', 'close_requested') else 1),
            json.dumps({'verdict': verdict, 'text': text}))


def main(argv):
    if len(argv) != 1:
        print(json.dumps({'refused': 'the door is started with one fleet file, by the owner'}))
        return 2
    code, text = handle(argv[0], os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    print(text)
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
