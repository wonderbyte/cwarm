# Changelog

All notable changes are documented here. This file is managed by
[Commitizen](https://commitizen-tools.github.io/commitizen/) — run `cz bump`
to cut a version and prepend the next entry from Conventional Commits.

## v0.2.0 (2026-07-03)

### Feat

- warm with --model haiku by default

## v0.1.2 (2026-06-22)

### Fix

- **systemd**: add ~/.local/bin to the unit PATH

## v0.1.1 (2026-06-21)

### Feat

- **cli**: default config to ~/.config/cwarm/config.json

### Fix

- **warmup**: poll cswap for the new window reset so 'ok' logs it

## v0.1.0 (2026-06-21)

Initial release.

### Feat

- Stagger-warm multiple coding-agent accounts on per-account cron schedules, so
  their rolling usage windows open early and reset at different times.
- Generic agent layer (a small data table): Claude Code via claude-swap today,
  with a pluggable account-switcher seam for other CLIs. Selected per account.
- Commands: `init`, `validate`, `list`, `run`, `daemon`.
- APScheduler daemon with correct crontab day-of-week handling, multi-schedule
  accounts, `skip_if_warm`, and save/restore of the active account (even on
  failure).
- systemd unit, structured per-attempt logging, PyPI trusted-publishing and CI
  workflows.
