"""Parser tests against the exact `cswap` output formats observed on the VM."""

from cwarm import cswap

STATUS_OUT = """Status: Account-3 (alice@example.com [alice@example.com's Organization])
  Total managed accounts: 3
  ├ 5h:   3%   resets 14:09         in 4h 19m
  └ 7d:  31%   resets Jun 23 05:29  in 1d 19h
"""

LIST_OUT = """Accounts:
  1: bob@example.com [bob@example.com's Organization]
     ├ 5h:  22%   resets 12:10         in 2h 19m
     └ 7d:  32%   resets Jun 23 05:30  in 1d 19h

  2: carol@example.com [carol@example.com's Organization]
     usage unavailable

  3: alice@example.com [alice@example.com's Organization] (active)
     ├ 5h:   3%   resets 14:09         in 4h 19m
     └ 7d:  31%   resets Jun 23 05:29  in 1d 19h

Running instances:
  ● CLI   ~  (1 session)
"""


def test_status_parse(monkeypatch):
    monkeypatch.setattr(cswap, "_run", lambda args: STATUS_OUT)
    active = cswap.status()
    assert active is not None
    assert active.slot == "3"
    assert active.email == "alice@example.com"
    assert active.window_reset == "14:09"
    assert active.ref == "3"


def test_status_none_when_unparseable(monkeypatch):
    monkeypatch.setattr(cswap, "_run", lambda args: "No active account\n")
    assert cswap.status() is None


def test_list_parse(monkeypatch):
    monkeypatch.setattr(cswap, "_run", lambda args: LIST_OUT)
    accounts = cswap.list_accounts()
    assert [a.slot for a in accounts] == ["1", "2", "3"]

    a1, a2, a3 = accounts
    assert a1.email == "bob@example.com"
    assert a1.window_open is True
    assert a1.active is False

    # "usage unavailable" -> window state unknown (None), not skippable.
    assert a2.window_open is None

    assert a3.active is True
    assert a3.window_open is True


def test_listed_account_matches_slot_and_email(monkeypatch):
    monkeypatch.setattr(cswap, "_run", lambda args: LIST_OUT)
    a1 = cswap.list_accounts()[0]
    assert a1.matches("1")
    assert a1.matches("bob@example.com")
    assert a1.matches("BOB@EXAMPLE.COM")  # case-insensitive email
    assert not a1.matches("2")
    assert not a1.matches("other@x.com")
