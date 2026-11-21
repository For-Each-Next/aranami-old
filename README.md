# Aranami

Aranami (荒波, “rough waves”) maintains Wikipedia project reports and provides
consistency checks and newsletter drafts. It serves
[WikiProject Video games on Chinese Wikipedia](https://zh.wikipedia.org/wiki/WikiProject:电子游戏)
from Toolforge.

Daily reports share a completed-day observation of project membership and
assessments. Hourly reports can use newer observations. Saved article evidence
and daily Pageviews support later reports and newsletter drafts.

## Results

- [Dashboard](https://aranami.toolforge.org/): reviews, main-page appearances,
  upcoming recognized content and popular articles.
- [Discussions](https://aranami.toolforge.org/discussions/): active project-talk
  topics from the past 30 days, grouped by project, article and other pages.
- [Maintenance checks](https://aranami.toolforge.org/checks/):
  metadata inconsistencies and quarterly update hints, grouped by issue type.
  The linked Tampermonkey script fills prepared talk-header repairs for a
  manual diff review.
- [Current quality articles and contributors](https://aranami.toolforge.org/quality-analysis/):
  one current-cohort overview, article directory and author statistics page,
  with universal class filters, listing revisions and saved contribution details.
- [Newsletter drafts](https://aranami.toolforge.org/newsletter/): copyable
  quarterly wikitext and a separate January annual review for manual publication.
- [Reports](https://aranami.toolforge.org/reports/): recorded attempts, confirmed
  updates and recent execution details.
- [Saved data](https://aranami.toolforge.org/data/): source-linked project
  captures with their original metadata, field schema and a bounded preview.

Saved results remain available during source failures. Unknown observations
are not converted to zeroes. Published and cancelled newsletter issues retain
their saved facts; delayed drafts can continue improving.

## Toolforge schedule

| Job | UTC launch | Work |
|---|---|---|
| Web service | Continuous | Serves saved data and generated pages |
| Project snapshot | Daily at 00:00 | Commits the durable completed-day project snapshot |
| Data fetch | Hourly at :02 | Recovers today's snapshot if needed, reads hourly observations and commits structured inputs |
| Data analysis and report updates | Hourly at :10 | Waits for the fetch result and uses saved inputs to calculate, publish wiki reports and prepare website data |
| Pageviews | Hourly at :37 | Collects and publishes eligible traffic reports |
| Article Statistics backfill | On demand | Runs successive batches until the pending cohort has been checked |
| Data completeness check | On demand or Sundays at 03:40 | Audits saved snapshots, report freshness and article coverage |

Daily assessment, newsletter and PexBot work is due after midnight. The next
hourly pass retries incomplete work for the same day and skips confirmed
results. The Pageviews report makes yesterday eligible at 19:00 UTC.
[Toolforge operations](docs/administration.md#register-grouped-jobs)

## Documentation

[Usage](docs/usage.md) covers terminal operations;
[Administration](docs/administration.md) covers deployment and recovery;
[Development](docs/development.md) covers the source layout and offline checks;
[Architecture](docs/architecture.md) defines ownership, data and migration.
The [documentation index](docs/README.md) links component references.

[CHANGELOG](CHANGELOG.md) records the completed releases.
Historical records remain available through normal data readers after old-format
extractors retire. Source is licensed under [CC0 1.0 Universal](LICENSE);
upstream content and bundled assets retain their attributed licenses.

The [saved-data map](docs/data/storage.md) documents the flat data layout,
Parquet schemas, revision shards, migration and each fileset’s consumers.
