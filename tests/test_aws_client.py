"""Tests for ec2.aws.client — lazy boto3 import and error mapping."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from ec2.cli._errors import CliError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hide_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import boto3`` raise ModuleNotFoundError."""
    import builtins

    original_import = builtins.__import__

    def _patched(name: str, *args, **kwargs):
        if name.startswith("boto3"):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _patched)


def _mock_boto3(monkeypatch: pytest.MonkeyPatch):
    """Return a mock boto3 module with a controllable ``client`` factory."""
    mock_boto3 = MagicMock()
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    return mock_boto3


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildClient:
    """build_client lazy-imports boto3 and maps AWS failures to CliError."""

    def test_lazy_import_raises_clierror_when_boto3_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _hide_boto3(monkeypatch)

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client

        with pytest.raises(CliError) as exc:
            build_client("ec2")

        err = exc.value
        assert err.code == 2
        assert "pip install" in err.remediation.lower() or "pip install" in err.remediation
        assert "boto3" in err.remediation.lower() or "ec2-cli" in err.remediation.lower()

    def test_build_client_returns_boto3_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        fake_client = MagicMock()
        mock_boto3.client.return_value = fake_client

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client

        result = build_client("ec2", region="us-east-1")
        mock_boto3.client.assert_called_once_with("ec2", region_name="us-east-1")
        assert result is fake_client

    def test_build_client_without_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        fake_client = MagicMock()
        mock_boto3.client.return_value = fake_client

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client

        result = build_client("ec2")
        mock_boto3.client.assert_called_once_with("ec2", region_name=None)
        assert result is fake_client

    def test_missing_credentials_raises_clierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)

        class NoCredentialsError(Exception):
            pass

        mock_boto3.client.side_effect = NoCredentialsError()

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client

        with pytest.raises(CliError) as exc:
            build_client("ec2")

        err = exc.value
        assert err.code == 2
        assert "credentials" in err.message.lower() or "credentials" in err.remediation.lower()

    def test_access_denied_raises_clierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)

        error_response = {"Error": {"Code": "AccessDenied", "Message": "ce:/ec2: actions"}}

        class ClientError(Exception):
            def __init__(self, resp):
                self.response = resp
                self.operation_name = "DescribeInstances"

        mock_boto3.client.side_effect = ClientError(error_response)

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client

        with pytest.raises(CliError) as exc:
            build_client("ec2")

        err = exc.value
        assert err.code == 2
        assert "permission" in err.message.lower() or "permission" in err.remediation.lower()

    def test_no_region_raises_clierror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)

        class NoRegionError(Exception):
            pass

        mock_boto3.client.side_effect = NoRegionError()

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client

        with pytest.raises(CliError) as exc:
            build_client("ec2")

        err = exc.value
        assert err.code == 2
        assert "region" in err.message.lower() or "region" in err.remediation.lower()


class TestOutputContract:
    """CliError output goes to stderr; stdout stays empty."""

    def test_missing_creds_stderr_only(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)

        class NoCredentialsError(Exception):
            pass

        mock_boto3.client.side_effect = NoCredentialsError()

        if "ec2.aws.client" in sys.modules:
            del sys.modules["ec2.aws.client"]

        from ec2.aws.client import build_client
        from ec2.cli._output import emit_error

        try:
            build_client("ec2")
        except CliError as exc:
            emit_error(exc, json_mode=False)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "error:" in captured.err
        assert "hint:" in captured.err
