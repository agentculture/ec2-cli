"""Boundary contract: ec2/ must not reference forbidden AWS APIs.

The project deliberately avoids resize (ModifyInstanceAttribute for instance
type) and AWS Budgets / CloudWatch alarm APIs. This test scans every ``.py``
source file under ``ec2/`` and asserts that none of those strings appear.

Note: instance *termination* used to be forbidden here too, but it is now a
deliberate, review-gated feature (``ec2 instance delete --apply`` — see
:mod:`ec2.deletion`), so ``terminate_instances`` is intentionally allowed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Both the PascalCase API names (catch docstrings/comments implying the
# capability) AND the snake_case boto3 client methods / service identifiers a
# *real* call uses — checking only PascalCase is vacuous, because boto3 clients
# are invoked as client.modify_instance_attribute(...) / build_client("budgets").
_FORBIDDEN = [
    "ModifyInstanceAttribute",
    "modify_instance_attribute",
    "Budgets",
    '"budgets"',
    "CloudWatch",
    '"cloudwatch"',
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
