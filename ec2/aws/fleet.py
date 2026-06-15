"""Fleet operations — list EC2 instances with pagination.

All AWS access goes through a pre-built client (from :func:`ec2.aws.client.build_client`).
boto3 is never imported at module level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ec2.aws.client import aws_call


@dataclass
class Instance:
    """Summary of an EC2 instance."""

    id: str
    type: str
    state: str
    name: str
    az: str
    lifecycle: str = "on-demand"


def _get_name(raw_tags: list[dict[str, str]] | None) -> str:
    """Return the ``Name`` tag value, or ``""`` when absent."""
    if not raw_tags:
        return ""
    for tag in raw_tags:
        if tag.get("Key") == "Name":
            return tag.get("Value", "")
    return ""


def list_instances(client: Any) -> list[Instance]:
    """Return every EC2 instance in the account, paginating through DescribeInstances.

    Parameters
    ----------
    client:
        A boto3 EC2 client (or mock) with a ``describe_instances`` method.

    Returns
    -------
    list[Instance]
        Flattened list of instances across all reservations and pages.
        Empty list when the account has no instances.
    """
    instances: list[Instance] = []
    next_token = None

    while True:
        kwargs: dict[str, Any] = {}
        if next_token:
            kwargs["NextToken"] = next_token

        resp = aws_call(client.describe_instances, **kwargs)

        for reservation in resp.get("Reservations", []):
            for raw in reservation.get("Instances", []):
                instances.append(
                    Instance(
                        id=raw["InstanceId"],
                        type=raw.get("InstanceType", ""),
                        state=raw.get("State", {}).get("Name", ""),
                        name=_get_name(raw.get("Tags")),
                        az=raw.get("Placement", {}).get("AvailabilityZone", ""),
                        # InstanceLifecycle is "spot" for spot instances and
                        # absent for on-demand; default to "on-demand".
                        lifecycle=raw.get("InstanceLifecycle") or "on-demand",
                    )
                )

        next_token = resp.get("NextToken")
        if not next_token:
            break

    return instances
