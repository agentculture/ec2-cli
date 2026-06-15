"""Tests for ec2.limits — spend-limit config store (stdlib only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ec2.limits import Limit, load_limits, save_limit


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Return a temporary directory to act as the config home."""
    return tmp_path / "config"


@pytest.fixture
def limits_file(config_dir: Path) -> Path:
    """Return the expected limits.json path inside the config dir."""
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "ec2-cli" / "limits.json"


class TestSaveLoadRoundTrip:
    """Acceptance 1: save/load round-trip yields identical data."""

    def test_round_trip_single_limit(self, config_dir: Path, limits_file: Path) -> None:
        limit = Limit(target="i-0abc123", amount=100.0, period="monthly", auto_stop=True)
        save_limit(limit, config_dir=config_dir)
        loaded = load_limits(config_dir=config_dir)
        assert len(loaded) == 1
        assert loaded[0].target == limit.target
        assert loaded[0].amount == limit.amount
        assert loaded[0].period == limit.period
        assert loaded[0].auto_stop == limit.auto_stop

    def test_round_trip_total_limit(self, config_dir: Path, limits_file: Path) -> None:
        limit = Limit(target="total", amount=5000.0, period="yearly")
        save_limit(limit, config_dir=config_dir)
        loaded = load_limits(config_dir=config_dir)
        assert len(loaded) == 1
        assert loaded[0].target == "total"
        assert loaded[0].amount == 5000.0
        assert loaded[0].period == "yearly"
        assert loaded[0].auto_stop is False

    def test_reload_in_fresh_call(self, config_dir: Path, limits_file: Path) -> None:
        """Reloading in a fresh call yields identical data."""
        limit = Limit(target="i-0def456", amount=250.5, period="monthly")
        save_limit(limit, config_dir=config_dir)

        # Simulate a fresh process: load twice
        first = load_limits(config_dir=config_dir)
        second = load_limits(config_dir=config_dir)
        assert first == second

    def test_multiple_limits_appended(self, config_dir: Path, limits_file: Path) -> None:
        l1 = Limit(target="i-001", amount=100.0, period="monthly")
        l2 = Limit(target="total", amount=1000.0, period="yearly", auto_stop=True)
        save_limit(l1, config_dir=config_dir)
        save_limit(l2, config_dir=config_dir)
        loaded = load_limits(config_dir=config_dir)
        assert len(loaded) == 2
        assert loaded[0].target == "i-001"
        assert loaded[1].target == "total"


class TestMissingConfig:
    """Acceptance 2: missing config file yields empty list."""

    def test_missing_file_returns_empty(self, config_dir: Path) -> None:
        """When no limits file exists, load_limits returns []."""
        loaded = load_limits(config_dir=config_dir)
        assert loaded == []

    def test_missing_config_dir_returns_empty(self, tmp_path: Path) -> None:
        """When the config dir itself is absent, load_limits returns []."""
        nonexistent = tmp_path / "does_not_exist"
        loaded = load_limits(config_dir=nonexistent)
        assert loaded == []


class TestMalformedConfig:
    """Acceptance 2: malformed config yields empty list, never a traceback."""

    def test_garbage_json_returns_empty(self, config_dir: Path, limits_file: Path) -> None:
        """A file with garbage JSON is treated as empty."""
        limits_file.parent.mkdir(parents=True, exist_ok=True)
        limits_file.write_text("not json at all {{{", encoding="utf-8")
        loaded = load_limits(config_dir=config_dir)
        assert loaded == []

    def test_partial_limit_ignored(self, config_dir: Path, limits_file: Path) -> None:
        """A limit dict missing required fields is silently skipped."""
        limits_file.parent.mkdir(parents=True, exist_ok=True)
        data = [{"target": "i-001"}, {"target": "total", "amount": 500.0, "period": "monthly"}]
        limits_file.write_text(json.dumps(data), encoding="utf-8")
        loaded = load_limits(config_dir=config_dir)
        assert len(loaded) == 1
        assert loaded[0].target == "total"

    def test_empty_file_returns_empty(self, config_dir: Path, limits_file: Path) -> None:
        """An empty file returns []."""
        limits_file.parent.mkdir(parents=True, exist_ok=True)
        limits_file.write_text("", encoding="utf-8")
        loaded = load_limits(config_dir=config_dir)
        assert loaded == []


class TestLookup:
    """Test lookup_limit_by_target."""

    def test_lookup_found(self, config_dir: Path) -> None:
        from ec2.limits import lookup_limit_by_target

        save_limit(Limit(target="i-0abc", amount=100.0, period="monthly"), config_dir=config_dir)
        result = lookup_limit_by_target("i-0abc", config_dir=config_dir)
        assert result is not None
        assert result.target == "i-0abc"

    def test_lookup_not_found(self, config_dir: Path) -> None:
        from ec2.limits import lookup_limit_by_target

        result = lookup_limit_by_target("i-0nonexistent", config_dir=config_dir)
        assert result is None

    def test_lookup_total(self, config_dir: Path) -> None:
        from ec2.limits import lookup_limit_by_target

        save_limit(Limit(target="total", amount=5000.0, period="yearly"), config_dir=config_dir)
        result = lookup_limit_by_target("total", config_dir=config_dir)
        assert result is not None
        assert result.target == "total"
        assert result.amount == 5000.0


class TestLimitDataclass:
    """Basic dataclass shape checks."""

    def test_defaults(self) -> None:
        limit = Limit(target="i-001", amount=10.0, period="monthly")
        assert limit.auto_stop is False

    def test_explicit_auto_stop(self) -> None:
        limit = Limit(target="total", amount=100.0, period="yearly", auto_stop=True)
        assert limit.auto_stop is True


class TestSaveIdempotentPerTarget:
    """Re-saving a target updates it in place (no duplicate accumulation)."""

    def test_resaving_same_target_replaces(self, config_dir: Path) -> None:
        save_limit(Limit(target="i-0abc123", amount=100.0, period="monthly"), config_dir=config_dir)
        save_limit(Limit(target="i-0abc123", amount=50.0, period="monthly"), config_dir=config_dir)
        loaded = load_limits(config_dir=config_dir)
        same_target = [limit_ for limit_ in loaded if limit_.target == "i-0abc123"]
        assert len(same_target) == 1
        assert same_target[0].amount == 50.0

    def test_distinct_targets_coexist(self, config_dir: Path) -> None:
        save_limit(Limit(target="i-0abc123", amount=100.0, period="monthly"), config_dir=config_dir)
        save_limit(Limit(target="total", amount=5000.0, period="yearly"), config_dir=config_dir)
        loaded = load_limits(config_dir=config_dir)
        assert {limit_.target for limit_ in loaded} == {"i-0abc123", "total"}
