"""Tests for `ec2 instance delete` — review → --apply termination gate."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ec2 import deletion
from ec2.cli._commands import instance as inst
from ec2.cli._errors import CliError

IID = "i-0abc123"


def _client(found: bool = True) -> MagicMock:
    c = MagicMock()
    if found:
        c.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": IID,
                            "InstanceType": "t2.micro",
                            "State": {"Name": "running"},
                            "Tags": [{"Key": "Name", "Value": "bot"}],
                            "Placement": {"AvailabilityZone": "us-east-1a"},
                            "BlockDeviceMappings": [
                                {
                                    "DeviceName": "/dev/xvda",
                                    "Ebs": {"VolumeId": "vol-1", "DeleteOnTermination": True},
                                }
                            ],
                        }
                    ]
                }
            ]
        }
    else:
        c.describe_instances.return_value = {"Reservations": []}
    c.terminate_instances.return_value = {
        "TerminatingInstances": [
            {
                "InstanceId": IID,
                "PreviousState": {"Name": "running"},
                "CurrentState": {"Name": "shutting-down"},
            }
        ]
    }
    return c


def _args(tmp_path: Path, *, apply: bool = False, json_mode: bool = False, found: bool = True):
    a = argparse.Namespace(instance_id=IID, apply=apply, json=json_mode)
    a._client = _client(found=found)
    a._config_dir = tmp_path / "config"
    return a


# ---------------------------------------------------------------------------
# Review step (default) — never terminates
# ---------------------------------------------------------------------------


class TestReviewStep:
    def test_review_records_token_and_does_not_terminate(self, tmp_path, capsys):
        args = _args(tmp_path)
        rc = inst.cmd_instance_delete(args)
        assert rc == 0
        args._client.terminate_instances.assert_not_called()
        assert deletion.fresh_review(IID, config_dir=args._config_dir) is not None
        out = capsys.readouterr().out
        assert "review" in out.lower()
        assert "--apply" in out

    def test_review_json_is_parseable(self, tmp_path, capsys):
        args = _args(tmp_path, json_mode=True)
        rc = inst.cmd_instance_delete(args)
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["review"]["id"] == IID
        assert payload["review"]["volumes"][0]["delete_on_termination"] is True
        assert payload["apply_command"].endswith("--apply")

    def test_not_found_raises(self, tmp_path):
        args = _args(tmp_path, found=False)
        with pytest.raises(CliError) as exc:
            inst.cmd_instance_delete(args)
        assert "not found" in exc.value.message.lower()
        args._client.terminate_instances.assert_not_called()


# ---------------------------------------------------------------------------
# Apply step — gated on a fresh review
# ---------------------------------------------------------------------------


class TestApplyGate:
    def test_apply_without_review_raises_and_does_not_terminate(self, tmp_path):
        args = _args(tmp_path, apply=True)
        with pytest.raises(CliError) as exc:
            inst.cmd_instance_delete(args)
        assert exc.value.code == 1
        assert "review" in exc.value.message.lower()
        args._client.terminate_instances.assert_not_called()

    def test_review_then_apply_terminates_and_clears_token(self, tmp_path):
        # Step 1: review
        review_args = _args(tmp_path)
        inst.cmd_instance_delete(review_args)
        # Step 2: apply (same config dir / fresh token)
        apply_args = _args(tmp_path, apply=True)
        apply_args._config_dir = review_args._config_dir
        rc = inst.cmd_instance_delete(apply_args)
        assert rc == 0
        apply_args._client.terminate_instances.assert_called_once_with(InstanceIds=[IID])
        # token cleared after a successful apply
        assert deletion.fresh_review(IID, config_dir=apply_args._config_dir) is None

    def test_stale_review_blocks_apply(self, tmp_path):
        cd = tmp_path / "config"
        # Record a review token 1000s in the past (> 15 min TTL).
        deletion.record_review(IID, {"id": IID}, config_dir=cd, now=time.time() - 1000)
        args = _args(tmp_path, apply=True)
        args._config_dir = cd
        with pytest.raises(CliError):
            inst.cmd_instance_delete(args)
        args._client.terminate_instances.assert_not_called()

    def test_apply_json_reports_transition(self, tmp_path, capsys):
        review_args = _args(tmp_path)
        inst.cmd_instance_delete(review_args)
        capsys.readouterr()  # discard the review output
        apply_args = _args(tmp_path, apply=True, json_mode=True)
        apply_args._config_dir = review_args._config_dir
        inst.cmd_instance_delete(apply_args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == IID
        assert payload["current_state"] == "shutting-down"


# ---------------------------------------------------------------------------
# deletion store
# ---------------------------------------------------------------------------


class TestDeletionStore:
    def test_ttl_expiry(self, tmp_path):
        cd = tmp_path / "config"
        deletion.record_review(IID, {"id": IID}, config_dir=cd, now=0.0)
        assert deletion.fresh_review(IID, config_dir=cd, now=deletion.REVIEW_TTL_SECONDS - 1)
        assert (
            deletion.fresh_review(IID, config_dir=cd, now=deletion.REVIEW_TTL_SECONDS + 1) is None
        )

    def test_clear_review(self, tmp_path):
        cd = tmp_path / "config"
        deletion.record_review(IID, {"id": IID}, config_dir=cd, now=0.0)
        deletion.clear_review(IID, config_dir=cd)
        assert deletion.fresh_review(IID, config_dir=cd, now=0.0) is None

    def test_malformed_file_returns_none(self, tmp_path):
        cd = tmp_path / "config"
        path = deletion._reviews_file(cd)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        assert deletion.fresh_review(IID, config_dir=cd) is None

    def test_missing_at_field_is_treated_as_expired(self, tmp_path):
        cd = tmp_path / "config"
        path = deletion._reviews_file(cd)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({IID: {"snapshot": {}}}) + "\n", encoding="utf-8")
        assert deletion.fresh_review(IID, config_dir=cd) is None

    def test_non_numeric_at_is_treated_as_expired(self, tmp_path):
        # A hand-edited/corrupt `at` must not crash `--apply` (ValueError).
        cd = tmp_path / "config"
        path = deletion._reviews_file(cd)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({IID: {"at": "garbage", "snapshot": {}}}) + "\n", encoding="utf-8"
        )
        assert deletion.fresh_review(IID, config_dir=cd, now=0.0) is None

    def test_non_finite_at_does_not_arm_a_stale_token(self, tmp_path):
        # json.loads accepts NaN/Infinity; both must fail safe (expired), never
        # defeat the TTL comparison and leave a stale review perpetually fresh.
        cd = tmp_path / "config"
        path = deletion._reviews_file(cd)
        path.parent.mkdir(parents=True, exist_ok=True)
        for bad in ("NaN", "Infinity", "-Infinity"):
            path.write_text('{"%s": {"at": %s, "snapshot": {}}}\n' % (IID, bad), encoding="utf-8")
            assert deletion.fresh_review(IID, config_dir=cd, now=10**9) is None
