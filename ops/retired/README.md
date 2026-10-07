# Retired — the box-side Claude

Triage on a fleet failure (`triage.sh`), the Telegram relay (`relay.py`) and the
daily range review (`range_review.py`), with their settings file and unit
templates. Retired by the owner on 2026-09-28 and switched off for good on
2026-10-06: the audit of 2026-10-05 found the settings cage
(`triage-settings.json`) is not read-only — an agent in it can read `.env` and
`~/.ssh` and write through `git diff --output` — and triage was found still
running on fleet failures because a token remained on the box.

Each entry point refuses to run. Nothing in `ops/systemd/` may call them; a
spec holds that. They stay as the shape to rebuild from in the agentic phase,
where the agent runs as its own OS user that cannot read the secrets — a
sandbox the operating system enforces, not a list the agent is asked to keep.
