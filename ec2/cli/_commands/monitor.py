"""``ec2 monitor`` — spend monitoring CLI + background daemon.

Sub-commands
------------
* ``ec2 monitor check`` — run evaluate once, dispatch alerts, exit non-zero
  on breach.
* ``ec2 monitor start`` — start the background daemon loop.
* ``ec2 monitor stop`` — stop the background daemon.
* ``ec2 monitor status`` — report daemon running/stopped.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ec2.cli._output import emit_diagnostic, emit_result
from ec2.monitor import alert
from ec2.monitor.daemon import _gather_spend, _period_bounds
from ec2.monitor.daemon import start as daemon_start
from ec2.monitor.daemon import status as daemon_status
from ec2.monitor.daemon import stop as daemon_stop
from ec2.monitor.evaluate import evaluate


def _get_interval(args: argparse.Namespace) -> float:
    """Return the monitor interval from args or environment, default 300 s."""
    if hasattr(args, "interval") and args.interval is not None:
        return float(args.interval)
    from os import environ

    env_val = environ.get("EC2_MONITOR_INTERVAL")
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    return 300.0


def _get_pidfile(args: argparse.Namespace) -> Path:
    """Return the PID file path from args or default."""
    if hasattr(args, "pidfile") and args.pidfile:
        return Path(args.pidfile)
    from os import environ

    env_path = environ.get("EC2_MONITOR_PIDFILE")
    if env_path:
        return Path(env_path)
    return Path("/tmp/ec2-monitor.pid")  # nosec B108


def cmd_check(args: argparse.Namespace) -> int:
    """Run a single monitor check: evaluate + dispatch.

    Exits non-zero if any finding is a breach.
    """
    from datetime import datetime, timezone

    from ec2.limits import load_limits

    limits = load_limits()
    now = datetime.now(timezone.utc)
    per_machine_spend, total_spend = _gather_spend()

    findings = evaluate(
        limits=limits,
        per_machine_spend=per_machine_spend,
        total_spend=total_spend,
        now=now,
        period_bounds=_period_bounds(now),
    )

    if findings:
        alert.dispatch(findings)

    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result([f.to_dict() for f in findings], json_mode=True)

    if any(f.breach for f in findings):
        return 1
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Start the background monitor daemon."""
    interval = _get_interval(args)
    pidfile = _get_pidfile(args)

    pid = daemon_start(pidfile, interval=interval)
    emit_result(f"monitor daemon started (pid {pid})", json_mode=False)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop the background monitor daemon."""
    pidfile = _get_pidfile(args)

    stopped = daemon_stop(pidfile)
    if stopped:
        emit_diagnostic("monitor daemon stopped")
    else:
        emit_diagnostic("monitor daemon was not running")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Report the monitor daemon status."""
    pidfile = _get_pidfile(args)

    info = daemon_status(pidfile)
    json_mode = bool(getattr(args, "json", False))

    if json_mode:
        emit_result(info, json_mode=True)
    else:
        if info["running"]:
            emit_result(f"monitor daemon running (pid {info['pid']})", json_mode=False)
        else:
            emit_result("monitor daemon stopped", json_mode=False)
    return 0


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def register(sub: argparse._SubParsersAction) -> None:
    """Register the ``monitor`` noun and its sub-commands on *sub*."""
    noun = sub.add_parser(
        "monitor",
        help="Spend monitoring (check, start/stop/status daemon).",
    )
    noun.add_argument("--json", action="store_true", help="Emit structured JSON.")
    noun.set_defaults(func=cmd_status, json=False)

    sub_verb = noun.add_subparsers(dest="monitor_command")

    # -- check ----------------------------------------------------------------
    p_check = sub_verb.add_parser("check", help="Run a single monitor check.")
    p_check.add_argument("--json", action="store_true", help="Emit findings as JSON.")
    p_check.set_defaults(func=cmd_check, json=False)

    # -- start ----------------------------------------------------------------
    p_start = sub_verb.add_parser("start", help="Start the background monitor daemon.")
    p_start.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Check interval in seconds (default: 300, override with EC2_MONITOR_INTERVAL).",
    )
    p_start.add_argument(
        "--pidfile",
        default=None,
        help="PID file path (default: /tmp/ec2-monitor.pid, override with EC2_MONITOR_PIDFILE).",
    )
    p_start.set_defaults(func=cmd_start, interval=None, pidfile=None)

    # -- stop -----------------------------------------------------------------
    p_stop = sub_verb.add_parser("stop", help="Stop the background monitor daemon.")
    p_stop.add_argument(
        "--pidfile",
        default=None,
        help="PID file path (default: /tmp/ec2-monitor.pid, override with EC2_MONITOR_PIDFILE).",
    )
    p_stop.set_defaults(func=cmd_stop, pidfile=None)

    # -- status ---------------------------------------------------------------
    p_status = sub_verb.add_parser("status", help="Report monitor daemon status.")
    p_status.add_argument("--json", action="store_true", help="Emit status as JSON.")
    p_status.add_argument(
        "--pidfile",
        default=None,
        help="PID file path (default: /tmp/ec2-monitor.pid, override with EC2_MONITOR_PIDFILE).",
    )
    p_status.set_defaults(func=cmd_status, json=False, pidfile=None)
