/** Render saved assessments, charts and contributor directories. */
import { jsx, iconHref, attribute, display, format, hasContent, OptionalLink } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { popup, table_labels, article_table } from "./shared.jsx";

export function DistributionPanel(context, rows, dimension, caption) {
    const { quality_analysis, t } = context;
    return (
        <figure class="analysis-pie-panel">
            <figcaption id={"analysis-" + attribute(dimension) + "-pie-heading"} class="visually-hidden">
                {display(caption)}
            </figcaption>
            <div data-quality-chart={attribute(dimension === "class" ? "grades" : "importance")} data-chart-caption={caption}>
                {display(
                    dimension === "class"
                        ? quality_analysis?.charts?.grades_svg
                        : quality_analysis?.charts?.importance_svg,
                )}
            </div>
            <table class="analysis-pie-key" data-no-pagination="">
                <caption class="visually-hidden">{display(caption)}</caption>
                <thead>
                    <tr>
                        <th scope="col">
                            {display(
                                dimension === "class"
                                    ? t.quality_authorship.grade
                                    : t.quality_analysis.importance,
                            )}
                        </th>
                        <th scope="col">{t.quality_analysis.count_column}</th>
                        <th scope="col">{display(t.quality_analysis.length_distribution)}</th>
                    </tr>
                </thead>
                <tbody>
                    {(rows ?? []).map((category, categoryIndex) => (
                        <tr key={categoryIndex}>
                            <th scope="row">
                                <span class="analysis-assessment-label">
                                    <svg
                                        viewBox="0 0 12 12"
                                        width="12"
                                        height="12"
                                        class="analysis-swatch"
                                        aria-hidden="true"
                                    >
                                        <rect width="12" height="12" fill={attribute(category?.color)} />
                                    </svg>
                                    {dimension === "class" ? (
                                        <a
                                            href="#analysis-articles"
                                            data-chart-group="grade"
                                            data-chart-value={attribute(category?.grade)}
                                            data-chart-label={attribute(category?.label)}
                                        >
                                            {display(category?.label)}
                                        </a>
                                    ) : (
                                        <a
                                            href="#analysis-articles"
                                            data-chart-group="importance"
                                            data-chart-value={attribute(category?.importance)}
                                            data-chart-label={attribute(category?.label)}
                                        >
                                            {display(category?.label)}
                                        </a>
                                    )}
                                </span>
                            </th>
                            <td class="analysis-number">
                                <span class="analysis-count">
                                    <span>{display(category?.count_label)}</span>
                                    <small>{display(category?.share_label)}</small>
                                </span>
                            </td>
                            <td
                                class="analysis-mini-cell"
                                data-quality-length={
                                    attribute(dimension === "class" ? "grade" : "importance") +
                                    ":" +
                                    attribute(
                                        dimension === "class" ? category?.grade : category?.importance,
                                    )
                                }
                            >
                                {display(
                                    quality_analysis?.charts?.lengths?.[
                                        dimension === "class" ? "grade:" + category?.grade : "importance:" + category?.importance
                                    ] ?? <span class="analysis-violin-placeholder">—</span>,
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </figure>
    );
}

export function QualityAnalysisContents(context) {
    const { t } = context;
    return (
        <ul>
            <li>
                <a href="#analysis-overview">{t.quality_analysis.overview}</a>
            </li>
            <li>
                <a href="#analysis-articles">{t.quality_analysis.articles}</a>
            </li>
            <li>
                <a href="#quality-authors">{t.quality_analysis.by_author}</a>
            </li>
        </ul>
    );
}

function AnalysisCheckbox({ label, input }) {
    return (
        <label class="cdx-checkbox cdx-checkbox--inline analysis-checkbox">
            <span class="cdx-checkbox__wrapper">
                <input type="checkbox" class="cdx-checkbox__input" {...input} />
                <span class="cdx-checkbox__icon" aria-hidden="true"></span>
                {label && <span class="cdx-checkbox__label">{label}</span>}
            </span>
        </label>
    );
}

function ListingAuthorsControl({ quality_analysis, t }) {
    return (
        <div class="analysis-authorship-basis">
            <AnalysisCheckbox
                label={t.quality_analysis.use_listing_authors}
                input={{
                    form: "analysis-authorship-basis",
                    name: "listing_authors",
                    value: "1",
                    checked: !!quality_analysis?.listing_authors,
                }}
            />
            <noscript>
                <button type="submit" form="analysis-authorship-basis" class="cdx-button cdx-button--action-progressive cdx-button--weight-primary">
                    {t.quality_analysis.apply}
                </button>
            </noscript>
        </div>
    );
}

function MatrixTable({ quality_analysis, t }) {
    const labels = t.quality_analysis;
    // Saved Vue pages created before grouping still have the original grades.
    const groups = quality_analysis.grade_groups ?? quality_analysis.matrix.grades.map(grade => ({
        value: grade.value,
        label: grade.label,
        grades: [grade],
    }));
    return (
        <div class="table-scroll" tabindex="0" role="region" aria-label={labels.grades}>
            <table class="analysis-matrix" data-no-pagination="">
                <colgroup span="1"></colgroup>
                {groups.map(group => <colgroup key={group.value} span={group.grades.length}></colgroup>)}
                <thead>
                    <tr>
                        <th scope="col" rowspan="2">
                            <AnalysisCheckbox input={{"data-matrix-all": "", "aria-label": labels.select_all}} />
                        </th>
                        {groups.map(group => (
                            <th key={group.value} scope="colgroup" colspan={group.grades.length}>
                                <AnalysisCheckbox label={group.label} input={{
                                    "data-matrix-group": group.value,
                                    checked: group.grades.every(grade => grade.checked),
                                }} />
                            </th>
                        ))}
                    </tr>
                    <tr>
                        {groups.flatMap(group => group.grades.map(grade => (
                            <th key={grade.value} scope="col">
                                <AnalysisCheckbox label={{
                                    article: labels.matrix_article,
                                    list: labels.matrix_list,
                                    unassessed: "-",
                                }[grade.kind] ?? grade.label} input={{
                                    "data-matrix-grade": grade.value,
                                    "aria-label": grade.label,
                                    checked: grade.checked,
                                }} />
                            </th>
                        )))}
                    </tr>
                </thead>
                <tbody>
                    {quality_analysis.matrix.importance.map(importance => (
                        <tr key={importance.value}>
                            <th scope="row">
                                <AnalysisCheckbox label={importance.label} input={{
                                    "data-matrix-importance": importance.value,
                                }} />
                            </th>
                            {groups.flatMap(group => group.grades.map(grade => (
                                <td key={grade.value}>
                                    <AnalysisCheckbox input={{
                                        "data-matrix-cell": "",
                                        "data-grade": grade.value,
                                        "data-grade-group": group.value,
                                        "data-importance": importance.value,
                                        "aria-label": importance.label + " · " + grade.label,
                                        checked: grade.checked,
                                    }} />
                                </td>
                            )))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function AssessmentMatrix(context) {
    const { t, quality_analysis } = context;
    return hasContent(quality_analysis?.matrix) ? (
        <>
            <form
                action="/quality-analysis/"
                method="get"
                class="analysis-selection"
                data-quality-matrix={""}
                ref={form => {
                    if (form) form.qualityOverview = {analysis: quality_analysis, labels: t.quality_analysis};
                }}
                data-authorship-icon={iconHref(context, "message-notice")}
                {...(hasContent(quality_analysis?.metadata_url)
                    ? {
                          "data-metadata-url": attribute(quality_analysis?.metadata_url),
                          ...(quality_analysis.directory_url ? {
                              "data-directory-url": quality_analysis.directory_url,
                              "data-loading-page": t.quality_analysis.loading_page,
                              "data-page-failed": t.quality_analysis.page_failed,
                          } : {
                              "data-selected-page-ids": attribute(
                                  JSON.stringify(quality_analysis?.selected_page_ids ?? null),
                              ),
                          }),
                          "data-loading": attribute(t.quality_analysis.loading_catalog),
                          "data-load-failed": attribute(t.quality_analysis.catalog_failed),
                          "data-retry": attribute(t.quality_analysis.retry),
                      }
                    : {
                          "data-metadata": attribute(JSON.stringify(quality_analysis?.matrix ?? null)),
                      })}
            >
                {hasContent(quality_analysis?.metadata_url) ? (
                    <>
                        <p
                            class="context"
                            data-quality-load-status={""}
                            role="status"
                            aria-live="polite"
                        ></p>
                        <button type="button" class="ui-button" data-quality-retry={""} hidden>
                            {t.quality_analysis.retry}
                        </button>
                    </>
                ) : null}
                {MatrixTable(context)}
                <div class="analysis-year-filter">
                    <label>
                        {t.quality_analysis.year_from}{" "}
                        <input
                            class="cdx-text-input__input"
                            type="number"
                            min="2009"
                            max={attribute(quality_analysis?.matrix?.last_year)}
                            value="2009"
                            data-matrix-from={""}
                            required
                        />
                    </label>
                    <label>
                        {t.quality_analysis.year_to}{" "}
                        <input
                            class="cdx-text-input__input"
                            type="number"
                            min="2009"
                            max={attribute(quality_analysis?.matrix?.last_year)}
                            value={attribute(quality_analysis?.matrix?.last_year)}
                            data-matrix-to={""}
                            required
                        />
                    </label>
                    <AnalysisCheckbox label={t.quality_analysis.unknown_time} input={{"data-matrix-unknown": "", checked: true}} />
                </div>
                {ListingAuthorsControl(context)}
                <div class="analysis-filter-actions">
                    <button type="submit" class="cdx-button cdx-button--action-progressive cdx-button--weight-primary" data-matrix-apply="" disabled>
                        {t.quality_analysis.apply_filters}
                    </button>
                    <p class="context" role="status" data-matrix-status=""
                        data-pending={t.quality_analysis.filters_pending}
                        data-working={t.quality_analysis.filters_working}
                        data-applied={t.quality_analysis.filters_applied}
                        data-failed={t.quality_analysis.filters_failed}
                        data-year-order={t.quality_analysis.filters_year_order}>
                        <span class="quality-detail-loading" data-matrix-spinner="" hidden aria-hidden="true"></span>
                        <span data-matrix-message=""></span>
                    </p>
                </div>
            </form>
        </>
    ) : null;
}

function QualityOverview(context) {
    const { t, quality_analysis } = context;
    return (
        <section id="analysis-overview" aria-labelledby="analysis-overview-heading">
            <h2 id="analysis-overview-heading">{t.quality_analysis.overview}</h2>
            {!hasContent(quality_analysis?.available) ? (
                <p class="notice">{t.quality_analysis.unavailable}</p>
            ) : (
                <>
                    <dl
                        class="analysis-summary analysis-coverage"
                        data-quality-coverage={""}
                        data-coverage-labels={attribute(
                            JSON.stringify(quality_analysis?.coverage_labels ?? null),
                        )}
                        {...(!hasContent(quality_analysis?.matrix)
                            ? {
                                  "data-coverage-comparison": attribute(
                                      JSON.stringify(quality_analysis?.assessment_comparison ?? null),
                                  ),
                              }
                            : {})}
                    >
                        {(quality_analysis?.coverage_cards ?? []).map((card, cardIndex) => (
                            <div key={cardIndex} class="analysis-coverage-card">
                                <dt>
                                    {display(card?.label)}{" "}
                                    <a
                                        href="#analysis-articles"
                                        class="analysis-authorship-info"
                                        data-coverage-open={attribute(card?.key)}
                                        aria-haspopup="dialog"
                                        aria-controls="analysis-coverage-dialog"
                                        aria-label={attribute(
                                            format(t.quality_coverage.info, {
                                                label: card?.label,
                                            }),
                                        )}
                                    >
                                        <svg
                                            width="16"
                                            height="16"
                                            viewBox="0 0 20 20"
                                            aria-hidden="true"
                                            focusable="false"
                                        >
                                            <use href={iconHref(context, "message-notice")}></use>
                                        </svg>
                                    </a>
                                </dt>
                                <dd
                                    data-coverage-count={attribute(card?.key)}
                                    {...(card?.key === "total"
                                        ? {
                                              "data-matrix-total": "",
                                          }
                                        : {})}
                                >
                                    {display(card?.count)}
                                </dd>
                                <dd class="analysis-coverage-updated">
                                    <small>
                                        {hasContent(card?.updated_at) ? (
                                            <>
                                                {display(t.quality_coverage.updated)}{" "}
                                                <time datetime={attribute(card?.updated_at)}>
                                                    {display(card?.updated_label)}
                                                    {" UTC"}
                                                </time>
                                            </>
                                        ) : (
                                            display(t.quality_coverage.unknown_time)
                                        )}
                                    </small>
                                </dd>
                            </div>
                        ))}
                    </dl>
                    {popup(
                        context,
                        <>
                            <p data-coverage-empty={""} hidden></p>
                            <div
                                class="table-scroll"
                                tabindex="0"
                                role="region"
                                aria-labelledby="analysis-coverage-dialog-heading"
                            >
                                <table class="analysis-editor-table">
                                    <thead>
                                        <tr>
                                            <th scope="col">{"#"}</th>
                                            <th scope="col">{display(t.quality_authorship.article)}</th>
                                            <th scope="col" data-coverage-comparison-column={""}>
                                                {display(t.quality_coverage.category)}
                                            </th>
                                            <th scope="col" data-coverage-comparison-column={""}>
                                                {display(t.quality_coverage.pageassessments)}
                                            </th>
                                            <th scope="col" data-coverage-comparison-column={""}>
                                                {display(t.quality_coverage.difference)}
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody data-coverage-rows={""}></tbody>
                                </table>
                            </div>
                            <nav
                                class="ui-table-pager"
                                aria-label={attribute(t.quality_analysis.articles)}
                            >
                                <label class="ui-table-pager__start">
                                    {t.reports.page_size}{" "}
                                    <select value={50}>
                                        {[20, 50, 100].map(count => (
                                            <option key={count} value={count}>{format(t.reports.rows, { count })}</option>
                                        ))}
                                    </select>
                                </label>
                                <span
                                    class="ui-table-pager__center"
                                    data-coverage-page-status={""}
                                    data-template={attribute(t.reports.page_status)}
                                ></span>
                                <div class="ui-table-pager__end">
                                    {[["first", t.backlog.first], ["previous", t.backlog.previous],
                                      ["next", t.backlog.next], ["last", t.backlog.last]].map(([key, label]) => (
                                        <button key={key} type="button" class="ui-button" data-coverage-page={key}>{label}</button>
                                    ))}
                                </div>
                            </nav>
                        </>,
                        "analysis-coverage-dialog",
                        t.quality_coverage.comparison,
                        "#analysis-overview",
                    )}
                    <section id="analysis-distribution" aria-labelledby="analysis-distribution-heading">
                        <h3 id="analysis-distribution-heading">{t.quality_analysis.grades}</h3>
                        <div class="analysis-pies">
                            {DistributionPanel(
                                context,
                                quality_analysis?.grades,
                                "class",
                                t.quality_analysis.grade_pie,
                            )}
                            {hasContent(quality_analysis?.importance_available) ? (
                                DistributionPanel(
                                    context,
                                    quality_analysis?.importance_totals,
                                    "importance",
                                    t.quality_analysis.importance_pie,
                                )
                            ) : (
                                <section>
                                    <h3>{display(t.quality_analysis.importance_pie)}</h3>
                                    <p class="notice">
                                        {display(t.quality_analysis.importance_pending)}
                                    </p>
                                </section>
                            )}
                        </div>
                    </section>
                    <section id="analysis-years" aria-labelledby="analysis-years-heading">
                        <h3 id="analysis-years-heading">{t.quality_analysis.years}</h3>
                        <p
                            class="context"
                            data-undated-count={""}
                            data-label={attribute(t.quality_analysis.years_note)}
                        >
                            {display(
                                format(t.quality_analysis.years_note, {
                                    count: quality_analysis?.unknown_dates,
                                }),
                            )}
                        </p>
                        <div
                            class="analysis-year-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={attribute(t.quality_analysis.years)}
                        >
                            <div data-quality-chart="years" data-chart-caption={t.quality_analysis.years}>
                                {display(quality_analysis?.charts?.years_svg)}
                            </div>
                        </div>
                        <ul class="analysis-legend" aria-label={attribute(t.quality_analysis.grades)}>
                            {(quality_analysis?.year_legend ?? []).map((grade, gradeIndex) => (
                                <li key={gradeIndex}>
                                    <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                                        <rect
                                            width="12"
                                            height="12"
                                            class={"analysis-grade-" + attribute(grade?.grade)}
                                            fill={attribute(grade?.color)}
                                        />
                                    </svg>{" "}
                                    {display(grade?.label)}
                                </li>
                            ))}
                        </ul>
                        <details class="analysis-chart-data">
                            <summary>{t.quality_analysis.chart_data}</summary>
                            <div
                                class="table-scroll"
                                tabindex="0"
                                role="region"
                                aria-label={attribute(t.quality_analysis.years)}
                            >
                                <table class="analysis-year-data" data-no-pagination="">
                                    <caption class="visually-hidden">
                                        {display(t.quality_analysis.years)}
                                    </caption>
                                    <thead>
                                        <tr>
                                            <th scope="col">{display(t.quality_analysis.year)}</th>
                                            {(quality_analysis?.year_table_grades ?? []).map(
                                                (grade, gradeIndex) => (
                                                    <th key={gradeIndex} scope="col">
                                                        {display(grade?.label)}
                                                    </th>
                                                ),
                                            )}
                                            <th scope="col" class="analysis-total-column">
                                                {display(t.quality_analysis.total_column)}
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(quality_analysis?.years ?? []).map((year, yearIndex) => (
                                            <tr key={yearIndex}>
                                                <th scope="row">{display(year?.year)}</th>
                                                {(quality_analysis?.year_table_grades ?? []).map(
                                                    (grade, gradeIndex) => (
                                                        <td key={gradeIndex}>
                                                            {display(year?.grades?.[grade?.value] ?? 0)}
                                                        </td>
                                                    ),
                                                )}
                                                <td class="analysis-total-column">
                                                    {display(year?.count_label)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </details>
                    </section>
                </>
            )}
        </section>
    );
}

function DirectoryFilters({ quality_analysis, t }) {
    const labels = t.quality_analysis;
    return (
        <div class="analysis-filters" data-analysis-controls="" hidden>
            <div class="analysis-filter-row">
                <label class="analysis-filter-field analysis-filter-search">
                    <span class="analysis-filter-title">{labels.search}</span>
                    <span class="cdx-text-input">
                        <input class="cdx-text-input__input" type="search" data-analysis-search="" autocomplete="off" maxlength="200" />
                    </span>
                </label>
                <AnalysisCheckbox label={labels.regex} input={{"data-analysis-regex": ""}} />
            </div>
            <div class="analysis-filter-row">
                <label class="analysis-filter-field analysis-filter-search">
                    <span class="analysis-filter-title">{labels.author_filter}</span>
                    <span class="cdx-text-input">
                        <input class="cdx-text-input__input" type="search" data-analysis-author="" autocomplete="off" maxlength="200" list="analysis-author-names" />
                    </span>
                </label>
                <datalist id="analysis-author-names"></datalist>
                <label class="analysis-filter-field">
                    <span>{labels.author_role}</span>
                    <select class="cdx-select" data-analysis-author-role="">
                        <option value="main">{labels.main_contributors}</option>
                        <option value="significant">{labels.significant_contributors}</option>
                    </select>
                </label>
            </div>
            <div class="analysis-filter-row" role="group" aria-labelledby="analysis-rating-label">
                <span class="analysis-filter-title" id="analysis-rating-label">{labels.rating ?? t.quality_authorship.grade}</span>
                <label class="analysis-filter-field">
                    <span>{t.quality_authorship.grade}</span>
                    <select class="cdx-select" data-analysis-grade-filter="">
                        <option value="">{labels.all_grades}</option>
                        {(quality_analysis.grade_options ?? []).map(grade => (
                            <option key={grade.value} value={grade.value}>{grade.label}</option>
                        ))}
                    </select>
                </label>
                <label class="analysis-filter-field">
                    <span>{labels.importance}</span>
                    <select class="cdx-select" data-analysis-importance-filter="">
                        <option value="">{labels.all_importance}</option>
                        {(quality_analysis.importance_options ?? []).map(importance => (
                            <option key={importance.value} value={importance.value}>{importance.label}</option>
                        ))}
                    </select>
                </label>
                <button type="button" class="cdx-button cdx-button--weight-quiet" data-analysis-reset="">
                    {labels.reset}
                </button>
            </div>
        </div>
    );
}

function ArticleDirectory(context) {
    const { t, quality_analysis, quality_authorship } = context;
    return (
        <section id="analysis-articles" aria-labelledby="analysis-articles-heading">
            <h2 id="analysis-articles-heading">{t.quality_analysis.articles}</h2>
            {hasContent(quality_analysis?.available) ? (
                <>
                    <div
                        class="analysis-directory"
                        data-quality-analysis={""}
                        data-sort-caption={attribute(t.quality_authorship.sort_caption)}
                        data-result-count={attribute(t.quality_analysis.result_count)}
                        data-page-status={attribute(t.reports.page_status)}
                        data-empty={attribute(t.quality_analysis.no_matches)}
                    >
                        {DirectoryFilters(context)}
                        <p role="status" aria-live="polite" data-analysis-result-count={""}></p>
                        <div class="ui-table">
                            <div
                                class="ui-table__table-wrapper table-scroll"
                                tabindex="0"
                                role="region"
                                aria-label={attribute(t.quality_analysis.articles)}
                            >
                                <table class="ui-table__table quality-data-table quality-article-directory">
                                    <caption class="visually-hidden">
                                        {display(t.quality_analysis.articles)}
                                    </caption>
                                    <colgroup>
                                        <col class="quality-column-ordinal" />
                                        <col class="quality-column-title" />
                                        <col class="quality-column-grade" />
                                        <col class="quality-column-importance" />
                                        <col class="quality-column-listed" />
                                        <col class="quality-column-authors" />
                                        <col class="quality-column-prose" />
                                        <col class="quality-column-size" />
                                    </colgroup>
                                    <thead>
                                        <tr>
                                            <th scope="col">{"#"}</th>
                                            <th scope="col">{display(t.quality_authorship.article)}</th>
                                            <th scope="col" data-sort-type="number">
                                                {display(t.quality_authorship.grade)}
                                            </th>
                                            <th scope="col" data-sort-type="number">
                                                {display(t.quality_analysis.importance)}
                                            </th>
                                            <th scope="col">{display(t.quality_authorship.listed)}</th>
                                            <th scope="col">
                                                {display(t.quality_analysis.contributors)}
                                            </th>
                                            <th scope="col" data-sort-type="number">
                                                {display(t.quality_analysis.prose)}
                                            </th>
                                            <th scope="col" data-sort-type="number">
                                                {display(t.quality_analysis.source_size)}
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(quality_analysis?.articles ?? []).map(
                                            (article, articleIndex) => (
                                                <tr
                                                    key={articleIndex}
                                                    data-analysis-row={""}
                                                    data-page-id={attribute(article?.page_id)}
                                                    data-coverage-authorship={attribute(
                                                        hasContent(article?.authorship?.available)
                                                            ? 1
                                                            : 0,
                                                    )}
                                                    data-main-authors={attribute(
                                                        JSON.stringify(article?.main_authors ?? null),
                                                    )}
                                                    data-main-author-labels={attribute(
                                                        JSON.stringify(
                                                            article?.main_author_labels ?? null,
                                                        ),
                                                    )}
                                                    data-significant-authors={attribute(
                                                        JSON.stringify(
                                                            article?.significant_authors ?? null,
                                                        ),
                                                    )}
                                                    {...(hasContent(quality_analysis?.matrix) &&
                                                    !hasContent(article?.default_selected)
                                                        ? {
                                                              hidden: true,
                                                              "data-cohort": "0",
                                                          }
                                                        : {})}
                                                    data-grade={attribute(article?.grade)}
                                                    data-importance={attribute(article?.importance)}
                                                    data-title={attribute(article?.title)}
                                                    data-year={attribute(
                                                        hasContent(article?.listed_date)
                                                            ? article?.listed_date?.slice(0, 4)
                                                            : "",
                                                    )}
                                                    data-measured={attribute(
                                                        !(article?.prose_characters == null) ? 1 : 0,
                                                    )}
                                                >
                                                    <td class="analysis-number">
                                                        {display(articleIndex + 1)}
                                                    </td>
                                                    <td data-sort={attribute(article?.title_label)}>
                                                        <a href={attribute(article?.url)}>
                                                            {display(article?.title_label)}
                                                        </a>{" "}
                                                        <span class="analysis-talk">
                                                            {display(
                                                                quality_authorship?.parenthesis_open,
                                                            )}
                                                            <a href={attribute(article?.talk_url)}>
                                                                {display(t.quality_authorship.talk)}
                                                            </a>
                                                            {display(
                                                                quality_authorship?.parenthesis_close,
                                                            )}
                                                        </span>
                                                    </td>
                                                    <td data-sort={attribute(article?.grade_order)}>
                                                        <span class="analysis-assessment-label">
                                                            <svg
                                                                viewBox="0 0 12 12"
                                                                width="12"
                                                                height="12"
                                                                class="analysis-swatch"
                                                                aria-hidden="true"
                                                            >
                                                                <rect
                                                                    width="12"
                                                                    height="12"
                                                                    fill={attribute(
                                                                        article?.grade_color,
                                                                    )}
                                                                />
                                                            </svg>
                                                            {display(article?.grade_label)}
                                                        </span>
                                                    </td>
                                                    <td data-sort={attribute(article?.importance_order)}>
                                                        <span class="analysis-assessment-label">
                                                            <svg
                                                                viewBox="0 0 12 12"
                                                                width="12"
                                                                height="12"
                                                                class="analysis-swatch"
                                                                aria-hidden="true"
                                                            >
                                                                <rect
                                                                    width="12"
                                                                    height="12"
                                                                    fill={attribute(
                                                                        article?.importance_color,
                                                                    )}
                                                                />
                                                            </svg>
                                                            {display(article?.importance_label)}
                                                        </span>
                                                    </td>
                                                    <td
                                                        data-sort={attribute(article?.listed_date || "")}
                                                    >
                                                        {hasContent(article?.listed_date) ? (
                                                            <OptionalLink
                                                                href={attribute(article?.listing_url)}
                                                                title={attribute(
                                                                    t.quality_analysis.listing_evidence,
                                                                )}
                                                            >
                                                                <time
                                                                    datetime={attribute(
                                                                        article?.listed_date,
                                                                    )}
                                                                >
                                                                    {display(article?.date_label)}
                                                                </time>
                                                            </OptionalLink>
                                                        ) : (
                                                            <span class="context">
                                                                {display(
                                                                    t.quality_analysis.unknown_listing,
                                                                )}
                                                            </span>
                                                        )}
                                                        {hasContent(article?.review_url) ? (
                                                            <>
                                                                {" "}
                                                                <span class="analysis-review">
                                                                    {display(
                                                                        quality_authorship?.parenthesis_open,
                                                                    )}
                                                                    <a
                                                                        href={attribute(
                                                                            article?.review_url,
                                                                        )}
                                                                    >
                                                                        {display(
                                                                            t.quality_analysis.review,
                                                                        )}
                                                                    </a>
                                                                    {display(
                                                                        quality_authorship?.parenthesis_close,
                                                                    )}
                                                                </span>
                                                            </>
                                                        ) : null}
                                                    </td>
                                                    <td
                                                        data-sort={attribute(
                                                            (article?.contributors ?? [])
                                                                .map((item) => item["label"])
                                                                .join(", "),
                                                        )}
                                                    >
                                                        {(article?.contributors ?? []).length ? (
                                                            (article?.contributors ?? []).map(
                                                                (author, authorIndex) => (
                                                                    <Fragment key={authorIndex}>
                                                                        {!hasContent(authorIndex === 0)
                                                                            ? "、"
                                                                            : null}
                                                                        {hasContent(author?.url) ? (
                                                                            <a
                                                                                href={attribute(
                                                                                    author?.url,
                                                                                )}
                                                                            >
                                                                                {display(author?.label)}
                                                                            </a>
                                                                        ) : (
                                                                            <span>
                                                                                {display(author?.label)}
                                                                            </span>
                                                                        )}
                                                                    </Fragment>
                                                                ),
                                                            )
                                                        ) : (
                                                            <span class="context">
                                                                {display(
                                                                    hasContent(
                                                                        article?.authorship?.available,
                                                                    )
                                                                        ? t.quality_analysis
                                                                              .no_main_contributors
                                                                        : t.quality_analysis
                                                                              .main_unavailable,
                                                                )}
                                                            </span>
                                                        )}
                                                        {hasContent(article?.authorship_popup_id) ? (
                                                            <>
                                                                {" "}
                                                                <a
                                                                    class="analysis-authorship-info"
                                                                    href={
                                                                        "#" +
                                                                        attribute(
                                                                            article?.authorship_popup_id,
                                                                        )
                                                                    }
                                                                    aria-controls={attribute(
                                                                        article?.authorship_popup_id,
                                                                    )}
                                                                    aria-haspopup="dialog"
                                                                    title={attribute(
                                                                        article?.authorship_popup_title,
                                                                    )}
                                                                    aria-label={attribute(
                                                                        article?.authorship_popup_title,
                                                                    )}
                                                                >
                                                                    <svg
                                                                        width="16"
                                                                        height="16"
                                                                        viewBox="0 0 20 20"
                                                                        aria-hidden="true"
                                                                        focusable="false"
                                                                    >
                                                                        <use
                                                                            href={iconHref(
                                                                                context,
                                                                                "message-notice",
                                                                            )}
                                                                        ></use>
                                                                    </svg>
                                                                </a>
                                                            </>
                                                        ) : null}
                                                    </td>
                                                    <td
                                                        data-sort={attribute(
                                                            !(article?.prose_characters == null)
                                                                ? article?.prose_characters
                                                                : "",
                                                        )}
                                                        class="analysis-number"
                                                    >
                                                        {display(article?.characters_label)}
                                                        {!(article?.prose_characters == null) ? (
                                                            <>
                                                                {quality_analysis?.locale === "en"
                                                                    ? " "
                                                                    : null}
                                                                <small>
                                                                    {display(t.quality_analysis.words)}
                                                                </small>
                                                            </>
                                                        ) : null}
                                                    </td>
                                                    <td
                                                        data-sort={attribute(
                                                            !(article?.source_bytes == null)
                                                                ? article?.source_bytes
                                                                : "",
                                                        )}
                                                        class="analysis-number"
                                                    >
                                                        {display(article?.source_label)}
                                                        {!(article?.source_bytes == null) ? (
                                                            <>
                                                                {" "}
                                                                <small>{"kB"}</small>
                                                            </>
                                                        ) : null}
                                                    </td>
                                                </tr>
                                            ),
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <p data-analysis-regex-error={""} role="status" hidden>{t.quality_analysis.regex_error}</p>
                        <p data-analysis-no-matches={""} hidden>
                            {t.quality_analysis.no_matches}
                        </p>
                        <nav
                            class="ui-table-pager"
                            aria-label={attribute(t.quality_analysis.articles)}
                            data-analysis-pager={""}
                            hidden
                        >
                            <label class="ui-table-pager__start">
                                {t.reports.page_size}
                                <select data-analysis-size={""}>
                                    <option value="20">{"20"}</option>
                                    <option value="50">{"50"}</option>
                                    <option value="100">{"100"}</option>
                                    {!quality_analysis.directory_url && <option value="all">{display(t.quality_analysis.all_rows)}</option>}
                                </select>
                            </label>
                            <span class="ui-table-pager__center" data-analysis-page-status={""}></span>
                            <div class="ui-table-pager__end">
                                <button type="button" class="ui-button" data-analysis-first={""}>
                                    {t.reports.first}
                                </button>
                                <button type="button" class="ui-button" data-analysis-prev={""}>
                                    {t.backlog.previous}
                                </button>
                                <button type="button" class="ui-button" data-analysis-next={""}>
                                    {t.backlog.next}
                                </button>
                                <button type="button" class="ui-button" data-analysis-last={""}>
                                    {t.reports.last}
                                </button>
                            </div>
                        </nav>
                    </div>
                    {popup(
                        context,
                        <>
                            <p
                                data-chart-article-count={""}
                                data-label={attribute(t.quality_analysis.chart_article_count)}
                            ></p>
                            <div
                                class="table-scroll"
                                tabindex="0"
                                role="region"
                                aria-label={attribute(t.quality_analysis.articles)}
                            >
                                <table class="analysis-chart-article-table quality-data-table quality-chart-articles">
                                    <colgroup>
                                        <col class="quality-column-ordinal" />
                                        <col class="quality-column-title" />
                                        <col class="quality-column-grade" />
                                        <col class="quality-column-importance" />
                                        <col class="quality-column-listed" />
                                        <col class="quality-column-prose" />
                                    </colgroup>
                                    <thead>
                                        <tr>
                                            <th scope="col">{"#"}</th>
                                            <th scope="col">{display(t.quality_authorship.article)}</th>
                                            <th scope="col">{display(t.quality_authorship.grade)}</th>
                                            <th scope="col">{display(t.quality_analysis.importance)}</th>
                                            <th scope="col">{display(t.quality_authorship.listed)}</th>
                                            <th scope="col">{display(t.quality_analysis.prose)}</th>
                                        </tr>
                                    </thead>
                                    <tbody data-chart-article-rows={""}></tbody>
                                </table>
                            </div>
                            <nav
                                class="ui-table-pager"
                                data-chart-pager={""}
                                data-page-status={attribute(t.reports.page_status)}
                                aria-label={attribute(t.quality_analysis.articles)}
                            >
                                <label class="ui-table-pager__start">
                                    {t.reports.page_size}
                                    <select data-chart-size={""}>
                                        <option value="20">{"20"}</option>
                                        <option value="50">{"50"}</option>
                                        <option value="100">{"100"}</option>
                                    </select>
                                </label>
                                <span class="ui-table-pager__center" data-chart-page-status={""}></span>
                                <div class="ui-table-pager__end">
                                    <button type="button" class="ui-button" data-chart-first={""}>
                                        {t.reports.first}
                                    </button>
                                    <button type="button" class="ui-button" data-chart-prev={""}>
                                        {t.backlog.previous}
                                    </button>
                                    <button type="button" class="ui-button" data-chart-next={""}>
                                        {t.backlog.next}
                                    </button>
                                    <button type="button" class="ui-button" data-chart-last={""}>
                                        {t.reports.last}
                                    </button>
                                </div>
                            </nav>
                        </>,
                        "analysis-chart-articles",
                        t.quality_analysis.articles,
                        "#analysis-overview",
                    )}
                    {(quality_analysis?.articles ?? []).map((article, articleIndex) => (
                        <Fragment key={articleIndex}>
                            {hasContent(article?.authorship_popup_id)
                                ? popup(
                                      context,
                                      <>
                                          <p>{display(t.quality_analysis.authorship_note)}</p>
                                          {!hasContent(article?.authorship?.available) ? (
                                              <p class="notice">
                                                  {display(t.quality_analysis.authorship_unavailable)}
                                              </p>
                                          ) : (
                                              <>
                                                  <p class="analysis-authorship-evidence">
                                                      {hasContent(article?.authorship?.range_end) ? (
                                                          <>
                                                              {display(t.quality_analysis.until)}
                                                              <a
                                                                  href={attribute(
                                                                      article?.authorship?.range_end
                                                                          ?.url,
                                                                  )}
                                                              >
                                                                  {display(
                                                                      article?.authorship?.range_end
                                                                          ?.date || t.data.unknown,
                                                                  )}
                                                              </a>
                                                          </>
                                                      ) : null}
                                                      {hasContent(
                                                          article?.authorship?.visualization_url,
                                                      ) ? (
                                                          <>
                                                              {" · "}
                                                              <a
                                                                  href={attribute(
                                                                      article?.authorship
                                                                          ?.visualization_url,
                                                                  )}
                                                              >
                                                                  {display(
                                                                      t.quality_analysis.visualization,
                                                                  )}
                                                              </a>
                                                          </>
                                                      ) : null}
                                                  </p>
                                                  <div
                                                      class="table-scroll"
                                                      tabindex="0"
                                                      role="region"
                                                      aria-label={attribute(
                                                          article?.authorship_popup_title,
                                                      )}
                                                  >
                                                      <table class="analysis-editor-table">
                                                          <thead>
                                                              <tr>
                                                                  <th scope="col">
                                                                      {display(
                                                                          t.quality_authorship.user,
                                                                      )}
                                                                  </th>
                                                                  <th scope="col">
                                                                      {display(
                                                                          t.quality_analysis
                                                                              .editor_share,
                                                                      )}
                                                                  </th>
                                                                  <th scope="col" title={t.quality_analysis.editor_characters_hint}>
                                                                      {t.quality_analysis.editor_characters}
                                                                  </th>
                                                                  <th scope="col" title={t.quality_analysis.editor_bytes_hint}>
                                                                      {t.quality_analysis.editor_bytes}
                                                                  </th>
                                                              </tr>
                                                          </thead>
                                                          <tbody>
                                                              {(article?.authorship?.editors ?? [])
                                                                  .length ? (
                                                                  (
                                                                      article?.authorship?.editors ?? []
                                                                  ).map((author, authorIndex) => (
                                                                      <tr key={authorIndex}>
                                                                          <th scope="row">
                                                                              {hasContent(
                                                                                  author?.url,
                                                                              ) ? (
                                                                                  <a
                                                                                      href={attribute(
                                                                                          author?.url,
                                                                                      )}
                                                                                  >
                                                                                      {display(
                                                                                          author?.name,
                                                                                      )}
                                                                                  </a>
                                                                              ) : (
                                                                                  display(author?.name)
                                                                              )}
                                                                          </th>
                                                                          <td>
                                                                              {display(
                                                                                  author?.share_label,
                                                                              )}
                                                                          </td>
                                                                          <td>{display(author?.characters_label)}</td>
                                                                          <td>
                                                                              {display(
                                                                                  author?.bytes_label,
                                                                              )}
                                                                          </td>
                                                                      </tr>
                                                                  ))
                                                              ) : (
                                                                  <tr>
                                                                      <td colspan="4">
                                                                          {display(
                                                                              t.quality_analysis
                                                                                  .no_top_editors,
                                                                          )}
                                                                      </td>
                                                                  </tr>
                                                              )}
                                                          </tbody>
                                                      </table>
                                                  </div>
                                              </>
                                          )}
                                      </>,
                                      article?.authorship_popup_id,
                                      article?.authorship_popup_title,
                                      "#analysis-articles",
                                      "analysis-authorship-dialog",
                                  )
                                : null}
                        </Fragment>
                    ))}
                </>
            ) : (
                <p class="notice">{t.quality_analysis.unavailable}</p>
            )}
        </section>
    );
}

function QualityContributors(context) {
    const { t, quality_authorship } = context;
    return (
        <section aria-labelledby="quality-authors">
            <h2 id="quality-authors">{t.quality_analysis.by_author}</h2>
            <p>{t.quality_authorship.intro}</p>
            <p>
                {t.quality_authorship.accuracy_prefix}
                <a href={attribute(quality_authorship?.wikiwho_url)}>{"WikiWho"}</a>
                {t.quality_authorship.accuracy_sources}
                <a href={attribute(quality_authorship?.year_reviews_url)}>
                    {t.quality_authorship.year_reviews}
                </a>
                {display(t.quality_authorship.accuracy_sources_separator)}
                <a href={attribute(quality_authorship?.earlier_intro_url)}>
                    {t.quality_authorship.earlier_intro}
                </a>
                {t.quality_authorship.accuracy_end}
            </p>
            {hasContent(quality_authorship?.observed_at) ? (
                <p class="context">
                    {display(t.quality_authorship.evidence_observed)}{" "}
                    <time datetime={attribute(quality_authorship?.observed_at?.value)}>
                        {display(quality_authorship?.observed_at?.label)}
                    </time>
                </p>
            ) : null}
            {!hasContent(quality_authorship?.available) ? (
                <p class="context">{t.quality_authorship.unavailable}</p>
            ) : !hasContent(quality_authorship?.authors) ? (
                <p class="context">{t.quality_authorship.empty}</p>
            ) : (
                <div
                    class="quality-authorship-table"
                    {...table_labels(context)}
                    data-default-sort="column2"
                >
                    <div class="ui-table">
                        <div
                            class="ui-table__table-wrapper table-scroll"
                            tabindex="0"
                            role="region"
                            aria-label={attribute(t.quality_authorship.authors)}
                        >
                            <table class="ui-table__table quality-data-table quality-author-directory">
                                <caption class="visually-hidden">
                                    {display(t.quality_authorship.authors)}
                                </caption>
                                <colgroup>
                                    <col class="quality-column-ordinal" />
                                    <col class="quality-column-title" />
                                    <col class="quality-column-count" />
                                    <col class="quality-column-active" />
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th scope="col" class="ui-table__table__cell--align-number">
                                            {"#"}
                                        </th>
                                        <th scope="col">{display(t.quality_analysis.contributors)}</th>
                                        <th scope="col" data-sort-type="number">
                                            {display(t.quality_authorship.article)}
                                        </th>
                                        <th scope="col">
                                            {display(t.quality_authorship.latest_active)}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(quality_authorship?.authors ?? []).map((author, authorIndex) => (
                                        <tr
                                            key={authorIndex}
                                            data-matrix-author={attribute(author?.name)}
                                            {...(author?.default_selected !== undefined &&
                                            !hasContent(author?.default_selected)
                                                ? {
                                                      hidden: true,
                                                      "data-cohort": "0",
                                                  }
                                                : {})}
                                            {...(author?.page_ids !== undefined
                                                ? {
                                                      "data-page-ids": attribute(
                                                          JSON.stringify(author?.page_ids ?? null),
                                                      ),
                                                  }
                                                : {})}
                                        >
                                            <td class="ui-table__table__cell--align-number">
                                                {display(author?.number)}
                                            </td>
                                            <td data-sort={attribute(author?.name)}>
                                                <a href={attribute(author?.url)}>
                                                    {display(author?.name)}
                                                </a>
                                                {display(quality_authorship?.parenthesis_open)}
                                                <a href={attribute(author?.talk_url)}>
                                                    {display(t.quality_authorship.talk)}
                                                </a>
                                                {display(quality_authorship?.parenthesis_close)}
                                            </td>
                                            <td data-sort={attribute(author?.credit)}>
                                                <a
                                                    href={attribute(
                                                        author?.detail_url ||
                                                            attribute("#") + attribute(author?.popup_id),
                                                    )}
                                                    {...(hasContent(author?.detail_url)
                                                        ? {
                                                              "data-quality-detail": attribute(
                                                                  author?.popup_id,
                                                              ),
                                                              "data-loading": attribute(
                                                                  t.quality_analysis.loading_details,
                                                              ),
                                                              "data-load-failed": attribute(
                                                                  t.quality_analysis.details_failed,
                                                              ),
                                                          }
                                                        : {})}
                                                    aria-controls={attribute(author?.popup_id)}
                                                    aria-haspopup="dialog"
                                                >
                                                    {display(author?.summary)}
                                                </a>
                                            </td>
                                            <td
                                                data-sort={attribute(
                                                    hasContent(author?.last_active)
                                                        ? author?.last_active?.value
                                                        : "",
                                                )}
                                            >
                                                {hasContent(author?.last_active) ? (
                                                    <>
                                                        <a href={attribute(author?.contributions_url)}>
                                                            <time
                                                                datetime={attribute(
                                                                    author?.last_active?.value,
                                                                )}
                                                                title={attribute(
                                                                    author?.last_active?.title,
                                                                )}
                                                            >
                                                                {display(author?.last_active?.label)}
                                                            </time>
                                                        </a>
                                                        <span class="context">
                                                            {display(
                                                                quality_authorship?.parenthesis_open,
                                                            )}
                                                            {display(author?.last_active?.age)}
                                                            {display(
                                                                quality_authorship?.parenthesis_close,
                                                            )}
                                                        </span>
                                                    </>
                                                ) : (
                                                    <span class="context">
                                                        {display(t.data.unknown)}
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}

export function QualityAnalysis(context) {
    const { quality_analysis, quality_authorship, t } = context;
    return (
        <>
            <p class="lead">{t.quality_analysis.intro}</p>
            <p>{t.quality_analysis.listing_intro}</p>
            <p>{t.quality_analysis.author_intro}</p>
            <form id="analysis-authorship-basis" method="get" action="/quality-analysis/" data-authorship-basis="">
                {hasContent(quality_analysis?.all_grades) ? (
                    <input type="hidden" name="all_grades" value="1" />
                ) : null}
                <input type="hidden" name="lang" value={attribute(quality_analysis?.locale)} />
            </form>
            {hasContent(quality_analysis?.matrix) ? AssessmentMatrix(context) : ListingAuthorsControl(context)}
            <div data-quality-results={""}>
                {QualityOverview(context)}
                {ArticleDirectory(context)}
                {QualityContributors(context)}
                {(quality_authorship?.authors ?? []).map((author, authorIndex) => (
                    <Fragment key={authorIndex}>
                        {!hasContent(author?.detail_url)
                            ? popup(
                                  context,
                                  article_table(context, author?.articles, author?.dialog_title),
                                  author?.popup_id,
                                  author?.dialog_title,
                                  "#quality-authors",
                              )
                            : null}
                    </Fragment>
                ))}
            </div>
        </>
    );
}
