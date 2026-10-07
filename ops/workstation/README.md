# The workstation's part

Two things run here, not on the box: the **nightly pull backup** (F27) and,
by hand, the **rebuild**. Both use the ssh alias you already have; the box
needs nothing new.

## The backup

```
mkdir -p ~/.config ~/.local/bin
printf 'REMOTE=gg:/path/to/the/checkout\nDEST=%s/dev/backups/gg\nKEEP=30\n' "$HOME" > ~/.config/gg-backup.env
chmod 600 ~/.config/gg-backup.env
ln -sf "$PWD/ops/workstation/backup.sh" ~/.local/bin/gg-backup
cp ops/workstation/gg-backup.service ops/workstation/gg-backup.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now gg-backup.timer
gg-backup                    # the first copy, by hand, while you watch
```

Each run writes `DEST/<UTC date>/` with `logs/`, `configs/` and `.env`
(mode kept), hard-linked against `DEST/latest` so unchanged files cost no
space; `latest` then points at it; the newest `KEEP` days stay. `systemctl
--user list-timers` shows the next run; `journalctl --user -u gg-backup`
the last. The copy is only as safe as this machine: keep the disk
encrypted and the directory mode 700 (the script sets it).

## Rebuilding a box from nothing

Untimed as of 2026-10-08; the steps, in order — `ops/README.md` has each:

1. A fresh Ubuntu box: the user, ssh key, `ufw` (22 only), `fail2ban`,
   `KillUserProcesses=yes`, `loginctl enable-linger`.
2. The repo's deploy key on the box; `git clone` over the alias.
3. `.env` from the newest backup (`DEST/latest/.env`), mode 600 — or new
   keys if the old box is suspect; the IP-bound keys need the new address
   bound on the exchange.
4. `configs/` from the backup (the fleet files are also in the repo; the
   state files — tombstones, slide windows — only in the backup).
5. The units from the templates, timers on, `DEADMAN_URL` in `.env`.
6. `logs/` from the backup if the kept history matters (it does).
7. Start one fleet, watch one cycle on the panel, then the rest.
