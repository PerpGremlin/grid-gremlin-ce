# Runbook — one page, for a bad day or a blank one

Read this when a page arrives, when you come back after a break, or when
you cannot remember how it all fits. Everything here is a pointer; the
detail is in `ops/README.md` (what runs), `README.md` (what the engine
does) and `docs/SPEC.md` (why it is pinned that way).

## Where everything is

- **The box**: your ssh alias to it (this page says `ssh box`). The
  checkout is the one working directory there. Never edit files on the
  box: it pulls a merged `main`. After every pull: `systemctl --user
  restart gg-panel`.
- **The panel**: `http://127.0.0.1:41900/` through an ssh tunnel to the
  box; the token is the cookie your browser holds (the panel prints the
  link with it at start). Cards, table, control, set up a bot, key.
- **The phone**: the Telegram group with your bot. Reading commands:
  `/help /status /pnl /positions /orders /grids /rounds /risk /today
  /alerts /market /log`. It never acts.
- **The money**: Bybit Demo Trading and Hyperliquid Testnet, play money,
  keys in the box's `.env` (mode 600). This edition cannot reach real money
  (`ops/promote.py --status` exists for the private edition's pinned copy).
- **The backup**: `DEST/latest/` on your workstation — the README's
  example is `~/dev/backups/gg/latest/` — nightly (`systemctl --user
  list-timers`); the rebuild recipe is in `ops/workstation/README.md`.
- **The record**: `docs/DECISIONS.md` (why), `logs/daily/` on the box
  (each day's results).

## What runs on the box

| unit | what | if it stops |
|---|---|---|
| `grid-gremlin3-demo`, `grid-gremlin3-hl` | the fleets (one per fleet file) | `Restart=always`; an `OnFailure` page after repeated failure |
| `grid-gremlin3-<fleet>-watchdog.timer` | every 5 min: staleness, margin, equity, drawdown, disk; pings the dead-man | its own `-failed` page; the dead-man alarms outside |
| `gg-panel` | the panel | restart it; nothing trades through it |
| `grid-gremlin3-phone` | the Telegram reading commands | restart it; nothing else depends on it |
| `grid-gremlin3-fills.timer` | hourly: the kept ledger | the panel's kept history goes stale |
| `grid-gremlin3-logrotate.timer` | hourly: rotation, then archive compression | the disk alarm catches it |
| `grid-gremlin3-market.timer`, `-market-report.timer` | hourly readings; reports at 00/08/16 UTC | cards lose the market line |
| `grid-gremlin3-archive.timer`, `-digest.timer` | 23:56 the day's results; 23:58 the digest | no digest |

`systemctl --user status <unit>` · `journalctl --user -u <unit> -n 50` ·
the fleet logs: `logs/fleet-<fleet>.log` (grep the botid).

## When a page arrives

| the page says | it means | do |
|---|---|---|
| **kill** / **stood down** / **max_loss** | a bot ended itself by its own rule (stop, loss limit, round limit) | read its card and `/log <bot>`; nothing is on fire. Its position: closed if the rule closes (X1); held if `leave_position` — then **close position** on the card (or `python3 -m gridgremlin.close <fleet.json> <botid>`) when you choose |
| **margin** / `mm_rate … >` / **account cap reached** | the account is near its maintenance margin, or at a cap you set | look at the strip's leverage and the liquidation lines; reduce by closing the biggest loser from its card, or lift the cap; the engine itself never force-closes |
| **snapshot is Ns old** / **no readable snapshot** | the fleet is not writing — hung, crashing, or the venue unreachable | `systemctl --user status grid-gremlin3-<fleet>`; `journalctl` for the traceback; `systemctl --user restart` it; orders rest on the venue meanwhile and are re-adopted by identity |
| **equity … <** / **below the peak** | the account fell through your floor or drawdown | decide, not the engine: it is a page. Pause by stopping the fleet; close by card |
| **disk N% used** | the box is filling | `du -sh logs/*` on the box; the archive compresses itself hourly; delete rotated `.gz` you have in the backup |
| **backoff** / **wallet read failed** / **venue down** | the exchange or the network, not the engine | wait; it retries; a re-page after 15 min means look at the exchange's status page |
| **the dead-man (outside) says "down"** | the box itself, or the watchdog, has stopped | `ssh box`; if it answers, `systemctl --user list-timers`; if it does not, your provider's console; rebuild from the backup if it is gone |
| **OnFailure: … failed** | a unit crashed repeatedly | `journalctl --user -u <unit> -n 100`; the traceback names the line; open an issue with it |

A page that recurs is said the first time and then at most every 15
minutes; silence after a page means it is still true, not that it healed.

## How to stop everything

```
ssh box
systemctl --user stop grid-gremlin3-demo grid-gremlin3-hl     # the fleets
```
Stopping a fleet **leaves its orders and positions on the exchange**; a
restart adopts them by identity (I1). To go flat: **close position** on
each holding card (the panel runs `gridgremlin.close`), then cancel what
still rests on the exchange's own page. The timers, panel and phone can
keep running; `systemctl --user stop '*.timer'` silences the lot.

## How to start again

`systemctl --user start grid-gremlin3-<fleet>`; watch one cycle on the
panel (the strip, then the cards); `/status` on the phone. A fleet that
will not start says why in its first lines (`journalctl -u … -n 50`): a
refused row is set aside by name, the rest run.

## Changing a bot

In the panel: **edit** on the card (a running fleet takes the row's new
terms without a restart, F12) or **set up a bot** (four gates, nothing
written until the last). The file on the box is the truth. Never hand-edit
the file on the box.

## When you are not there

The box needs nothing from your workstation: fleets, watchdogs, pages,
digest and the dead-man run on their own. What stops: the nightly backup
(workstation off). If you run the assistant from a session on the
workstation, `/remote-control` reaches it from the phone; the box never
depends on it.

## If the workstation is lost

The provider's web console opens the box without ssh — keep its login in
a password manager, with 2FA. Keep a spare ssh key in one other place,
already in the box's `authorized_keys`. Play-money keys are the only keys
that ever live on the box; this edition cannot hold others.
