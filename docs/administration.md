# Operating Aranami on Toolforge

Use this guide to deploy a verified source generation, replace services safely
and recover without losing data. Aranami runs on Toolforge. Local machines
prepare source and run offline tests. [Usage](usage.md) covers
report commands, and [Development](development.md) covers verification.

## Maintain on Toolforge

Use existing maintainer access and the tool account:

```shell
ssh <maintainer>@login.toolforge.org
become aranami
cd /data/project/aranami
```

Job launchers use `TOOL_DATA_DIR` when Toolforge provides it. The usual
path is `/data/project/aranami`, which can resolve to the tool's physical
NFS home. Keep credentials, `.my.cnf`, Pywikibot configuration and OAuth
secrets outside source.
Do not print account dumps. Preserve platform-managed credential permissions.
The launchers pin the selected source and its Python 3.15 environment for each
process lifetime, including manual jobs.

## Runtime folder architecture

The jobs mount the tool's shared NFS directory with `mount: all`. Use it
for committed Parquet and JSON files, job receipts and source generations
that multiple pods need. Writers stage replacements on the same filesystem
as their destinations. Use the container's `/tmp` for disposable work that
stays within one pod. [Toolforge shared storage][storage] [Managing files][files]

| Path relative to tool home | Purpose |
|---|---|
| `app` | Atomic symlink selecting an immutable uploaded generation |
| `app-staging-<id>/` | Source payload; its path remains immutable after activation |
| `deployment-envs/source-<id>/` | Locked Python environment for that generation |
| `deployment-backups/source-<id>/` | Validation receipt, former selection and saved job settings |
| `deployment.lock/` | Promotion serialization; do not remove while setup/promotion is active |
| `python/`, `uv-bootstrap/` | Managed interpreter and setup tooling |
| `data/archive/<day>.parquet`, `data/raw/<project>-<day>.parquet` | Immutable full daily project observations |
| `data/raw/pageviews-*--*` | Latest/previous detailed traffic generations and coverage |
| `data/parsed/` | Durable history, authorship, milestones and scope evidence |
| `data/parsed/newsletter--*` | Current and original prepared newsletter facts |
| `data/parsed/` | Prepared report bundles and independent dated newsletter archives |
| `data/parsed/assessments--*`, `backups/report-layout/` | Retained legacy observations and recovery originals |
| `data/revisions/00/` through `FF/` | Revision text and metadata, sharded by revision ID |
| `data/webservice/` | Pre-rendered quality-analysis presets for direct HTTP delivery |
| `state/observability/status.json` | Versioned service, execution, dataset and publication observations |
| `state/observability/web-status.json` | Independent Web lifecycle and resource heartbeat |
| `state/` | Completion checkpoints, publication membership and active execution locks |
| `state/toolforge-jobs/` | Individual job activation and UTC cycle receipts |
| `cache/` | Disposable source and presentation optimizations |
| `logs/activity/` | Versioned UTC activity segments correlated by service/run/attempt |
| `logs/diagnostics/` | Readable UTC diagnostic segments with bounded tracebacks |
| `dry-run/` | Isolated preview source data, results and proposed edits |

Daily captures use the preceding completed UTC date in their filenames. New dates
require fresh complete queries. The [retirement checklist](transition.md)
tracks historical-source dependencies and verification before removal.
The scheduling boundary and actual query time remain separately recorded.

## Validate and upload source

Complete the [offline checks](development.md#verification-and-releases) on the
development computer:

```shell
uv sync --locked
uv run python scripts/upload_toolforge.py --dry-run
```

The validator checks source inventory, version and content hashes, rejecting
symlinks and private/runtime files. It packages the checked-in Vue bundle,
native HTML templates, styles and browser scripts under `src/webservice/`.
`--archive <new-file.tar.gz>` optionally retains
the same reproducible compressed payload without network access.
Packaging records a UTC build time in `deployment.json`; repackaging preserves
it and the About page displays it independently of process restarts. An
unpackaged checkout or an older source generation without that field omits it.

Upload the verified payload:

```shell
uv run python scripts/upload_toolforge.py
```

Retain its version, manifest digest, unique staging path and printed promotion
command. Uploading does not select the source or restart jobs.
`TOOLFORGE_SSH_TARGET` overrides the configured maintainer;
`TOOLFORGE_KNOWN_HOSTS` can select an existing verified host file. Keep host
verification enabled. Identify each deployment by its version and exact content digest.

## Promote the uploaded generation

Run the exact uploader-provided command as the tool account:

```shell
sh /data/project/aranami/app-staging-<id>/scripts/toolforge/deploy-source.sh /data/project/aranami/app-staging-<id>
```

Promotion verifies the payload, builds an isolated locked environment, and runs
setup/import validation in a one-off Toolforge job. A matching success receipt
is mandatory. Setup failure leaves existing services running.

Scheduled jobs select the new source at their next launch. In-flight jobs finish
with their pinned interpreter and code. With the legacy hub running, promotion
drains it before selection and resumes wiki scheduling before replacing the
website. Web rollout health is checked after the updater resumes. Deliberately
paused deployments stay paused. Job definitions, routes, credentials, reports,
logs and state stay outside selected source.

Keep both the new generation and the last validated recovery generation. Keep
every generation used by an active job.

## Register individual jobs

The generated configuration publishes only `aranami-web`. Each collector and
wiki routine has its own scheduled Toolforge job, log stream, deadline, CPU
limit and memory limit. The Jobs Framework runs each in its own pod. The website
serves committed files, and its request load and container restarts are
independent of report dispatch. [Toolforge Jobs Framework][jobs]

Run these from the tool directory after promoting the source generation.

```shell
toolforge jobs quota
kubectl describe resourcequotas
mkdir -p state
sh app/scripts/toolforge/run-job.sh --manifest > state/aranami-jobs.yaml
toolforge jobs load state/aranami-jobs.yaml
```

The manifest uses JSON, which is accepted as YAML. Loading a changed job
definition can replace that job. Use `toolforge jobs load --job NAME FILE`
for a deliberate change to one job. A run pins the managed Python 3.15
environment even though the Toolforge image label is `python3.13`.

For a fresh tool, enable the jobs after registration. For migration from a
running hub, wait for its current work to finish and for its pod to terminate
before enabling the schedules.

```shell
kubectl exec deployment/aranami-hub -- python3 /data/project/aranami/app/scripts/toolforge/drain-hub.py
kubectl scale deployment aranami-hub --current-replicas=1 --replicas=0
kubectl wait --for=delete pod -l app.kubernetes.io/name=aranami-hub --timeout=180s
kubectl get pods -l app.kubernetes.io/name=aranami-hub
```

Confirm the last command lists no pods. Complete source promotions and
cutovers outside 23:59:00–00:01:59 UTC to protect the daily capture. Then
enable the schedules and start primary collection for the current hour.

```shell
mkdir -p state/toolforge-jobs
touch state/toolforge-jobs/active
toolforge jobs restart aranami-project-data
```

A short wait for this hour's collection receipt prevents dependent jobs from
publishing with incomplete inputs. An absent receipt causes a failed run and
the configured Toolforge retry. Daily reports select the committed midnight
snapshot, and Pageviews checks its 19:00 UTC eligibility in the worker.
`toolforge jobs restart NAME` can retry a failed scheduled job in the current
cycle. Each job's lease and receipt guard duplicate runs.

### CPU and memory

The starting profile has one continuous job and thirteen scheduled jobs.
The published web job gets 2 GiB and one CPU core based on its observed
working set. Scheduled jobs get 512 MiB to 2 GiB each. The busiest planned
window uses 6.75 GiB, 2.05 CPU cores and seven pods including web. The setup
job raises that to 7.25 GiB, 2.15 cores and eight pods. Aranami's Toolforge
account has 8 GiB, 16 cores and 16 pods. Its web Deployment uses Recreate,
which releases its old pod before starting the replacement. Check actual
allocations, other running jobs and rollout strategy before changing limits.
[Job quotas][job-quotas] [Kubernetes quotas][quotas]

[Jobs and allocations](../src/shared/toolforge_jobs.py) defines the launch
minutes and per-job deadlines. Confirm that each collector and report finishes
within its allocation after the first regular and midnight cycles. Use
`toolforge jobs logs NAME` and inspect the pod status for deadline, scheduling
or out-of-memory failures.

## Enable the shared page cache

Toolforge supplies `TOOL_REDIS_URI` to jobs. Create the tool-private signing
secret once as the tool account, then restart the web job to load it.

```shell
openssl rand -hex 32 | toolforge envvars create ARANAMI_REDIS_SECRET
toolforge jobs restart aranami-web
```

The web job shares small prepared Article Statistics pages for up to 45
seconds. Entries are authenticated against their exact saved input generation
and source release. The local page cache and shared files serve requests
after expiry, an invalid entry or a Redis failure. Rotate the signing secret
through Toolforge Envvars to create a fresh namespace. [Toolforge Redis][redis]
[Toolforge Envvars][envvars]

## Inspect operation

```shell
toolforge jobs list
toolforge jobs show aranami-project-data
toolforge jobs logs aranami-project-data
toolforge jobs logs aranami-assessment-log
toolforge jobs logs aranami-web
```

The launch commands send process output to Toolforge's internal logs.
Use `toolforge jobs logs -f aranami-web` for web startup and runtime messages.
The application also keeps its dated activity and diagnostic streams for the
public Logs view.

Confirm the public site, deployed version, next configured launches and
actual job completions. Verify complete adjacent project files and their
manifests before expecting daily comparisons.
Compare `/api/config` with the promoted version after each rollout: ready pods
alone do not prove which source they selected. If the web process selected the
previous generation, verify that the new `app` selector is visible inside its
pod, restart `aranami-web`, and repeat the version check. Inspect scheduled
job outcomes and retained source generations independently.
Detailed Pageviews is written only after an accepted traffic acquisition.
Diagnostic Python processes must set `PYTHONPYCACHEPREFIX` to the tool's
`cache/pycache` directory, or set `PYTHONDONTWRITEBYTECODE=1`, before importing
selected source. `kubectl exec` starts a fresh environment and does not inherit
variables exported by the running launcher. Generated bytecode inside a source
generation fails later deployment validation; keep all diagnostic caches outside
the immutable generation.

The hub's local read-only diagnostics are `/healthz` and `/dashboard.json` at
`127.0.0.1:8765`. Public Reports reads saved execution evidence, not log guesses.
Check service heartbeat age, task outcome, accepted dataset coverage and each
destination's publication result separately. A failed refresh can leave useful
older data available; a successful collection does not establish a wiki save.
The log streams retain 30 UTC dates within a combined 512 MiB ceiling. Segment
rotation prevents a busy day from silently stopping activity recording.

## Stop or restart a service

Restart the website with `toolforge jobs restart aranami-web`. Use the named
scheduled job for individual collector or report recovery.

To roll back to the legacy hub, remove `state/toolforge-jobs/active` and wait
for every running scheduled worker to exit. Check `kubectl get jobs` for active
workers before starting the original hub replica. If the hub already runs in
legacy mode, drain and stop it before restoring its replica.

```shell
kubectl exec deployment/aranami-hub -- python3 /data/project/aranami/app/scripts/toolforge/drain-hub.py
kubectl scale deployment aranami-hub --current-replicas=1 --replicas=0
kubectl wait --for=delete pod -l app.kubernetes.io/name=aranami-hub --timeout=180s
kubectl get pods -l app.kubernetes.io/name=aranami-hub
kubectl scale deployment aranami-hub --current-replicas=0 --replicas=1
kubectl rollout status deployment/aranami-hub --timeout=180s
```

Proceed only after each command succeeds; confirm the pod listing is empty
before restoring the replica. Leave zero replicas to pause deliberately.
SIGTERM/SIGINT also pause dispatch and drain jobs, but forced termination may
leave incomplete observations. Use source promotion for code changes, and change
job definitions only when their image/command/resources/route must change.

## Recovery and cleanup

A promotion transaction retains `jobs.yaml`, setup evidence, previous source
selection in `app.before`, saved replica counts and stop markers. Interpret
`app.before` relative to tool home. If setup cancellation cannot confirm the
job exited, inspect the retained deployment lock before retrying.

A failure after source selection retains the new selection and both generations:
a process may already have loaded the new source. Inspect actual jobs/pods,
receipts and logs before further replacement. A shutdown timeout must never
start a second publisher. To select a retained generation, acquire
`deployment.lock/`, then invoke its validated selector:

```shell
python3 /data/project/aranami/app-staging-<id>/scripts/toolforge/validate-source.py select /data/project/aranami/app-staging-<id>
```

Restart services through the safe sequence and release the lock after recovery.
Source selection does not undo runtime data or wiki edits. Remove only exact
obsolete paths after verifying no running process uses them. Never clear daily
project files, detailed traffic, newsletter archives or article evidence as
caches. Alpha suspends new automatic evidence purges; 2026 facts remain needed
by newsletters into 2027 and by delayed issues afterward. Legacy retirement
requires verified replacements and zero remaining consumers, not a date alone.


[jobs]: https://wikitech.wikimedia.org/wiki/Help:Toolforge/Running_jobs
[job-quotas]: https://wikitech.wikimedia.org/wiki/Help:Toolforge/Running_jobs#Job_quotas
[quotas]: https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes#Quotas_and_Resources
[storage]: https://wikitech.wikimedia.org/wiki/Help:Shared_storage
[files]: https://wikitech.wikimedia.org/wiki/Help:Toolforge/Managing_and_sharing_files
[redis]: https://wikitech.wikimedia.org/wiki/Help:Toolforge/Redis
[envvars]: https://wikitech.wikimedia.org/wiki/Help:Toolforge/Envvars
