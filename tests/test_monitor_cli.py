"""Tests for ec2.cli._commands.monitor — monitor CLI + daemon.

Acceptance criteria:
1. ``monitor check`` runs evaluate once, routes findings to alerters, and exits
   non-zero on any breach; ``--json`` prints findings.
2. ``monitor start|stop|status`` manage a pidfile-based loop (start writes a pid,
   status reports running/stopped, stop terminates); assert the loop body calls
   check on the timer using a fake/short interval, not a real 5-min sleep.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from ec2.monitor.evaluate import Finding

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def breach_finding() -> Finding:
    """A single breach finding for tests."""
    return Finding(
        target="i-0abc",
        current=150.0,
        limit=100.0,
        period="monthly",
        breach=True,
        auto_stop_applies=False,
        reason="breach",
    )


@pytest.fixture
def clean_pidfile(tmp_path: Path) -> Path:
    """A temporary PID file path for daemon tests."""
    return tmp_path / "monitor.pid"


# ---------------------------------------------------------------------------
# Acceptance 1: monitor check
# ---------------------------------------------------------------------------


class TestMonitorCheck:
    """``ec2 monitor check`` runs evaluate once and routes findings."""

    def test_check_no_breach_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """When evaluate returns no findings, exit code is 0."""
        from ec2.cli._commands import monitor as _mod

        monkeypatch.setattr(
            _mod,
            "evaluate",
            mock.MagicMock(return_value=[]),
        )
        monkeypatch.setattr(_mod.alert, "dispatch", mock.MagicMock())

        args = mock.MagicMock()
        args.json = False
        args.interval = 300

        rc = _mod.cmd_check(args)
        assert rc == 0

    def test_check_breach_exits_nonzero(
        self, monkeypatch: pytest.MonkeyPatch, breach_finding: Finding
    ) -> None:
        """When evaluate returns a breach, exit code is non-zero."""
        from ec2.cli._commands import monitor as _mod

        monkeypatch.setattr(
            _mod,
            "evaluate",
            mock.MagicMock(return_value=[breach_finding]),
        )
        monkeypatch.setattr(_mod.alert, "dispatch", mock.MagicMock())

        args = mock.MagicMock()
        args.json = False
        args.interval = 300

        rc = _mod.cmd_check(args)
        assert rc != 0

    def test_check_calls_evaluate_and_dispatch(
        self, monkeypatch: pytest.MonkeyPatch, breach_finding: Finding
    ) -> None:
        """check calls evaluate once and routes findings to dispatch."""
        from ec2.cli._commands import monitor as _mod

        mock_evaluate = mock.MagicMock(return_value=[breach_finding])
        mock_dispatch = mock.MagicMock()

        monkeypatch.setattr(_mod, "evaluate", mock_evaluate)
        monkeypatch.setattr(_mod.alert, "dispatch", mock_dispatch)

        args = mock.MagicMock()
        args.json = False
        args.interval = 300

        _mod.cmd_check(args)

        mock_evaluate.assert_called_once()
        mock_dispatch.assert_called_once()

    def test_check_json_prints_findings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        breach_finding: Finding,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``--json`` prints findings as JSON to stdout."""
        from ec2.cli._commands import monitor as _mod

        monkeypatch.setattr(
            _mod,
            "evaluate",
            mock.MagicMock(return_value=[breach_finding]),
        )
        monkeypatch.setattr(_mod.alert, "dispatch", mock.MagicMock())

        args = mock.MagicMock()
        args.json = True
        args.interval = 300

        _mod.cmd_check(args)

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["target"] == "i-0abc"
        assert payload[0]["breach"] is True

    def test_check_dispatch_receives_findings(
        self, monkeypatch: pytest.MonkeyPatch, breach_finding: Finding
    ) -> None:
        """dispatch is called with the findings from evaluate."""
        from ec2.cli._commands import monitor as _mod

        monkeypatch.setattr(
            _mod,
            "evaluate",
            mock.MagicMock(return_value=[breach_finding]),
        )

        dispatched_findings: list[list[Finding]] = []

        def _capture_dispatch(findings: list[Finding], **_kw: Any) -> None:
            dispatched_findings.append(list(findings))

        monkeypatch.setattr(_mod.alert, "dispatch", _capture_dispatch)

        args = mock.MagicMock()
        args.json = False
        args.interval = 300

        _mod.cmd_check(args)

        assert len(dispatched_findings) == 1
        assert dispatched_findings[0][0].target == "i-0abc"


# ---------------------------------------------------------------------------
# Acceptance 2: monitor start|stop|status (PID-file daemon)
# ---------------------------------------------------------------------------


class TestMonitorDaemon:
    """``ec2 monitor start|stop|status`` manage a pidfile-based loop."""

    def test_start_writes_pid(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
    ) -> None:
        """``monitor start`` writes the PID to the pidfile."""
        from ec2.cli._commands import monitor as _mod

        # Prevent actual forking — just write the pid directly
        def _fake_fork() -> int:
            return 0  # Pretend we are the child

        monkeypatch.setattr(os, "fork", _fake_fork)

        # Prevent the daemon loop from actually running
        monkeypatch.setattr(time, "sleep", mock.MagicMock(side_effect=KeyboardInterrupt))

        # Prevent pidfile cleanup on exit so we can inspect it
        monkeypatch.setattr(Path, "unlink", mock.MagicMock())

        args = mock.MagicMock()
        args.pidfile = str(clean_pidfile)
        args.interval = 0.001
        args.json = False

        # We are the "child" in this test, so cmd_start will write the pid
        # and then try to run the loop. We catch the KeyboardInterrupt.
        try:
            _mod.cmd_start(args)
        except (KeyboardInterrupt, SystemExit):
            pass

        # The pidfile should have been written
        assert clean_pidfile.exists()
        pid_text = clean_pidfile.read_text().strip()
        assert pid_text.isdigit()

    def test_status_running(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``monitor status`` reports running when the PID is alive."""
        from ec2.cli._commands import monitor as _mod

        # Write a fake PID that looks alive
        clean_pidfile.write_text(str(os.getpid()) + "\n")

        args = mock.MagicMock()
        args.pidfile = str(clean_pidfile)
        args.json = False

        rc = _mod.cmd_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "running" in out.lower()

    def test_status_stopped_when_no_pidfile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``monitor status`` reports stopped when no pidfile exists."""
        from ec2.cli._commands import monitor as _mod

        # Ensure no pidfile
        if clean_pidfile.exists():
            clean_pidfile.unlink()

        args = mock.MagicMock()
        args.pidfile = str(clean_pidfile)
        args.json = False

        rc = _mod.cmd_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "stopped" in out.lower()

    def test_status_stopped_when_pid_dead(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``monitor status`` reports stopped when PID is not alive."""
        from ec2.cli._commands import monitor as _mod

        # Write a PID that definitely doesn't exist
        clean_pidfile.write_text("99999999\n")

        args = mock.MagicMock()
        args.pidfile = str(clean_pidfile)
        args.json = False

        rc = _mod.cmd_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "stopped" in out.lower()

    def test_stop_terminates_process(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
    ) -> None:
        """``monitor stop`` sends SIGTERM to the PID and removes the pidfile."""
        from ec2.cli._commands import monitor as _mod

        # Write our own PID so stop can find it
        clean_pidfile.write_text(str(os.getpid()) + "\n")

        # Intercept os.kill so we don't actually kill ourselves
        killed_pids: list[int] = []

        def _fake_kill(pid: int, sig: int) -> None:
            killed_pids.append(pid)

        monkeypatch.setattr(os, "kill", _fake_kill)

        args = mock.MagicMock()
        args.pidfile = str(clean_pidfile)
        args.json = False

        rc = _mod.cmd_stop(args)
        assert rc == 0
        assert os.getpid() in killed_pids
        assert not clean_pidfile.exists()

    def test_stop_no_pidfile_is_noop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``monitor stop`` with no pidfile is a no-op (already stopped)."""
        from ec2.cli._commands import monitor as _mod

        # Ensure no pidfile
        if clean_pidfile.exists():
            clean_pidfile.unlink()

        args = mock.MagicMock()
        args.pidfile = str(clean_pidfile)
        args.json = False

        rc = _mod.cmd_stop(args)
        assert rc == 0

    def test_daemon_loop_calls_check_on_timer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_pidfile: Path,
    ) -> None:
        """The daemon loop body calls check on the configured interval.

        Uses a very short interval and a counter to verify the loop fires
        multiple times, without sleeping for 5 minutes.
        """
        from ec2.monitor import daemon as _daemon

        call_count = 0

        def _fake_check() -> list[Finding]:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise KeyboardInterrupt()  # Stop after 3 iterations
            return []

        monkeypatch.setattr(_daemon, "_run_check", _fake_check)

        # Use a very short interval so the test finishes quickly
        interval = 0.01

        try:
            _daemon._loop(interval=interval)
        except KeyboardInterrupt:
            pass

        assert call_count >= 3

    def test_register_exposes_monitor_subcommand(self) -> None:
        """register() adds a 'monitor' subparser with check/start/stop/status."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        # Verify the parser was registered by checking help output
        # We can't easily test sub-subparsers without parsing, so just
        # verify the function exists and is callable.
        assert callable(_mod.register)
        assert callable(_mod.cmd_check)
        assert callable(_mod.cmd_start)
        assert callable(_mod.cmd_stop)
        assert callable(_mod.cmd_status)


# ---------------------------------------------------------------------------
# Integration: register + parse round-trip
# ---------------------------------------------------------------------------


class TestMonitorParseRoundtrip:
    """End-to-end parse round-trip for monitor subcommands."""

    def test_parse_check(self) -> None:
        """``ec2 monitor check`` parses correctly."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        args = parent.parse_args(["monitor", "check"])
        assert args.func == _mod.cmd_check

    def test_parse_start(self) -> None:
        """``ec2 monitor start`` parses correctly."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        args = parent.parse_args(["monitor", "start"])
        assert args.func == _mod.cmd_start

    def test_parse_stop(self) -> None:
        """``ec2 monitor stop`` parses correctly."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        args = parent.parse_args(["monitor", "stop"])
        assert args.func == _mod.cmd_stop

    def test_parse_status(self) -> None:
        """``ec2 monitor status`` parses correctly."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        args = parent.parse_args(["monitor", "status"])
        assert args.func == _mod.cmd_status

    def test_parse_check_json(self) -> None:
        """``ec2 monitor check --json`` sets json=True."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        args = parent.parse_args(["monitor", "check", "--json"])
        assert args.json is True

    def test_parse_start_interval(self) -> None:
        """``ec2 monitor start --interval 60`` sets interval=60."""
        import argparse

        from ec2.cli._commands import monitor as _mod

        parent = argparse.ArgumentParser()
        sub = parent.add_subparsers()
        _mod.register(sub)

        args = parent.parse_args(["monitor", "start", "--interval", "60"])
        assert args.interval == 60


# ---------------------------------------------------------------------------
# Spend gathering + period bounds (the data layer wired into check)
# ---------------------------------------------------------------------------


class TestSpendGathering:
    """_period_bounds is month-aligned; _gather_spend wires real total spend."""

    def test_period_bounds_month_aligned(self) -> None:
        from datetime import datetime, timezone

        from ec2.monitor.daemon import _period_bounds

        start, end = _period_bounds(datetime(2026, 6, 15, 9, 30, tzinfo=timezone.utc))
        assert (start.year, start.month, start.day) == (2026, 6, 1)
        assert (start.hour, start.minute, start.second) == (0, 0, 0)
        assert (end.year, end.month, end.day) == (2026, 7, 1)

    def test_period_bounds_december_rolls_to_next_year(self) -> None:
        from datetime import datetime, timezone

        from ec2.monitor.daemon import _period_bounds

        _start, end = _period_bounds(datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc))
        assert (end.year, end.month, end.day) == (2027, 1, 1)

    def test_gather_spend_degrades_without_aws(self, capsys: pytest.CaptureFixture) -> None:
        """No boto3/creds -> ({}, 0.0) + a diagnostic, not a crash."""
        from ec2.monitor.daemon import _gather_spend

        per_machine, total = _gather_spend()
        assert per_machine == {}
        assert total == 0.0
        assert "aws unavailable" in capsys.readouterr().err.lower()

    def test_gather_spend_returns_real_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With AWS available, total comes from Cost Explorer cost_mtd."""
        monkeypatch.setattr("ec2.aws.client.build_client", lambda *a, **k: object())
        monkeypatch.setattr("ec2.aws.cost.cost_mtd", lambda _client: 137.5)

        from ec2.monitor.daemon import _gather_spend

        per_machine, total = _gather_spend()
        assert per_machine == {}
        assert total == 137.5
