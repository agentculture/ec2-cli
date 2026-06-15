# ec2-cli

Agent and CLI for managing AWS EC2 machines (instances) — launch, inspect, start/stop, and operate fleets.

## Audience

An AWS user or mesh agent who wants a single at-a-glance answer to "what am I
running and what is it costing me" without opening the AWS console.

## Before → After

**Before:** Today you stitch `describe-instances` and Cost Explorer queries by
hand to answer "what am I running + spending."

**After:** `ec2 overview` gives you the fleet and cost figures in one command;
`ec2 instance` manages power and limits; `ec2 monitor` watches spend against
limits.

## Why it matters

Cost surprise is the #1 EC2 pain. A single trustworthy "running + spend +
forecast" view turns reactive bill-shock into a glanceable habit.

## Usage

### `ec2 overview`

Live dashboard: fleet listing plus four EC2-service cost figures (MTD, YTD,
end-of-month forecast, end-of-year forecast).

```bash
ec2 overview
ec2 overview --json
```

### `ec2 instance`

Manage instances — list, start, stop, and set spend limits.

```bash
ec2 instance                          # list instances
ec2 instance start <id> --yes       # start an instance
ec2 instance stop <id> --yes        # stop an instance
ec2 instance limit <id> <amount> --monthly  # set a spend cap
```

### `ec2 monitor`

Spend monitoring — evaluate against limits, manage a background daemon.

```bash
ec2 monitor check                    # evaluate once, alert on breach
ec2 monitor start                    # start the background daemon (~5 min loop)
ec2 monitor stop                     # stop the daemon
ec2 monitor status                   # report daemon running/stopped
```

### Cost figures

The per-machine cost figure is an **estimate**: spot or on-demand hourly rate ×
running hours + attached EBS cost. It excludes RI/Savings-Plan discounts and
data transfer. Cost Explorer is the billed-truth source.

### Monitor scope

Monthly **total** spend limits are enforced end-to-end with real Cost Explorer
data. Per-machine limits and yearly totals are a known follow-up (they require a
price/usage-gathering layer).

## What you get

- **An agent-first CLI** cited from [teken](https://github.com/agentculture/teken)
  (`afi-cli`) — the runtime package has no third-party dependencies.
- **A mesh identity** — `culture.yaml` (`suffix` + `backend`) and the matching
  prompt file (`CLAUDE.md` for `backend: claude`).
- **The canonical guildmaster skill kit** (11 skills) under `.claude/skills/`,
  vendored cite-don't-import. See [`docs/skill-sources.md`](docs/skill-sources.md).
- **A build + deploy baseline** — pytest, lint, the agent-first rubric gate, and
  PyPI Trusted Publishing wired into GitHub Actions.

## Quickstart

```bash
uv sync
uv run pytest -n auto                 # run the test suite
uv run ec2 whoami  # identity from culture.yaml (command is `ec2`; dist is `ec2-cli`)
uv run ec2 learn   # self-teaching prompt (add --json)
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` | Report this agent's nick, version, backend, and model from `culture.yaml`. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Live dashboard: fleet + EC2 cost figures (MTD, YTD, forecasts). |
| `doctor` | Check the agent-identity invariants (prompt-file-present, backend-consistency). |
| `instance` | Manage instances (list, start, stop, spend limit). |
| `monitor` | Spend monitoring (check, daemon start/stop/status). |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Make it your own

1. Rename the package `ec2/` and the `ec2-cli`
   CLI/dist name throughout `pyproject.toml`, the package, `tests/`,
   `sonar-project.properties`, and this `README.md`. The name is hard-coded in
   ~100 places, so list every occurrence first — see the `git grep` discovery
   command in [`CLAUDE.md`](CLAUDE.md), the authoritative rename procedure.
2. Edit `culture.yaml` with your `suffix` and `backend`.
3. Rewrite `CLAUDE.md` for your agent and run `/init`.
4. Re-vendor only the skills you need from guildmaster (see
   [`docs/skill-sources.md`](docs/skill-sources.md)).

See [`CLAUDE.md`](CLAUDE.md) for the full conventions (version-bump-every-PR,
the `cicd` PR lane, deploy setup).

## License

MIT — see [`LICENSE`](LICENSE).
