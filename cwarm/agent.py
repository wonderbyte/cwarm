"""What makes one coding agent different from another — as plain data.

Sending a warmup is uniform across agents: a single non-interactive prompt
(`<cli> -p "Hi"`). The only agent-specific part is the **account switcher** that
decides which credentials are active. So agents are rows in a table, not classes:

    name      command            switcher
    claude    ("claude", "-p")   "cswap"     # claude-swap manages the accounts

Add a coding agent by adding a row. Only a *new* switcher (something other than
cswap) needs code — a sibling module to cswap.py, registered in `_SWITCHERS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from . import cswap

DEFAULT_AGENT = "claude"


@dataclass(frozen=True)
class Agent:
    name: str
    command: tuple[str, ...]  # warmup invocation; the message is appended
    switcher: str | None  # account-switcher backend, or None for no switching


_AGENTS: dict[str, Agent] = {
    "claude": Agent("claude", ("claude", "-p"), switcher="cswap"),
    # To add Codex once its non-interactive invocation is confirmed:
    #   "codex": Agent("codex", ("codex", "exec"), switcher=None),
    # switcher=None warms whichever account that CLI has active (no multi-account
    # switching). If Codex can swap accounts, add a cswap-style module and name it.
}

# Switcher backends, keyed by the name used in Agent.switcher.
_SWITCHERS: dict[str, ModuleType] = {"cswap": cswap}


def known_agents() -> list[str]:
    return list(_AGENTS)


def get_agent(name: str) -> Agent:
    try:
        return _AGENTS[name]
    except KeyError:
        raise ValueError(f"unknown agent {name!r}; known agents: {', '.join(_AGENTS)}") from None


def get_switcher(name: str | None) -> ModuleType | None:
    """The switcher module for an agent, or None when the agent does no switching."""
    return _SWITCHERS.get(name) if name else None
