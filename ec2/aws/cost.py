"""Cost Explorer helpers — EC2-service spend and forecast (lazy boto3).

The Cost Explorer API is a global service; all calls target ``us-east-1``.
Build the client via :func:`ec2.aws.client.build_client("ce", region="us-east-1")`
and pass it into the functions below.

EC2-service filter
------------------
The dimension filter used here targets the EC2-Compute service::

    Filter={"Dimensions":{"Key":"SERVICE","Values":["Amazon Elastic Compute Cloud - Compute"]}}

To include EC2-Other charges (e.g. EBS, NAT Gateway), append
``"EC2 - Other"`` to the ``Values`` list.
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# EC2-service filter
# ---------------------------------------------------------------------------

EC2_FILTER: dict[str, object] = {
    "Dimensions": {
        "Key": "SERVICE",
        "Values": ["Amazon Elastic Compute Cloud - Compute"],
    },
}

# ---------------------------------------------------------------------------
# Forecast sentinel
# ---------------------------------------------------------------------------


def forecast_unavailable() -> dict[str, object]:
    """Return the forecast-unavailable sentinel.

    Used when Cost Explorer raises ``DataUnavailableException`` or
    ``ValidationException`` (insufficient history / start must be in future).
    """
    return {"available": False}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _first_of_month() -> str:
    return date.today().replace(day=1).isoformat()


def _first_of_year() -> str:
    return date.today().replace(month=1, day=1).isoformat()


def _end_of_month() -> str:
    """Last day of the current month."""
    today = date.today()
    if today.month == 12:
        return today.replace(month=12, day=31).isoformat()
    return today.replace(month=today.month + 1, day=1).isoformat()


def _end_of_year() -> str:
    return date(date.today().year, 12, 31).isoformat()


# ---------------------------------------------------------------------------
# Cost queries
# ---------------------------------------------------------------------------


def cost_mtd(client: object) -> float:
    """Return EC2 spend for the current month (USD).

    Calls ``GetCostAndUsage`` with ``UnblendedCost``, monthly granularity,
    and the EC2-service filter for *first-of-month .. today*.
    """
    resp = client.get_cost_and_usage(
        TimePeriod={"Start": _first_of_month(), "End": _today()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter=EC2_FILTER,
    )
    return _sum_unblended(resp)


def cost_ytd(client: object) -> float:
    """Return EC2 spend year-to-date (USD).

    Calls ``GetCostAndUsage`` with ``UnblendedCost``, monthly granularity,
    and the EC2-service filter for *first-of-year .. today*.
    """
    resp = client.get_cost_and_usage(
        TimePeriod={"Start": _first_of_year(), "End": _today()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter=EC2_FILTER,
    )
    return _sum_unblended(resp)


def _sum_unblended(resp: dict[str, object]) -> float:
    """Sum ``UnblendedCost.Amount`` across all result groups."""
    total = 0.0
    for group in resp.get("ResultsByTime", []):
        amount = group.get("TotalEstimate", {}).get("UnblendedCost", {}).get("Amount", "0")
        total += float(amount)
    return total


# ---------------------------------------------------------------------------
# Forecast queries
# ---------------------------------------------------------------------------


def forecast_month(client: object) -> dict[str, object]:
    """Return EC2 cost forecast for the remainder of the current month.

    Calls ``GetCostForecast`` for *today .. end-of-month*.  When CE raises
    ``DataUnavailableException`` or ``ValidationException``, returns the
    forecast-unavailable sentinel instead of raising.
    """
    try:
        resp = client.get_cost_forecast(
            TimePeriod={"Start": _today(), "End": _end_of_month()},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            Filter=EC2_FILTER,
        )
        amount = _forecast_amount(resp)
        return {"available": True, "amount": amount}
    except Exception as exc:
        if _is_ce_unavailable(exc):
            return forecast_unavailable()
        raise


def forecast_year(client: object) -> dict[str, object]:
    """Return EC2 cost forecast for the remainder of the current year.

    Calls ``GetCostForecast`` for *today .. end-of-year*.  When CE raises
    ``DataUnavailableException`` or ``ValidationException``, returns the
    forecast-unavailable sentinel instead of raising.
    """
    try:
        resp = client.get_cost_forecast(
            TimePeriod={"Start": _today(), "End": _end_of_year()},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            Filter=EC2_FILTER,
        )
        amount = _forecast_amount(resp)
        return {"available": True, "amount": amount}
    except Exception as exc:
        if _is_ce_unavailable(exc):
            return forecast_unavailable()
        raise


def _forecast_amount(resp: dict[str, object]) -> float:
    """Extract total forecasted amount from a GetCostForecast response."""
    total = 0.0
    for entry in resp.get("ForecastResults", []):
        amount = entry.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
        total += float(amount)
    return total


def _is_ce_unavailable(exc: Exception) -> bool:
    """Check whether *exc* is a CE data-unavailable / validation error."""
    name = type(exc).__name__
    return name in ("DataUnavailableException", "ValidationException")
