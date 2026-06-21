"""Load and validate the cwarm JSON config (§7).

No tokens live here — accounts are referenced by the handle their agent uses
(e.g. a claude-swap slot number or email). Per-account fields fall back to
`defaults`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent import DEFAULT_AGENT, known_agents
from .cron import to_trigger

# 5-field cron, the subset APScheduler's CronTrigger.from_crontab accepts.
_CRON_FIELDS = 5


class ConfigError(ValueError):
    """Raised when the config file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class Defaults:
    agent: str = DEFAULT_AGENT
    message: str = "Hi"
    timezone: str = "Asia/Kolkata"
    settle_seconds: int = 3
    skip_if_warm: bool = False


@dataclass(frozen=True)
class Account:
    id: str
    agent: str
    schedules: tuple[str, ...]
    enabled: bool
    message: str
    timezone: str
    settle_seconds: int
    skip_if_warm: bool


@dataclass(frozen=True)
class Config:
    defaults: Defaults
    accounts: list[Account]

    def enabled_accounts(self) -> list[Account]:
        return [a for a in self.accounts if a.enabled]

    def find(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)


def load_config(path: str | Path) -> Config:
    """Read, parse, and validate the config at `path`. Raises ConfigError."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    return _build(raw, path)


def _build(raw: object, path: Path) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a JSON object")

    defaults = _build_defaults(raw.get("defaults", {}))

    raw_accounts = raw.get("accounts")
    if not isinstance(raw_accounts, list) or not raw_accounts:
        raise ConfigError(f"{path}: 'accounts' must be a non-empty array")

    accounts: list[Account] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw_accounts):
        account = _build_account(entry, defaults, i)
        if account.id in seen:
            raise ConfigError(f"{path}: duplicate account id {account.id!r}")
        seen.add(account.id)
        accounts.append(account)

    return Config(defaults=defaults, accounts=accounts)


def _build_defaults(raw: object) -> Defaults:
    if not isinstance(raw, dict):
        raise ConfigError("'defaults' must be a JSON object")
    base = Defaults()
    agent = raw.get("agent", base.agent)
    message = raw.get("message", base.message)
    timezone = raw.get("timezone", base.timezone)
    settle = raw.get("settle_seconds", base.settle_seconds)
    skip = raw.get("skip_if_warm", base.skip_if_warm)
    _check_agent("defaults", agent)
    _check_message("defaults", message)
    _check_timezone("defaults", timezone)
    _check_settle("defaults", settle)
    _check_bool("defaults.skip_if_warm", skip)
    return Defaults(
        agent=agent,
        message=message,
        timezone=timezone,
        settle_seconds=settle,
        skip_if_warm=skip,
    )


def _build_account(raw: object, defaults: Defaults, index: int) -> Account:
    where = f"accounts[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: must be a JSON object")

    account_id = raw.get("id")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ConfigError(f"{where}: 'id' is required and must be a non-empty string")
    account_id = account_id.strip()

    schedules = _collect_schedules(raw, f"{where} ({account_id})")

    enabled = raw.get("enabled", True)
    _check_bool(f"{where} ({account_id}).enabled", enabled)

    agent = raw.get("agent", defaults.agent)
    message = raw.get("message", defaults.message)
    timezone = raw.get("timezone", defaults.timezone)
    settle = raw.get("settle_seconds", defaults.settle_seconds)
    skip = raw.get("skip_if_warm", defaults.skip_if_warm)
    _check_agent(f"{where} ({account_id})", agent)
    _check_message(f"{where} ({account_id})", message)
    _check_timezone(f"{where} ({account_id})", timezone)
    _check_settle(f"{where} ({account_id})", settle)
    _check_bool(f"{where} ({account_id}).skip_if_warm", skip)

    return Account(
        id=account_id,
        agent=agent,
        schedules=schedules,
        enabled=enabled,
        message=message,
        timezone=timezone,
        settle_seconds=settle,
        skip_if_warm=skip,
    )


def _collect_schedules(raw: dict, where: str) -> tuple[str, ...]:
    """Gather warmup times from `schedule` (string) and/or `schedules` (array).

    Either or both keys may be present; the result is the de-duplicated union,
    so one account can fire at several times of day (e.g. 05:00, 11:00, 21:00).
    """
    collected: list[str] = []

    single = raw.get("schedule")
    if single is not None:
        if not isinstance(single, str) or not single.strip():
            raise ConfigError(f"{where}: 'schedule' must be a non-empty cron string")
        collected.append(single.strip())

    multi = raw.get("schedules")
    if multi is not None:
        if not isinstance(multi, list) or not multi:
            raise ConfigError(f"{where}: 'schedules' must be a non-empty array of cron strings")
        for entry in multi:
            if not isinstance(entry, str) or not entry.strip():
                raise ConfigError(f"{where}: every 'schedules' entry must be a non-empty cron string")
            collected.append(entry.strip())

    if not collected:
        raise ConfigError(f"{where}: provide 'schedule' (string) or 'schedules' (array of 5-field cron)")

    for cron in collected:
        _check_cron(where, cron)

    return tuple(dict.fromkeys(collected))  # de-dup, preserve order


def _check_agent(where: str, value: object) -> None:
    if not isinstance(value, str) or value not in known_agents():
        raise ConfigError(
            f"{where}.agent: must be one of {known_agents()}, got {value!r}"
        )


def _check_bool(where: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: must be a boolean")


def _check_message(where: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.message: must be a non-empty string")


def _check_settle(where: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{where}.settle_seconds: must be a non-negative integer")


def _check_timezone(where: str, value: object) -> None:
    if not isinstance(value, str):
        raise ConfigError(f"{where}.timezone: must be a string")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"{where}.timezone: unknown timezone {value!r}") from exc


def _check_cron(where: str, value: str) -> None:
    fields = value.split()
    if len(fields) != _CRON_FIELDS:
        raise ConfigError(
            f"{where}.schedule: expected a 5-field cron expression, got {len(fields)} fields: {value!r}"
        )
    try:
        to_trigger(value, "UTC")  # tz irrelevant here; this also validates each field
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{where}.schedule: invalid cron {value!r}: {exc}") from exc
