# Current quality articles and contributors

The `/quality-analysis/` page combines the current Chinese Wikipedia Video
games quality cohort and its contributor statistics. Former
`/quality-authorship/` links redirect here while preserving language. Only currently selected articles and lists count; historical
promotions and departed project members do not add author credits.

A leading quality-by-importance checkbox matrix selects any current article
class, from featured through unassessed. Grade headers group their article
and list columns, with one column for unassessed pages. The default includes
FA, FL, A, AL, GA and Bplus. The inclusive year range defaults to 2009 through the current
year; unknown dates are included by default through a separate checkbox.
Quality distribution rows show article grades first, list grades next and
unassessed articles last. Matrix labels contain no counts. Every chart and both directories use the
same cohort. Table-local title, author and contribution-type filters further
restrict the article directory without changing the cohort charts.

The unchecked listing-version checkbox uses prepared current-revision
attribution. Checking it selects prepared listing-time evidence. Both are
collected hourly in the background; changing the setting only reads saved
Parquet. Unknown evidence never falls back silently to the other version.

## Overview and article directory

The overview cards show total membership and the immutable report generation's
preparation time. Source observation times remain separate saved metadata.
Quality and importance pies include exact counts and percentages. Their colors
come from the assessment profile; importance colors follow Chinese
[Template:Importance/colour](https://zh.wikipedia.org/w/index.php?oldid=95173028).
Annual columns cover a continuous year range beginning in 2009, retaining
zero-count years. They describe the latest supported listing at each current
grade, not historical annual project totals. Unknown dates stay outside bars.

The annual legend uses the categories and colors actually plotted for the
selected years. Its data table includes only the selected quality columns,
plus the year and total; selected categories with zero values retain their
columns. Narrow screens can scroll the chart horizontally.

The article table shows ordinal, article with talk link, quality, importance,
listing date, main contributors, prose count and page size. Display titles use
spaces instead of underscores; original titles and page IDs retain their
identity. The ordinal column cannot be sorted and follows the displayed order
after sorting, filtering or pagination. Other missing observations sort last.
Table-local filters do not change the whole-cohort overview; the matrix does.
Clicking a chart opens the corresponding article list from saved rows. Its
non-ordinal columns support ascending and descending sorting, keep missing
values last, and reset pagination when the sort changes. Reopening a chart
restores newest-listing-first order. Annual
segments select both year and grade, independently of directory filters. No
source requests occur. The annual data table labels and bolds its total column.
Coverage dialogs list articles whose attribution is still missing, with article
links so those cases can be inspected.

Listing dates link to an explicit retained article oldid when available. Missing
oldids are resolved from the listing date through Wiki Replica revision
metadata. A separately retained review link appears beside the date. A date
without verified revision metadata remains unlinked until acquisition resolves
it; a talk revision is never substituted as an article oldid.

## Prose units and attribution

Prose is measured on the observed current article revision. Each Chinese
character counts as one unit; each Western word or continuous number block
counts as two. Spaces and punctuation are excluded. For example,
`PlayStation 5` counts as four. Shared extraction rules omit references and
other non-prose sections; list grades include readable template values.
Legacy word counts remain readable internally but are never displayed as these
new character units.

Miniature horizontal violin charts sit beside the quality and importance
counts. The horizontal scale is `log(1 + characters)`, with the same catalog
maximum across groups and filters. Density is evaluated on that scale and
clipped at each group's observed minimum and maximum. A shared vertical
scale makes the area proportional to its number of measured articles and
lists. A group with one distinct length is marked at that length.

Dots mark P25 and P75. Vertical lines mark the minimum, median and maximum.
The red cross marks the arithmetic mean. Tooltips show the underlying
character counts, and the accessible label gives the length summary.
Percentiles interpolate linearly between observed lengths. Missing lengths
remain unknown. The browser uses saved density samples and histograms, and
Matplotlib applies the same axis and area rules to the native figures.

NA and Bottom importance groups are omitted. A/AL groups hide when their
current count is zero. Central 68% and 95% intervals use empirical
16th–84th and 2.5th–97.5th percentiles. Page size uses known SQL byte
length while prose is pending.

Main contributors must have a saved attributable byte share strictly greater
than 33%. The article table, main-contributor filter and author directory use
the same threshold; being the largest contributor alone does not qualify.
IP main contributors appear as unlinked anonymous-user labels in the article
table. Acquired evidence with no qualifying main contributor displays None;
missing evidence remains explicitly unavailable.
The adjacent information dialog gives the actual saved attribution revision
endpoint date and significant contributors whose attributable byte share is
at least 10%.
Anonymous contributors link to their public contribution history. The endpoint date links to the exact revision and an XTools WikiWho
visualization; the first revision is not displayed. Missing endpoints remain
unknown. Missing attribution explicitly says that data has not been acquired.
Only a successfully acquired result can say that no editor reached 10%; a
share of exactly 10% qualifies. Both the initial article
dialogs and dynamically created rows use these distinct states.

Existing high-quality attribution can use a saved end-of-listing-day revision
that differs from the review template's explicit oldid. The dialog preserves
that actual proof range; it does not claim that the listing link and attribution
endpoint are the same revision. Author summaries use only the current cohort
and grade, including the verified AL-to-A review-source equivalence.

## Acquisition and cache reuse

The collector first reads current membership, grades, importance, revision IDs
and byte lengths from Wiki Replicas. Required revision boundaries and missing
creation metadata also use read-only SQL first. Content is unavailable on the
replicas, so missing current-page and historical-revision bodies are acquired
in batches of up to fifty exact revisions. Each body is checked against its
expected page and revision identity. Known SQL metadata does not cause an extra
page-info API request. Source APIs that provide no batch operation retain their
bounded per-article request.

Successful history ranges, cutoffs and attribution evidence remain reusable
while their relevant identities and boundaries are valid. An optional metadata
field is filled independently rather than invalidating an attribution proof.
A changed current revision or newly required character measurement requests only
the missing body facts. Partial histories resume their saved predecessor cursor;
unread candidates do not lose their next-pass priority. Presentation-only
importance colors are excluded from the existing rating-history parser identity.

## Saved reports and lifecycle

The raw quality-analysis Parquet retains current membership and measurements.
`data.articles.current_quality` projects it with saved attribution into the
atomic frontend document `data/parsed/current-quality.json`, with one universal
catalog, normal/all-class default charts, article details and author summaries.
Startup serves the existing prepared projection. New projection and chart
preparation run only in the low-priority workers, so article statistics cannot
delay source dispatch or on-wiki reports.
Bounded analysis and authorship passes refresh it after their checkpoints.
Background presentation then renders twelve localized presets into
`data/webservice/quality-page-*.json`. Each preset contains a small initial
page, a server-side directory and individual contributor detail pages.
The browser draws the default figures from the prepared summaries.
Selecting **Apply filters** requests counts and plotted length summaries for
the confirmed cohort. The pies and annual stacked bars use stored counts.
Violin summaries use saved densities and exact length histograms.
Focused figures accept arrow keys, plus/minus
and Home for pan, zoom and reset. Figures link to paginated article lists.
Script-free views use prepared Matplotlib figures and native tables.

Analysis and all-grade authorship keep separate short-lived workers scheduled hourly
at :02 UTC after ordinary collection and regular idle reports finish. The parent retains no article bodies or
worker frames. Each pass checkpoints bounded work and releases parser/native
memory on exit. Foreground work and the protected midnight window stop admission
of new source work, including between individual text measurements.
Queued regular idle reports also stop further statistics work; completed
measurements and history cursors remain saved for the next pass. A nonblocking collection lease prevents duplicate writers.

Reviewed-grade attribution and correction audits run in this idle pass instead
of the regular hourly recognition scan. The first quarter of its budget serves
saved reviewed-grade events, preserving their end-of-listing-day cutoffs.

The authorship pass admits up to eighty history candidates within its overall
240-second budget, allowing approximately ninety seconds for talk history and
up to forty article attempts afterward. Existing successful evidence is skipped.
A completed history batch processes at most fifty selected revision bodies at a
time. Native Polars pools default to two threads unless explicitly configured.
Rendered HTML is bounded to eight MiB per entry and cached by saved generation,
locale, class preset and attribution basis.

## Browser pagination

The initial document includes twenty article rows and the figure summaries.
Search, sorting and paging read the full confirmed cohort on the server and
encode only the requested rows. Page sizes are 20, 50 and 100. Chart and
coverage dialogs request their own pages when opened. The browser retains
up to three recently requested pages for the current document.

Contributor summaries link to separately prepared detail pages. JavaScript
opens the selected detail in a dialog and initializes only that table. Native
links still open a readable detail page without JavaScript. Detail rows follow
the current matrix selection when opened in the enhanced page.

Metadata, directory and detail URLs include their content digest and preset identity.
Only matching saved resources receive immutable browser caching and ETags;
the main HTML continues to use `no-store`. Each preset is committed atomically
with its resources so a request never substitutes a different generation for
the requested digest. Older HTML-only presets remain readable until the next
background preparation.

The browser builds fresh article rows for the visible page after every filter,
sort or page change. Initial and subsequently displayed rows retain the same links,
assessment colors, number formats and attribution controls. Filtering,
sorting and chart dialogs use the saved catalog without contacting upstream
APIs or replicas. Chart dialogs likewise materialize only their visible page
and share the standard pagination footer. Author filtering offers two types:
main contributors shown in the article table, and significant contributors
whose saved attribution share is at least 10%. Suggestions and
matches use these qualified names; editing a page alone does not qualify.
Missing attribution cannot establish significant-contributor membership.

All site table footers share typography, spacing, record counts and navigation
button styling. Contributor tables display one total article count without
quality-subset parentheses. Three-column article-contribution dialogs use a
narrower width. Article, author and chart-dialog ordinal columns use about
four em in directories and five em in dialogs, with room for three-digit ordinals. Page-size values are plain
text. Column headings are centered; ordinal values remain right-aligned.
Chinese grade labels use their first two characters in every table, and
unassessed articles share the unknown-importance gray. Compact assessment,
prose and size columns leave more room for dates and review links. The author
directory spans the full content width, with an 18em activity column that keeps
the date and relative age on one line. Missing rating dates are labeled as not obtained,
including contributor details. Detail downloads keep the count link and show
a compact spinner with accessible loading status and visible failure feedback.

The `rating-history` bundle replaces the former `b-listings` name. It covers
B/BL and lower article/list grades using exact continuous banner transitions.
Reviewed grades retain their independent Article history dates and explicit
oldids or end-of-day cutoffs. Both feed the shared article statistics view.
Existing B-listings evidence and partial scan cursors are read until the first
checkpoint writes the renamed bundle; original evidence remains intact.
