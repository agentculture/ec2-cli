"""Tests for ec2 overview — live dashboard (fleet + cost figures).

The top-level ``ec2 overview`` renders a live dashboard:
  * fleet (ec2.aws.fleet.list_instances)
  * four EC2-service cost figures (MTD, YTD, forecast EOM, forecast EOY)

``cli overview`` still emits the descriptive self-report (tested separately
in test_cli_introspection.py).
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest

from ec2.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_boto3(monkeypatch: pytest.MonkeyPatch):
    """Return a mock boto3 module with controllable client factory."""
    mock_boto3 = MagicMock()
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    return mock_boto3


def _make_clients(mock_boto3: MagicMock):
    """Return (ec2_client, ce_client) mocks from the mocked boto3."""
    ec2_client = MagicMock()
    ce_client = MagicMock()

    def _client_factory(service, region_name=None):
        if service == "ec2":
            return ec2_client
        if service == "ce":
            return ce_client
        return MagicMock()

    mock_boto3.client.side_effect = _client_factory
    return ec2_client, ce_client


def _describe_instances_response(instances: list[dict], next_token=None):
    body: dict = {"Reservations": [{"Instances": instances}]}
    if next_token:
        body["NextToken"] = next_token
    return body


def _cost_response(amount: str):
    return {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}]}


def _forecast_response(amount: str):
    return {"ForecastResults": [{"Total": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}]}


def _setup_mocks(monkeypatch: pytest.MonkeyPatch):
    """Set up mocked boto3 and return (ec2_client, ce_client)."""
    mock_boto3 = _mock_boto3(monkeypatch)
    ec2_client, ce_client = _make_clients(mock_boto3)

    # Clear cached modules so build_client re-imports the mock
    for mod in list(sys.modules.keys()):
        if mod.startswith("ec2.aws"):
            del sys.modules[mod]

    return ec2_client, ce_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOverviewDashboard:
    """``ec2 overview`` renders fleet + four cost figures."""

    def _populate(self, ec2_client, ce_client):
        """Wire up mock responses for a typical dashboard."""
        ec2_client.describe_instances.return_value = _describe_instances_response(
            [
                {
                    "InstanceId": "i-001",
                    "InstanceType": "t3.micro",
                    "State": {"Name": "running"},
                    "Tags": [{"Key": "Name", "Value": "web-1"}],
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                },
                {
                    "InstanceId": "i-002",
                    "InstanceType": "t3.small",
                    "State": {"Name": "stopped"},
                    "Tags": [],
                    "Placement": {"AvailabilityZone": "us-east-1b"},
                },
            ]
        )
        ce_client.get_cost_and_usage.side_effect = [
            _cost_response("12.50"),  # MTD
            _cost_response("150.00"),  # YTD
        ]
        ce_client.get_cost_forecast.side_effect = [
            _forecast_response("18.00"),  # forecast month
            _forecast_response("200.00"),  # forecast year
        ]

    def test_overview_text_shows_fleet_and_figures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview"])
        assert rc == 0

    def test_overview_text_has_fleet_header(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Fleet" in out or "fleet" in out

    def test_overview_text_has_cost_figures(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview"])
        assert rc == 0
        out = capsys.readouterr().out
        # Check for the four figure labels
        assert "MTD" in out or "mtd" in out.lower()
        assert "YTD" in out or "ytd" in out.lower()
        assert "forecast" in out.lower()

    def test_overview_json_is_parseable(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, dict)
        # Dashboard payload has fleet and cost keys
        assert "fleet" in payload
        assert "cost" in payload

    def test_overview_json_fleet_contains_instances(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        fleet = payload["fleet"]
        assert isinstance(fleet, list)
        assert len(fleet) == 2
        assert fleet[0]["id"] == "i-001"
        assert fleet[0]["type"] == "t3.micro"
        assert fleet[0]["state"] == "running"

    def test_overview_json_cost_has_all_figures(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        cost = payload["cost"]
        assert "mtd" in cost
        assert "ytd" in cost
        assert "forecast_eom" in cost
        assert "forecast_eoy" in cost

    def test_overview_no_stderr_on_success(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        self._populate(ec2_client, ce_client)

        rc = main(["overview"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_overview_empty_account(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        ec2_client.describe_instances.return_value = {"Reservations": []}
        ce_client.get_cost_and_usage.return_value = {"ResultsByTime": []}
        ce_client.get_cost_forecast.return_value = {"ForecastResults": []}

        rc = main(["overview"])
        assert rc == 0
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

    def test_overview_forecast_unavailable_handled(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        ec2_client, ce_client = _setup_mocks(monkeypatch)
        ec2_client.describe_instances.return_value = {"Reservations": []}
        ce_client.get_cost_and_usage.return_value = {"ResultsByTime": []}

        class DataUnavailableException(Exception):
            pass

        ce_client.get_cost_forecast.side_effect = DataUnavailableException()

        rc = main(["overview"])
        assert rc == 0
        out = capsys.readouterr().out
        # Should still render without crashing
        assert len(out.strip()) > 0


class TestOverviewAwsFallback:
    """When AWS is unavailable, ``ec2 overview`` falls back to descriptive overview."""

    def test_missing_boto3_falls_back_to_descriptive(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # Hide boto3 entirely
        import builtins

        original_import = builtins.__import__

        def _patched(name: str, *args, **kwargs):
            if name.startswith("boto3"):
                raise ModuleNotFoundError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _patched)

        # Clear cached modules
        for mod in list(sys.modules.keys()):
            if mod.startswith("ec2.aws"):
                del sys.modules[mod]

        rc = main(["overview"])
        assert rc == 0
        out = capsys.readouterr().out
        # Falls back to descriptive agent overview
        assert "# ec2" in out
        assert "Identity" in out

    def test_ec2_client_failure_falls_back_to_descriptive(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)

        class NoCredentialsError(Exception):
            pass

        mock_boto3.client.side_effect = NoCredentialsError()

        for mod in list(sys.modules.keys()):
            if mod.startswith("ec2.aws"):
                del sys.modules[mod]

        rc = main(["overview"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "# ec2" in captured.out
        assert "Identity" in captured.out
        # Honest about WHY it degraded: a diagnostic naming the AWS failure.
        assert "AWS unavailable" in captured.err

    def test_fallback_json_is_parseable(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        import builtins

        original_import = builtins.__import__

        def _patched(name: str, *args, **kwargs):
            if name.startswith("boto3"):
                raise ModuleNotFoundError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _patched)

        for mod in list(sys.modules.keys()):
            if mod.startswith("ec2.aws"):
                del sys.modules[mod]

        rc = main(["overview", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["subject"] == "ec2"
        assert isinstance(payload["sections"], list)


class TestCliOverviewPreserved:
    """``cli overview`` still emits the descriptive self-report."""

    def test_cli_overview_still_works(self, capsys) -> None:
        rc = main(["cli", "overview"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "# ec2 cli" in out

    def test_cli_overview_json_still_works(self, capsys) -> None:
        rc = main(["cli", "overview", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["subject"] == "ec2 cli"
        assert isinstance(payload["sections"], list)
