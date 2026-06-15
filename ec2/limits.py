"""Spend-limit config store (stdlib only).

Persists :class:`Limit` objects to a local JSON file at
``~/.config/ec2-cli/limits.json``.  Uses only :mod:`json`, :mod:`pathlib`,
and :dataclass:`dataclasses`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ec2.cli._errors import EXIT_ENV_ERROR, CliError


@dataclass
class Limit:
    """A spend limit for an EC2 instance or the aggregate total."""

    target: str
    amount: float
    period: str
    auto_stop: bool = False


def _config_dir(config_dir: Path | None = None) -> Path:
    """Return the config directory for ec2-cli (``~/.config`` by default).

    When *config_dir* is provided (e.g. in tests), it is used directly. The
    path is intentionally derived from ``Path.home()`` and fixed literals (not
    from environment variables) so the write target can't be steered by
    user-controlled input.
    """
    if config_dir is not None:
        return config_dir
    return Path.home() / ".config"


def _limits_file(config_dir: Path | None = None) -> Path:
    """Return the full path to the limits JSON file."""
    base = _config_dir(config_dir)
    return base / "ec2-cli" / "limits.json"


def save_limit(limit: Limit, config_dir: Path | None = None) -> None:
    """Persist *limit* to the local JSON config file.

    Idempotent per target: any existing limit with the same target is
    replaced (not duplicated), so re-setting a target's limit updates it.
    Creates parent directories as needed.
    """
    path = _limits_file(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_raw(path)
    deduped = [e for e in existing if not (isinstance(e, dict) and e.get("target") == limit.target)]
    deduped.append(asdict(limit))
    _write_raw(path, deduped)


def load_limits(config_dir: Path | None = None) -> list[Limit]:
    """Return all persisted limits.

    Returns an empty list when the config file is missing, empty, or
    contains malformed data — never raises.
    """
    path = _limits_file(config_dir)
    raw = _read_raw(path)
    limits: list[Limit] = []
    for entry in raw:
        limit = _dict_to_limit(entry)
        if limit is not None:
            limits.append(limit)
    return limits


def lookup_limit_by_target(target: str, config_dir: Path | None = None) -> Limit | None:
    """Return the first limit matching *target*, or ``None``."""
    for limit in load_limits(config_dir=config_dir):
        if limit.target == target:
            return limit
    return None


# -- private helpers --------------------------------------------------------


def _read_raw(path: Path) -> list[dict[str, Any]]:
    """Read the raw JSON array from *path*.

    Returns an empty list when the file is missing, empty, or malformed.
    """
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _write_raw(path: Path, data: list[dict[str, Any]]) -> None:
    """Write *data* as a JSON array to *path*.

    Guards the write sink: the destination must be our own limits file
    (``<config>/ec2-cli/limits.json``), never an attacker-steered path
    (path-injection defense, SonarCloud S2083).
    """
    if path.name != "limits.json" or path.parent.name != "ec2-cli":
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="refusing to write the limits file to an unexpected path",
            remediation="the limits file must be <config>/ec2-cli/limits.json",
        )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _dict_to_limit(entry: dict[str, Any]) -> Limit | None:
    """Convert a dict to a :class:`Limit`, returning ``None`` on bad data."""
    try:
        return Limit(
            target=entry["target"],
            amount=float(entry["amount"]),
            period=entry["period"],
            auto_stop=bool(entry.get("auto_stop", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None
