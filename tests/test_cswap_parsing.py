"""Reader tests against the exact `cswap --json` payloads observed on the VM.

Keep these fixtures in sync with real output — they are the contract between
cwarm and cswap. `schemaVersion` guards the shape at runtime.
"""

import json

import pytest

from cwarm import cswap

STATUS_JSON = json.dumps(
    {
        "schemaVersion": 1,
        "active": {
            "number": 3,
            "email": "alice@example.com",
            "organizationName": "alice@example.com's Organization",
            "isOrganization": True,
            "managed": True,
            "usageStatus": "ok",
            "usage": {
                "fiveHour": {
                    "pct": 3.0,
                    "resetsAt": "2026-07-19T13:20:00.101181+00:00",
                    "countdown": "4h 19m",
                    "clock": "14:09",
                },
                "sevenDay": {
                    "pct": 31.0,
                    "resetsAt": "2026-07-21T00:00:00.101208+00:00",
                    "countdown": "1d 19h",
                    "clock": "Jun 23 05:29",
                },
                "scoped": [],
            },
        },
        "totalManagedAccounts": 3,
    }
)

LIST_JSON = json.dumps(
    {
        "schemaVersion": 1,
        "activeAccountNumber": 3,
        "accounts": [
            {
                "number": 1,
                "email": "bob@example.com",
                "active": False,
                "usageStatus": "ok",
                "usage": {
                    "fiveHour": {"pct": 22.0, "countdown": "2h 19m", "clock": "12:10"},
                    "sevenDay": {"pct": 32.0, "countdown": "1d 19h", "clock": "Jun 23 05:30"},
                    "scoped": [],
                },
            },
            {
                "number": 2,
                "email": "carol@example.com",
                "active": False,
                "usageStatus": "no_credentials",
                "usage": None,
            },
            {
                "number": 3,
                "email": "alice@example.com",
                "active": True,
                "usageStatus": "ok",
                "usage": {
                    "fiveHour": {"pct": 3.0, "countdown": "4h 19m", "clock": "14:09"},
                    "sevenDay": {"pct": 31.0, "countdown": "1d 19h", "clock": "Jun 23 05:29"},
                    "scoped": [],
                },
            },
            {
                # Credentials fine, but no window currently open.
                "number": 4,
                "email": "dave@example.com",
                "active": False,
                "usageStatus": "ok",
                "usage": {"fiveHour": None, "sevenDay": None, "scoped": []},
            },
        ],
    }
)


def _stub(monkeypatch, out):
    monkeypatch.setattr(cswap, "_run", lambda args: out)


def test_status_parse(monkeypatch):
    _stub(monkeypatch, STATUS_JSON)
    active = cswap.status()
    assert active is not None
    assert active.slot == "3"
    assert active.email == "alice@example.com"
    assert active.window_reset == "14:09"
    assert active.ref == "3"


def test_status_passes_json_flag(monkeypatch):
    seen: list[list[str]] = []

    def record(args):
        seen.append(args)
        return STATUS_JSON

    monkeypatch.setattr(cswap, "_run", record)
    cswap.status()
    assert seen == [["status", "--json"]]


def test_status_none_when_no_active_account(monkeypatch):
    _stub(monkeypatch, json.dumps({"schemaVersion": 1, "active": None}))
    assert cswap.status() is None


def test_list_parse(monkeypatch):
    _stub(monkeypatch, LIST_JSON)
    accounts = cswap.list_accounts()
    assert [a.slot for a in accounts] == ["1", "2", "3", "4"]

    a1, a2, a3, a4 = accounts
    assert a1.email == "bob@example.com"
    assert a1.window_open is True
    assert a1.active is False
    assert a1.credentials_ok

    # No credentials -> window state unknown (None), not skippable, and flagged.
    assert a2.window_open is None
    assert a2.cred_status == "no_credentials"
    assert not a2.credentials_ok

    assert a3.active is True
    assert a3.window_open is True

    # Usage readable but no open window -> cold (False), credentials still fine.
    assert a4.window_open is False
    assert a4.credentials_ok


def test_listed_account_matches_slot_and_email(monkeypatch):
    _stub(monkeypatch, LIST_JSON)
    a1 = cswap.list_accounts()[0]
    assert a1.matches("1")
    assert a1.matches("bob@example.com")
    assert a1.matches("BOB@EXAMPLE.COM")  # case-insensitive email
    assert not a1.matches("2")
    assert not a1.matches("other@x.com")


def test_unsupported_schema_version_raises(monkeypatch):
    _stub(monkeypatch, json.dumps({"schemaVersion": 2, "accounts": []}))
    with pytest.raises(cswap.CswapError, match="schemaVersion"):
        cswap.list_accounts()


def test_invalid_json_raises(monkeypatch):
    _stub(monkeypatch, "not json at all")
    with pytest.raises(cswap.CswapError, match="invalid JSON"):
        cswap.list_accounts()


def test_malformed_entries_are_skipped(monkeypatch):
    _stub(
        monkeypatch,
        json.dumps(
            {
                "schemaVersion": 1,
                "accounts": [
                    {"number": None, "email": "ghost@example.com"},
                    {"number": 7, "email": ""},
                    {"number": 8, "email": "real@example.com", "usageStatus": "ok"},
                ],
            }
        ),
    )
    accounts = cswap.list_accounts()
    assert [a.slot for a in accounts] == ["8"]
