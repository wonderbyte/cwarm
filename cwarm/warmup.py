"""Warm a single account: (optionally switch) -> settle -> send message (FR4).

The send is just the agent's configured command with the message appended
(`claude -p "Hi"`). If the agent has a switcher, we switch to the target account
first; a fresh process then reads the swapped credentials at startup, so no
interactive restart is needed — the `settle_seconds` delay covers the write race.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from types import ModuleType

from .agent import get_agent, get_switcher
from .config import Account
from .cswap import CswapError
from .log import log_attempt

# Outcomes (FR11)
OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

_SEND_TIMEOUT = 180  # seconds for a single warmup message
_SEND_ERRORS = (CswapError, OSError, subprocess.SubprocessError, RuntimeError)


@dataclass(frozen=True)
class WarmResult:
    account_id: str
    outcome: str
    reset: str | None = None
    error: str | None = None


def warm_account(account: Account) -> WarmResult:
    """Switch to `account` (if its agent switches), settle, and anchor its window."""
    agent = get_agent(account.agent)
    switcher = get_switcher(agent.switcher)

    if account.skip_if_warm and switcher:
        try:
            if _is_warm(switcher, account):
                log_attempt(account.id, SKIPPED, error="already-warm")
                return WarmResult(account.id, SKIPPED, error="already-warm")
        except CswapError as exc:
            # Can't tell if warm — fall through and warm it rather than skip blindly.
            log_attempt(account.id, "warn", error=f"skip-check-failed: {exc}")

    command = agent.command
    if account.model:
        command = (*command, "--model", account.model)

    try:
        if switcher:
            switcher.switch_to(account.id)
            if account.settle_seconds > 0:
                time.sleep(account.settle_seconds)
        _send(command, account.message)
    except _SEND_ERRORS as exc:
        result = WarmResult(account.id, FAILED, error=_summary(exc))
        log_attempt(account.id, FAILED, error=result.error)
        return result

    reset = _reset(switcher)
    log_attempt(account.id, OK, reset=reset)
    return WarmResult(account.id, OK, reset=reset)


def _send(command: tuple[str, ...], message: str) -> None:
    """Send one non-interactive warmup message via the agent's CLI."""
    proc = subprocess.run([*command, message], capture_output=True, text=True, timeout=_SEND_TIMEOUT)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"{command[0]} exited {proc.returncode}")


def _is_warm(switcher: ModuleType, account: Account) -> bool:
    """True if the account's usage window is already open (skip-if-warm, FR6)."""
    listed = next((a for a in switcher.list_accounts() if a.matches(account.id)), None)
    return bool(listed and listed.window_open)


def _reset(switcher: ModuleType | None) -> str | None:
    """Window reset time for the log line.

    A freshly-anchored window takes a few seconds to show up in `cswap --status`,
    so poll briefly rather than reading once and missing it.
    """
    if switcher is None:
        return None
    for attempt in range(4):
        try:
            active = switcher.status()
        except CswapError:
            return None
        if active and active.window_reset:
            return active.window_reset
        if attempt < 3:
            time.sleep(2)
    return None


def _summary(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:200] if text else exc.__class__.__name__
