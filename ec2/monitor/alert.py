"""Alert dispatcher — routes structured alerts per breach finding.

Channels
--------
- **stderr baseline**: always on; emits a structured alert line to stderr.
- **CULTURE.DEV mesh**: native channel; send via an injectable sender (default
  degrades gracefully when no transport is available).
- **OTEL log**: optional; lazy-imports ``opentelemetry``; if absent the channel
  disables itself with a diagnostic rather than crashing.
- **webhook**: optional; stdlib ``urllib`` POST of JSON to a configured URL.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ec2.cli._output import emit_diagnostic
from ec2.monitor.evaluate import Finding

# -- sender types -----------------------------------------------------------

Sender = Callable[[dict[str, Any]], None]
WebhookSender = Callable[[str, dict[str, Any]], None]


# -- default CULTURE.DEV sender (degrades gracefully) ----------------------


def _default_culture_dev_sender(alert: dict[str, Any]) -> None:
    """Default CULTURE.DEV mesh sender.

    Degrades gracefully when no transport is available by emitting a
    diagnostic to stderr instead of crashing.
    """
    emit_diagnostic(
        f"culture.dev: no transport available; alert for {alert.get('target', '?')} "
        f"logged to stderr only"
    )


# -- alert payload builder --------------------------------------------------


def _build_alert(finding: Finding) -> dict[str, Any]:
    """Build a structured alert dict from a :class:`Finding`."""
    return {
        "type": "alert",
        "target": finding.target,
        "current": finding.current,
        "limit": finding.limit,
        "period": finding.period,
        "breach": finding.breach,
        "auto_stop_applies": finding.auto_stop_applies,
        "reason": finding.reason,
    }


# -- channel dispatchers ----------------------------------------------------


def _dispatch_stderr(alert: dict[str, Any]) -> None:
    """Emit a structured alert line to stderr (always on)."""
    emit_diagnostic(f"ALERT: {json.dumps(alert, ensure_ascii=False)}")


def _dispatch_culture_dev(
    alert: dict[str, Any],
    senders: dict[str, Sender] | None,
) -> None:
    """Route alert to CULTURE.DEV mesh via the injected sender."""
    sender = (senders or {}).get("culture.dev", _default_culture_dev_sender)
    sender(alert)


def _dispatch_otel(alert: dict[str, Any]) -> None:
    """Route alert to OTEL log.

    Lazy-imports opentelemetry; if absent, emits a diagnostic and returns.
    """
    try:
        # Lazy import succeeded — use the logger
        from opentelemetry import logs  # noqa: F401
        from opentelemetry import trace  # noqa: F401

        logger = logs.get_logger("ec2.alert")
        logger.info("EC2 alert", **alert)
    except ImportError:
        emit_diagnostic("otel: opentelemetry not installed; channel disabled")


def _dispatch_webhook(
    alert: dict[str, Any],
    senders: dict[str, WebhookSender] | None,
    channel_config: dict[str, dict[str, Any]] | None,
) -> None:
    """Route alert to webhook via POST.

    Uses an injectable sender for testability; falls back to stdlib urllib
    when no custom sender is provided.
    """
    sender: WebhookSender | None = (senders or {}).get("webhook")
    if sender:
        config = (channel_config or {}).get("webhook", {})
        url = config.get("url", "")
        sender(url, alert)
        return

    # No custom sender — use stdlib urllib POST
    config = (channel_config or {}).get("webhook", {})
    url = config.get("url", "")

    if not url:
        emit_diagnostic("webhook: no URL configured; channel disabled")
        return

    import urllib.request

    data = json.dumps(alert, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req):
            pass
    except Exception as exc:
        emit_diagnostic(f"webhook: POST to {url} failed: {exc}")


# -- public API -------------------------------------------------------------


def dispatch(
    findings: list[Finding],
    *,
    channels: list[str] | None = None,
    senders: dict[str, Callable[..., Any]] | None = None,
    channel_config: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Route structured alerts per breach finding to enabled channels.

    Parameters
    ----------
    findings:
        List of :class:`Finding` objects to alert on.
    channels:
        Channel names to enable (e.g. ``["culture.dev", "otel", "webhook"]``).
        Defaults to ``["culture.dev"]`` when not provided.
    senders:
        Optional mapping of channel name → sender callable for injection.
    channel_config:
        Optional per-channel configuration (e.g. webhook URL).
    """
    if channels is None:
        channels = ["culture.dev"]

    for finding in findings:
        alert = _build_alert(finding)

        # Stderr baseline — always on
        _dispatch_stderr(alert)

        for channel in channels:
            if channel == "culture.dev":
                _dispatch_culture_dev(alert, senders)
            elif channel == "otel":
                _dispatch_otel(alert)
            elif channel == "webhook":
                _dispatch_webhook(alert, senders, channel_config)
            else:
                emit_diagnostic(f"alert: unknown channel '{channel}'")
