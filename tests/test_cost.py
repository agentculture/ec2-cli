"""Tests for ec2.aws.cost — Cost Explorer spend and forecast (mocked CE client)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Import the date helpers from the module under test (single source of truth)
# so the assertions validate production's date logic instead of duplicating it.
from ec2.aws.cost import (
    EC2_FILTER,
    _end_of_month,
    _end_of_year,
    _first_of_month,
    _first_of_year,
    _today,
    _tomorrow,
    cost_mtd,
    cost_ytd,
    forecast_month,
    forecast_unavailable,
    forecast_year,
)
from ec2.cli._errors import CliError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# EC2 filter shape
# ---------------------------------------------------------------------------


class TestEc2Filter:
    def test_filter_shape(self) -> None:
        assert EC2_FILTER == {
            "Dimensions": {
                "Key": "SERVICE",
                "Values": ["Amazon Elastic Compute Cloud - Compute"],
            }
        }


# ---------------------------------------------------------------------------
# cost_mtd / cost_ytd
# ---------------------------------------------------------------------------


class TestCostMtd:
    def test_calls_get_cost_and_usage(self) -> None:
        client = _mock_client()
        client.get_cost_and_usage.return_value = {
            "ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": "10.00", "Unit": "USD"}}}]
        }

        result = cost_mtd(client)

        client.get_cost_and_usage.assert_called_once_with(
            TimePeriod={"Start": _first_of_month(), "End": _tomorrow()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter=EC2_FILTER,
        )
        assert result == 10.0

    def test_sums_multiple_groups(self) -> None:
        client = _mock_client()
        client.get_cost_and_usage.return_value = {
            "ResultsByTime": [
                {"Total": {"UnblendedCost": {"Amount": "5.00", "Unit": "USD"}}},
                {"Total": {"UnblendedCost": {"Amount": "3.50", "Unit": "USD"}}},
            ]
        }

        result = cost_mtd(client)
        assert result == 8.5


class TestCostYtd:
    def test_calls_get_cost_and_usage(self) -> None:
        client = _mock_client()
        client.get_cost_and_usage.return_value = {
            "ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": "100.00", "Unit": "USD"}}}]
        }

        result = cost_ytd(client)

        client.get_cost_and_usage.assert_called_once_with(
            TimePeriod={"Start": _first_of_year(), "End": _tomorrow()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter=EC2_FILTER,
        )
        assert result == 100.0


# ---------------------------------------------------------------------------
# forecast_month / forecast_year
# ---------------------------------------------------------------------------


class TestForecastMonth:
    def test_calls_get_cost_forecast(self) -> None:
        client = _mock_client()
        client.get_cost_forecast.return_value = {
            "ForecastResults": [{"Total": {"UnblendedCost": {"Amount": "15.00", "Unit": "USD"}}}]
        }

        result = forecast_month(client)

        client.get_cost_forecast.assert_called_once_with(
            TimePeriod={"Start": _today(), "End": _end_of_month()},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            Filter=EC2_FILTER,
        )
        assert result["available"] is True
        assert result["amount"] == 15.0

    def test_returns_unavailable_on_data_unavailable(self) -> None:
        client = _mock_client()

        class DataUnavailableException(Exception):
            pass

        client.get_cost_forecast.side_effect = DataUnavailableException()

        result = forecast_month(client)
        assert result == forecast_unavailable()

    def test_returns_unavailable_on_validation_exception(self) -> None:
        client = _mock_client()

        class ValidationException(Exception):
            pass

        client.get_cost_forecast.side_effect = ValidationException()

        result = forecast_month(client)
        assert result == forecast_unavailable()


class TestForecastYear:
    def test_calls_get_cost_forecast(self) -> None:
        client = _mock_client()
        client.get_cost_forecast.return_value = {
            "ForecastResults": [{"Total": {"UnblendedCost": {"Amount": "200.00", "Unit": "USD"}}}]
        }

        result = forecast_year(client)

        client.get_cost_forecast.assert_called_once_with(
            TimePeriod={"Start": _today(), "End": _end_of_year()},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            Filter=EC2_FILTER,
        )
        assert result["available"] is True
        assert result["amount"] == 200.0

    def test_returns_unavailable_on_data_unavailable(self) -> None:
        client = _mock_client()

        class DataUnavailableException(Exception):
            pass

        client.get_cost_forecast.side_effect = DataUnavailableException()

        result = forecast_year(client)
        assert result == forecast_unavailable()

    def test_returns_unavailable_on_validation_exception(self) -> None:
        client = _mock_client()

        class ValidationException(Exception):
            pass

        client.get_cost_forecast.side_effect = ValidationException()

        result = forecast_year(client)
        assert result == forecast_unavailable()


# ---------------------------------------------------------------------------
# forecast_unavailable sentinel
# ---------------------------------------------------------------------------


class TestForecastUnavailable:
    def test_sentinel_shape(self) -> None:
        sentinel = forecast_unavailable()
        assert sentinel["available"] is False
        assert "amount" not in sentinel or sentinel.get("amount") is None


class TestCostErrorMapping:
    """API-call errors (not just client creation) map to CliError code 2."""

    def test_accessdenied_during_get_cost_and_usage(self) -> None:
        client = _mock_client()

        class ClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "AccessDenied"}}

        client.get_cost_and_usage.side_effect = ClientError()

        with pytest.raises(CliError) as exc:
            cost_mtd(client)
        assert exc.value.code == 2

    def test_generic_api_error_during_forecast_maps_to_clierror(self) -> None:
        client = _mock_client()
        client.get_cost_forecast.side_effect = RuntimeError("throttled")

        with pytest.raises(CliError) as exc:
            forecast_month(client)
        assert exc.value.code == 2
