# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`ec2-cli` is an **AgentCulture mesh agent**, freshly scaffolded from
`culture-agent-template` (see `git log` — `scaffold ec2-cli from
culture-agent-template`). Its **intended domain** is managing AWS EC2 instances
(launch, inspect, start/stop, operate fleets), per `pyproject.toml`'s
description and the README.

**That domain is not implemented yet.** The runtime has `dependencies = []`
(no `boto3`, no AWS SDK) and the only code present is the *template's*
agent-first introspection CLI: `whoami`, `learn`, `explain`, `overview`,
`doctor`, and a `cli` noun group. When you add EC2 functionality you are
building the actual agent on top of this scaffold — the template machinery
(error contract, output contract, explain catalog, identity probe) is the
reusable substrate, not the product.

**This agent is public.** Most AgentCulture mesh agents are private peers; this
one is meant to serve everyone. The bar is therefore *general AWS-client
usability*, not just mesh-internal use — every EC2 verb you add should be
ergonomic and discoverable for an outside AWS user, not only for another agent.
The agent-first contracts (`--json` everywhere, structured errors with `hint:`,
the `explain`/`learn` self-description surface) are exactly what make the CLI
usable to both audiences at once; keep extending them as the surface grows.

## Three names, deliberately distinct

This agent wears three names; keep them straight when editing:

| Name | What it is | Where it lives |
|------|-----------|----------------|
| **`ec2`** | The **CLI command** you type. | `[project.scripts]`, argparse `prog`, all help / `learn` / `explain` / `overview` text, the explain catalog. |
| **`ec2-cli`** | The **PyPI distribution** *and* the **mesh nick**. | `pyproject.toml` `name`, `importlib.metadata.version("ec2-cli")`, SonarCloud `agentculture_ec2-cli`, `culture.yaml` `suffix`, `whoami`'s `nick`, repo URLs. |
| **`ec2`** | The **Python package / import**. | the `ec2/` directory; `from ec2 import …`. |

So: run the CLI as `uv run ec2 <verb>` (**not** `uv run ec2-cli` — there is no
such script); install it as `uv tool install ec2-cli`; and `whoami` reports
`nick: ec2-cli`. The command-surface strings were swept to `ec2` (and the
`explain` catalog accepts both `ec2` and the `ec2-cli` alias) so
`uv run teken cli doctor . --strict` passes 26/26 — **don't reintroduce
`ec2-cli` into command/help text**, or the rubric's `explain ec2` check breaks
again. The distribution-name and nick occurrences above are load-bearing and
must stay `ec2-cli`.

## Commands

All Python work uses **uv** (Python 3.12, hatchling build backend).

```bash
uv sync                                   # create .venv, install runtime + dev deps
uv run pytest -n auto                     # full suite (xdist parallel)
uv run pytest tests/test_cli.py -q        # one file
uv run pytest tests/test_cli.py::test_whoami_json   # one test
uv run pytest -n auto --cov=ec2 --cov-report=term-missing   # with coverage

uv run ec2 whoami                         # run the CLI (command is `ec2`)
uv run ec2 learn --json                   # every verb supports --json
python -m ec2 doctor                      # equivalent entry via __main__
```

Coverage gate: `fail_under = 60` (`[tool.coverage.report]`); the suite sits
~93%. CI writes `coverage.xml` with `relative_files = true` so SonarCloud maps
paths to `sonar.sources=ec2` — do not remove that flag or Sonar silently
reports 0% coverage.

### Lint (mirror CI's `lint` job before pushing)

```bash
uv run black --check ec2 tests
uv run isort --check-only ec2 tests
uv run flake8 ec2 tests
uv run bandit -c pyproject.toml -r ec2
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills" "#.teken"
uv run teken cli doctor . --strict        # the agent-first rubric gate (must stay 26/26)
```

`black`/`flake8` line length is 100; `isort` uses the black profile. `bandit`
skips `B101,B404,B603` and excludes `tests`.

## Architecture

Single-package CLI under `ec2/`. The whole design serves the **agent-first
rubric** (`teken cli doctor`): output is machine-parseable, errors are
structured, and the CLI is self-describing.

### Dispatch and the error contract

`ec2/cli/__init__.py` is the entry point. `main(argv)` → `_build_parser()` →
`_dispatch(args)`. Two hard rules run through here:

- **Every failure raises `CliError`** (`ec2/cli/_errors.py`), carrying
  `{code, message, remediation}`. `_dispatch` catches `CliError`, routes it
  through `emit_error`, and returns `err.code`. Any *other* exception is
  wrapped into a `CliError` so **no Python traceback ever reaches stderr**
  (a rubric requirement).
- **Argparse errors also use the structured format.** `_CliArgumentParser`
  overrides `.error()` to emit `error:` / `hint:` and exit 1 instead of
  argparse's default `prog: error:` / exit 2. `parser_class` is propagated to
  every subparser so this holds for nested verbs too (e.g. `cli overview
  --bogus`). Because parse-time errors happen before `args.json` exists,
  `main()` pre-scans raw argv for `--json` and sets the class-level
  `_json_hint` so even parse errors honour JSON mode.

Exit-code policy (centralised in `_errors.py`, documented in `learn`):
`0` success · `1` user-input error · `2` environment/setup error · `3+`
reserved.

### Output contract

`ec2/cli/_output.py`: **results → stdout, diagnostics/errors → stderr, never
mixed.** `emit_result` (stdout), `emit_error` (stderr; renders `error:` +
`hint:` lines, the `hint:` prefix is rubric-required), `emit_diagnostic`
(stderr). JSON mode routes structured payloads to the same streams. Honour this
split in any new command — tests and the rubric assert `stderr` is empty on
success.

### Commands and registration

Each verb is a module in `ec2/cli/_commands/` exposing a `register(sub)`
function and a `cmd_*` handler that takes `argparse.Namespace` and returns an
`int` (or `None` = 0). `_build_parser()` calls each `register()`. To add a verb
or noun group, write the module, then add its `register()` call in
`_build_parser()` (there's a marked spot for "your own noun groups").

The `cli` noun (`_commands/cli.py`) exists only to satisfy the rubric's
`overview_cli_noun_exists` check: any noun with action-verbs must expose
`overview`. `cli overview` describes the *CLI surface*; the global `overview`
describes the *agent*. They share render helpers in `overview.py`.

### Explain catalog

`ec2/explain/catalog.py` holds verbatim markdown keyed by command-path tuples
(`("whoami",)`, `("cli","overview")`, …). `ec2/explain/__init__.py:resolve()`
looks up the tuple and raises `CliError` on a miss. **Every registered
noun/verb should have a catalog entry**, and `test_every_catalog_path_resolves`
enforces that the registered keys resolve. The root resolves under both
`("ec2",)` (the command — required by the rubric's `explain ec2` check) and
`("ec2-cli",)` (a back-compat alias for the dist/nick name).

### Identity model

`ec2/cli/_commands/whoami.py` parses `culture.yaml` **without a YAML
dependency** (the runtime must stay dependency-free): `find_culture_yaml()`
walks up from `__file__` to find the agent's *own* config (not the caller's
CWD), and `read_agent_fields()` scrapes `suffix`/`backend`/`model` from the
first agent block via simple line matching. In a wheel install no
`culture.yaml` ships, so it falls back to literal defaults. `whoami`,
`overview`, and `doctor` all build on this.

`doctor` (`_commands/doctor.py`) checks the mesh-agent invariants `steward
doctor` verifies: **backend-consistency** (`culture.yaml`'s `backend` →
required prompt file, via `_PROMPT_FILE`: `claude`→`CLAUDE.md`,
`colleague`→`AGENTS.colleague.md`, `acp`→`AGENTS.md`, `gemini`→`GEMINI.md`)
and **skills-present** (`.claude/skills/` non-empty). If you change
`culture.yaml`'s backend, update `_PROMPT_FILE` and ship the matching prompt
file or `doctor` (and the rubric) go red — `test_doctor_recognizes_declared_backend`
guards exactly this.

### Identity files (two backends, two prompt files)

`culture.yaml` currently declares `backend: colleague` with a pinned model and
the prompt file `AGENTS.colleague.md` (the agent was promoted from `claude` to
a colleague resident in 0.3.0 — the seed text claiming `backend: claude` is
stale). **This `CLAUDE.md` is the prompt for Claude Code (you);
`AGENTS.colleague.md` is the prompt for the colleague resident.** Both coexist
deliberately. `doctor` validates against whatever `culture.yaml` declares, so
keep `AGENTS.colleague.md` present as long as the backend is `colleague`.

## AgentCulture conventions (enforced by CI)

- **Bump the version on every PR — even docs/config/CI-only changes.** The
  `version-check` CI job fails the PR if `pyproject.toml`'s version equals
  `main`'s. Use the `version-bump` skill (`/version-bump patch|minor|major`),
  which also prepends a Keep-a-Changelog entry to `CHANGELOG.md`.
- **PR lifecycle goes through the `cicd` skill** (layered on `devex pr`):
  create PRs, poll CI/SonarCloud status (`status`/`await`), and reply to review
  threads. Issue comments and PR bodies auto-sign as `- ec2-cli (Claude)` via
  the skill scripts — don't hand-sign inside `cicd`/`communicate` script output.
- **SonarCloud gates the `test` job** (`sonar.qualitygate.wait=true`,
  project key `agentculture_ec2-cli`). The scan step is guarded by
  `if: env.SONAR_TOKEN != ''`, so token-less repos and fork PRs stay green.
- **PyPI publish is Trusted Publishing** (`publish.yml`): TestPyPI dev builds
  on same-repo PRs, real PyPI on push to `main`. Triggered only by changes to
  `pyproject.toml` or `ec2/**`.
- **Skills are cite-don't-import.** The 12 skills under `.claude/skills/` are
  vendored verbatim from `guildmaster` (one, `ask-colleague`, directly from
  `colleague`). Provenance and the re-sync procedure live in
  `docs/skill-sources.md` — edit there, don't hand-patch skill bodies. Every
  `SKILL.md` must keep `type: command` (load-bearing; the loader skips files
  without it).
- **`ask-colleague` is the reflexive second-opinion tool.** Before opening a PR
  on a non-trivial committed diff, run `ask-colleague review`; for a fresh read
  of an unfamiliar area, `ask-colleague explore`. Both are read-only (throwaway
  worktree, zero side effects) — safe to reach for unprompted. The
  side-effecting `write --apply`/`write --pr` needs the user's go-ahead.

## Re-branding to a different agent

This repo descends from `culture-agent-template`, so some surface text still
reads as a generic "clonable template" rather than as an EC2 manager — that's
accurate for now (no EC2 functionality exists yet), but if you fork this into a
*different* agent you must rename all three identities (see the table at the
top). Discover every occurrence first:

```bash
git grep -n -e 'ec2-cli' -e '\bec2\b' -- ':!uv.lock'
```

Targets: the package dir `ec2/`, `pyproject.toml` (name, `[project.scripts]`,
`[tool.hatch...]`, coverage `source`, isort `known_first_party`), every module
under `ec2/`, `tests/`, `sonar-project.properties`, `culture.yaml`,
`docs/skill-sources.md`, and `README.md`. Then re-run `uv run pytest -n auto`
and `uv run teken cli doctor . --strict` until both are green (26/26).
