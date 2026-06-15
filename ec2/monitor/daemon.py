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


def _run_check() -> list:
    """Run a single monitor check cycle.

    Imports are lazy so boto3 is not required at module level.
    Returns the list of findings from evaluate.
    """
    from datetime import datetime, timezone

    from ec2.limits import load_limits
    from ec2.monitor.alert import dispatch
    from ec2.monitor.evaluate import evaluate

    limits = load_limits()
    now = datetime.now(timezone.utc)
    # Use a 24-hour rolling window for the period bounds.
    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    period_end = period_start.replace(day=period_start.day + 1)
    if period_end <= period_start:
        period_end = period_start.replace(day=period_start.day + 2)

    findings = evaluate(
        limits=limits,
        per_machine_spend={},
        total_spend=0.0,
        now=now,
        period_bounds=(period_start, period_end),
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
            _run_check()
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
    """
    pid = _read_pid(pidfile)
    if pid is None or not _pid_alive(pid):
        return {"running": False, "pid": None}
    return {"running": True, "pid": pid}
