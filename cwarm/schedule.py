"""Batch execution and the long-lived daemon (FR3, FR5, FR8).

Warmups are strictly serial — a switcher has only one active account at a time.
For each switcher the batch touches, the active account is captured before and
restored after, even on failure (FR3). The daemon maps each enabled account's
cron+timezone to a job and serialises all firings through a single lock.
"""

from __future__ import annotations

import threading

from apscheduler.schedulers.blocking import BlockingScheduler

from .agent import get_agent, get_switcher
from .config import Account, Config
from .cron import to_trigger
from .cswap import ActiveAccount, CswapError
from .log import log_event
from .warmup import FAILED, WarmResult, warm_account

# Serialises warmups so two coincident cron firings never run concurrently (FR5).
_warmup_lock = threading.Lock()


def run_batch(config: Config, account_ids: list[str] | None = None) -> list[WarmResult]:
    """Warm the selected accounts serially, saving and restoring each switcher's active one.

    `account_ids=None` warms every enabled account. Restore (FR3) runs in a
    `finally` so it survives any individual warmup failure.
    """
    accounts = _select(config, account_ids)
    with _warmup_lock:
        return _run_serial(accounts)


def _run_serial(accounts: list[Account]) -> list[WarmResult]:
    # Distinct switcher backends this batch will touch (agents may share one).
    switchers = {get_agent(a.agent).switcher for a in accounts}
    switchers.discard(None)
    saved = {name: _save_active(name) for name in switchers}
    results: list[WarmResult] = []
    try:
        for account in accounts:
            results.append(warm_account(account))
    finally:
        for name, active in saved.items():
            _restore_active(name, active)
    return results


def _save_active(switcher_name: str) -> ActiveAccount | None:
    try:
        active = get_switcher(switcher_name).status()
    except CswapError as exc:
        log_event("save-active", switcher=switcher_name, outcome=FAILED, error=str(exc))
        return None
    if active:
        log_event("save-active", switcher=switcher_name, account=active.email, ref=active.ref)
    else:
        log_event("save-active", switcher=switcher_name, outcome="none", error="no-active-account")
    return active


def _restore_active(switcher_name: str, saved: ActiveAccount | None) -> None:
    if saved is None:
        log_event("restore-active", switcher=switcher_name, outcome="skipped", error="nothing-to-restore")
        return
    try:
        get_switcher(switcher_name).switch_to(saved.ref)
        log_event("restore-active", switcher=switcher_name, account=saved.email, ref=saved.ref, outcome="ok")
    except CswapError as exc:
        log_event("restore-active", switcher=switcher_name, account=saved.email, outcome=FAILED, error=str(exc))


def _select(config: Config, account_ids: list[str] | None) -> list[Account]:
    if account_ids is None:
        return config.enabled_accounts()
    selected: list[Account] = []
    for account_id in account_ids:
        account = config.find(account_id)
        if account is None:
            raise ValueError(f"account id {account_id!r} not found in config")
        if not account.enabled:
            log_event("select", account=account_id, outcome="skipped", error="disabled")
            continue
        selected.append(account)
    return selected


def run_daemon(config: Config) -> None:
    """Long-lived scheduler: one cron job per enabled account (FR8)."""
    # Explicit scheduler tz avoids tzlocal probing /etc/timezone; each job still
    # carries its own per-account timezone.
    scheduler = BlockingScheduler(timezone=config.defaults.timezone)
    enabled = config.enabled_accounts()
    if not enabled:
        log_event("daemon", outcome="no-enabled-accounts")
        return

    jobs = 0
    for account in enabled:
        for idx, cron in enumerate(account.schedules):
            trigger = to_trigger(cron, account.timezone)
            scheduler.add_job(
                _fire,
                trigger=trigger,
                args=[account],
                id=f"cwarm:{account.agent}:{account.id}:{idx}",
                name=f"warmup {account.agent}:{account.id} [{cron}]",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )
            log_event("schedule", account=account.id, cron=repr(cron), tz=account.timezone)
            jobs += 1

    log_event("daemon", outcome="started", jobs=jobs)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log_event("daemon", outcome="stopped")


def _fire(account: Account) -> None:
    """A single account's scheduled firing: its own save/restore batch."""
    with _warmup_lock:
        _run_serial([account])
