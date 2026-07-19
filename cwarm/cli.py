"""Command-line entrypoint: init | validate | list | run | daemon."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .agent import get_agent, get_switcher
from .config import Account, Config, ConfigError, load_config
from .cron import next_fire
from .cswap import CswapError
from .log import log_event, setup_logging
from .schedule import run_batch, run_daemon
from .warmup import FAILED


def default_config_path() -> Path:
    """Permanent config location: $XDG_CONFIG_HOME/cwarm/config.json (~/.config/...)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cwarm" / "config.json"

CONFIG_TEMPLATE = """{
  "defaults": {
    "message": "Hi",
    "model": "haiku",
    "timezone": "Asia/Kolkata",
    "settle_seconds": 3,
    "skip_if_warm": true
  },
  "accounts": [
    { "id": "1", "schedules": ["0 5 * * 1-5", "0 10 * * 1-5", "0 15 * * 1-5"] }
  ]
}
"""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    setup_logging(log_file=args.log_file)
    config_path = args.config or default_config_path()

    # `init` writes the config, so it must run before we try to load one.
    if args.command == "init":
        return _cmd_init(config_path, args.force)

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        return _cmd_validate(config)
    if args.command == "list":
        return _cmd_list(config)
    if args.command == "run":
        return _cmd_run(config, args.account)
    if args.command == "daemon":
        return _cmd_daemon(config)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cwarm",
        description="Stagger-warm coding-agent accounts so their usage windows reset at different times.",
    )
    parser.add_argument("--version", action="version", version=f"cwarm {__version__}")
    parser.add_argument(
        "-c", "--config", default=None, type=Path,
        help="path to the JSON config (default: ~/.config/cwarm/config.json)",
    )
    parser.add_argument(
        "--log-file", default=None, type=Path,
        help="also append structured logs to this file",
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    init = sub.add_parser("init", help="write a starter config.json")
    init.add_argument("--force", action="store_true", help="overwrite an existing config")

    sub.add_parser("validate", help="validate config and environment; send nothing")
    sub.add_parser("list", help="show configured accounts, window state, and next run")

    run = sub.add_parser("run", help="warm all enabled accounts (or one) immediately")
    run.add_argument("--account", default=None, help="warm only this account id (slot or email)")

    sub.add_parser("daemon", help="run long-lived, firing each account on its cron schedule")
    return parser


def _cmd_init(config_path: Path, force: bool) -> int:
    if config_path.exists() and not force:
        print(f"init: {config_path} already exists — use --force to overwrite", file=sys.stderr)
        return 1
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(CONFIG_TEMPLATE)
    print(f"init: wrote {config_path} — edit the account ids/schedules, then run `cwarm validate`")
    return 0


def _cmd_validate(config: Config) -> int:
    """Schema OK; each agent's CLI present and (if it switches) every id known. Sends nothing."""
    for agent_name, accounts in _by_agent(config).items():
        agent = get_agent(agent_name)
        if shutil.which(agent.command[0]) is None:
            print(f"validate: agent '{agent_name}': '{agent.command[0]}' is not on PATH", file=sys.stderr)
            return 1

        switcher = get_switcher(agent.switcher)
        if switcher is None:
            continue  # no switcher: can't enumerate accounts, nothing more to check
        if not switcher.is_installed():
            print(f"validate: agent '{agent_name}': switcher '{agent.switcher}' is not on PATH", file=sys.stderr)
            return 1
        try:
            listed = switcher.list_accounts()
        except CswapError as exc:
            print(f"validate: agent '{agent_name}': could not list accounts: {exc}", file=sys.stderr)
            return 1

        missing = [a.id for a in accounts if not any(la.matches(a.id) for la in listed)]
        if missing:
            known = ", ".join(f"{la.slot}:{la.email}" for la in listed) or "(none)"
            print(
                f"validate: these ids are not known to agent '{agent_name}': "
                + ", ".join(missing)
                + f"\n  known accounts: {known}",
                file=sys.stderr,
            )
            return 1

    enabled = len(config.enabled_accounts())
    used = ", ".join(sorted(_by_agent(config)))
    print(f"validate: ok — {len(config.accounts)} account(s) configured, {enabled} enabled, agents: {used}")
    return 0


def _cmd_list(config: Config) -> int:
    """Read-only overview: each account's agent, credential + window state (live), and next run.

    Sends nothing. CREDS comes straight from cswap's `usageStatus`: an account
    reading anything but `ok` cannot be warmed until it is re-authenticated,
    which is otherwise only visible by digging through the daemon log.
    """
    listings: dict[str, list | None] = {}

    def listed_account(account: Account):
        """The switcher's live record for this account, or a marker string."""
        switcher = get_switcher(get_agent(account.agent).switcher)
        if switcher is None:
            return "n/a"
        name = get_agent(account.agent).switcher
        if name not in listings:
            try:
                listings[name] = switcher.list_accounts()
            except CswapError:
                listings[name] = None
        listed = listings[name]
        if listed is None:
            return "?"
        return next((a for a in listed if a.matches(account.id)), "unknown")

    def window_state(match) -> str:
        if isinstance(match, str):
            return match
        return {True: "warm", False: "cold", None: "?"}[match.window_open]

    def cred_state(match) -> str:
        if isinstance(match, str):
            return match
        return "ok" if match.credentials_ok else match.cred_status

    rows = []
    degraded = 0
    for account in config.accounts:
        match = listed_account(account)
        if not isinstance(match, str) and not match.credentials_ok:
            degraded += 1
        rows.append(
            (
                account.id,
                account.agent,
                "yes" if account.enabled else "no",
                cred_state(match),
                window_state(match),
                _next_run(account) if account.enabled else "-",
                ", ".join(account.schedules),
            )
        )
    _print_table(("ID", "AGENT", "ON", "CREDS", "WINDOW", "NEXT RUN", "SCHEDULE(S)"), rows)
    if degraded:
        sys.stdout.flush()  # keep the warning below the table when stdout is piped
        print(
            f"\n{degraded} account(s) have unusable credentials and will fail to warm. "
            "Re-authenticate them, then `cswap add --slot <n>`.",
            file=sys.stderr,
        )
    return 0


def _cmd_run(config: Config, account: str | None) -> int:
    account_ids = [account] if account else None
    try:
        results = run_batch(config, account_ids)
    except ValueError as exc:
        print(f"run: {exc}", file=sys.stderr)
        return 2
    failed = sum(1 for r in results if r.outcome == FAILED)
    log_event("run", outcome="done", total=len(results), failed=failed)
    return 1 if failed else 0


def _cmd_daemon(config: Config) -> int:
    run_daemon(config)
    return 0


def _by_agent(config: Config) -> dict[str, list[Account]]:
    grouped: dict[str, list[Account]] = {}
    for account in config.accounts:
        grouped.setdefault(account.agent, []).append(account)
    return grouped


def _next_run(account: Account) -> str:
    """Soonest upcoming fire across the account's schedules, in its timezone."""
    now = datetime.now(ZoneInfo(account.timezone))
    fires = [f for cron in account.schedules if (f := next_fire(cron, account.timezone, now))]
    if not fires:
        return "-"
    return min(fires).strftime("%a %H:%M (%d %b)")


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(c))) for w, c in zip(widths, row, strict=False)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=False)))


if __name__ == "__main__":
    sys.exit(main())
