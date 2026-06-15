"""Boundary contract: ec2/ must not reference forbidden AWS APIs.

The project deliberately avoids TerminateInstances, ModifyInstanceAttribute
(for instance type changes), and AWS Budgets / CloudWatch alarm APIs.  This
test scans every ``.py`` source file under ``ec2/`` and asserts that none of
those strings appear.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_FORBIDDEN = [
    "TerminateInstances",
    "ModifyInstanceAttribute",
    "Budgets",
    "CloudWatch",
]


def _source_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1] / "ec2"
    return sorted(root.rglob("*.py"))


@pytest.mark.parametrize("forbidden", _FORBIDDEN)
def test_no_forbidden_api_references(forbidden: str) -> None:
    for src in _source_files():
        text = src.read_text(encoding="utf-8")
        assert (
            forbidden not in text
        ), f"{src.relative_to(src.parents[1])} references forbidden API: {forbidden}"
