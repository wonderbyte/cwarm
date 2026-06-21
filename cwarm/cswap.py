"""The one account-switcher backend: claude-swap (`cswap`).

It switches Claude Code credentials and reports per-account usage-window state —
the only genuinely agent-specific machinery in cwarm. A different coding agent
that can swap accounts would get a sibling module exposing the same surface
(`status` / `list_accounts` / `switch_to`), referenced from `agent.py`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

CSWAP = "cswap"

# `Status: Account-3 (email@x [Org])`
_STATUS_RE = re.compile(r"^Status:\s+Account-(\d+)\s+\(([^\s\[\]()]+)")
# A listed account header: `  3: email@x [Org] (active)`
_LIST_HEAD_RE = re.compile(r"^\s*(\d+):\s+(\S+)\s+\[.*?\](?P<active>\s+\(active\))?\s*$")
# A 5h usage line with a reset time: `├ 5h:   3%   resets 14:09   in 4h 19m`
_FIVE_H_RE = re.compile(r"5h:\s*\d+%\s*resets\s+(\d{1,2}:\d{2})")


class CswapError(RuntimeError):
    """A cswap invocation failed."""


@dataclass(frozen=True)
class ActiveAccount:
    slot: str
    email: str
    window_reset: str | None  # HH:MM if a window is open, else None

    @property
    def ref(self) -> str:
        """The id to pass back to switch_to (slot is the most stable handle)."""
        return self.slot


@dataclass(frozen=True)
class ListedAccount:
    slot: str
    email: str
    active: bool
    window_open: bool | None  # True=warm, False=closed, None=usage unavailable

    def matches(self, account_id: str) -> bool:
        return account_id == self.slot or account_id.lower() == self.email.lower()


def is_installed() -> bool:
    return shutil.which(CSWAP) is not None


def status() -> ActiveAccount | None:
    """Currently-active account, or None if none could be determined."""
    out = _run(["--status"])
    slot = email = reset = None
    for line in out.splitlines():
        m = _STATUS_RE.match(line)
        if m:
            slot, email = m.group(1), m.group(2)
            continue
        if reset is None:
            fm = _FIVE_H_RE.search(line)
            if fm:
                reset = fm.group(1)
    if slot is None or email is None:
        return None
    return ActiveAccount(slot=slot, email=email, window_reset=reset)


def list_accounts() -> list[ListedAccount]:
    """All managed accounts with their usage-window state."""
    out = _run(["--list"])
    accounts: list[ListedAccount] = []
    current: dict | None = None

    def flush() -> None:
        if current is not None:
            accounts.append(ListedAccount(**current))

    for line in out.splitlines():
        head = _LIST_HEAD_RE.match(line)
        if head:
            flush()
            current = {
                "slot": head.group(1),
                "email": head.group(2),
                "active": head.group("active") is not None,
                "window_open": None,
            }
            continue
        if current is None:
            continue
        if "Running instances" in line:
            break
        if _FIVE_H_RE.search(line):
            current["window_open"] = True
        elif "usage unavailable" in line.lower():
            current["window_open"] = None
    flush()
    return accounts


def switch_to(account_id: str) -> None:
    """Make `account_id` (slot number or email) the active account."""
    _run(["--switch-to", account_id])


def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run([CSWAP, *args], capture_output=True, text=True, timeout=60)
    except FileNotFoundError as exc:
        raise CswapError(f"{CSWAP} is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise CswapError(f"cswap {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise CswapError(f"cswap {' '.join(args)} exited {proc.returncode}: {detail}")
    return proc.stdout
