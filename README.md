# cwarm

[![CI](https://github.com/wonderbyte/cwarm/actions/workflows/ci.yml/badge.svg)](https://github.com/wonderbyte/cwarm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cwarm.svg)](https://pypi.org/project/cwarm/)
[![Python](https://img.shields.io/pypi/pyversions/cwarm.svg)](https://pypi.org/project/cwarm/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Stagger-warm multiple **coding-agent accounts** so their rolling usage windows
open early in the day and reset at different times. Today it warms **Claude Code**
accounts (paired with [`claude-swap`](https://pypi.org/project/claude-swap/),
`cswap`); the agent layer is generic, so other CLIs (e.g. Codex) can be added.
When the active account exhausts its window, another is already warm to switch
into.

This tool **stores no credentials** — the account-switcher (`claude-swap`) is the
source of truth for accounts and tokens. cwarm only orchestrates it.

## How it works

Claude Code's 5-hour window starts on an account's first message and resets
exactly 5 hours later. It's a fixed budget, not free capacity — warming only
*relocates* the dead/regeneration time so it lands outside your working hours.
Staggering the warmups (e.g. 05:00, 07:30, 10:00) keeps at least one fresh
account available through the day.

For each due account, cwarm:

1. switches to it (for Claude: `cswap --switch-to <id>`),
2. waits `settle_seconds` for the credential swap to land,
3. sends one minimal message via the agent's command (for Claude: `claude -p "Hi"`)
   — anchoring that account's window,

then restores whichever account you had active before the batch (always, even
if a warmup fails).

> A **weekly cap** is shared across web, app, and Claude Code. Warming several
> accounts daily consumes some of it. Tracking that cap is out of scope.

## Agents

An "agent" is just two things: a **command** that sends a non-interactive prompt
(`<cli> -p "Hi"`) and an optional **account-switcher**. They live as a small data
table in `cwarm/agent.py` — not a class per agent:

| agent | command | switcher |
| --- | --- | --- |
| `claude` | `claude -p` | `cswap` (claude-swap) |

Each account picks its agent via the `agent` field (default `claude`). To add a
coding agent, add one row. Only a *new* switcher (something other than `cswap`)
needs code — a sibling module to `cwarm/cswap.py`. An agent with no switcher
warms whatever account that CLI currently has active (no multi-account swapping).

## Requirements

- For the `claude` agent: `claude-swap` installed and configured with every
  target account added (`cswap --add-account` / `cswap --add-token sk-ant-oat01-…`),
  and Claude Code (`claude`) runnable non-interactively.
- Python 3.12+.

## Platform support

cwarm is pure Python and runs anywhere the agent's CLIs (`claude`, `cswap`) do:

- **Linux** — fully supported, with the bundled `systemd` user service.
- **macOS** — the tool and `cwarm daemon` work the same; for boot persistence
  use `launchd` or `cron` instead of systemd.
- **Windows** — works too; `tzdata` is pulled in automatically (Windows has no
  system IANA tz database). Use Task Scheduler or run `cwarm daemon` as a
  service instead of systemd.

`cwarm run`/`daemon` are cross-platform; only the deployment recipe differs.

## Install

```bash
cd ~/workspace/apps/cwarm
uv venv
uv pip install -e .
cp config.example.json config.json   # then edit ids/schedules
```

`config.json` is gitignored — it holds your real account ids.

## Configuration (`config.json`)

No tokens. Accounts are referenced by the handle their agent uses — for Claude, a
`cswap` **slot number** or **email**.

```json
{
  "defaults": {
    "agent": "claude",
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
time. Both keys may be present; their union (de-duplicated) is used. Each cron
time becomes its own daemon job, fired in the account's `timezone`.

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `id` | yes | — | unique; the agent's account handle (cswap slot or email) |
| `schedule` / `schedules` | yes | — | one (string) or many (array) 5-field cron times, read in the account's `timezone` |
| `agent` | no | `defaults` / `claude` | which coding agent warms this account |
| `enabled` | no | `true` | `false` skips the account entirely |
| `message` | no | `defaults` / `"Hi"` | the warmup message |
| `timezone` | no | `defaults` / `Asia/Kolkata` | IANA tz name |
| `settle_seconds` | no | `defaults` / `3` | delay after switching before sending |
| `skip_if_warm` | no | `defaults` / `false` | skip if the window is already open |

## Usage

```bash
cwarm init                           # write a starter config.json
cwarm validate                       # check config + agents; sends nothing
cwarm list                           # show accounts, live window state, next run
cwarm run                            # warm all enabled accounts now
cwarm run --account work@example.com # warm just one
cwarm daemon                         # long-lived; fires each account on its cron

# global flags
cwarm --config /path/to/config.json --log-file /path/to/cwarm.log <command>
```

- **`init`** — writes a starter `config.json` (won't clobber an existing one
  without `--force`).
- **`validate`** — confirms the JSON matches the schema, each account's agent CLI
  (and its switcher) is installed, and every configured `id` exists. Exits
  non-zero and sends nothing on any problem.
- **`list`** — read-only table of every account: agent, enabled, live window
  state (warm/cold), next scheduled run, and its cron times. Sends nothing.
- **`run`** — warms enabled accounts immediately (one batch, one save/restore per
  switcher). Good for testing or a system `crontab`. Non-zero if any warmup failed.
- **`daemon`** — schedules one job per account per cron time, in the account's
  timezone. Warmups are always serial.

### Logging

Every attempt emits one structured line to stderr (and the log file if set):

```
2026-06-21T05:00:03+0530 INFO save-active switcher=cswap account=work@example.com ref=1
2026-06-21T05:00:09+0530 INFO warmup account=work@example.com outcome=ok reset=10:00
2026-06-21T05:00:10+0530 INFO restore-active switcher=cswap account=work@example.com ref=1 outcome=ok
```

Outcomes: `ok` (with the window `reset` time), `failed` (with an `error`
summary), `skipped` (`skip_if_warm` and already warm).

## Deployment

### systemd (recommended)

```bash
mkdir -p ~/.config/systemd/user ~/.local/state/cwarm
cp systemd/cwarm.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now cwarm
loginctl enable-linger "$USER"        # run without an active login session
journalctl --user -u cwarm -f
```

### Alternative: system crontab

One line per warmup time invoking the one-shot mode (repeat a line per account
to warm it several times a day):

```cron
0 5  * * 1-5 cd ~/workspace/apps/cwarm && .venv/bin/cwarm run --account work@example.com
0 11 * * 1-5 cd ~/workspace/apps/cwarm && .venv/bin/cwarm run --account work@example.com
0 21 * * 1-5 cd ~/workspace/apps/cwarm && .venv/bin/cwarm run --account work@example.com
30 7 * * 1-5 cd ~/workspace/apps/cwarm && .venv/bin/cwarm run --account 2
```

## Energy

The daemon does **not** poll — it sleeps on an event until the next scheduled
warmup, so idle cost is ~25 MB RAM and effectively 0% CPU (measured: 1 voluntary
context switch over 3 s idle). There is no busy-loop to optimise.

The real per-warmup energy is the `claude -p "Hi"` call: it boots the Node
Claude Code CLI **and** sends a real LLM inference request to anchor the window.
That's irreducible — anchoring *requires* a server-side message. So the only
meaningful lever is **not sending redundant ones**:

- **`skip_if_warm: true`** (the example default) — before switching, parse
  `cswap --list`; if the account's window is already open, log `skipped` and send
  nothing. This skips the entire heavy `claude -p` call, the single biggest
  energy saving available.
- **Stagger, don't stack** — overlapping schedules waste warmups (and the shared
  weekly cap). One warmup per window per account is enough to anchor it.

For literally zero idle footprint, use systemd timers or cron instead of the
daemon — no process is resident between warmups — but the saving over the
sleeping daemon is marginal.

## System restart

Yes. Via the systemd **user** service plus linger:

- `systemctl --user enable` + `loginctl enable-linger "$USER"` → the daemon
  **starts on boot**, with no login session required.
- `Restart=always` (RestartSec=10) → if the process ever exits — crash or
  otherwise — systemd brings it straight back.
- On every (re)start the schedule is **rebuilt fresh from `config.json`**
  (in-memory jobstore; the config is the single source of truth — no stale
  persisted state to reconcile).
- **Short downtime is tolerated:** `misfire_grace_time=3600` + `coalesce=True`
  mean a warmup missed by under an hour still fires once on recovery.
- **Long power-off is *not* caught up by design:** a 05:00 warmup missed because
  the machine was off until noon is skipped, not fired late — firing it hours
  late would defeat the staggering. Edit `config.json` and
  `systemctl --user restart cwarm` to re-plan.

## Safety

- No credentials stored or logged — the switcher (`claude-swap`) owns them.
- Switching changes your local active account; run warmups at off-hours. The
  save/restore guarantees your default is unchanged after a batch.
- Only configure accounts you legitimately own or are authorised to use.

## Contributing / releasing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, `ci:`, …). Lint and tests run in CI:

```bash
ruff check .
pytest
```

Versioning and the changelog are managed by
[Commitizen](https://commitizen-tools.github.io/commitizen/).

**To release:** run the **Release & Publish** workflow from the Actions tab
("Run workflow", optionally choosing the bump size). In one run it bumps the
version (`pyproject.toml` + `cwarm/__init__.py`), updates `CHANGELOG.md`, tags
and creates the GitHub Release, then builds and publishes to PyPI via Trusted
Publishing — no token stored. The next version is inferred from the Conventional
Commits since the last release.

Or do it locally:

```bash
cz bump                 # bump version + changelog + create the vX.Y.Z tag
git push --follow-tags
```

The project is in `0.x` (`major_version_zero`), so breaking changes bump the
minor until `1.0.0`.
