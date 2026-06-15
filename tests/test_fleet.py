"""Tests for ec2.aws.fleet — list_instances with pagination."""

from __future__ import annotations

import sys
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

from ec2.aws.fleet import Instance, list_instances

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


def _describe_response(instances, next_token=None):
    """Build a DescribeInstances response payload."""
    body: dict = {"Reservations": [{"Instances": instances}]}
    if next_token:
        body["NextToken"] = next_token
    return body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListInstances:
    """list_instances pages through DescribeInstances and returns Instance list."""

    def test_empty_account_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = {"Reservations": []}

        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]

        result = list_instances(client)
        assert result == []

    def test_single_page_returns_instances(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        client.describe_instances.return_value = _describe_response(instances)

        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]

        result = list_instances(client)
        assert len(result) == 1
        inst = result[0]
        assert inst.id == "i-0abc123"
        assert inst.type == "t3.micro"
        assert inst.state == "running"
        assert inst.name == "web-1"
        assert inst.az == "us-east-1a"

    def test_two_pages_aggregates_all_instances(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)

        page1_instances = [
            {
                "InstanceId": "i-0001",
                "InstanceType": "t3.small",
                "State": {"Name": "running"},
                "Tags": [{"Key": "Name", "Value": "app-1"}],
                "Placement": {"AvailabilityZone": "us-east-1a"},
            }
        ]
        page2_instances = [
            {
                "InstanceId": "i-0002",
                "InstanceType": "t3.medium",
                "State": {"Name": "stopped"},
                "Tags": [],
                "Placement": {"AvailabilityZone": "us-east-1b"},
            }
        ]

        client.describe_instances.side_effect = [
            _describe_response(page1_instances, next_token="tok-1"),
            _describe_response(page2_instances),
        ]

        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]

        result = list_instances(client)
        assert len(result) == 2

        assert result[0].id == "i-0001"
        assert result[0].type == "t3.small"
        assert result[0].state == "running"
        assert result[0].name == "app-1"
        assert result[0].az == "us-east-1a"

        assert result[1].id == "i-0002"
        assert result[1].type == "t3.medium"
        assert result[1].state == "stopped"
        assert result[1].name == ""
        assert result[1].az == "us-east-1b"

    def test_instance_without_name_tag_returns_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)

        instances = [
            {
                "InstanceId": "i-0no-tags",
                "InstanceType": "t3.nano",
                "State": {"Name": "pending"},
                "Placement": {"AvailabilityZone": "eu-west-1c"},
            }
        ]
        client.describe_instances.return_value = _describe_response(instances)

        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]

        result = list_instances(client)
        assert len(result) == 1
        assert result[0].name == ""

    def test_instance_without_tags_list_returns_empty_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)

        instances = [
            {
                "InstanceId": "i-0no-tags",
                "InstanceType": "t3.nano",
                "State": {"Name": "pending"},
                "Tags": None,
                "Placement": {"AvailabilityZone": "eu-west-1c"},
            }
        ]
        client.describe_instances.return_value = _describe_response(instances)

        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]

        result = list_instances(client)
        assert len(result) == 1
        assert result[0].name == ""


class TestInstanceDataclass:
    """Instance dataclass serialises correctly."""

    def test_instance_fields(self) -> None:
        inst = Instance(
            id="i-001",
            type="t3.micro",
            state="running",
            name="test",
            az="us-east-1a",
        )
        assert inst.id == "i-001"
        assert inst.type == "t3.micro"
        assert inst.state == "running"
        assert inst.name == "test"
        assert inst.az == "us-east-1a"

    def test_instance_asdict(self) -> None:
        inst = Instance(
            id="i-001",
            type="t3.micro",
            state="running",
            name="test",
            az="us-east-1a",
        )
        d = asdict(inst)
        assert d["id"] == "i-001"
        assert d["type"] == "t3.micro"


class TestLifecycle:
    """list_instances populates Instance.lifecycle from InstanceLifecycle."""

    def test_spot_instance_marked_spot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_response(
            [
                {
                    "InstanceId": "i-spot1",
                    "InstanceType": "t3.micro",
                    "State": {"Name": "running"},
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                    "InstanceLifecycle": "spot",
                }
            ]
        )
        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]
        result = list_instances(client)
        assert result[0].lifecycle == "spot"

    def test_ondemand_instance_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)
        client.describe_instances.return_value = _describe_response(
            [
                {
                    "InstanceId": "i-od1",
                    "InstanceType": "t3.micro",
                    "State": {"Name": "running"},
                    "Placement": {"AvailabilityZone": "us-east-1a"},
                }
            ]
        )
        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]
        result = list_instances(client)
        assert result[0].lifecycle == "on-demand"


class TestFleetErrorMapping:
    """describe_instances API errors map to CliError code 2."""

    def test_accessdenied_during_describe_instances(
        self, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        from ec2.cli._errors import CliError

        mock_boto3 = _mock_boto3(monkeypatch)
        client = _make_client(mock_boto3)

        class ClientError(Exception):
            def __init__(self) -> None:
                self.response = {"Error": {"Code": "AccessDenied"}}

        client.describe_instances.side_effect = ClientError()
        if "ec2.aws.fleet" in sys.modules:
            del sys.modules["ec2.aws.fleet"]

        with pytest.raises(CliError) as exc:
            list_instances(client)
        assert exc.value.code == 2
