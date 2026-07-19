# CLAUDE.md

Project notes for `cwarm` — for Claude Code sessions and contributors. The
user-facing docs are in [README.md](README.md); this file is the "how it's
built" side.

## What it is

A small scheduler that anchors multiple coding-agent accounts' usage windows on
staggered, per-account cron schedules. It stores **no credentials** — it shells
out to an account-switcher (`claude-swap`/`cswap`) and to the agent's CLI
(`claude -p`). The active account is captured before a batch and restored after,
always (even on failure).

## Dev setup

```bash
git clone https://github.com/wonderbyte/cwarm
cd cwarm
uv venv
uv pip install -e ".[dev]"     # apscheduler + pytest + ruff + commitizen
ruff check .
pytest
```

## Architecture

One small package, flat modules. Everything except the switcher and the send is
provider-agnostic.

| Module | Role |
| --- | --- |
| `cwarm/cli.py` | argparse entrypoint: `init \| validate \| list \| run \| daemon` |
| `cwarm/config.py` | load + validate the JSON config (dataclasses, defaults merge) |
| `cwarm/agent.py` | the agent table + switcher registry |
| `cwarm/cswap.py` | the one switcher backend: wraps `cswap` (status/list/switch) |
| `cwarm/warmup.py` | warm one account: (switch →) settle → send |
| `cwarm/schedule.py` | serial batch with per-switcher save/restore; APScheduler daemon |
| `cwarm/cron.py` | crontab → APScheduler `CronTrigger` translation |
| `cwarm/log.py` | one structured line per attempt |

### Agents are data, not classes

Sending a warmup is uniform across agents (`<cli> -p "Hi"`); the only
agent-specific part is the **account-switcher**. So agents are rows in a table in
`agent.py`:

```python
Agent(name="claude", command=("claude", "-p"), switcher="cswap")
```

- **Add an agent** = add a row. If it reuses an existing switcher, that's all.
- **A new switcher** (something other than `cswap`) = a sibling module to
  `cswap.py` exposing `status() / list_accounts() / switch_to() / is_installed()`,
  registered in `agent._SWITCHERS`.
- `switcher=None` → cwarm warms whatever account that CLI currently has active
  (no multi-account switching, no skip-if-warm/window-reset info).

`cswap.py` reads `cswap status --json` / `cswap list --json` (`schemaVersion` 1)
rather than parsing human-readable output. `_run_json` rejects an unexpected
`schemaVersion` with a clear error instead of silently misreading the payload.
The fixtures in `tests/test_cswap_parsing.py` are real observed payloads — keep
them in sync if the schema changes.

The JSON also carries `usageStatus` per account, exposed as
`ListedAccount.cred_status` / `.credentials_ok`. `no_credentials` means the slot
cannot be warmed until it is re-authenticated; `cwarm list` surfaces this in a
CREDS column and warns on stderr.

## Gotchas worth remembering

- **Crontab day-of-week.** APScheduler's `CronTrigger.from_crontab()` does *not*
  remap day-of-week (crontab `0/7=Sun..6=Sat`; APScheduler `0=Mon..6=Sun`), which
  silently shifts weekday schedules by a day. `cron.py` translates it; don't go
  back to `from_crontab`. Covered by `tests/test_cron.py`.
- **Save/restore is per switcher**, not per account — a batch captures each
  switcher's active account once and restores it in a `finally`.
- **`--token-status` can't combine with `--json`** — cswap rejects the pair, so
  OAuth expiry detail stays text-only. `usageStatus` in the JSON is the machine-
  readable proxy: it separates `ok` from `no_credentials`.
- **PyPI publisher is tied to the workflow filename** `publish.yml`. Don't rename
  that file or the Trusted Publisher stops matching.
- **A release created by `GITHUB_TOKEN` doesn't trigger other workflows.** That's
  why bump + release + publish all live in the one `publish.yml` run rather than
  a release event triggering a separate publish workflow.

## Conventions

- Python 3.12+, functional style, minimal error handling beyond restore + logging.
- **Lint/test:** `ruff check .` and `pytest` (both gate CI). Config in
  `pyproject.toml`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `ci:`, `build:`, …) — Commitizen derives versions
  and the changelog from them.

## Releasing

Versioning + changelog are managed by
[Commitizen](https://commitizen-tools.github.io/commitizen/) (`pep621` provider:
the single source of truth is `[project].version`, mirrored into
`cwarm/__init__.py`). The project is `0.x` (`major_version_zero`), so breaking
changes bump the minor until `1.0.0`.

**Preferred:** run the **Release & Publish** workflow from the GitHub Actions tab
("Run workflow", optional bump size). One run: lint + test → `cz bump` (version,
`CHANGELOG.md`, tag) → GitHub Release → build → publish to PyPI via Trusted
Publishing (OIDC, no token).

**Local equivalent:**

```bash
cz bump                 # version + changelog + vX.Y.Z tag from the commits
git push --follow-tags
```

## CI / workflows

- `.github/workflows/ci.yml` — `ruff` + `pytest` on Python 3.12 & 3.13, on every
  push to `main` and PR.
- `.github/workflows/publish.yml` — the dispatch-triggered Release & Publish
  pipeline described above (named `publish.yml` for the PyPI publisher match).
