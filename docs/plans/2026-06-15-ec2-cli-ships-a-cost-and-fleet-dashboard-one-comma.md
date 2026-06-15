# Build Plan — ec2-cli ships a cost-and-fleet dashboard: one command shows your EC2 instances alongside spend — month-to-date, year-to-date, and forecast cost for the rest of the month and year — as a table or --json.

slug: `ec2-cli-ships-a-cost-and-fleet-dashboard-one-comma` · status: `exported` · from frame: `ec2-cli-ships-a-cost-and-fleet-dashboard-one-comma`

> ec2-cli ships a cost-and-fleet dashboard: one command shows your EC2 instances alongside spend — month-to-date, year-to-date, and forecast cost for the rest of the month and year — as a table or --json.

## Tasks

### t1 — AWS client layer + boto3 wiring + error mapping

- covers: c12, h4
- acceptance:
  - build_client(service, region) lazy-imports boto3; missing boto3 raises CliError code 2 with a pip-install hint, not ImportError
  - Missing creds, AccessDenied for ce:/ec2:, and unset region each map to CliError with error:/hint: and non-zero exit, asserted by monkeypatching boto3; stdout stays empty

### t2 — Spend-limit config store (local file)

- covers: c23, h5
- acceptance:
  - save/load round-trip a limit (target, amount, period in monthly|yearly, auto_stop flag) through a local config file; reload after restart is identical
  - A malformed or missing config file yields a clear no-limits-set or structured error, never a traceback

### t3 — Cost Explorer module: MTD/YTD actuals + month/year forecast (EC2-filtered)

- depends on: t1
- covers: c9, c10, h1, h2
- acceptance:
  - cost_mtd/cost_ytd call GetCostAndUsage with UnblendedCost, an EC2-service filter, and ranges first-of-month..today and first-of-year..today, asserted via a mocked CE client
  - forecast_month/forecast_year call GetCostForecast for today..end-of-month/year; when CE raises a data-unavailable/validation error the function returns a forecast-unavailable sentinel instead of raising

### t4 — Fleet module: DescribeInstances with pagination + per-instance summary

- depends on: t1
- covers: c11, h3
- acceptance:
  - list_instances pages through DescribeInstances via NextToken and returns every instance across more than one page, asserted with a two-page mocked response
  - Each instance summarised as id, type, state, name-tag, az; an empty account returns an empty list and renders cleanly, not an error

### t5 — Per-machine layered cost estimate: spot/on-demand rate x hours + EBS

- depends on: t1, t4
- covers: c35, h18
- acceptance:
  - estimate picks the spot price when InstanceLifecycle is spot and on-demand otherwise, multiplies by running hours, and adds attached-EBS cost counted even when the instance is stopped, asserted with mocked pricing and volumes
  - Output labels the figure an estimate and lists exclusions (RI/SP, data transfer); a missing rate or volume lookup degrades via the fallback chain instead of raising

### t6 — ec2 overview command + move descriptive self-report to cli overview

- depends on: t3, t4
- covers: c30, h17
- acceptance:
  - ec2 overview renders the fleet plus four EC2-service figures (MTD, YTD, forecast end-of-month, forecast end-of-year); --json emits a parseable payload; results go to stdout only
  - cli overview still emits the descriptive agent self-report and uv run teken cli doctor . --strict stays 26/26

### t7 — ec2 instance noun: list / start / stop / limit

- depends on: t1, t2, t4
- covers: c21, c24, h15, h6
- acceptance:
  - ec2 instance lists instances; instance start|stop id invokes the matching AWS action only behind confirmation or --yes and is idempotent (already-running start / already-stopped stop is a clean no-op) on a mocked client
  - instance limit id amount --monthly|--yearly [--auto-stop] persists via the limit store and reads back identically

### t8 — Monitor evaluator + check logic (spend vs limits, findings, auto-stop gating)

- depends on: t2, t3, t5
- covers: c25, h6, h8
- acceptance:
  - evaluate compares per-machine (layered estimate) and total (Cost Explorer) spend against configured limits and returns findings with a breach flag; --json findings parse
  - With auto-stop disabled (default) a breached limit yields an alert finding but zero StopInstances calls; auto-stop is proposed only for targets whose limit set the explicit auto-stop flag, asserted on a mocked client
  - Spike detection uses run-rate projection: a finding is raised when projected end-of-period spend (current run-rate extrapolated to month/year end) exceeds the limit, asserted with a mocked spend fixture

### t9 — Monitor alerters: CULTURE.DEV mesh + stderr baseline, OTEL/webhook optional

- depends on: t8
- covers: c22
- acceptance:
  - On a breach finding the CULTURE.DEV mesh alerter and the stderr baseline both emit a structured alert; OTEL-log and webhook alerters are optional and lazy-imported so an absent dependency disables the channel rather than crashing

### t10 — Monitor CLI + daemon: check / start / stop / status (pidfile, ~5 min loop)

- depends on: t8, t9
- covers: c22, h16
- acceptance:
  - ec2 monitor check runs evaluate once, routes findings to enabled alerters, and exits non-zero on any breach; --json prints findings
  - ec2 monitor start|stop|status manages a background loop via a pidfile (start writes pid, status reports running/stopped, stop terminates); the loop body is check on a ~5-minute timer

### t11 — Wire verbs into parser + explain catalog + boundary contract test

- depends on: t6, t7, t10
- covers: c20, h14
- acceptance:
  - overview/instance/monitor are registered in _build_parser() and each has an explain catalog entry; the catalog-resolves test passes for the new keys
  - A boundary contract test asserts no code path references TerminateInstances, ModifyInstanceAttribute for type, or Budgets/CloudWatch APIs

### t12 — README + rationale docs (audience, before-state, why-it-matters, usage)

- depends on: t11
- covers: c2, c4, c5, h10, h11, h12
- acceptance:
  - README documents the audience, the before-state (console + Cost Explorer stitching), the why (bill-shock), and usage for overview/instance/monitor; markdownlint-cli2 passes

### t13 — End-to-end integration test (mocked AWS client, whole surface)

- depends on: t11
- covers: c1, c6, h9, h13
- acceptance:
  - An end-to-end test with a fully mocked AWS client runs ec2 overview and asserts fleet + all four figures render and --json parses, and that missing-creds/permission/region paths produce structured errors with zero stdout

## Risks

- [unknown_nonblocking] Spend-spike detection is unspecified in the spec; v1 default = projected end-of-period spend (run-rate) exceeding the limit, plus an optional percent-jump vs trailing average. Needs confirmation before t8 lands. (task t8)
- [unknown_nonblocking] CI cannot hit live Cost Explorer (per-call cost + ~24h activation), so all AWS interaction is tested via mocked clients; figure-accuracy honesty (h1) is validated against fixtures plus a manual live check before release.
- [out_of_scope] Daemon pidfile/process model is POSIX-oriented; Windows supervision is out of scope for this plan. (task t10)
- [follow_up] Phase-2 on-machine cost reporter to CloudWatch Logs (parked in the frame) is explicitly out of this plan's scope.
