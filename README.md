# cwarm

[![CI](https://github.com/wonderbyte/cwarm/actions/workflows/ci.yml/badge.svg)](https://github.com/wonderbyte/cwarm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cwarm.svg)](https://pypi.org/project/cwarm/)
[![Python](https://img.shields.io/pypi/pyversions/cwarm.svg)](https://pypi.org/project/cwarm/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Warm your **Claude Code** 5-hour usage window on a schedule, so its dead
regeneration time lands outside your working hours instead of stranding you
mid-flow. cwarm sends a tiny "Hi" at the times you choose to anchor the window
early — and can stagger several accounts too, if you rotate them with
[`claude-swap`](https://pypi.org/project/claude-swap/) (`cswap`).

cwarm **stores no credentials** — `claude-swap` owns your account and tokens;
cwarm only triggers the warmup.

## Why I built it

I kept hitting the same wall: my Claude Code 5-hour window starts on the first
message and resets exactly 5 hours later — and I burn through its budget in about
2 hours, then sit idle for the remaining 3 waiting for the reset. Start cold at
8 AM and that dead stretch lands around 10 AM–1 PM, right in the middle of my day.

The fix: send a throwaway "Hi" *before* I start. Fire it at 5 AM and the window
runs 05:00–10:00 — so I work 8–10, exhaust it, and the reset is already there;
the 3-hour gap happened before I sat down instead of mid-morning. Re-warm at the
reset times and the windows stay anchored to clock times I choose, so the idle
stretches land on lunch instead of mid-flow. It doesn't create more budget — it
just moves the dead time out of my way.

I kept meaning to fire that ping every morning and kept forgetting. cwarm just
does it, on a schedule. (It handles several accounts too, if you rotate them —
that's just not how I use it.)

## How it works

A Claude Code 5-hour window starts on your first message and resets exactly 5
hours later. It's a fixed budget, not free capacity — warming only *relocates*
the dead/regeneration time. Send a warmup "Hi" at 05:00 and the window runs
05:00–10:00, so the idle stretch happens before work instead of mid-morning. Give
an account several warmup times to re-anchor each new window to clock times you
pick, dropping the dead gaps onto your breaks.

**Multiple accounts (optional).** If you keep more than one account in
`claude-swap`, cwarm warms each on its own staggered schedule — switching to it,
sending the message, then **restoring whichever account you had active before**
(always, even if a warmup fails, so running it never leaves your setup changed).
Staggered resets mean there's always a fresh account to switch into.

> A **weekly cap** is shared across web, app, and Claude Code; cwarm does not
> track it.

## Install

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install cwarm     # installs the `cwarm` command, isolated
# or run it without installing:
uvx cwarm --help
```

Or with pipx / pip:

```bash
pipx install cwarm
# or
pip install cwarm
```

Requires Python 3.12+ (`uv`/`pipx` handle that for you).

## Quick start

```bash
cwarm init        # writes a starter config to ~/.config/cwarm/config.json
$EDITOR ~/.config/cwarm/config.json
cwarm validate    # checks your config + that cswap/claude are set up; sends nothing
cwarm list        # shows each account, whether it's warm, and the next run
cwarm run         # warm everything now (optional sanity check)
cwarm daemon      # leave running to warm on schedule
```

cwarm reads `~/.config/cwarm/config.json` by default (override with `--config`),
so the commands above work from any directory.

You also need, for each account you list:

- [`claude-swap`](https://pypi.org/project/claude-swap/) installed, with the
  account added (`cswap --add-account` or `cswap --add-token sk-ant-oat01-…`),
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude`) installed.

## Configuration (`config.json`)

No tokens. Accounts are referenced by their `cswap` handle — a **slot number**
or **email**. The simplest config is a single account warmed before work:

```json
{
  "defaults": {
    "message": "Hi",
    "timezone": "Asia/Kolkata",
    "settle_seconds": 3,
    "skip_if_warm": true
  },
  "accounts": [
    { "id": "1", "schedules": ["0 5 * * 1-5", "0 10 * * 1-5", "0 15 * * 1-5"] }
  ]
}
```

That warms account `1` at 05:00, 10:00, and 15:00 on weekdays, anchoring each new
5-hour window to those clock times. An account can warm at **several times a
day** — give it a `schedules` array — or use the singular `schedule` string for
one time. Each cron time fires in the account's `timezone`.

**Rotating multiple accounts?** Add more entries on staggered times so a fresh
window is always available to switch into:

```json
"accounts": [
  { "id": "1", "schedule": "0 5 * * 1-5" },
  { "id": "2", "schedule": "30 7 * * 1-5" },
  { "id": "3", "enabled": false, "schedule": "0 10 * * *" }
]
```

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

Your config lives at `~/.config/cwarm/config.json` (it holds your real account
ids — keep it out of version control). Point anywhere else with `--config`.

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

A sample unit ships in [`systemd/cwarm.service`](systemd/cwarm.service); it reads
the default `~/.config/cwarm/config.json` that `cwarm init` writes.

```bash
mkdir -p ~/.config/systemd/user ~/.local/state/cwarm
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
