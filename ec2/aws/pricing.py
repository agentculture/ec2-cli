"""Per-machine layered cost estimate — spot/on-demand rate × hours + EBS.

All price/volume lookups are injected (callables or plain values) so callers
and tests never need live AWS.  Missing data *degrades* (best-effort figure
plus a note) rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Estimate:
    """Cost estimate for a single instance."""

    figure: float
    label: str = "ESTIMATE"
    exclusions: list[str] = field(
        default_factory=lambda: ["RI/Savings-Plan discounts", "data transfer"]
    )
    notes: list[str] = field(default_factory=list)


def estimate_cost(
    instance: object,
    *,
    ondemand_rate: float | None,
    spot_rate: float | None,
    running_hours: float,
    ebs_monthly: float | None,
) -> Estimate:
    """Return a per-machine cost estimate.

    Parameters
    ----------
    instance:
        An :class:`Instance` (or any object with ``lifecycle`` and ``state``
        attributes).
    ondemand_rate:
        On-demand hourly rate in USD, or ``None`` when unavailable.
    spot_rate:
        Spot hourly rate in USD, or ``None`` when unavailable.
    running_hours:
        Number of hours the instance was running in the period.
    ebs_monthly:
        Monthly EBS cost in USD, or ``None`` when unavailable.

    Returns
    -------
    Estimate
        Best-effort figure with notes when any lookup degraded.
    """
    notes: list[str] = []

    # --- Pick the right rate with fallback chain ---------------------------
    lifecycle = getattr(instance, "lifecycle", "on-demand")
    if lifecycle == "spot":
        rate = spot_rate
        if rate is None:
            rate = ondemand_rate
            if rate is None:
                notes.append(
                    "spot rate unavailable; on-demand rate also missing — compute cost set to 0"
                )
                rate = 0.0
            else:
                notes.append("spot rate unavailable; fell back to on-demand rate")
    else:
        rate = ondemand_rate
        if rate is None:
            notes.append("on-demand rate unavailable — compute cost set to 0")
            rate = 0.0

    # --- Compute cost (0 when stopped) -----------------------------------
    state = getattr(instance, "state", "running")
    if state == "stopped":
        compute = 0.0
    else:
        compute = rate * running_hours

    # --- EBS cost (counted even when stopped ----------------------------
    if ebs_monthly is None:
        ebs = 0.0
        notes.append("EBS volume cost unavailable — EBS set to 0")
    else:
        ebs = ebs_monthly

    return Estimate(figure=compute + ebs, notes=notes)
