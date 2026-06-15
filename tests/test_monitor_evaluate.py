"""Tests for ec2.monitor.evaluate — monitor evaluator + check logic (pure function).

Acceptance criteria:
1. evaluate compares per-machine + total vs limits and returns findings with a
   breach flag; findings serialise to parseable JSON.
2. With auto-stop disabled (default) a breach yields a finding but
   auto_stop_applies is False for every finding (evaluator issues ZERO
   StopInstances calls — it has no AWS client at all); auto_stop_applies is
   True only when the limit set auto_stop=True.
3. Spike via run-rate projection: a projected end-of-period spend exceeding
   the limit raises a finding (mocked spend fixture), even when current < limit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ec2.limits import Limit
from ec2.monitor.evaluate import evaluate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now() -> datetime:
    """Fixed reference time: day 10 of a 30-day month."""
    return datetime(2025, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def period_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Period covers 2025-06-01 .. 2025-07-01 (30 days)."""
    start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    return (start, end)


# ---------------------------------------------------------------------------
# Acceptance 1: breach detection + JSON serialisation
# ---------------------------------------------------------------------------


class TestBreachDetection:
    """evaluate compares per-machine + total vs limits and returns findings."""

    def test_per_machine_breach(self, now: datetime, period_bounds: tuple) -> None:
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 150.0}
        total_spend = 150.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        f = findings[0]
        assert f.target == "i-0abc"
        assert f.current == 150.0
        assert f.limit == 100.0
        assert f.breach is True
        assert f.reason == "breach"

    def test_total_breach(self, now: datetime, period_bounds: tuple) -> None:
        limits = [Limit(target="total", amount=500.0, period="monthly")]
        per_machine_spend = {"i-0abc": 300.0, "i-0def": 250.0}
        total_spend = 550.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        f = findings[0]
        assert f.target == "total"
        assert f.current == 550.0
        assert f.limit == 500.0
        assert f.breach is True

    def test_no_breach_returns_empty(self, now: datetime, period_bounds: tuple) -> None:
        limits = [Limit(target="i-0abc", amount=200.0, period="monthly")]
        per_machine_spend = {"i-0abc": 50.0}
        total_spend = 50.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert findings == []

    def test_findings_serialise_to_json(self, now: datetime, period_bounds: tuple) -> None:
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 150.0}
        total_spend = 150.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        payload = [f.to_dict() for f in findings]
        raw = json.dumps(payload)
        parsed = json.loads(raw)
        assert len(parsed) == 1
        assert parsed[0]["target"] == "i-0abc"
        assert parsed[0]["breach"] is True
        assert parsed[0]["auto_stop_applies"] is False


# ---------------------------------------------------------------------------
# Acceptance 2: auto_stop_applies flag
# ---------------------------------------------------------------------------


class TestAutoStopApplies:
    """auto_stop_applies is True only when the limit has auto_stop=True."""

    def test_default_auto_stop_false_on_breach(self, now: datetime, period_bounds: tuple) -> None:
        """Default (auto_stop=False) breach → auto_stop_applies is False."""
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 150.0}
        total_spend = 150.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        assert findings[0].auto_stop_applies is False

    def test_auto_stop_true_on_breach(self, now: datetime, period_bounds: tuple) -> None:
        """Limit with auto_stop=True and breach → auto_stop_applies is True."""
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly", auto_stop=True)]
        per_machine_spend = {"i-0abc": 150.0}
        total_spend = 150.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        assert findings[0].auto_stop_applies is True

    def test_auto_stop_false_on_projected_spike(self, now: datetime, period_bounds: tuple) -> None:
        """Projected spike (not a hard breach) → auto_stop_applies is False
        even if auto_stop=True on the limit."""
        # 10 days elapsed of 30; current=60; projected = 60 / (10/30) = 180 > 100
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly", auto_stop=True)]
        per_machine_spend = {"i-0abc": 60.0}
        total_spend = 60.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        assert findings[0].breach is False
        assert findings[0].auto_stop_applies is False
        assert findings[0].reason == "projected"

    def test_evaluator_has_no_aws_client(self) -> None:
        """The evaluate function signature takes no AWS client parameter."""
        import inspect

        sig = inspect.signature(evaluate)
        params = list(sig.parameters.keys())
        assert "client" not in params
        assert "boto3" not in str(sig)


# ---------------------------------------------------------------------------
# Acceptance 3: spike via run-rate projection
# ---------------------------------------------------------------------------


class TestSpikeProjection:
    """Projected end-of-period spend exceeding the limit raises a finding."""

    def test_projected_exceeds_limit(self, now: datetime, period_bounds: tuple) -> None:
        """Current=60 at day 10 of 30 → projected=180 > 100 limit."""
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 60.0}
        total_spend = 60.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        f = findings[0]
        assert f.target == "i-0abc"
        assert f.breach is False
        assert f.reason == "projected"
        assert f.auto_stop_applies is False

    def test_projected_below_limit_no_finding(self, now: datetime, period_bounds: tuple) -> None:
        """Current=20 at day 10 of 30 → projected=60 < 100 limit → no finding."""
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 20.0}
        total_spend = 20.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert findings == []

    def test_projected_total_spend(self, now: datetime, period_bounds: tuple) -> None:
        """Total spend projected spike."""
        limits = [Limit(target="total", amount=500.0, period="monthly")]
        per_machine_spend = {"i-0abc": 300.0}
        total_spend = 300.0  # projected = 300 / (10/30) = 900 > 500

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        f = findings[0]
        assert f.target == "total"
        assert f.breach is False
        assert f.reason == "projected"

    def test_breach_takes_precedence_over_projection(
        self, now: datetime, period_bounds: tuple
    ) -> None:
        """When current >= limit, report breach (not projected)."""
        limits = [Limit(target="i-0abc", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 150.0}
        total_spend = 150.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 1
        assert findings[0].breach is True
        assert findings[0].reason == "breach"

    def test_multiple_limits_multiple_findings(self, now: datetime, period_bounds: tuple) -> None:
        """Multiple limits can each produce findings independently."""
        limits = [
            Limit(target="i-0abc", amount=50.0, period="monthly"),
            Limit(target="total", amount=100.0, period="monthly"),
        ]
        per_machine_spend = {"i-0abc": 60.0}  # breach on per-machine
        total_spend = 60.0  # projected = 180 > 100

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert len(findings) == 2
        targets = {f.target for f in findings}
        assert targets == {"i-0abc", "total"}

    def test_unknown_target_ignored(self, now: datetime, period_bounds: tuple) -> None:
        """A limit targeting an instance not in per_machine_spend is ignored."""
        limits = [Limit(target="i-0unknown", amount=100.0, period="monthly")]
        per_machine_spend = {"i-0abc": 50.0}
        total_spend = 50.0

        findings = evaluate(
            limits=limits,
            per_machine_spend=per_machine_spend,
            total_spend=total_spend,
            now=now,
            period_bounds=period_bounds,
        )

        assert findings == []
