"""Pending-deletion review store for ``ec2 instance delete``.

``ec2 instance delete <id>`` is a two-step, irreversible operation: the first
call *reviews* what would be destroyed and records a short-lived review token;
``--apply`` only terminates when a **fresh** token exists for that exact
instance id. This module persists those tokens to a local JSON file under the
same config dir as :mod:`ec2.limits`.

Tokens expire after :data:`REVIEW_TTL_SECONDS` so a stale, forgotten review can
never silently arm a later ``--apply``.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from ec2.cli._errors import EXIT_ENV_ERROR, CliError
from ec2.limits import _config_dir

# A review is only valid for a short window — fresh-review gate.
REVIEW_TTL_SECONDS = 15 * 60


def _reviews_file(config_dir: Path | None = None) -> Path:
    """Return the path to the deletion-review token file."""
    return _config_dir(config_dir) / "ec2-cli" / "deletion_reviews.json"


def record_review(
    instance_id: str,
    snapshot: dict[str, Any],
    *,
    config_dir: Path | None = None,
    now: float | None = None,
) -> None:
    """Record a review token for *instance_id* (with the reviewed *snapshot*)."""
    stamp = time.time() if now is None else now
    path = _reviews_file(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(path)
    data[instance_id] = {"at": stamp, "snapshot": snapshot}
    _write(path, data)


def fresh_review(
    instance_id: str,
    *,
    config_dir: Path | None = None,
    now: float | None = None,
    ttl: float = REVIEW_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Return the review token for *instance_id* if one exists and is fresh.

    Returns ``None`` when there is no token or it is older than *ttl* seconds.
    """
    stamp = time.time() if now is None else now
    rec = _read(_reviews_file(config_dir)).get(instance_id)
    if not isinstance(rec, dict):
        return None
    at = _parse_at(rec.get("at"))
    if at is None:
        # Missing, non-numeric, or non-finite `at` -> no usable timestamp.
        # Fail *safe*: treat the token as expired rather than crashing or (worse)
        # letting NaN/Inf defeat the TTL check and arm a stale `--apply`.
        return None
    # `>` (not `>=`): a review at exactly the TTL boundary is still valid; the
    # window closes strictly *after* ttl seconds.
    if stamp - at > ttl:
        return None
    return rec


def clear_review(instance_id: str, *, config_dir: Path | None = None) -> None:
    """Remove the review token for *instance_id* (no-op if absent)."""
    path = _reviews_file(config_dir)
    data = _read(path)
    if instance_id in data:
        del data[instance_id]
        _write(path, data)


# -- private helpers --------------------------------------------------------


def _parse_at(value: Any) -> float | None:
    """Coerce a persisted ``at`` timestamp to a finite float, else ``None``.

    The review file is local state that can be hand-edited or corrupted. A
    non-numeric value (``float(...)`` raises) or a non-finite float — ``json``
    accepts ``NaN``/``Infinity`` by default, and ``stamp - NaN > ttl`` is
    ``False``, which would make a stale token look perpetually fresh — must
    fail safe: return ``None`` so the caller treats it as an expired token.
    """
    try:
        at = float(value)
    except (TypeError, ValueError):
        return None
    return at if math.isfinite(at) else None


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return {}
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    # Guard the write sink to our own review file under an ec2-cli/ dir.
    if path.name != "deletion_reviews.json" or path.parent.name != "ec2-cli":
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="refusing to write deletion reviews to an unexpected path",
            remediation="the review file must be <config>/ec2-cli/deletion_reviews.json",
        )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
