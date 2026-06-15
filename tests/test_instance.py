"""Tests for ec2.cli._commands.instance — instance noun (list / start / stop / limit)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ec2.cli._errors import CliError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_boto3(monkeypatch: pytest.MonkeyPatch):
    """Return a mock boto3 module with a controllable ``client`` factory."""
    mock_boto3 = MagicMock()
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    return mock_boto3


def _make_client(mock_boto3: MagicMock):
    """Return a mock EC2 client from the mocked boto3."""
    fake_client = MagicMock()
    mock_boto3.client.return_value = fake_client
    return fake_client


def _describe_instances_response(instances, next_token=None):
    """Build a DescribeInstances response payload."""
    body: dict = {"Reservations": [{"Instances": instances}]}
    if next_token:
        body["NextToken"] = next_token
    return body


def _describe_instances_for_state(instance_id: str, state: str):
    """Build a DescribeInstances response for a single instance in a given state."""
    return _describe_instances_response(
        [
            {
                "InstanceId": instance_id,
                "InstanceType": "t3.micro",
                "State": {"Name": state},
                "Tags": [{"Key": "Name", "Value": "test"}],
                "Placement": {"AvailabilityZone": "us-east-1a"},
            }
        ]
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Temporary config directory for limits."""
    return tmp_path / "config"


@pytest.fixture
def monkeypatch_config(monkeypatch: pytest.MonkeyPatch, config_dir: Path):
    """Monkeypatch the limits config dir so tests use a tmp path."""
    from ec2 import limits as _limits_mod

    original_config_dir = _limits_mod._config_dir

    def _patched_config_dir(config_dir_arg=None):
        if config_dir_arg is not None:
            return original_config_dir(config_dir_arg)
        return config_dir

    monkeypatch.setattr(_limits_mod, "_config_dir", _patched_config_dir)
    return config_dir


# ---------------------------------------------------------------------------
# Tests: instance list (no subverb)
# ---------------------------------------------------------------------------


class TestInstanceList:
    """`ec2 instance` lists instances via list_instances."""

    def test_list_empty_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = {"Reservations": []}

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(json=False, _client=client)
        rc = inst_mod.cmd_instance(args)
        assert rc == 0

    def test_list_with_instances(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)

        instances = [
            {
                "InstanceId": "i-0abc123",
                "InstanceType": "t3.micro",
                "State": {"Name": "running"},
                "Tags": [{"Key": "Name", "Value": "web-1"}],
                "Placement": {"AvailabilityZone": "us-east-1a"},
            }
        ]
        client.describe_instances.return_value = _describe_instances_response(instances)

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(json=False, _client=client)
        rc = inst_mod.cmd_instance(args)
        assert rc == 0

    def test_list_json(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)

        instances = [
            {
                "InstanceId": "i-0abc123",
                "InstanceType": "t3.micro",
                "State": {"Name": "running"},
                "Tags": [{"Key": "Name", "Value": "web-1"}],
                "Placement": {"AvailabilityZone": "us-east-1a"},
            }
        ]
        client.describe_instances.return_value = _describe_instances_response(instances)

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(json=True, _client=client)
        rc = inst_mod.cmd_instance(args)
        assert rc == 0

        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "i-0abc123"


# ---------------------------------------------------------------------------
# Tests: instance start
# ---------------------------------------------------------------------------


class TestInstanceStart:
    """`ec2 instance start <id>` invokes StartInstances behind --yes."""

    def test_start_without_yes_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_instances_for_state("i-0abc", "stopped")

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(instance_id="i-0abc", yes=False, _client=client)
        with pytest.raises(CliError):
            inst_mod.cmd_instance_start(args)

    def test_start_with_yes_calls_start_instances(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_instances_for_state("i-0abc", "stopped")

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(instance_id="i-0abc", yes=True, _client=client)
        rc = inst_mod.cmd_instance_start(args)
        assert rc == 0
        client.start_instances.assert_called_once_with(InstanceIds=["i-0abc"])

    def test_start_idempotent_already_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When instance is already running, no mutating call is made."""
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_instances_for_state("i-0abc", "running")

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(instance_id="i-0abc", yes=True, _client=client)
        rc = inst_mod.cmd_instance_start(args)
        assert rc == 0
        client.start_instances.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: instance stop
# ---------------------------------------------------------------------------


class TestInstanceStop:
    """`ec2 instance stop <id>` invokes StopInstances behind --yes."""

    def test_stop_without_yes_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_instances_for_state("i-0abc", "running")

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(instance_id="i-0abc", yes=False, _client=client)
        with pytest.raises(CliError):
            inst_mod.cmd_instance_stop(args)

    def test_stop_with_yes_calls_stop_instances(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_instances_for_state("i-0abc", "running")

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(instance_id="i-0abc", yes=True, _client=client)
        rc = inst_mod.cmd_instance_stop(args)
        assert rc == 0
        client.stop_instances.assert_called_once_with(InstanceIds=["i-0abc"])

    def test_stop_idempotent_already_stopped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When instance is already stopped, no mutating call is made."""
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_instances_for_state("i-0abc", "stopped")

        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(instance_id="i-0abc", yes=True, _client=client)
        rc = inst_mod.cmd_instance_stop(args)
        assert rc == 0
        client.stop_instances.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: instance limit
# ---------------------------------------------------------------------------


class TestInstanceLimit:
    """`ec2 instance limit <id> <amount> --monthly|--yearly [--auto-stop]`."""

    def test_limit_monthly(self, monkeypatch_config: Path) -> None:
        from ec2.cli._commands import instance as inst_mod
        from ec2.limits import load_limits

        args = argparse.Namespace(
            instance_id="i-0abc123",
            amount=100.0,
            monthly=True,
            yearly=False,
            auto_stop=False,
        )
        rc = inst_mod.cmd_instance_limit(args)
        assert rc == 0

        limits = load_limits(config_dir=monkeypatch_config)
        assert len(limits) == 1
        assert limits[0].target == "i-0abc123"
        assert limits[0].amount == 100.0
        assert limits[0].period == "monthly"
        assert limits[0].auto_stop is False

    def test_limit_yearly(self, monkeypatch_config: Path) -> None:
        from ec2.cli._commands import instance as inst_mod
        from ec2.limits import load_limits

        args = argparse.Namespace(
            instance_id="i-0def456",
            amount=500.0,
            monthly=False,
            yearly=True,
            auto_stop=False,
        )
        rc = inst_mod.cmd_instance_limit(args)
        assert rc == 0

        limits = load_limits(config_dir=monkeypatch_config)
        assert len(limits) == 1
        assert limits[0].target == "i-0def456"
        assert limits[0].amount == 500.0
        assert limits[0].period == "yearly"

    def test_limit_with_auto_stop(self, monkeypatch_config: Path) -> None:
        from ec2.cli._commands import instance as inst_mod
        from ec2.limits import load_limits

        args = argparse.Namespace(
            instance_id="i-0ghi789",
            amount=200.0,
            monthly=True,
            yearly=False,
            auto_stop=True,
        )
        rc = inst_mod.cmd_instance_limit(args)
        assert rc == 0

        limits = load_limits(config_dir=monkeypatch_config)
        assert len(limits) == 1
        assert limits[0].auto_stop is True

    def test_limit_round_trip(self, monkeypatch_config: Path) -> None:
        """Save a limit and read it back — data is identical."""
        from ec2.cli._commands import instance as inst_mod
        from ec2.limits import load_limits

        args = argparse.Namespace(
            instance_id="i-0roundtrip",
            amount=75.5,
            monthly=True,
            yearly=False,
            auto_stop=True,
        )
        rc = inst_mod.cmd_instance_limit(args)
        assert rc == 0

        loaded = load_limits(config_dir=monkeypatch_config)
        assert len(loaded) == 1
        limit = loaded[0]
        assert limit.target == "i-0roundtrip"
        assert limit.amount == 75.5
        assert limit.period == "monthly"
        assert limit.auto_stop is True

    def test_limit_requires_period(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing both --monthly and --yearly raises CliError."""
        from ec2.cli._commands import instance as inst_mod

        args = argparse.Namespace(
            instance_id="i-0abc",
            amount=100.0,
            monthly=False,
            yearly=False,
            auto_stop=False,
        )
        with pytest.raises(CliError):
            inst_mod.cmd_instance_limit(args)


# ---------------------------------------------------------------------------
# Tests: register() produces correct parser structure
# ---------------------------------------------------------------------------


class TestRegister:
    """register(sub) builds the expected parser tree."""

    def test_register_creates_instance_parser(self) -> None:
        from ec2.cli._commands import instance as inst_mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        inst_mod.register(sub)

    def test_instance_no_subverb_defaults_to_list(self) -> None:
        from ec2.cli._commands import instance as inst_mod

        parent = argparse.ArgumentParser(prog="ec2")
        sub = parent.add_subparsers(dest="noun", parser_class=type(parent))
        inst_mod.register(sub)

        args = parent.parse_args(["instance"])
        assert args.noun == "instance"
        assert hasattr(args, "func")

    def test_instance_start_subcommand(self) -> None:
        from ec2.cli._commands import instance as inst_mod

        parent = argparse.ArgumentParser(prog="ec2")
        sub = parent.add_subparsers(dest="noun", parser_class=type(parent))
        inst_mod.register(sub)

        args = parent.parse_args(["instance", "start", "i-0abc", "--yes"])
        assert args.instance_id == "i-0abc"
        assert args.yes is True

    def test_instance_stop_subcommand(self) -> None:
        from ec2.cli._commands import instance as inst_mod

        parent = argparse.ArgumentParser(prog="ec2")
        sub = parent.add_subparsers(dest="noun", parser_class=type(parent))
        inst_mod.register(sub)

        args = parent.parse_args(["instance", "stop", "i-0abc", "--yes"])
        assert args.instance_id == "i-0abc"
        assert args.yes is True

    def test_instance_limit_subcommand(self) -> None:
        from ec2.cli._commands import instance as inst_mod

        parent = argparse.ArgumentParser(prog="ec2")
        sub = parent.add_subparsers(dest="noun", parser_class=type(parent))
        inst_mod.register(sub)

        args = parent.parse_args(
            [
                "instance",
                "limit",
                "i-0abc",
                "100",
                "--monthly",
                "--auto-stop",
            ]
        )
        assert args.instance_id == "i-0abc"
        assert args.amount == 100
        assert args.monthly is True
        assert args.auto_stop is True
