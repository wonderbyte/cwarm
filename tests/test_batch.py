"""Batch save/restore and per-account outcome semantics (AC3, AC4, AC6, AC7)."""

import json

import pytest

from cwarm import cswap, warmup as warmup_mod
from cwarm.config import load_config
from cwarm.schedule import run_batch

SAVED = cswap.ActiveAccount(slot="9", email="saved@x.com", window_reset="10:00")


@pytest.fixture
def cfg(tmp_path):
    data = {
        "defaults": {"settle_seconds": 0},
        "accounts": [
            {"id": "a@x.com", "schedule": "0 5 * * *"},
            {"id": "2", "schedule": "0 7 * * *"},
            {"id": "warm@x.com", "schedule": "0 9 * * *", "skip_if_warm": True},
        ],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return load_config(p)


@pytest.fixture
def harness(monkeypatch):
    """Record cswap.switch_to calls and stub status/send to avoid real I/O."""
    switches: list[str] = []
    monkeypatch.setattr(cswap, "switch_to", lambda account_id: switches.append(account_id))
    monkeypatch.setattr(cswap, "status", lambda: SAVED)
    monkeypatch.setattr(warmup_mod, "_send", lambda command, message: None)
    return switches


def test_batch_restores_saved_account(cfg, harness):
    """AC4: after the batch, the saved account is switched back to — last of all."""
    results = run_batch(cfg, ["a@x.com", "2"])
    assert [r.outcome for r in results] == ["ok", "ok"]
    assert results[0].reset == "10:00"  # window reset read from status
    assert harness[-1] == SAVED.ref == "9"
    assert harness == ["a@x.com", "2", "9"]


def test_failed_warmup_does_not_stop_others_or_skip_restore(cfg, harness, monkeypatch):
    """AC6: one failure logs failed, the rest run, restore still happens."""
    def send(command, message):
        if send.call == 0:  # first account fails
            send.call += 1
            raise RuntimeError("boom")
        send.call += 1
    send.call = 0
    monkeypatch.setattr(warmup_mod, "_send", send)

    results = run_batch(cfg, ["a@x.com", "2"])
    assert results[0].outcome == "failed"
    assert "boom" in results[0].error
    assert results[1].outcome == "ok"
    assert harness[-1] == "9"  # restore still ran


def test_skip_if_warm(cfg, harness, monkeypatch):
    """AC7: an account already inside its usage window is skipped, not switched to."""
    listed = [
        cswap.ListedAccount(
            slot="5", email="warm@x.com", active=False, window_open=True, cred_status="ok"
        )
    ]
    monkeypatch.setattr(cswap, "list_accounts", lambda: listed)

    results = run_batch(cfg, ["warm@x.com"])
    assert results[0].outcome == "skipped"
    assert "warm@x.com" not in harness
    assert harness == ["9"]  # only the restore happened


def test_warmup_appends_default_model(cfg, harness, monkeypatch):
    """The warmup command carries --model haiku by default."""
    captured: list[tuple] = []
    monkeypatch.setattr(warmup_mod, "_send", lambda command, message: captured.append(command))
    run_batch(cfg, ["a@x.com"])
    assert captured == [("claude", "-p", "--model", "haiku")]


def test_run_single_account(cfg, harness):
    """AC3: warming one account switches to it, sends, logs ok with reset."""
    results = run_batch(cfg, ["a@x.com"])
    assert len(results) == 1
    assert results[0].outcome == "ok"
    assert results[0].reset == "10:00"
    assert harness == ["a@x.com", "9"]


def test_disabled_account_skipped_in_select(tmp_path, harness):
    """AC1: disabled accounts are skipped in a full-batch run."""
    data = {
        "defaults": {"settle_seconds": 0},
        "accounts": [
            {"id": "on@x.com", "schedule": "0 5 * * *"},
            {"id": "off@x.com", "schedule": "0 6 * * *", "enabled": False},
        ],
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data))
    cfg = load_config(p)
    results = run_batch(cfg)  # all enabled
    assert [r.account_id for r in results] == ["on@x.com"]
    assert "off@x.com" not in harness
