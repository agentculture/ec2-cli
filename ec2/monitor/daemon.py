"""Monitor daemon — background loop with PID-file management.

The daemon runs :func:`_run_check` on a configurable timer (default 300 s).
Management is via a PID file: ``start`` writes the PID and forks, ``stop``
sends SIGTERM, ``status`` checks whether the PID is alive.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ec2.cli._output import emit_diagnostic


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* is currently running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(pidfile: Path) -> int | None:
    """Read the PID from *pidfile*, or return ``None`` if missing/invalid."""
    if not pidfile.is_file():
        return None
    try:
        text = pidfile.read_text().strip()
        return int(text)
    except (ValueError, OSError):
        return None


def _period_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Current-month bounds ``[first-of-month 00:00, first-of-next-month 00:00)``.

    Month-aligned so the evaluator's run-rate projection is meaningful for
    monthly limits. (Aligning the window to yearly limits is a documented
    follow-up — hard-breach detection is correct regardless of the window.)
    """
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _gather_spend() -> tuple[dict[str, float], float]:
    """Return ``(per_machine_spend, total_spend)`` for the current month.

    ``total_spend`` is real EC2 month-to-date spend from Cost Explorer, so a
    monthly *total* limit is enforced end-to-end. ``per_machine_spend`` is left
    empty for now: it needs a price/usage-gathering layer (on-demand/spot rate ×
    running hours + EBS) — t5 built the estimate *formula* but nothing fetches
    its inputs yet. See the FOLLOW-UP note in the build plan.

    When AWS *setup* is unavailable (no boto3 / credentials / region) the spend
    can't be read this cycle: emit a diagnostic and report zero spend so the
    monitor degrades rather than crashing (the daemon must survive; a one-shot
    check shouldn't traceback). For a hard error on a broken AWS setup, use the
    action verb ``ec2 instance``.
    """
    from ec2.cli._errors import CliError

    try:
        from ec2.aws.client import build_client
        from ec2.aws.cost import cost_mtd

        ce_client = build_client("ce", region="us-east-1")
        return {}, cost_mtd(ce_client)
    except CliError as err:
        emit_diagnostic(f"monitor: AWS unavailable ({err.message}); spend assumed 0 this cycle")
        return {}, 0.0


def _run_check() -> list:
    """Run a single monitor check cycle: gather spend, evaluate, dispatch.

    Imports are lazy so boto3 is not required at module level.
    Returns the list of findings from evaluate.
    """
    from ec2.limits import load_limits
    from ec2.monitor.alert import dispatch
    from ec2.monitor.evaluate import evaluate

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
        dispatch(findings)

    return findings


def _loop(interval: float = 300.0) -> None:
    """Run the monitor loop: check every *interval* seconds.

    Exits on ``KeyboardInterrupt`` (SIGTERM / SIGINT).
    """
    emit_diagnostic(f"monitor daemon: loop started (interval={interval}s)")
    try:
        while True:
            try:
                _run_check()
            except Exception as exc:  # a transient AWS error must not kill the daemon
                emit_diagnostic(f"monitor daemon: check failed ({exc}); continuing")
            time.sleep(interval)
    except KeyboardInterrupt:
        emit_diagnostic("monitor daemon: loop stopped")


def start(pidfile: Path, interval: float = 300.0) -> int:
    """Start the monitor daemon.

    Forks a child process that writes its PID to *pidfile* and runs
    :func:`_loop`.  The parent returns immediately with the child PID.

    Returns the child PID on success.
    """
    if pidfile.exists():
        existing = _read_pid(pidfile)
        if existing is not None and _pid_alive(existing):
            emit_diagnostic(f"monitor daemon: already running (pid {existing})")
            return existing

    pid = os.fork()
    if pid > 0:
        # Parent: return immediately
        emit_diagnostic(f"monitor daemon: started (pid {pid})")
        return pid

    # Child: write PID and run the loop
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()) + "\n")

    # Detach from controlling terminal
    try:
        os.setsid()
    except OSError:
        pass

    _loop(interval=interval)
    # Clean up pidfile on exit
    try:
        pidfile.unlink(missing_ok=True)
    except OSError:
        pass

    sys.exit(0)


def stop(pidfile: Path) -> bool:
    """Stop the monitor daemon.

    Sends SIGTERM to the PID in *pidfile* and removes the file.
    Returns True if a process was terminated, False if already stopped.
    """
    if not pidfile.exists():
        return False

    pid = _read_pid(pidfile)
    if pid is None:
        pidfile.unlink(missing_ok=True)
        return False

    if not _pid_alive(pid):
        # Stale pidfile — clean up
        pidfile.unlink(missing_ok=True)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    pidfile.unlink(missing_ok=True)
    return True


def status(pidfile: Path) -> dict[str, object]:
    """Return the daemon status as a dict.

    Keys:
        - running (bool): whether the daemon is currently running.
        - pid (int | None): PID of the running daemon, or None.
        - stale (bool): True when a pidfile exists but its PID is dead
          (a crashed/leftover daemon), distinct from never-started.
    """
    pid = _read_pid(pidfile)
    if pid is None:
        return {"running": False, "pid": None, "stale": False}
    if not _pid_alive(pid):
        return {"running": False, "pid": None, "stale": True}
    return {"running": True, "pid": pid, "stale": False}
