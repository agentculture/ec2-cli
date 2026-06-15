"""``ec2 overview`` — live dashboard (fleet + cost figures).

The top-level ``ec2 overview`` renders a live dashboard: the fleet
(:func:`ec2.aws.fleet.list_instances`) plus four EC2-service cost figures
(:func:`ec2.aws.cost.cost_mtd`, :func:`ec2.aws.cost.cost_ytd`,
:func:`ec2.aws.cost.forecast_month`, :func:`ec2.aws.cost.forecast_year`).

Human table by default; ``--json`` emits a structured payload. Results to
STDOUT only; AWS failures surface as :class:`CliError` via
:func:`ec2.aws.client.build_client`.

The shared section/render helpers here are reused by the ``cli`` noun's
``overview`` (see :mod:`ec2.cli._commands.cli`), which still emits the
descriptive agent self-report.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from typing import Any

from ec2.cli._output import emit_diagnostic, emit_result

# ---------------------------------------------------------------------------
# Descriptive overview helpers (reused by ``cli overview``)
# ---------------------------------------------------------------------------

_ARTIFACTS = [
    "culture.yaml + CLAUDE.md — mesh identity (suffix + backend)",
    ".claude/skills/ — the canonical guildmaster skill kit (cite-don't-import)",
    "docs/skill-sources.md — skill provenance ledger",
    "pyproject.toml + .github/workflows/ — buildable, deployable package baseline",
]

_VERBS = [
    "whoami — identity probe (nick, version, backend, model)",
    "learn — structured self-teaching prompt",
    "explain <path> — markdown docs for a topic",
    "overview — live dashboard (fleet + cost figures)",
    "doctor — check the agent-identity invariants",
]


def agent_sections() -> list[dict[str, object]]:
    """Sections describing the agent (used by the global verb)."""
    from ec2.cli._commands.whoami import report

    ident = report()
    return [
        {
            "title": "Identity",
            "items": [
                f"nick: {ident['nick']}",
                f"version: {ident['version']}",
                f"backend: {ident['backend']}",
                f"model: {ident['model']}",
            ],
        },
        {"title": "Verbs", "items": list(_VERBS)},
        {"title": "Sibling-pattern artifacts", "items": list(_ARTIFACTS)},
    ]


def cli_sections() -> list[dict[str, object]]:
    """Sections describing the CLI surface itself (used by `cli overview`)."""
    return [
        {
            "title": "Verbs",
            "items": list(_VERBS) + ["cli overview — describe the CLI surface (this command)"],
        },
        {
            "title": "Conventions",
            "items": [
                "every command supports --json",
                "results to stdout, errors/diagnostics to stderr (never mixed)",
                "exit codes: 0 success, 1 user error, 2 environment error, 3+ reserved",
            ],
        },
    ]


def render_text(subject: str, sections: list[dict[str, object]]) -> str:
    lines = [f"# {subject}", ""]
    for section in sections:
        lines.append(f"## {section['title']}")
        for item in section["items"]:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip()


def emit_overview(subject: str, sections: list[dict[str, object]], *, json_mode: bool) -> None:
    if json_mode:
        emit_result({"subject": subject, "sections": sections}, json_mode=True)
    else:
        emit_result(render_text(subject, sections), json_mode=False)


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------


def _format_currency(value: float) -> str:
    """Format a USD amount as ``$X.XX``."""
    return f"${value:.2f}"


def _render_fleet_table(instances: list[Any]) -> str:
    """Render instances as a human-readable table."""
    if not instances:
        return "  (no instances)"
    lines: list[str] = []
    # Header
    lines.append(f"  {'ID':<14} {'TYPE':<14} {'STATE':<12} {'AZ':<16} NAME")
    lines.append("  " + "-" * 70)
    for inst in instances:
        lines.append(f"  {inst.id:<14} {inst.type:<14} {inst.state:<12} {inst.az:<16} {inst.name}")
    return "\n".join(lines)


def _render_cost_table(cost: dict[str, Any]) -> str:
    """Render cost figures as a human-readable table."""
    lines: list[str] = []
    lines.append(f"  {'Figure':<20} {'Value':>12}")
    lines.append("  " + "-" * 35)

    mtd = cost.get("mtd", 0.0)
    ytd = cost.get("ytd", 0.0)
    lines.append(f"  {'MTD':<20} {_format_currency(mtd):>12}")
    lines.append(f"  {'YTD':<20} {_format_currency(ytd):>12}")

    eom = cost.get("forecast_eom")
    eoy = cost.get("forecast_eoy")
    eom_str = _format_currency(eom["amount"]) if eom.get("available") else "N/A"
    eoy_str = _format_currency(eoy["amount"]) if eoy.get("available") else "N/A"
    lines.append(f"  {'Forecast EOM':<20} {eom_str:>12}")
    lines.append(f"  {'Forecast EOY':<20} {eoy_str:>12}")

    return "\n".join(lines)


def _build_dashboard(instances: list[Any], cost: dict[str, Any]) -> dict[str, Any]:
    """Build the structured dashboard payload."""
    return {
        "fleet": [asdict(inst) for inst in instances],
        "cost": cost,
    }


def _render_dashboard_text(instances: list[Any], cost: dict[str, Any]) -> str:
    """Render the dashboard as human-readable text."""
    lines: list[str] = ["# ec2 dashboard", ""]
    lines.append("## Fleet")
    lines.append(_render_fleet_table(instances))
    lines.append("")
    lines.append("## Cost")
    lines.append(_render_cost_table(cost))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


def cmd_overview(args: argparse.Namespace) -> int:
    """Live dashboard: fleet + four EC2-service cost figures.

    ``overview`` is the agent-first **descriptive** verb (the teken rubric
    requires it to always exit 0 with output — hard-failing is ``verify``'s
    job). So when AWS is unavailable (boto3 missing, credentials/region
    absent) it degrades to the descriptive agent overview and exits 0 — but
    emits an honest diagnostic to stderr naming *why*. The hard error contract
    (structured error + non-zero exit on missing creds/permissions) is carried
    by the action verbs ``instance`` / ``monitor``, which legitimately fail.
    """
    from ec2.aws.client import build_client
    from ec2.aws.cost import cost_mtd, cost_ytd, forecast_month, forecast_year
    from ec2.aws.fleet import list_instances
    from ec2.cli._errors import CliError

    json_mode = bool(getattr(args, "json", False))

    try:
        ec2_client = build_client("ec2")
        ce_client = build_client("ce", region="us-east-1")

        instances = list_instances(ec2_client)
        cost: dict[str, Any] = {
            "mtd": cost_mtd(ce_client),
            "ytd": cost_ytd(ce_client),
            "forecast_eom": forecast_month(ce_client),
            "forecast_eoy": forecast_year(ce_client),
        }

        if json_mode:
            emit_result(_build_dashboard(instances, cost), json_mode=True)
        else:
            emit_result(_render_dashboard_text(instances, cost), json_mode=False)
    except CliError as err:
        # Descriptive verb: never hard-fail. Degrade to the agent overview,
        # but be honest about why on stderr (use `ec2 instance` for a hard
        # error when you need a non-zero exit on a broken AWS setup).
        emit_diagnostic(
            f"AWS unavailable: {err.message}. {err.remediation} "
            "— showing agent overview instead."
        )
        emit_overview("ec2", agent_sections(), json_mode=json_mode)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "overview",
        help="Live dashboard: fleet + EC2 cost figures (MTD, YTD, forecasts).",
    )
    p.add_argument(
        "target",
        nargs="?",
        help="Ignored — overview always describes this agent itself. Accepted so a "
        "stray path argument never hard-fails.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_overview)
