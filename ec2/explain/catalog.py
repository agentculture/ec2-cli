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

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

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
}
