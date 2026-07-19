"""The one account-switcher backend: claude-swap (`cswap`).

It switches Claude Code credentials and reports per-account usage-window state —
the only genuinely agent-specific machinery in cwarm. A different coding agent
that can swap accounts would get a sibling module exposing the same surface
(`status` / `list_accounts` / `switch_to`), referenced from `agent.py`.

State comes from `cswap --json` (`schemaVersion` 1), not from parsing the
human-readable output. The JSON also carries `usageStatus`, which is how we
tell "this account has no usable credentials" apart from "usage lookup failed".
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

CSWAP = "cswap"

# The `--json` payload we know how to read. cswap bumps this if the shape changes.
SCHEMA_VERSION = 1

# usageStatus values that mean the stored credentials are gone or unusable —
# the account cannot be warmed until it is re-authenticated.
_BROKEN_CRED_STATUSES = frozenset({"no_credentials", "expired", "unauthorized"})


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
    cred_status: str  # cswap's usageStatus verbatim ("ok", "no_credentials", ...)

    def matches(self, account_id: str) -> bool:
        return account_id == self.slot or account_id.lower() == self.email.lower()

    @property
    def credentials_ok(self) -> bool:
        """False when cswap reports the stored credentials as missing or expired."""
        return self.cred_status not in _BROKEN_CRED_STATUSES


def is_installed() -> bool:
    return shutil.which(CSWAP) is not None


def status() -> ActiveAccount | None:
    """Currently-active account, or None if none could be determined."""
    payload = _run_json(["status"])
    active = payload.get("active")
    if not isinstance(active, dict):
        return None
    slot, email = _identity(active)
    if slot is None or email is None:
        return None
    return ActiveAccount(slot=slot, email=email, window_reset=_window_reset(active))


def list_accounts() -> list[ListedAccount]:
    """All managed accounts with their usage-window and credential state."""
    payload = _run_json(["list"])
    accounts: list[ListedAccount] = []
    for entry in payload.get("accounts") or []:
        if not isinstance(entry, dict):
            continue
        slot, email = _identity(entry)
        if slot is None or email is None:
            continue
        accounts.append(
            ListedAccount(
                slot=slot,
                email=email,
                active=bool(entry.get("active")),
                window_open=_window_open(entry),
                cred_status=str(entry.get("usageStatus") or "unknown"),
            )
        )
    return accounts


def switch_to(account_id: str, *, backup: bool = True) -> None:
    """Make `account_id` (slot number or email) the active account.

    A plain switch backs the *outgoing* live credentials up into that account's
    stored snapshot first. That is what you want after a healthy session (Claude
    Code may have rotated the token, and the snapshot must keep up), but it is
    destructive after a failed one: it writes the broken live credentials over
    the last good snapshot. `backup=False` uses cswap's `--force`, which
    activates the target without backing up the current login.
    """
    args = ["switch", account_id]
    if not backup:
        args.append("--force")
    _run(args)


def _identity(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """(slot, email) from an account object, or (None, None) if either is missing."""
    number, email = entry.get("number"), entry.get("email")
    if number is None or not email:
        return None, None
    return str(number), str(email)


def _five_hour(entry: dict[str, Any]) -> dict[str, Any] | None:
    usage = entry.get("usage")
    if not isinstance(usage, dict):
        return None
    five_hour = usage.get("fiveHour")
    return five_hour if isinstance(five_hour, dict) else None


def _window_reset(entry: dict[str, Any]) -> str | None:
    """The 5h window's local reset clock (HH:MM), or None if no window is open."""
    five_hour = _five_hour(entry)
    if not five_hour:
        return None
    clock = five_hour.get("clock")
    return str(clock) if clock else None


def _window_open(entry: dict[str, Any]) -> bool | None:
    """True=window open, False=closed, None=usage unavailable (don't skip blindly)."""
    if not isinstance(entry.get("usage"), dict):
        return None
    return bool(_window_reset(entry))


def _run_json(args: list[str]) -> dict[str, Any]:
    """Run a cswap subcommand with --json and return the decoded payload."""
    out = _run([*args, "--json"])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise CswapError(f"cswap {' '.join(args)} --json returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CswapError(f"cswap {' '.join(args)} --json did not return an object")
    version = payload.get("schemaVersion")
    if version != SCHEMA_VERSION:
        raise CswapError(
            f"cswap --json schemaVersion {version!r} is unsupported "
            f"(cwarm expects {SCHEMA_VERSION}); upgrade cwarm or pin cswap"
        )
    return payload


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
