# Runtime instructions

`runtime` schedules and coordinates Aranami on Toolforge. It calls acquisition
and calculation tasks, retains their data, then delegates presentation and
publication. Keep wiki extraction rules and schemas in their owning packages.

- Target Python 3.15 and run from the immutable source generation selected by
  `/data/project/aranami/app`. Pin its `src` on PYTHONPATH at startup. Keep
  credentials and all runtime files outside the source generation.
- `run-job.sh NAME` starts one Toolforge report or collection. The launcher
  pins the selected generation. `run-job.sh --manifest` generates job
  definitions from `shared.toolforge_jobs`. `run-web.sh` starts the public
  read-only service. `run-hub.sh` starts the legacy scheduler for recovery.
- `runtime.run(dry=False)` starts continuous schedules. Repeated starts reuse
  an active monitor in the same mode. `run_once(date=None, dry=False, tasks=None)`
  coordinates selected immediate work without changing schedules.
- Toolforge owns scheduled launches in individual-job mode. The runner
  leases each job and checks committed collection receipts for its UTC hour.
  The legacy hub owns its in-process dispatch and observations. Jobs
  coordinate typed task results and outputs.
- Use `shared.config` for scopes, destinations and independent cron triggers.
  Coalesce missed work; allow one active invocation per routine. Idle work waits
  outside legacy workers. Individual jobs wait within their configured
  deadline for required committed data. Article statistics launch later and
  yield to active foreground work.
- Capture required daily inputs before dependent work. Midnight uses immutable
  daily membership; later hours may use temporary observations. Keep actual
  observation times separate from report anchors.
- A website failure does not undo a wiki result or vice versa. Preserve
  per-output success, retries and confirmation evidence independently.
- Imports, help, heartbeat and app construction must not query sources.
  Shutdown pauses dispatch and drains active workers before closing resources.
- Use existing Toolforge authentication, PYWIKIBOT_DIR and replica credentials.
  Provisioning does not belong in the application.
- Runtime files live under `/data/project/aranami`: `logs`, `state`, `cache`,
  `dry-run` and `reports`. Retain current UTC daily logs plus 29 previous dates.
- Preview runs never save wiki pages, request PexBot refreshes or advance
  production datasets, completion evidence or live status.

[Architecture](../../docs/architecture.md) defines the complete dependency and
storage contracts. [Jobs](jobs/AGENTS.md) covers a report pass.
