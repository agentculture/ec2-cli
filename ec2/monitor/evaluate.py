"""Monitor evaluator — pure function, no side effects, no AWS client.

Compares per-machine (layered estimate) and total (Cost Explorer) spend
against configured :class:`ec2.limits.Limit` objects and returns a list of
:class:`Finding` objects.

SPIKE RULE (run-rate projection)
--------------------------------
Project the current run-rate to the end of the period.  If the *projected*
end-of-period spend exceeds the limit, raise a finding with
``reason="projected"``.  A hard breach (``current >= limit``) also raises
with ``reason="breach"``.

auto_stop_applies is True **only** for a *breached* target whose limit has
``auto_stop=True``; otherwise False (default alert-only).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ec2.limits import Limit


@dataclass
class Finding:
    """Result of evaluating one target against its limit."""

    target: str
    current: float
    limit: float
    period: str
    breach: bool
    auto_stop_applies: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict."""
        return {
            "target": self.target,
            "current": self.current,
            "limit": self.limit,
            "period": self.period,
            "breach": self.breach,
            "auto_stop_applies": self.auto_stop_applies,
            "reason": self.reason,
        }


def evaluate(
    *,
    limits: list[Limit],
    per_machine_spend: dict[str, float],
    total_spend: float,
    now: datetime,
    period_bounds: tuple[datetime, datetime],
) -> list[Finding]:
    """Evaluate spend against limits and return findings.

    Parameters
    ----------
    limits:
        Configured spend limits to check.
    per_machine_spend:
        Mapping of instance ID → current spend (layered estimate).
    total_spend:
        Aggregate spend for the period (Cost Explorer).
    now:
        Current reference time.
    period_bounds:
        ``(start, end)`` of the evaluation period.

    Returns
    -------
    list[Finding]
        Findings for targets that breach or are projected to breach.
    """
    findings: list[Finding] = []
    period_start, period_end = period_bounds

    for limit in limits:
        if limit.target == "total":
            current = total_spend
        elif limit.target in per_machine_spend:
            current = per_machine_spend[limit.target]
        else:
            # Limit targets an instance not in spend data — skip.
            continue

        # Hard breach check
        if current >= limit.amount:
            findings.append(
                Finding(
                    target=limit.target,
                    current=current,
                    limit=limit.amount,
                    period=limit.period,
                    breach=True,
                    auto_stop_applies=limit.auto_stop,
                    reason="breach",
                )
            )
            continue

        # Run-rate projection (spike rule)
        projected = _project(current, now, period_start, period_end)
        if projected > limit.amount:
            findings.append(
                Finding(
                    target=limit.target,
                    current=current,
                    limit=limit.amount,
                    period=limit.period,
                    breach=False,
                    auto_stop_applies=False,
                    reason="projected",
                )
            )

    return findings


def _project(
    current: float,
    now: datetime,
    period_start: datetime,
    period_end: datetime,
) -> float:
    """Project *current* spend to end-of-period using run-rate.

    projected = current / (elapsed / total_period)

    When elapsed is zero, returns current (no projection possible).
    """
    total_delta = (period_end - period_start).total_seconds()
    elapsed = (now - period_start).total_seconds()

    if total_delta <= 0 or elapsed <= 0:
        return current

    return current * (total_delta / elapsed)


def findings_to_json(findings: list[Finding]) -> str:
    """Render a list of :class:`Finding` as a JSON array string."""
    return json.dumps([f.to_dict() for f in findings], ensure_ascii=False)
