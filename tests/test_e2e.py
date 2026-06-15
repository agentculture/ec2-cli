"""End-to-end integration tests — drive the CLI via ec2.cli.main with mocked AWS.

Patches ec2.aws.client.build_client so that both Cost Explorer
(get_cost_and_usage / get_cost_forecast) and EC2 (describe_instances)
responses are served without any network calls.

Acceptance
----------
1. ``ec2 overview`` / ``ec2 overview --json``: fleet + all four cost figures
   render; --json payload parses with keys ``fleet`` and ``cost``.
2. ``ec2 overview`` degrades gracefully when boto3/creds absent: exits 0,
   prints the descriptive agent overview to stdout, emits an "AWS unavailable"
   diagnostic to stderr.
3. ``ec2 instance`` carries the hard error contract: missing credentials,
   AccessDenied, and unset region all produce structured error (error:/hint:
   on stderr) with zero stdout and a non-zero exit code.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest

from ec2.cli import main
from ec2.cli._errors import CliError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_ec2_client():
    """Return a mock EC2 client with a default describe_instances response."""
    client = MagicMock()
    client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0abc123",
                        "InstanceType": "t3.micro",
                        "State": {"Name": "running"},
                        "Tags": [{"Key": "Name", "Value": "web-1"}],
                        "Placement": {"AvailabilityZone": "us-east-1a"},
                    },
                ],
            },
        ],
    }
    return client


def _fake_ce_client():
    """Return a mock Cost Explorer client with default cost/forecast responses."""
    client = MagicMock()
    client.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {"Total": {"UnblendedCost": {"Amount": "12.50", "Unit": "USD"}}},
        ],
    }
    client.get_cost_forecast.return_value = {
        "ForecastResults": [
            {"Total": {"UnblendedCost": {"Amount": "18.00", "Unit": "USD"}}},
        ],
    }
    return client


def _patch_build_client(monkeypatch: pytest.MonkeyPatch, ec2_client=None, ce_client=None):
    """Patch ec2.aws.client.build_client to return fake clients.

    Returns the (ec2_client, ce_client) pair that was installed.
    """
    if ec2_client is None:
        ec2_client = _fake_ec2_client()
    if ce_client is None:
        ce_client = _fake_ce_client()

    def _factory(service, region=None):
        if service == "ec2":
            return ec2_client
        if service == "ce":
            return ce_client
        return MagicMock()

    # Patch at the module level so cmd_overview / cmd_instance pick it up.
    monkeypatch.setattr(
        "ec2.aws.client.build_client",
        _factory,
    )
    return ec2_client, ce_client


def _hide_boto3(monkeypatch: pytest.MonkeyPatch):
    """Make ``import boto3`` raise ModuleNotFoundError."""
    import builtins

    original_import = builtins.__import__

    def _patched(name: str, *args, **kwargs):
        if name.startswith("boto3"):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)


# ---------------------------------------------------------------------------
# 1. ec2 overview — happy path (fleet + four figures)
# ---------------------------------------------------------------------------


class TestOverviewHappyPath:
    """``ec2 overview`` renders fleet + all four cost figures."""

    def test_overview_text_shows_fleet_and_figures(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _patch_build_client(monkeypatch)

        rc = main(["overview"])
        assert rc == 0

        out = capsys.readouterr().out
        # Fleet section
        assert "Fleet" in out
        # Cost figures
        assert "MTD" in out
        assert "YTD" in out
        assert "Forecast EOM" in out
        assert "Forecast EOY" in out

    def test_overview_json_parses_with_fleet_and_cost(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _patch_build_client(monkeypatch)

        rc = main(["overview", "--json"])
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, dict)
        assert "fleet" in payload
        assert "cost" in payload

        fleet = payload["fleet"]
        assert isinstance(fleet, list)
        assert len(fleet) == 1
        assert fleet[0]["id"] == "i-0abc123"

        cost = payload["cost"]
        assert "mtd" in cost
        assert "ytd" in cost
        assert "forecast_eom" in cost
        assert "forecast_eoy" in cost

    def test_overview_json_cost_figures_are_numeric(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _patch_build_client(monkeypatch)

        rc = main(["overview", "--json"])
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        cost = payload["cost"]
        assert isinstance(cost["mtd"], float)
        assert isinstance(cost["ytd"], float)
        assert isinstance(cost["forecast_eom"], dict)
        assert isinstance(cost["forecast_eom"]["amount"], (int, float))
        assert isinstance(cost["forecast_eoy"], dict)
        assert isinstance(cost["forecast_eoy"]["amount"], (int, float))

    def test_overview_no_stderr_on_success(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        _patch_build_client(monkeypatch)

        rc = main(["overview"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# 2. ec2 overview — graceful degradation when AWS unavailable
# ---------------------------------------------------------------------------


class TestOverviewDegradation:
    """``ec2 overview`` degrades gracefully when boto3/creds are absent."""

    def test_missing_boto3_exits_zero_with_descriptive_overview(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        _hide_boto3(monkeypatch)

        # Clear cached modules so build_client re-imports the hidden boto3.
        for mod in list(sys.modules.keys()):
            if mod.startswith("ec2.aws"):
                del sys.modules[mod]

        rc = main(["overview"])
        assert rc == 0

        captured = capsys.readouterr()
        # Stdout: descriptive agent overview
        assert "# ec2" in captured.out
        assert "Identity" in captured.out
        # Stderr: honest diagnostic
        assert "AWS unavailable" in captured.err

    def test_missing_creds_exits_zero_with_descriptive_overview(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        # build_client raises CliError for missing credentials.
        def _failing_factory(service, region=None):
            raise CliError(
                code=2,
                message="AWS credentials are not configured",
                remediation="Configure AWS credentials",
            )

        monkeypatch.setattr("ec2.aws.client.build_client", _failing_factory)

        rc = main(["overview"])
        assert rc == 0

        captured = capsys.readouterr()
        assert "# ec2" in captured.out
        assert "Identity" in captured.out
        assert "AWS unavailable" in captured.err

    def test_degraded_json_is_parseable(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        _hide_boto3(monkeypatch)

        for mod in list(sys.modules.keys()):
            if mod.startswith("ec2.aws"):
                del sys.modules[mod]

        rc = main(["overview", "--json"])
        assert rc == 0

        payload = json.loads(capsys.readouterr().out)
        assert payload["subject"] == "ec2"
        assert isinstance(payload["sections"], list)


# ---------------------------------------------------------------------------
# 3. ec2 instance — hard error contract (structured error, non-zero exit)
# ---------------------------------------------------------------------------


class TestInstanceErrorContract:
    """``ec2 instance`` produces structured error on AWS failures."""

    def _assert_error(self, captured):
        """Assert the structured error contract: error:/hint: on stderr,
        zero stdout, non-zero exit code."""
        assert captured.out == ""
        assert "error:" in captured.err
        assert "hint:" in captured.err

    def test_missing_credentials(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """Missing credentials → structured error, exit 2."""

        def _failing_factory(service, region=None):
            raise CliError(
                code=2,
                message="AWS credentials are not configured",
                remediation="Configure AWS credentials (e.g. aws configure)",
            )

        monkeypatch.setattr("ec2.aws.client.build_client", _failing_factory)

        rc = main(["instance"])
        assert rc == 2

        captured = capsys.readouterr()
        self._assert_error(captured)
        assert "credentials" in captured.err.lower()

    def test_access_denied(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """AccessDenied → structured error, exit 2."""

        def _failing_factory(service, region=None):
            raise CliError(
                code=2,
                message="AWS AccessDenied — insufficient IAM permissions",
                remediation="Check IAM policy grants the required ec2:* actions",
            )

        monkeypatch.setattr("ec2.aws.client.build_client", _failing_factory)

        rc = main(["instance"])
        assert rc == 2

        captured = capsys.readouterr()
        self._assert_error(captured)
        assert "permission" in captured.err.lower() or "access" in captured.err.lower()

    def test_unset_region(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """Unset region → structured error, exit 2."""

        def _failing_factory(service, region=None):
            raise CliError(
                code=2,
                message="No AWS region configured",
                remediation="Set AWS_DEFAULT_REGION or pass --region",
            )

        monkeypatch.setattr("ec2.aws.client.build_client", _failing_factory)

        rc = main(["instance"])
        assert rc == 2

        captured = capsys.readouterr()
        self._assert_error(captured)
        assert "region" in captured.err.lower()

    def test_instance_error_json(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """Error in --json mode emits structured JSON to stderr."""

        def _failing_factory(service, region=None):
            raise CliError(
                code=2,
                message="AWS credentials are not configured",
                remediation="Configure AWS credentials",
            )

        monkeypatch.setattr("ec2.aws.client.build_client", _failing_factory)

        rc = main(["instance", "--json"])
        assert rc == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        payload = json.loads(captured.err)
        assert payload["code"] == 2
        assert "credentials" in payload["message"].lower()


# ---------------------------------------------------------------------------
# 4. Cross-cutting: overview degrades, instance hard-fails (contrast)
# ---------------------------------------------------------------------------


class TestVerbContrast:
    """Verify that overview degrades while instance hard-fails under the
    same AWS-unavailable condition."""

    def test_overview_degrades_but_instance_fails_on_missing_creds(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Same missing-creds condition: overview → exit 0, instance → exit 2."""

        def _failing_factory(service, region=None):
            raise CliError(
                code=2,
                message="AWS credentials are not configured",
                remediation="Configure AWS credentials",
            )

        monkeypatch.setattr("ec2.aws.client.build_client", _failing_factory)

        # overview degrades
        rc = main(["overview"])
        assert rc == 0
        capsys.readouterr()

        # instance hard-fails
        rc = main(["instance"])
        assert rc == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "error:" in captured.err
        assert "hint:" in captured.err
