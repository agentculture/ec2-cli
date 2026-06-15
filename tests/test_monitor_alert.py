"""Tests for ec2.monitor.alert — alert dispatch to enabled channels.

Acceptance criteria:
1. On a breach finding, the CULTURE.DEV mesh sender and the stderr baseline
   both emit a structured alert (assert via injected sender + captured stderr).
2. OTEL-log and webhook are optional and lazy-imported so an absent dependency
   disables that channel rather than crashing.
"""

from __future__ import annotations

from typing import Any

import pytest

from ec2.monitor.alert import dispatch
from ec2.monitor.evaluate import Finding

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def breach_finding() -> Finding:
    """A single breach finding for alert tests."""
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
def projected_finding() -> Finding:
    """A projected (non-breach) finding."""
    return Finding(
        target="i-0def",
        current=60.0,
        limit=100.0,
        period="monthly",
        breach=False,
        auto_stop_applies=False,
        reason="projected",
    )


# ---------------------------------------------------------------------------
# Acceptance 1: stderr baseline + CULTURE.DEV mesh sender
# ---------------------------------------------------------------------------


class TestStderrBaselineAndMeshSender:
    """stderr baseline is ALWAYS on; CULTURE.DEV mesh sender is called."""

    def test_stderr_baseline_emits_structured_alert(
        self, breach_finding: Finding, capsys: pytest.CaptureFixture
    ) -> None:
        """Even with no channels, stderr baseline emits a diagnostic line."""
        dispatch([breach_finding], channels=[])

        stderr = capsys.readouterr().err
        assert "alert" in stderr.lower()
        assert breach_finding.target in stderr

    def test_mesh_sender_called_with_structured_alert(self, breach_finding: Finding) -> None:
        """CULTURE.DEV mesh sender receives a structured alert dict."""
        received: list[dict[str, Any]] = []

        def mock_sender(alert: dict[str, Any]) -> None:
            received.append(alert)

        dispatch(
            [breach_finding],
            channels=["culture.dev"],
            senders={"culture.dev": mock_sender},
        )

        assert len(received) == 1
        alert = received[0]
        assert alert["target"] == breach_finding.target
        assert alert["breach"] is True
        assert alert["reason"] == "breach"

    def test_both_stderr_and_mesh_on_breach(
        self, breach_finding: Finding, capsys: pytest.CaptureFixture
    ) -> None:
        """Both stderr baseline and CULTURE.DEV mesh emit on a breach."""
        received: list[dict[str, Any]] = []

        def mock_sender(alert: dict[str, Any]) -> None:
            received.append(alert)

        dispatch(
            [breach_finding],
            channels=["culture.dev"],
            senders={"culture.dev": mock_sender},
        )

        stderr = capsys.readouterr().err
        assert len(received) == 1
        assert breach_finding.target in stderr

    def test_multiple_findings_produce_multiple_alerts(
        self, breach_finding: Finding, projected_finding: Finding
    ) -> None:
        """Each finding produces its own alert to each enabled channel."""
        received: list[dict[str, Any]] = []

        def mock_sender(alert: dict[str, Any]) -> None:
            received.append(alert)

        dispatch(
            [breach_finding, projected_finding],
            channels=["culture.dev"],
            senders={"culture.dev": mock_sender},
        )

        assert len(received) == 2
        targets = [a["target"] for a in received]
        assert breach_finding.target in targets
        assert projected_finding.target in targets

    def test_empty_findings_produces_no_alerts(self, capsys: pytest.CaptureFixture) -> None:
        """No findings → no alerts emitted."""
        dispatch([], channels=["culture.dev"])

        stderr = capsys.readouterr().err
        assert "alert" not in stderr.lower()


# ---------------------------------------------------------------------------
# Acceptance 2: OTEL channel degrades gracefully when dep absent
# ---------------------------------------------------------------------------


class TestOtelChannelDegrades:
    """OTEL-log channel disables itself when opentelemetry is absent."""

    def test_otel_channel_missing_dep_emits_diagnostic(
        self, breach_finding: Finding, capsys: pytest.CaptureFixture
    ) -> None:
        """When opentelemetry is not installed, the OTEL channel emits a
        diagnostic and does NOT crash."""
        dispatch(
            [breach_finding],
            channels=["otel"],
        )

        stderr = capsys.readouterr().err
        # Should have a diagnostic about the missing dependency
        assert "otel" in stderr.lower() or "opentelemetry" in stderr.lower()

    def test_otel_channel_does_not_crash(self, breach_finding: Finding) -> None:
        """dispatch with otel channel should not raise when dep is missing."""
        # This should complete without raising
        dispatch(
            [breach_finding],
            channels=["otel"],
        )


# ---------------------------------------------------------------------------
# Acceptance 3: webhook channel
# ---------------------------------------------------------------------------


class TestWebhookChannel:
    """Webhook channel POSTs JSON to a configured URL."""

    def test_webhook_sender_called_with_json_payload(self, breach_finding: Finding) -> None:
        """Webhook sender receives a structured alert dict."""
        received: list[dict[str, Any]] = []

        def mock_webhook(url: str, payload: dict[str, Any]) -> None:
            received.append(payload)

        dispatch(
            [breach_finding],
            channels=["webhook"],
            senders={"webhook": mock_webhook},
        )

        assert len(received) == 1
        assert received[0]["target"] == breach_finding.target

    def test_webhook_with_url_config(self, breach_finding: Finding) -> None:
        """Webhook channel uses the configured URL from channels config."""
        received_urls: list[str] = []
        received_payloads: list[dict[str, Any]] = []

        def mock_webhook(url: str, payload: dict[str, Any]) -> None:
            received_urls.append(url)
            received_payloads.append(payload)

        dispatch(
            [breach_finding],
            channels=["webhook"],
            senders={"webhook": mock_webhook},
            channel_config={"webhook": {"url": "https://hooks.example.com/alert"}},
        )

        assert len(received_urls) == 1
        assert received_urls[0] == "https://hooks.example.com/alert"


# ---------------------------------------------------------------------------
# Acceptance 4: default sender degrades gracefully
# ---------------------------------------------------------------------------


class TestDefaultSenderDegrades:
    """The default CULTURE.DEV sender degrades when no transport is available."""

    def test_default_sender_does_not_crash(
        self, breach_finding: Finding, capsys: pytest.CaptureFixture
    ) -> None:
        """Using the default sender (no custom sender injected) should not crash."""
        dispatch(
            [breach_finding],
            channels=["culture.dev"],
        )

        # Should complete without raising; stderr may have a degradation note
        stderr = capsys.readouterr().err
        # At minimum, the stderr baseline alert should be present
        assert breach_finding.target in stderr
