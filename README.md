# cwarm

[![CI](https://github.com/wonderbyte/cwarm/actions/workflows/ci.yml/badge.svg)](https://github.com/wonderbyte/cwarm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cwarm.svg)](https://pypi.org/project/cwarm/)
[![Python](https://img.shields.io/pypi/pyversions/cwarm.svg)](https://pypi.org/project/cwarm/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Stagger-warm multiple **Claude Code accounts** so their rolling 5-hour usage
windows open early in the day and reset at different times. Paired with
[`claude-swap`](https://pypi.org/project/claude-swap/) (`cswap`), this keeps a
fresh account warm to switch into through the whole working day — when the
active account exhausts its window, another is already going.

cwarm **stores no credentials**. `claude-swap` owns your accounts and tokens;
cwarm only tells it which account to make active, then sends one tiny message.

## How it works

A Claude Code 5-hour window starts on an account's first message and resets
exactly 5 hours later. It's a fixed budget, not free capacity — warming only
*relocates* the dead/regeneration time so it lands outside your working hours.
Staggering the warmups (e.g. 05:00, 07:30, 10:00) means at least one account is
always fresh.

For each scheduled account, cwarm switches to it, sends a one-word message to
anchor its window, then **restores whichever account you had active before** —
always, even if a warmup fails. So running it never leaves your setup changed.

> A **weekly cap** is shared across web, app, and Claude Code. Warming several
> accounts daily consumes some of it. cwarm does not track that cap.

## Install

```bash
pipx install cwarm     # recommended (isolated)
# or
pip install cwarm
```

Requires Python 3.12+.

## Quick start

```bash
cwarm init        # writes a starter config.json
$EDITOR config.json
cwarm validate    # checks your config + that cswap/claude are set up; sends nothing
cwarm list        # shows each account, whether it's warm, and the next run
cwarm run         # warm everything now (optional sanity check)
cwarm daemon      # leave running to warm on schedule
```

You also need, for each account you list:

- [`claude-swap`](https://pypi.org/project/claude-swap/) installed, with the
  account added (`cswap --add-account` or `cswap --add-token sk-ant-oat01-…`),
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude`) installed.

## Configuration (`config.json`)

No tokens. Accounts are referenced by their `cswap` handle — a **slot number**
or **email**.

```json
{
  "defaults": {
    "message": "Hi",
    "timezone": "Asia/Kolkata",
    "settle_seconds": 3,
    "skip_if_warm": true
  },
  "accounts": [
    { "id": "work@example.com", "enabled": true,  "schedules": ["0 5 * * 1-5", "0 11 * * 1-5", "0 21 * * 1-5"] },
    { "id": "2",                "enabled": true,  "schedule": "30 7 * * 1-5" },
    { "id": "personal@x.com",   "enabled": true,  "schedules": ["0 10 * * *", "0 18 * * *"] },
    { "id": "4",                "enabled": false, "schedule": "30 12 * * *" }
  ]
}
```

An account can warm at **several times a day** — give it a `schedules` array
(e.g. 05:00, 11:00, 21:00). Use the singular `schedule` string for a single
time. Each cron time fires in the account's `timezone`.

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `id` | yes | — | unique; the account's `cswap` slot number or email |
| `schedule` / `schedules` | yes | — | one (string) or many (array) of 5-field cron times, read in the account's `timezone` |
| `enabled` | no | `true` | `false` skips the account entirely |
| `message` | no | `"Hi"` | the warmup message |
| `timezone` | no | `Asia/Kolkata` | IANA tz name |
| `settle_seconds` | no | `3` | delay after switching before sending |
| `skip_if_warm` | no | `false` | skip if the window is already open (saves usage) |
| `agent` | no | `claude` | which coding agent warms this account (currently `claude`) |

`config.json` holds your real account ids — keep it out of version control.

## Commands

```bash
cwarm init                           # write a starter config.json
cwarm validate                       # check config + setup; sends nothing
cwarm list                           # accounts, live window state, next run
cwarm run                            # warm all enabled accounts now
cwarm run --account work@example.com # warm just one
cwarm daemon                         # long-lived; fires each account on its cron

# global flags
cwarm --config /path/to/config.json --log-file /path/to/cwarm.log <command>
```

- **`validate`** — confirms the config is valid, `cswap`/`claude` are installed,
  and every configured `id` exists. Exits non-zero and sends nothing on a problem.
- **`list`** — read-only table: account, enabled, live window state (warm/cold),
  next scheduled run, cron times. Sends nothing.
- **`run`** — warms enabled accounts immediately. Non-zero if any warmup failed.
- **`daemon`** — schedules one job per account per cron time. Warmups are serial.

### Logging

Every attempt emits one structured line to stderr (and the log file if set):

```
2026-06-21T05:00:03+0530 INFO save-active switcher=cswap account=work@example.com ref=1
2026-06-21T05:00:09+0530 INFO warmup account=work@example.com outcome=ok reset=10:00
2026-06-21T05:00:10+0530 INFO restore-active switcher=cswap account=work@example.com ref=1 outcome=ok
```

Outcomes: `ok` (with the window `reset` time), `failed` (with an `error`
summary), `skipped` (already warm, with `skip_if_warm`).

## Running it on a schedule

### systemd (Linux)

A sample unit ships in [`systemd/cwarm.service`](systemd/cwarm.service). Put your
config somewhere stable, then:

```bash
mkdir -p ~/.config/cwarm ~/.config/systemd/user ~/.local/state/cwarm
cp config.json ~/.config/cwarm/config.json
cp systemd/cwarm.service ~/.config/systemd/user/   # adjust the cwarm path if needed
systemctl --user daemon-reload
systemctl --user enable --now cwarm
loginctl enable-linger "$USER"        # run without an active login session
journalctl --user -u cwarm -f
```

It starts on boot and restarts on failure. On (re)start the schedule is rebuilt
from `config.json`; a warmup missed by under an hour still fires once on
recovery, but a warmup missed across a long power-off is skipped (firing a 05:00
warmup at noon would defeat the staggering).

### Alternative: cron

One line per warmup time (`cwarm` must be on PATH):

```cron
0 5  * * 1-5 cwarm --config ~/.config/cwarm/config.json run --account work@example.com
0 11 * * 1-5 cwarm --config ~/.config/cwarm/config.json run --account work@example.com
30 7 * * 1-5 cwarm --config ~/.config/cwarm/config.json run --account 2
```

### macOS / Windows

`cwarm run`/`daemon` are cross-platform — only the boot-persistence recipe
differs. On macOS use `launchd` or `cron`; on Windows use Task Scheduler (or run
`cwarm daemon` as a service). The tool needs `claude` and `cswap` available on
that OS.

## Tips

- **`skip_if_warm: true`** is the biggest usage saver — it skips the whole
  `claude -p` call (a real LLM request) when an account's window is already open.
- **Stagger, don't stack.** Overlapping schedules waste warmups and the shared
  weekly cap; one warmup per window per account is enough to anchor it.
- The daemon doesn't poll — it sleeps until the next job (~25 MB RAM, ~0% CPU
  idle).

## Safety

- No credentials stored or logged — `claude-swap` owns them.
- Switching changes your active account momentarily; the save/restore guarantees
  your default is unchanged after a run, so prefer off-hours anyway.
- Only configure accounts you legitimately own or are authorised to use.

## License

MIT — see [LICENSE](LICENSE). Project internals and contribution notes live in
[CLAUDE.md](CLAUDE.md).
