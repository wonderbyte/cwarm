"""Config loading, defaults merging, and validation (§7)."""

import json

import pytest

from cwarm.config import ConfigError, load_config

VALID = {
    "defaults": {"message": "Yo", "timezone": "Asia/Kolkata", "settle_seconds": 5, "skip_if_warm": True},
    "accounts": [
        {"id": "work@example.com", "enabled": True, "schedule": "0 5 * * 1-5"},
        {"id": "2", "schedule": "30 7 * * 1-5", "message": "Hi"},
        {"id": "4", "enabled": False, "schedule": "30 12 * * *"},
    ],
}


def _write(tmp_path, data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data))
    return p


def test_loads_and_merges_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert len(cfg.accounts) == 3
    assert len(cfg.enabled_accounts()) == 2  # account 4 disabled

    a0, a1, _ = cfg.accounts
    assert a0.message == "Yo"
    assert a0.settle_seconds == 5
    assert a0.skip_if_warm is True
    assert a0.agent == "claude"  # default agent
    assert a1.message == "Hi"
    assert a1.timezone == "Asia/Kolkata"
    assert a1.enabled is True  # default


def test_single_schedule_normalised_to_tuple(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.accounts[0].schedules == ("0 5 * * 1-5",)


def test_multiple_schedules(tmp_path):
    data = {"accounts": [
        {"id": "x", "schedules": ["0 5 * * *", "0 11 * * *", "0 21 * * *"]},
    ]}
    cfg = load_config(_write(tmp_path, data))
    assert cfg.accounts[0].schedules == ("0 5 * * *", "0 11 * * *", "0 21 * * *")


def test_schedule_and_schedules_merge_and_dedup(tmp_path):
    data = {"accounts": [
        {"id": "x", "schedule": "0 5 * * *", "schedules": ["0 5 * * *", "0 21 * * *"]},
    ]}
    cfg = load_config(_write(tmp_path, data))
    assert cfg.accounts[0].schedules == ("0 5 * * *", "0 21 * * *")


def test_per_account_agent_override(tmp_path):
    data = {"accounts": [{"id": "x", "schedule": "0 5 * * *", "agent": "claude"}]}
    cfg = load_config(_write(tmp_path, data))
    assert cfg.accounts[0].agent == "claude"


def test_unknown_agent_rejected(tmp_path):
    data = {"accounts": [{"id": "x", "schedule": "0 5 * * *", "agent": "gpt9000"}]}
    with pytest.raises(ConfigError, match="agent"):
        load_config(_write(tmp_path, data))


def test_find(tmp_path):
    cfg = load_config(_write(tmp_path, VALID))
    assert cfg.find("2").id == "2"
    assert cfg.find("nope") is None


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.json")


def test_bad_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{ not json")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(p)


def test_empty_accounts(tmp_path):
    with pytest.raises(ConfigError, match="non-empty array"):
        load_config(_write(tmp_path, {"accounts": []}))


def test_duplicate_id(tmp_path):
    data = {"accounts": [
        {"id": "x", "schedule": "0 5 * * *"},
        {"id": "x", "schedule": "0 6 * * *"},
    ]}
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(_write(tmp_path, data))


def test_bad_cron(tmp_path):
    data = {"accounts": [{"id": "x", "schedule": "0 5 * *"}]}
    with pytest.raises(ConfigError, match="5-field cron"):
        load_config(_write(tmp_path, data))


def test_empty_schedules_array(tmp_path):
    data = {"accounts": [{"id": "x", "schedules": []}]}
    with pytest.raises(ConfigError, match="non-empty array"):
        load_config(_write(tmp_path, data))


def test_bad_cron_in_schedules_array(tmp_path):
    data = {"accounts": [{"id": "x", "schedules": ["0 5 * * *", "0 11 * *"]}]}
    with pytest.raises(ConfigError, match="5-field cron"):
        load_config(_write(tmp_path, data))


def test_bad_timezone(tmp_path):
    data = {"accounts": [{"id": "x", "schedule": "0 5 * * *", "timezone": "Mars/Phobos"}]}
    with pytest.raises(ConfigError, match="unknown timezone"):
        load_config(_write(tmp_path, data))


def test_missing_schedule(tmp_path):
    data = {"accounts": [{"id": "x"}]}
    with pytest.raises(ConfigError, match="schedule"):
        load_config(_write(tmp_path, data))


def test_negative_settle(tmp_path):
    data = {"defaults": {"settle_seconds": -1}, "accounts": [{"id": "x", "schedule": "0 5 * * *"}]}
    with pytest.raises(ConfigError, match="settle_seconds"):
        load_config(_write(tmp_path, data))
