"""Markdown catalog for ``ec2 explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("ec2",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# ec2

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `ec2 whoami` — identity probe from `culture.yaml`.
- `ec2 learn` — structured self-teaching prompt.
- `ec2 explain <path>` — markdown docs for any noun/verb.
- `ec2 overview` — descriptive snapshot of the agent.
- `ec2 doctor` — check the agent-identity invariants.
- `ec2 cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `ec2 explain whoami`
- `ec2 explain doctor`
"""

_WHOAMI = """\
# ec2 whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    ec2 whoami
    ec2 whoami --json
"""

_LEARN = """\
# ec2 learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    ec2 learn
    ec2 learn --json
"""

_EXPLAIN = """\
# ec2 explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    ec2 explain ec2
    ec2 explain whoami
    ec2 explain --json <path>
"""

_OVERVIEW = """\
# ec2 overview

Live dashboard: fleet listing plus four EC2-service cost figures (MTD, YTD,
end-of-month forecast, end-of-year forecast). Degrades gracefully to the
descriptive agent overview when AWS is unavailable.

## Usage

    ec2 overview
    ec2 overview --json
"""

_DOCTOR = """\
# ec2 doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`claude` → `CLAUDE.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    ec2 doctor
    ec2 doctor --json
"""

_CLI = """\
# ec2 cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    ec2 cli overview
    ec2 cli overview --json
"""

_INSTANCE = """\
# ec2 instance

Noun group for EC2 instance management. Lists instances by default; sub-verbs
handle start, stop, and spend-limit operations. All mutating actions are
idempotent: if the instance is already in the target state, no AWS call is
made.

## Sub-commands

- `ec2 instance` — list instances
- `ec2 instance start <id>` — start an instance (requires `--yes`)
- `ec2 instance stop <id>` — stop an instance (requires `--yes`)
- `ec2 instance limit <id> <amount>` — persist a spend limit

## Usage

    ec2 instance
    ec2 instance start i-0abc123 --yes
    ec2 instance stop i-0abc123 --yes
    ec2 instance limit i-0abc123 100 --monthly
"""

_MONITOR = """\
# ec2 monitor

Noun group for spend monitoring. Sub-verbs run checks, manage a background
daemon, and report status.

## Sub-commands

- `ec2 monitor check` — run evaluate once, dispatch alerts, exit non-zero on
  breach
- `ec2 monitor start` — start the background daemon loop
- `ec2 monitor stop` — stop the background daemon
- `ec2 monitor status` — report daemon running/stopped

## Usage

    ec2 monitor check
    ec2 monitor start
    ec2 monitor stop
    ec2 monitor status
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("ec2",): _ROOT,
    # Back-compat alias: the command is `ec2`, but the PyPI dist and mesh nick
    # are `ec2-cli`, so a reader may address the root by either name.
    ("ec2-cli",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
    ("instance",): _INSTANCE,
    ("instance", "start"): _INSTANCE,
    ("instance", "stop"): _INSTANCE,
    ("instance", "limit"): _INSTANCE,
    ("monitor",): _MONITOR,
    ("monitor", "check"): _MONITOR,
    ("monitor", "start"): _MONITOR,
    ("monitor", "stop"): _MONITOR,
    ("monitor", "status"): _MONITOR,
}
