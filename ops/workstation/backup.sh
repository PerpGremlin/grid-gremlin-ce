#!/bin/sh
# F27: the nightly pull backup — the box's logs, configs and keys file,
# copied TO the workstation over the ssh alias you already use (the box
# needs nothing new: no key, no software, no inbound rule). Dated copies,
# hard-linked against the previous one so an unchanged file costs nothing,
# the newest KEEP days kept. Settings come from one file, never from here:
#   REMOTE=gg:/path/to/the/checkout     DEST=$HOME/dev/backups/gg     KEEP=30
set -eu
ENV="${GG_BACKUP_ENV:-$HOME/.config/gg-backup.env}"
[ -r "$ENV" ] || { echo "backup: no settings at $ENV" >&2; exit 2; }
# shellcheck disable=SC1090
. "$ENV"
: "${REMOTE:?REMOTE is required}" "${DEST:?DEST is required}" "${KEEP:=30}"
DATE="${GG_DATE:-$(date -u +%F)}"
umask 077
mkdir -p "$DEST"
target="$DEST/$DATE"
mkdir -p "$target"
link=""
[ -d "$DEST/latest" ] && link="--link-dest=$DEST/latest/"
# the files: logs/ (rotated and archived included), configs/, .env (mode kept)
rsync -a --delete $link \
  "$REMOTE/logs" "$REMOTE/configs" "$REMOTE/.env" "$target/"
ln -sfn "$DATE" "$DEST/latest"
# prune: keep the newest KEEP dated directories
ls -1d "$DEST"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] 2>/dev/null | sort | head -n "-$KEEP" \
  | while read -r old; do rm -rf "$old"; done
echo "backup: $target ($(du -sh "$target" | cut -f1)), $(ls -1d "$DEST"/[0-9]* | wc -l) kept"
