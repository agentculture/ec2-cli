# ec2-cli ships a cost-and-fleet dashboard: one command shows your EC2 instances alongside spend — month-to-date, year-to-date, and forecast cost for the rest of the month and year — as a table or --json.

> ec2-cli ships a cost-and-fleet dashboard: one command shows your EC2 instances alongside spend — month-to-date, year-to-date, and forecast cost for the rest of the month and year — as a table or --json.

## Audience

- An AWS user (human operator or mesh agent) who wants a single at-a-glance answer to 'what am I running and what is it costing me' without opening the AWS console or stitching together describe-instances + Cost Explorer by hand.

## Before → After

- Before: Today the repo has zero EC2/AWS functionality (dependencies = []); the only 'overview' is the template's descriptive agent-introspection verb. To get this answer a user must run AWS CLI describe-instances and Cost Explorer queries separately and do the math themselves.
- After: 'ec2 instance start|stop <id>' powers an instance up/down (with state waiters and a confirmation/--yes guard); 'ec2 instance' with no verb lists instances; 'ec2 instance limit <id> <amount> --monthly|--yearly' records a per-machine cap.
- After: 'ec2 monitor' evaluates current spend vs limits once (and can loop every ~5 min), emitting an alert per breach/spike and, only when auto-stop is enabled for that target, stopping the offending instance; --json yields machine-parseable findings.
- After: 'ec2 overview' prints the live EC2 fleet plus four EC2-service spend figures — MTD actual, YTD actual, forecast end-of-month, forecast end-of-year — as a human table and, with --json, a structured payload; the descriptive agent self-report moves to 'cli overview' so the rubric stays green.

## Why it matters

- Cost surprise is the #1 EC2 pain; a single trustworthy 'running + spend + forecast' view turns reactive bill-shock into a glanceable habit, and it's the first real domain capability that makes ec2-cli an EC2 manager rather than a scaffold.

## Requirements

- MTD and YTD actual spend come from AWS Cost Explorer GetCostAndUsage (UnblendedCost, MONTHLY granularity, time periods = first-of-month..today and first-of-year..today).
  - honesty: Re-running on a known account, MTD/YTD figures match the AWS Cost Explorer console for the same dates to the cent (same UnblendedCost metric, same date math).
- Forecast end-of-month and end-of-year come from AWS Cost Explorer GetCostForecast (UNBLENDED_COST) for today..end-of-month and today..end-of-year.
  - honesty: GetCostForecast is called with a valid future period; when AWS refuses (too little history / start must be in the future), we degrade to a clear 'forecast unavailable' line, not a crash.
- The live fleet comes from EC2 DescribeInstances, summarised per instance (id, type, state, name tag, AZ) in the chosen region.
  - honesty: DescribeInstances pagination is handled (NextToken) so accounts with >1 page of instances are fully listed, and an empty fleet renders cleanly (not an error).
- The command honours the agent-first output contract: human table by default, --json for structured payload, results to stdout, errors to stderr, and credential/permission/region failures raise CliError -> structured error with a hint, never a traceback.
  - honesty: On missing creds, missing ce:/ec2: permission, and unset region, the command exits non-zero with error:/hint: lines and zero stdout — verified by tests that monkeypatch the AWS client.
- Per-machine and total spend limits (amount + monthly/yearly period + optional auto-stop flag) are persisted in a local config file and are the single source of truth the monitor evaluates against.
  - honesty: Limit config round-trips: written by 'instance limit', read identically by 'monitor', survives process restart, and a malformed/missing file degrades to a clear error or 'no limits set', not a crash.
- Power verbs (start/stop) and auto-stop are write operations guarded for safety: a dry-run/preview is the default for destructive auto-stop, start/stop require confirmation or --yes, and operations are idempotent (already-running/already-stopped is a clean no-op).
  - honesty: Tests prove start/stop are idempotent and that auto-stop in default (dry-run/alert-only) mode never calls StopInstances — verified by monkeypatching the AWS client and asserting no mutating call.
- Auto-stop never fires unless explicitly enabled per-target (opt-in); the default monitor behaviour is alert-only.
  - honesty: A test confirms that with auto-stop disabled (the default) a breached limit produces an alert but zero StopInstances calls; auto-stop only fires when the target's limit was set with the explicit auto-stop flag.
- The monitor's per-machine cost figure is the layered estimate: pick spot vs on-demand rate by InstanceLifecycle, multiply by running hours, add attached-EBS cost (counted even when the instance is stopped); label it an estimate and list exclusions (RI/SP, data transfer).
  - honesty: Tests show: a spot instance is priced at the spot rate (not on-demand), attached EBS is included even for a STOPPED instance, output labels the figure an estimate and names its exclusions, and a missing rate/volume lookup degrades cleanly via the fallback chain rather than crashing.

## Honesty conditions

- A user with valid AWS creds runs 'ec2 overview' and the four figures + fleet render correctly and match the AWS console; the whole surface (overview/instance/monitor) honours --json and the structured-error contract.
- A real user (operator or mesh agent) currently answers 'what am I running + spending' by stitching describe-instances + Cost Explorer by hand; the single command demonstrably replaces that workaround.
- Verified against the repo: today dependencies=[] and no EC2/AWS code exists; the only 'overview' is the descriptive introspection verb.
- The feature is justified only because MTD/YTD + forecast together pre-empt bill-shock; if cost-surprise weren't the driver the forecast figures would be pointless.
- An end-to-end test with a mocked AWS client shows fleet + all four figures rendered, --json parseable, and error paths structured — the signal is observable, not aspirational.
- A contract/test asserts no code path calls TerminateInstances, ModifyInstanceAttribute(type), or Budgets/CloudWatch APIs — the boundary is enforced, not just stated.
- Each instance verb has a test: list renders, start/stop invoke the right AWS action behind --yes, limit persists to config and reads back.
- monitor check returns findings + non-zero exit on breach against a mocked client; the daemon loop is that same check on a timer; --json findings parse.
- overview renders fleet + four EC2-service figures while 'cli overview' still emits the descriptive self-report, and 'teken cli doctor . --strict' stays 26/26.

## Success signals

- A user with valid AWS credentials runs one command and sees their instances and all four cost figures correctly; --json output is machine-parseable; missing creds/permissions/region produce a structured error with a hint, never a traceback.

## Scope / boundaries

- It can start/stop and auto-stop instances and set tool-side spend limits, but it does NOT terminate or resize instances, and limits are tracked by this tool (local config) — it does not create AWS-native Budgets or CloudWatch alarms.

## Non-goals

- Out of scope: instance termination, resizing/right-sizing advice, AWS-native Budgets/CloudWatch alarms, multi-account/Organizations roll-ups, and non-EC2 cost breakdowns.

## Assumptions

- The account has AWS Cost Explorer enabled (it is opt-in, activates ~24h after first enable, and GetCostAndUsage/GetCostForecast bill ~$0.01 per request).
- AWS access uses the standard credential chain (env vars / shared profile / IMDS role); no new auth mechanism is introduced.

## Decisions

- Cost scope = EC2 service only: Cost Explorer is filtered to the EC2 service so spend figures line up with the listed fleet.
- AWS access = boto3, lazy-imported inside the AWS verbs only; introspection verbs (whoami/learn) keep working dep-free and a missing boto3 yields a clean CliError.
- Top-level 'ec2 overview' becomes the live fleet+cost dashboard (the user's named command); the descriptive agent self-report stays reachable via 'cli overview' so the teken rubric stays 26/26.
- Add an 'ec2 instance' noun: 'ec2 instance' (no verb) lists/shows instances; 'instance start|stop <id>' controls power; 'instance limit <id> <amount> [--monthly|--yearly]' sets a spend cap used by monitor.
- Add an 'ec2 monitor' capability: a recurring check (every ~5 min) that compares per-machine and total spend vs configured monthly/yearly limits, alerts on threshold breach and on spend spikes, and can auto-stop a machine over its limit.
- Monitor process model = a stateless 'ec2 monitor check' primitive (evaluate once, alert, exit non-zero on breach) plus a self-managed daemon 'ec2 monitor start|stop|status' (pidfile) that loops check every ~5 min.
- Alert channels: AgentCulture mesh = CULTURE.DEV is the native channel; optional log via OpenTelemetry (OTEL, lazy/optional dependency) and optional webhook POST; stderr + non-zero exit are always-on baseline. Desktop notification is out of scope.
- Optional dependencies are lazy-imported and isolated like boto3: OTEL only when log-alerting is enabled, webhook via stdlib; the base introspection CLI stays installable dependency-free.
- v1 per-machine estimate is the LAYERED controller-side estimate: spot-or-on-demand hourly rate (chosen by InstanceLifecycle) x running hours + attached-EBS cost (which accrues even when stopped). It excludes RI/Savings-Plan discounts and data transfer (documented); Cost Explorer remains the billed-truth source.
- An optional on-machine cost-reporting add-on is a Phase-2 follow-up (own spec), NOT v1. When built, it writes periodic state+estimate heartbeats to CloudWatch Logs; ec2-cli reads them via the Logs API so a machine's last estimate survives stop/termination for post-mortem review. It still reports list-cost estimate, not RI/SP-discounted billed cost.
- Per-machine cost resolves via a fallback chain so the Phase-2 add-on slots in cleanly: add-on CloudWatch-Logs report (if present) -> spot/on-demand + EBS estimate -> on-demand-only estimate.

## Hard questions

- risk: AWS dependency: pulling in boto3 breaks the repo's current dependencies=[] / dependency-free runtime invariant; the SDK approach is a load-bearing decision.
- Is 'cost' scoped to EC2 service only, or total account spend? They differ a lot and need different Cost Explorer filters.
- risk: Command-name collision: the existing 'overview' verb is descriptive (agent self-report); reusing that name for a live-AWS view would conflate two very different behaviours.
- How does the 'independent process' run — a self-managed background daemon (start/stop/status + pidfile), an installed cron/systemd-timer that runs one-shot checks, or a foreground loop the user supervises?
- Where do alerts go — stderr/log file, the AgentCulture mesh/IRC channel, a webhook/email, or desktop notification?

## Open / follow-up

- Optional on-machine cost-reporting add-on (Phase 2, own spec): instance-side component reads IMDS (type/region/lifecycle/spot), uptime, egress bytes and EBS; emits periodic state+estimate heartbeats to CloudWatch Logs; ec2-cli reads them back (survives instance termination for post-mortem). Open design: install path (user-data/SSM/AMI), retention policy, IAM scoping. Cannot see RI/SP discounts.
