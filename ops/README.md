# ops — the deploy layer, reproducible from the repo

Templates for the systemd `--user` units that run a fleet unattended. The live
box holds the filled-in copies; this directory holds the shape, so the setup
survives the box. Placeholder paths only — the hygiene rule (written as if public) bars
real ones.

The one-page **runbook** — pages → what to do, how to stop everything,
where everything is — is `docs/RUNBOOK.md`.

## The layers

What runs, from the inside out:

1. `Restart=always` — crashes recover themselves.
2. `OnFailure` → a rate-limited Telegram alert, one page per 30 minutes at
   most (the stamp-file comment in the template says why: the naive version
   paged once per retry through a venue outage). The watchdog has the same
   alarm for itself (`watchdog-failed`).
3. **The watchdog** on a timer — liveness by *output*: snapshot staleness,
   margin ratio, the equity floor and drawdown, and per-bot bounds where a row
   opts in (D32). It pages and never acts (D39). Exit 1 = breached and paged =
   unit success (`SuccessExitStatus=1`); only a crash or an undelivered page
   fails the unit. Each fleet's watchdog takes its own minute slot (`*:4/5`,
   `*:1/5`, …) so ticks never queue behind each other on a small box.
4. **Log rotation and retention** (`ops/logrotate.conf`, hourly, F11/F26) —
   fleet logs at 100 MB, five kept, compressed, `copytruncate` because the
   writer is never restarted for it. Snapshot files are not rotated: the
   watchdog and every post-mortem read them as one history; the disk alarm
   watches their growth. The same unit then compresses, in place, any log
   under `logs/archive/` older than a day — kept, never deleted
   (`gridgremlin.retention`).
5. **The kept ledger** (`gridgremlin.kept_fills`, hourly at :27, R18) — every
   fill of each fleet, once, in `logs/fills/<fleet>.json`; the first run
   backfills 90 days (Hyperliquid answers only its newest ~10,000 fills). The
   panel's kept history reads it. Read-only toward the venues; not rotated.
6. **The daily archive** (`gridgremlin.archive`, 23:56 UTC, R17) — each
   fleet's readout and newest snapshot, one file per fleet per day under
   `logs/daily/`, the record the soak's results are cited from.
7. **The daily digest** (`gridgremlin.digest`, 23:58 UTC, F17/D62) — tops up
   the ledger, then sends one message: each exchange's day after fees and
   before funding, open and kept P&L, what the log said, health.
8. **Reading commands** (`gridgremlin.phone`, a long-running service,
   F18/D61) — answers the owner's `/commands` from the snapshot, readout,
   ledger and logs. Owner-only (`TELEGRAM_OWNER_ID`, fail closed), read-only,
   and the channel's one getUpdates consumer.
9. **The panel** (`panel.server`, `gg-panel`; since 2026-10-08 a façade over
   `panel/css.py`, `reference.py`, `render.py`, `forms.py`, `routes.py`) — the fleet on a screen
   (README §11), on a loopback port behind its token.
10. **Market readings** (`gridgremlin.market`, hourly at :33, D67) — what a
    grid or DCA operator wants to know about each market the fleets are on,
    from public endpoints, kept in `logs/market.jsonl` beside the day's
    readout; a report paged at the session opens (00, 08, 16 UTC) by
    `market-report.timer`. Read-only, keyless; nothing acts on it.
11. **The dead-man's switch** (F24/D74) — every completed watchdog run ends
    with one GET to `DEADMAN_URL` (an outside uptime check such as
    healthchecks.io, expecting a ping every 5 minutes with a 10-minute
    grace). The check's own alarm — email, Telegram — is what says the box
    is dead, which nothing on the box can. The watchdog also pages when the
    disk passes 85% (`disk_used_max`, F25).
12. **The pull backup** (F27/D74) — on the workstation, not the box:
    `ops/workstation/` pulls `logs/`, `configs/` and `.env` nightly over the
    ssh alias already in use, dated and hard-linked, thirty days kept. Its
    README has the install, and the rebuild recipe.

13. **One state file per fleet** (`ops/split_local_state.py`, X7b/G22) —
    run once per box, with every fleet stopped, when a box still holds the
    fleet-wide `logs/tombstones.json`, `logs/slide_state.json` or
    `logs/portfolio_state.json`: each fleet
    gets its own rows (a window offset from its latest snapshot when it has
    one), leftovers are named and kept only in the archive copy, the old
    files move to `logs/archive/`. The engine refuses to start beside the
    old files until it has run.

14. **The expiry calendar** (`configs/expiry.json`, F29/D79) — what runs
    out and when: keys, tokens, demo accounts, the box's billing. The demo
    watchdog names it (`expiry`) and pages a week out (`expiry_warn_days`),
    names what has run out, and reminds on its own interval;
    `python3 -m gridgremlin.expiry configs/expiry.json` prints the list.
    Dates are the owner's to fill; unknown is listed, never paged.

15. **The agent's door** (`gridgremlin.agent_door`, J1/J3, D80) — not a
    unit: a forced command behind its own ssh key. On the box, one line in
    the trading user's `~/.ssh/authorized_keys`, the fleet named here and
    nowhere else:

    ```
    command="cd <repo> && python3 -m gridgremlin.agent_door configs/fleet.agent.json",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 <the agent's public key> agent
    ```

    On the workstation, a host alias using that key; the supervised session
    then runs `ssh <alias> read` and `ssh <alias> 'intent {...}'`. The fleet
    file's `agent` block holds the limits (`paper: true` until the owner
    says otherwise); its trades land in the trades file like any other, and
    every intent in `logs/agent-intents-<fleet>.jsonl`.

> **Retired: the box-side Claude** — triage on failure, the Telegram relay
> and the daily range review, kept in the private tree's `ops/retired/`
> (never exported, like `ops/research/`; its README says why).
> Retired by the owner 2026-09-28, switched off for good 2026-10-06: the
> audit of 2026-10-05 found their settings cage is not read-only, and triage
> was still running on fleet failures while a token sat in `.env`. Each
> entry point now refuses to run, no template in `ops/systemd/` may call
> them (a spec holds it), and a box keeps no Claude token. The agentic phase
> rebuilds it in an OS-level sandbox.

## Install

Fill the `{{PLACEHOLDERS}}` in each template you use and save it without the
`.template` suffix under the names below. A fleet on a second account (H5:
`"account": "<name>"` in its fleet file, `BYBIT_<NAME>_*` in `.env`) is a
fleet like any other here — its own units, its own watchdog slot, listed in
the once-per-box units beside the rest; each process selects the fleet's
keys as it reads the file. Per fleet: `fleet.service` →
`grid-gremlin3-<fleet>.service`, `fleet-failed.service` →
`grid-gremlin3-<fleet>-failed.service`, and `watchdog.{service,timer}` /
`watchdog-failed.service` → `grid-gremlin3-<fleet>-watchdog.*` /
`grid-gremlin3-<fleet>-watchdog-failed.service`. Once per box, listing every
fleet file in `{{MORE_FLEET_CONFIGS}}`: `logrotate.*`, `fills.*`, `archive.*`,
`digest.*`, `market.*`, `market-report.*` → `grid-gremlin3-<name>.*`; `phone.service` →
`grid-gremlin3-phone.service`; `panel.service` → `gg-panel.service`. The
panel shows the fleets in the order its unit names them — the owner's: the
Bybit accounts first, Hyperliquid after (U59).

```
cp grid-gremlin3-*.service grid-gremlin3-*.timer gg-panel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now grid-gremlin3-<fleet>.service           # each fleet
systemctl --user enable --now grid-gremlin3-<fleet>-watchdog.timer    # each fleet
systemctl --user enable --now grid-gremlin3-logrotate.timer grid-gremlin3-fills.timer \
  grid-gremlin3-archive.timer grid-gremlin3-digest.timer \
  grid-gremlin3-market.timer grid-gremlin3-market-report.timer
systemctl --user enable --now grid-gremlin3-phone.service gg-panel.service
loginctl enable-linger $USER        # units survive logout
```

**Then make a logout end what the login started** (as root, once per box):

```
mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nKillUserProcesses=yes\n' > /etc/systemd/logind.conf.d/10-kill-user-processes.conf
systemctl restart systemd-logind
busctl get-property org.freedesktop.login1 /org/freedesktop/login1 \
  org.freedesktop.login1.Manager KillUserProcesses          # b true
```

Ubuntu's default keeps every process an ssh session started running after the
session closes, so a box worked over ssh — by hand, or by an agent's watch
loop — collects them (2026-10-06: 41 forgotten loops held one box's core at
90% pressure). With this setting a session's
processes end with it. The fleets, the panel, the phone service and every timer
are untouched: they run under your user's own service manager, which linger
keeps alive without a login. Test it — `ssh box 'nohup sleep 900 >/dev/null 2>&1 &'`,
then `pgrep -x sleep` on a fresh login finds nothing. The one change in habit:
a job meant to outlive your login runs as a unit of its own,
`systemd-run --user --unit=NAME <command>`, and `systemctl --user stop NAME`
ends it. To undo, remove the file and restart `systemd-logind`.

`ops/logrotate.conf.template` takes the same `{{REPO_DIR}}`; save it as
`ops/logrotate.conf` (gitignored, box-local like the rendered units).

**The dead-man's switch** (F24): make a check on an uptime service (period
5 min, grace 10 min, alerting to your email and Telegram), then on the box
append `DEADMAN_URL=<its ping URL>` to `.env`. The next watchdog run pings
it; silence it by removing the line.

**Deploying.** The repo is private. The box carries its own SSH key,
registered on the repo as a **read-only deploy key** (a push from the box is
refused), under an SSH host alias so it is used for this repo alone. A deploy
is then `git pull --ff-only origin main` in the checkout, followed by a
restart of `gg-panel` after **every** deploy, not only a panel change: the
panel holds some engine modules in memory and imports others on demand, so a
half-new import breaks its pages (2026-10-06: the edit page raised an
ImportError after an engine-only deploy and a leverage edit could not be
saved). A fleet picks up engine changes at its next restart, and hot config
terms live (F12). Never edit
files on the box: the panel's own writes are flowed back into the repo as
the row they are (U19).

**The live copy (D65, F19).** Real money never runs from the checkout every
deploy updates. It runs from a second copy beside it — a git worktree of the
same repository, detached at one version, with its own `.env`, `logs/` and
fleet file (never in git: its rows are real sizes, D64). Make it once:

```
git -C <REPO_DIR> worktree add --detach <REPO_DIR>-live HEAD
mkdir <REPO_DIR>-live/logs
```

Render the real-money fleet's units with `{{REPO_DIR}}` set to the live copy;
give the panel its fleet file like any other (D64). Then the copy moves only
by promotion, from the main checkout:

```
python3 ops/promote.py --status          # what live runs, what waits, for how long
python3 ops/promote.py <version>          # merged, and a day on play money
python3 ops/promote.py <version> --hotfix "why it cannot wait"
```

A promotion is refused unless the version is on the merged main and has run
in the play-money checkout for a day (its reflog says when it arrived); a
hotfix skips the day and writes its reason. Every move lands in the live
copy's `logs/promotions.log`. Nothing restarts: the live fleet takes the new
version when its owner restarts it.

| placeholder | meaning |
|---|---|
| `{{FLEET}}` | short fleet tag (`demo`, `hl`, …) — names units, logs, stamps. The live HL fleet is the one exception: unit tag `hl`, log and snapshot tag `hl-testnet` (its rendered unit was set by hand; `watchdog.hl.testnet.json` follows that) |
| `{{LABEL}}` | the page's venue label, e.g. the venue colours from config.py |
| `{{PANEL_PORT}}` / `{{UNITS}}` / `{{MORE_FLEET_CONFIGS}}` | panel only: its loopback port, the units its control page may act on (comma-separated), further fleet files |
| `{{DESC}}` | one-line description shown by systemctl |
| `{{REPO_DIR}}` | absolute path of the deployed checkout |
| `{{FLEET_CONFIG}}` / `{{WATCHDOG_CONFIG}}` | file names under `configs/` |
| `{{START_LIMIT_INTERVAL}}` | `600` normally; `0` for patient-retry fleets (venue outages) |
| `{{RESTART_SEC}}` | `10` normally; longer (`30`) for patient-retry fleets |
| `{{SLOT}}` | the fleet's own watchdog minute slot, e.g. `*:4/5` |

The fleet needs `{{REPO_DIR}}/.env` (chmod 600 — the engine refuses a
group/other-readable one) with the venue keys, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, and `TELEGRAM_OWNER_ID` for the phone service. Every fleet
file names a watchdog config, and the fleet refuses to build without one (F1):
its account guards cover every bot; per-bot bounds are opt-in (D32).
