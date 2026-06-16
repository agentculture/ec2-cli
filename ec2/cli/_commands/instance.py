"""``ec2 instance`` — instance noun (list / start / stop / limit).

Sub-commands
------------
* ``ec2 instance``          — list instances (default, no sub-verb)
* ``ec2 instance start <id>`` — start an instance (requires ``--yes``)
* ``ec2 instance stop <id>``  — stop an instance (requires ``--yes``)
* ``ec2 instance limit <id> <amount> --monthly|--yearly [--auto-stop]``
  — persist a spend limit
* ``ec2 instance delete <id>`` — *review* what terminating would destroy;
  ``ec2 instance delete <id> --apply`` terminates (only after a fresh review).

Power actions (start/stop) are idempotent: if the instance is already in the
target state, no AWS call is made. ``delete`` is the one irreversible verb and
is gated behind a two-step review → ``--apply`` flow (see :mod:`ec2.deletion`).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from typing import Any

from ec2 import deletion
from ec2.cli._errors import EXIT_USER_ERROR, CliError
from ec2.cli._output import emit_diagnostic, emit_result

_INSTANCE_ID_HELP = "Instance ID (e.g. i-0abc123)."
REVIEW_TTL_MINUTES = deletion.REVIEW_TTL_SECONDS // 60


def _get_client(args: argparse.Namespace) -> Any:
    """Return the EC2 client from *args* or build one lazily.

    Tests inject a mock via ``args._client``; production code calls
    :func:`ec2.aws.client.build_client`.
    """
    if hasattr(args, "_client") and args._client is not None:
        return args._client

    # Lazy import — boto3 is an optional dependency.
    from ec2.aws.client import build_client

    return build_client("ec2")


def _current_state(client: Any, instance_id: str) -> str | None:
    """Return the current state of *instance_id*, or ``None`` if not found."""
    resp = client.describe_instances(InstanceIds=[instance_id])
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            if inst["InstanceId"] == instance_id:
                return inst.get("State", {}).get("Name")
    return None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def cmd_instance(args: argparse.Namespace) -> int:
    """List instances (default when no sub-verb is given)."""
    client = _get_client(args)
    from ec2.aws.fleet import list_instances

    instances = list_instances(client)
    json_mode = bool(getattr(args, "json", False))

    if json_mode:
        emit_result([asdict(i) for i in instances], json_mode=True)
    else:
        lines: list[str] = []
        for inst in instances:
            lines.append(f"{inst.id}  {inst.type}  {inst.state}  {inst.name}  {inst.az}")
        if lines:
            emit_result("\n".join(lines), json_mode=False)
        else:
            emit_diagnostic("no instances found", stream=sys.stderr)
    return 0


def cmd_instance_start(args: argparse.Namespace) -> int:
    """Start an instance. Requires ``--yes``; idempotent when already running."""
    if not bool(getattr(args, "yes", False)):
        raise CliError(
            code=EXIT_USER_ERROR,
            message="confirmation required to start an instance",
            remediation="pass --yes to confirm",
        )

    client = _get_client(args)
    instance_id = args.instance_id
    state = _current_state(client, instance_id)

    if state == "running":
        emit_diagnostic(f"{instance_id} is already running (no-op)")
        return 0

    client.start_instances(InstanceIds=[instance_id])
    emit_diagnostic(f"start requested for {instance_id}")
    return 0


def cmd_instance_stop(args: argparse.Namespace) -> int:
    """Stop an instance. Requires ``--yes``; idempotent when already stopped."""
    if not bool(getattr(args, "yes", False)):
        raise CliError(
            code=EXIT_USER_ERROR,
            message="confirmation required to stop an instance",
            remediation="pass --yes to confirm",
        )

    client = _get_client(args)
    instance_id = args.instance_id
    state = _current_state(client, instance_id)

    if state == "stopped":
        emit_diagnostic(f"{instance_id} is already stopped (no-op)")
        return 0

    client.stop_instances(InstanceIds=[instance_id])
    emit_diagnostic(f"stop requested for {instance_id}")
    return 0


def cmd_instance_limit(args: argparse.Namespace) -> int:
    """Persist a spend limit for an instance."""
    if not args.monthly and not args.yearly:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="must specify --monthly or --yearly",
            remediation="pass --monthly or --yearly to set the billing period",
        )

    period = "monthly" if args.monthly else "yearly"
    auto_stop = bool(getattr(args, "auto_stop", False))

    from ec2.limits import Limit, save_limit

    limit = Limit(
        target=args.instance_id,
        amount=float(args.amount),
        period=period,
        auto_stop=auto_stop,
    )
    save_limit(limit)
    emit_result(
        f"limit set: {limit.target} ${limit.amount:.2f}/{period}"
        + (" (auto-stop)" if auto_stop else ""),
        json_mode=False,
    )
    return 0


def _deletion_preview(client: Any, instance_id: str) -> dict[str, Any] | None:
    """Return a snapshot of what terminating *instance_id* would destroy.

    ``None`` when the instance is not found. AWS errors map to CliError via
    :func:`ec2.aws.client.aws_call`.
    """
    from ec2.aws.client import aws_call

    resp = aws_call(client.describe_instances, InstanceIds=[instance_id])
    inst = None
    for reservation in resp.get("Reservations", []):
        for candidate in reservation.get("Instances", []):
            if candidate.get("InstanceId") == instance_id:
                inst = candidate
    if inst is None:
        return None

    name = ""
    for tag in inst.get("Tags", []) or []:
        if tag.get("Key") == "Name":
            name = tag.get("Value", "")
    volumes = []
    for bd in inst.get("BlockDeviceMappings", []):
        ebs = bd.get("Ebs", {})
        volumes.append(
            {
                "volume_id": ebs.get("VolumeId", ""),
                "device": bd.get("DeviceName", ""),
                "delete_on_termination": bool(ebs.get("DeleteOnTermination", False)),
            }
        )
    return {
        "id": instance_id,
        "type": inst.get("InstanceType", ""),
        "state": inst.get("State", {}).get("Name", ""),
        "name": name,
        "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
        "volumes": volumes,
    }


def _render_preview(preview: dict[str, Any]) -> str:
    lines = [
        f"# review: terminate {preview['id']} (IRREVERSIBLE)",
        "",
        "## Instance",
        f"  {preview['id']}  {preview['type']}  {preview['state']}  "
        f"{preview['name']}  {preview['az']}",
        "",
        "## EBS volumes that will be deleted on termination",
    ]
    deleted = [v for v in preview["volumes"] if v["delete_on_termination"]]
    kept = [v for v in preview["volumes"] if not v["delete_on_termination"]]
    if deleted:
        for v in deleted:
            lines.append(f"  - {v['volume_id']} ({v['device']})")
    else:
        lines.append("  (none)")
    if kept:
        lines.append("")
        lines.append("## Volumes that will be DETACHED but kept (DeleteOnTermination=false)")
        for v in kept:
            lines.append(f"  - {v['volume_id']} ({v['device']})")
    lines += [
        "",
        f"To terminate, run within {REVIEW_TTL_MINUTES} min:",
        f"  ec2 instance delete {preview['id']} --apply",
    ]
    return "\n".join(lines)


def cmd_instance_delete(args: argparse.Namespace) -> int:
    """Review a termination (default) or ``--apply`` it after a fresh review."""
    client = _get_client(args)
    instance_id = args.instance_id
    config_dir = getattr(args, "_config_dir", None)
    json_mode = bool(getattr(args, "json", False))

    if bool(getattr(args, "apply", False)):
        if deletion.fresh_review(instance_id, config_dir=config_dir) is None:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"no fresh review for {instance_id} (required before --apply)",
                remediation=(
                    f"run 'ec2 instance delete {instance_id}' to review what will be "
                    f"destroyed, then re-run with --apply within {REVIEW_TTL_MINUTES} min"
                ),
            )

        from ec2.aws.client import aws_call

        resp = aws_call(client.terminate_instances, InstanceIds=[instance_id])
        # Best-effort: if clearing the token fails (or the process is killed
        # here), re-running --apply is still safe — AWS rejects a duplicate
        # terminate on an already-terminating/gone instance.
        deletion.clear_review(instance_id, config_dir=config_dir)

        ti = (resp.get("TerminatingInstances") or [{}])[0]
        result = {
            "id": instance_id,
            "previous_state": ti.get("PreviousState", {}).get("Name"),
            "current_state": ti.get("CurrentState", {}).get("Name"),
        }
        if json_mode:
            emit_result(result, json_mode=True)
        else:
            emit_result(
                f"terminated {instance_id}: {result['previous_state']} -> "
                f"{result['current_state']} (DeleteOnTermination volumes are deleted)",
                json_mode=False,
            )
        return 0

    # Review mode — never terminates.
    preview = _deletion_preview(client, instance_id)
    if preview is None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"instance {instance_id} not found",
            remediation="check the id with 'ec2 instance'",
        )
    deletion.record_review(instance_id, preview, config_dir=config_dir)
    if json_mode:
        emit_result(
            {"review": preview, "apply_command": f"ec2 instance delete {instance_id} --apply"},
            json_mode=True,
        )
    else:
        emit_result(_render_preview(preview), json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def _no_verb(args: argparse.Namespace) -> int:
    """``ec2 instance`` with no sub-verb → list."""
    return cmd_instance(args)


def register(sub: argparse._SubParsersAction) -> None:
    """Register the ``instance`` noun and its sub-commands on *sub*."""
    noun = sub.add_parser(
        "instance",
        help="Manage EC2 instances (list, start, stop, limit, delete).",
    )
    noun.add_argument("--json", action="store_true", help="Emit structured JSON.")
    noun.set_defaults(func=_no_verb, json=False)

    sub_verb = noun.add_subparsers(dest="instance_command")

    # -- start ----------------------------------------------------------------
    p_start = sub_verb.add_parser("start", help="Start an instance.")
    p_start.add_argument("instance_id", help=_INSTANCE_ID_HELP)
    p_start.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    p_start.set_defaults(func=cmd_instance_start, yes=False)

    # -- stop -----------------------------------------------------------------
    p_stop = sub_verb.add_parser("stop", help="Stop an instance.")
    p_stop.add_argument("instance_id", help=_INSTANCE_ID_HELP)
    p_stop.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    p_stop.set_defaults(func=cmd_instance_stop, yes=False)

    # -- limit ----------------------------------------------------------------
    p_limit = sub_verb.add_parser("limit", help="Set a spend limit for an instance.")
    p_limit.add_argument("instance_id", help=_INSTANCE_ID_HELP)
    p_limit.add_argument("amount", type=float, help="Dollar amount.")
    p_limit.add_argument("--monthly", action="store_true", help="Monthly billing period.")
    p_limit.add_argument("--yearly", action="store_true", help="Yearly billing period.")
    p_limit.add_argument(
        "--auto-stop", action="store_true", help="Auto-stop when limit is reached."
    )
    p_limit.set_defaults(func=cmd_instance_limit, monthly=False, yearly=False, auto_stop=False)

    # -- delete ---------------------------------------------------------------
    p_delete = sub_verb.add_parser(
        "delete",
        help="Review a termination; --apply terminates (irreversible).",
    )
    p_delete.add_argument("instance_id", help=_INSTANCE_ID_HELP)
    p_delete.add_argument(
        "--apply",
        action="store_true",
        help="Terminate now (only valid after a fresh review of the same id).",
    )
    p_delete.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p_delete.set_defaults(func=cmd_instance_delete, apply=False, json=False)
