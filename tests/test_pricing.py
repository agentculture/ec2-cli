"""Tests for ec2.aws.pricing — per-machine layered cost estimate (mocked pricing)."""

from __future__ import annotations

from ec2.aws.fleet import Instance
from ec2.aws.pricing import Estimate, estimate_cost

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _spot_instance() -> Instance:
    return Instance(
        id="i-0spot",
        type="t3.micro",
        state="running",
        name="spot-1",
        az="us-east-1a",
        lifecycle="spot",
    )


def _ondemand_instance() -> Instance:
    return Instance(
        id="i-0on",
        type="t3.micro",
        state="running",
        name="on-1",
        az="us-east-1a",
        lifecycle="on-demand",
    )


def _stopped_instance() -> Instance:
    return Instance(
        id="i-0stop",
        type="t3.micro",
        state="stopped",
        name="stopped-1",
        az="us-east-1a",
        lifecycle="on-demand",
    )


# ---------------------------------------------------------------------------
# Spot pricing
# ---------------------------------------------------------------------------


class TestSpotPricing:
    """A spot instance is priced at the spot rate, not on-demand."""

    def test_spot_instance_uses_spot_rate(self) -> None:
        inst = _spot_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=5.0,
        )
        # spot_rate * hours + ebs = 0.02 * 100 + 5.0 = 7.0
        assert est.figure == 7.0

    def test_spot_instance_does_not_use_ondemand_rate(self) -> None:
        inst = _spot_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.10,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=0.0,
        )
        # Must use spot_rate (0.02), NOT ondemand_rate (0.10)
        assert est.figure == 2.0


# ---------------------------------------------------------------------------
# On-demand pricing
# ---------------------------------------------------------------------------


class TestOndemandPricing:
    """An on-demand instance is priced at the on-demand rate."""

    def test_ondemand_instance_uses_ondemand_rate(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=5.0,
        )
        # ondemand_rate * hours + ebs = 0.05 * 100 + 5.0 = 10.0
        assert est.figure == 10.0


# ---------------------------------------------------------------------------
# Stopped instance — EBS still counted
# ---------------------------------------------------------------------------


class TestStoppedInstance:
    """EBS cost is counted even when the instance is stopped."""

    def test_stopped_instance_compute_is_zero_but_ebs_counts(self) -> None:
        inst = _stopped_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=5.0,
        )
        # stopped → compute = 0, but EBS = 5.0
        assert est.figure == 5.0

    def test_stopped_instance_no_ebs_is_zero(self) -> None:
        inst = _stopped_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=0.0,
        )
        assert est.figure == 0.0


# ---------------------------------------------------------------------------
# Estimate label and exclusions
# ---------------------------------------------------------------------------


class TestEstimateLabel:
    """Output labels the figure an estimate and names exclusions."""

    def test_estimate_labels_figure_as_estimate(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=5.0,
        )
        assert est.label == "ESTIMATE"

    def test_estimate_lists_exclusions(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=5.0,
        )
        assert "RI/Savings-Plan discounts" in est.exclusions
        assert "data transfer" in est.exclusions


# ---------------------------------------------------------------------------
# Fallback chain — missing rate/volume degrades, never raises
# ---------------------------------------------------------------------------


class TestFallbackChain:
    """A missing rate or volume lookup degrades via the fallback chain."""

    def test_missing_spot_rate_falls_back_to_ondemand(self) -> None:
        inst = _spot_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=None,
            running_hours=100,
            ebs_monthly=5.0,
        )
        # spot_rate missing → fall back to ondemand_rate
        assert est.figure == 10.0
        assert len(est.notes) > 0

    def test_missing_ondemand_rate_degrades(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=None,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=5.0,
        )
        # ondemand_rate missing → compute degrades to 0, note added
        assert est.figure == 5.0
        assert len(est.notes) > 0

    def test_both_rates_missing_degrades_to_ebs_only(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=None,
            spot_rate=None,
            running_hours=100,
            ebs_monthly=5.0,
        )
        # Both missing → compute = 0, EBS still counted
        assert est.figure == 5.0
        assert len(est.notes) > 0

    def test_missing_ebs_volume_degrades(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=0.05,
            spot_rate=0.02,
            running_hours=100,
            ebs_monthly=None,
        )
        # ebs_monthly missing → EBS = 0, note added
        assert est.figure == 5.0
        assert len(est.notes) > 0

    def test_all_missing_degrades_gracefully(self) -> None:
        inst = _ondemand_instance()
        est = estimate_cost(
            inst,
            ondemand_rate=None,
            spot_rate=None,
            running_hours=100,
            ebs_monthly=None,
        )
        assert est.figure == 0.0
        assert len(est.notes) > 0


# ---------------------------------------------------------------------------
# Estimate dataclass shape
# ---------------------------------------------------------------------------


class TestEstimateDataclass:
    """Estimate dataclass has the expected fields."""

    def test_estimate_default_exclusions(self) -> None:
        est = Estimate(figure=1.0)
        assert est.label == "ESTIMATE"
        assert est.exclusions == ["RI/Savings-Plan discounts", "data transfer"]
        assert est.notes == []
