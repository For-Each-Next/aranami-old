# Using Aranami

Aranami maintains Wikipedia project reports and provides saved dashboard,
maintenance and newsletter data. Use this guide to inspect or run it on
Toolforge. Local development remains offline; account access and service
replacement are in [Administration](administration.md).

## Article Statistics

Open **Article Statistics** to explore assessments, listing dates,
article lengths and contributors. Choose grades, importance levels and years
in the matrix, then select **Apply filters**. The browser updates the figures,
coverage and tables from the downloaded catalog. The summary tables show their
full fixed sets. Article directories and lists opened from figures are paginated.

The main contributor directory counts current articles and lists where a
registered editor supplied over 33% of the eligible content and at least
500 attributed characters. It defaults to high-quality grades. The
listing-time authorship option uses saved proof for the exact listing revision.
Contributor links open the matching articles and the last-active date links
to the account's contributions. Activity comes from the latest saved public
Wiki Replica observation, refreshed during the hourly idle authorship pass.

## Inspect results and logs

The [dashboard](https://aranami.toolforge.org/) shows active reviews and article
highlights. Active discussions show the last seven days of comments, ordered
by subject type: articles, drafts, projects/portals, categories/templates, then
other pages. Within each type, newest comments lead regardless of assessment
grade. [Recent discussions](https://aranami.toolforge.org/discussions/) shows
twenty-eight days with the same types, splitting articles into four week groups.
Recognized content reviews appear only in the review section. Discussion cards omit
assessment chips.
The header's Tools menu links to
[maintenance checks](https://aranami.toolforge.org/checks/), grouped
by issue type; [their guide](webservice/maintenance.md) explains the evidence.
[Reports](https://aranami.toolforge.org/reports/) lists the on-wiki reports,
their destinations, schedules, latest results and recent executions. Select a
result to inspect its action log and publication details. [Logs](https://aranami.toolforge.org/logs/)
provides structured activity and downloadable diagnostic segments. A check with
no changed content need not save an edit; missing evidence remains unknown.

As the `aranami` tool account:

```shell
cd /data/project/aranami
toolforge jobs list
toolforge jobs logs aranami-hub
toolforge jobs logs aranami-web
tail -n 100 logs/diagnostics/YYYYMMDD.000.log
```

Choose a UTC log date and segment. `state/observability/status.json` retains the
four independent status domains; logs explain their activity. See the [saved-data map](data/storage.md) for project observations,
traffic facts, report results and newsletter archives. Read these through data APIs rather than editing them.

## Routine names and UTC triggers

| Identifier | UTC trigger | Result |
|---|---|---|
| `project-data` collection | Every hour :00; daily at 00:00:00 | Shared page lists, replica revision IDs and categories; complete daily snapshots |
| `assessment_log` | Daily idle after 00:00 | Adjacent saved assessment differences |
| `dyks` | Hourly :00, deferred | Revision-aware completed DYK entries, nominees and statistics |
| `new_pages` | Idle after 00:00; hourly retries while behind | Keyword-selected creations and redirect conversions |
| `assessment_lists` | Daily idle after 00:00 | Quality and project-review lists |
| `enwp_key_articles` | Daily idle after 00:00 | English importance/quality comparisons |
| `pageviews` | 19:00 normally; hourly :00 retries while behind | Project and task-force rankings from verified traffic |
| `pexbot` | Daily idle after 00:00 | Delegated maintenance refresh requests |
| Newsletter collection | Daily idle after 00:00, due retries | Updated saved facts for eligible unpublished drafts |
| `quality-analysis` collection | Hourly :02, idle after reports | Saved article/list text lengths |
| `quality-authorship` collection | Hourly :02, idle after reports | Rating histories and all-grade authorship |
| Website collection | Every hour :00 | Saved reviews, showcases and maintenance data |

Collection identifiers are scheduler work, not `run_once(tasks=...)` wiki-task
names. All daily consumers obtain their required committed project data before
preparation. Page lists are collected first, followed by source data and then
dependent reports. Hourly work at midnight uses the daily observation; later
hours share disposable current-hour Parquet. Startup recovery does not move
the next hourly boundary. Independent reports run concurrently after source collection and daily
newsletter preparation. Article statistics wait until those reports finish. PexBot skips reports
updated by it within the preceding 24 hours.

Each filename names the completed UTC day, captured at the next midnight.
Every file comes from a fresh full query. Missed dates stay missing; actual
query time is recorded separately from midnight. The
[retirement checklist](transition.md) tracks remaining historical-source
dependencies.

Pageviews uses titles, classes, importance and task-force flags from the saved
closing observation for its report date, even on delayed retries. For example,
November 2 traffic uses `20261102.parquet`, captured at November 3 midnight;
it never substitutes November 3 membership. Missing historical files block the
report. All acquisition and calculation waits until 19:00 UTC, including catch-up;
source readiness is checked.
Continuous retained page histories receive only missing
tails; gapped histories and sparse supplements trigger a full-history fetch.
Detailed daily observations are saved independently of wiki publication and
can be reused by other consumers.

## Preview selected routines

Submit a one-off Toolforge job using the pinned runtime launcher:

```shell
toolforge jobs run aranami-preview --image python3.13 --no-filelog --mount=all \
  --command 'tool_dir=/data/project/aranami; set -eu; . "$tool_dir/app/scripts/toolforge/runtime-env.sh"; export PYWIKIBOT_DIR="$tool_dir"; exec "$runtime_python" -c "from runtime import run_once; run_once(dry=True, tasks=[\"new_pages\", \"pageviews\"])"'
toolforge jobs logs aranami-preview
```

Preview writes are isolated under `dry-run/`. Existing production snapshots
may be read, but new preview data cannot advance live datasets, publication
baselines, completion status or PexBot actions. Inspect summaries and exact
`.wikitext` proposals, then delete the completed job definition before reuse.

## Run an immediate update

When that routine is idle, use the same one-off pattern with
`run_once(dry=False, tasks=["assessment_lists"])`. This authorizes live wiki
publication. The public API is
`run_once(date=None, dry=False, tasks=None, clear_cache=False)`; `tasks=None`
selects all routines. `date` is a report anchor, not a time machine for project
membership or Pageviews readiness. Normal startup and immediate work preserve
recurring schedules. Reserve cache clearing for deliberate revalidation.

## Managed report settings

Generated ranges are paired comments, for example:

```wikitext
<!-- aranami begin="assessment-log" days="30" -->
...generated history...
<!-- aranami end="assessment-log" -->
```

New pages uses `new-pages` and retains the previous calendar month by default;
`days` can override that window. Traffic uses `page_views` and
`history-days="800"`, plus `<!-- report date YYYY-MM-DD -->`. Missing,
duplicate, reversed or ambiguous required markers prevent publication. Preserve
attributes and text outside ranges; keep functional section tags outside them.
Creating initial markers or historical backfills is separate wiki maintenance.

Assessment changes compare page IDs, retain removed titles, and do not equate
project departure with page deletion. Adjacent unchanged snapshots may record
`無變更`; initial observations and gaps do not. DYK charts require `dyk`,
`dykn`, `dyk-chart-x` and `dyk-chart-y` ranges with comma-space CSV chart values.

## Prepare a newsletter

Open [Newsletter drafts](https://aranami.toolforge.org/newsletter/) and select
an unpublished issue or retained data date. Copy the literal wikitext, review
its evidence and fill editorial sections, then publish manually on Wikipedia.
January combines a quarterly issue with a separate annual feature. The website
never collects sources or publishes edits when opened. See
[Newsletter drafts](webservice/newsletter.md) for dates, missing evidence and
copying; [Newsletter collection](tasks/newsletter.md) explains source history.
