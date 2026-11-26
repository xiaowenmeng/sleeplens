"""Offline coverage for disabling the lifetime cap without resetting its ledger."""

import sqlite3

import pytest

from sleeplens.config import ConfigError, load_settings
from sleeplens.request_budget import BudgetError, RequestBudget


def test_unlimited_budget_accepts_requests_after_historical_cap(tmp_path):
    path = tmp_path / "usage.sqlite3"
    budget = RequestBudget(path, request_limit=0)
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO requests VALUES (?, 1, 2, 0, 'completed')",
                       [(f"old-{i}",) for i in range(260)])

    reservation = budget.reserve()
    assert budget.finish(reservation, "completed")
    reopened = RequestBudget(path, request_limit=0)
    assert reopened.status() == {
        "reserved_requests": 261, "active_requests": 0, "request_limit": 0,
        "remaining_requests": None, "max_concurrent": 2,
    }
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM requests WHERE id LIKE 'old-%'").fetchone()[0] == 260


def test_unlimited_budget_still_enforces_shared_concurrency(tmp_path):
    path = tmp_path / "usage.sqlite3"
    first = RequestBudget(path, request_limit=0, max_concurrent=1)
    second = RequestBudget(path, request_limit=0, max_concurrent=1)
    reservation = first.reserve()
    with pytest.raises(BudgetError, match="concurrency"):
        second.reserve()
    assert first.finish(reservation, "error")
    next_reservation = second.reserve()
    assert second.finish(next_reservation, "completed")
    assert first.status()["reserved_requests"] == 2


def test_finite_cap_still_counts_finished_requests(tmp_path):
    path = tmp_path / "usage.sqlite3"
    budget = RequestBudget(path, request_limit=1)
    assert budget.finish(budget.reserve(), "error")
    with pytest.raises(BudgetError, match="request limit"):
        RequestBudget(path, request_limit=1).reserve()
    assert budget.status()["remaining_requests"] == 0


@pytest.mark.parametrize("limit", [0, 260])
def test_settings_accept_unlimited_and_finite_cap(monkeypatch, tmp_path, limit):
    monkeypatch.setenv("SLEEPLENS_REQUEST_LIMIT", str(limit))
    monkeypatch.setenv("SLEEPLENS_BUDGET_DB", ".state/usage.sqlite3")
    settings = load_settings(tmp_path / ".env")
    assert settings.request_limit == limit


def test_settings_reject_negative_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("SLEEPLENS_REQUEST_LIMIT", "-1")
    with pytest.raises(ConfigError):
        load_settings(tmp_path / ".env")


@pytest.mark.parametrize("limit", [-1, True, None])
def test_budget_rejects_invalid_cap(tmp_path, limit):
    with pytest.raises(ValueError):
        RequestBudget(tmp_path / "usage.sqlite3", request_limit=limit)
