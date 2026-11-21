/** Render shared dialogs, timestamps and editor article tables. */
import { jsx, iconHref, attribute, display, format, hasContent, OptionalLink } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { AssessmentChips } from "./articles.jsx";

/** Present bounded server pages with the same controls as local tables. */
export function TablePager({ paging, action, fields, title, css, dataset, t }) {
    const navigation = [
        ["first", t.reports.first],
        ["previous", t.backlog.previous],
        ["next", t.backlog.next],
        ["last", t.reports.last],
    ];
    const [pagePrefix, pageSuffix] = t.quality_analysis.page_number.split("{page}");
    return (
        <nav class={`ui-table-pager ${css}`} aria-label={title}>
            <form class="page-size ui-table-pager__start" action={action} method="get">
                {Object.entries(fields).map(([name, value]) => (
                    <input key={name} name={name} value={attribute(value)} type="hidden" />
                ))}
                <label>
                    {t.reports.page_size}{" "}
                    <select name="size" value={paging?.size}>
                        {(paging?.size_choices ?? []).map(count => (
                            <option key={count} value={count}>{format(t.reports.rows, { count })}</option>
                        ))}
                    </select>
                </label>
            </form>
            <div class="ui-table-pager__center">{display(paging?.label)}</div>
            <div class="ui-table-pager__end">
                {navigation.map(([key, label]) => (
                    <Fragment key={key}>
                        {paging?.[key] ? (
                            <a href={attribute(paging[key])} aria-label={label}
                               class="ui-button ui-button--fake-button ui-button--fake-button--enabled"
                               rel={key === "previous" ? "prev" : key === "next" ? "next" : undefined}
                               data-dataset-page={dataset ? "" : undefined}>{label}</a>
                        ) : (
                            <button type="button" class="ui-button" disabled>{label}</button>
                        )}
                        {dataset && key === "previous" ? (
                            <form action={action} method="get">
                                {Object.entries(fields).map(([name, value]) => (
                                    <input key={name} name={name} value={attribute(value)} type="hidden" />
                                ))}
                                <input type="hidden" name="size" value={paging.size} />
                                <label class="quality-page-number">
                                    {pagePrefix}<input class="cdx-text-input__input" type="number" name="page" inputmode="numeric"
                                        min="1" max={paging.page_count} value={paging.page} required aria-label={t.quality_analysis.go_to_page}
                                        aria-description={format(t.data.page, { page: paging.page, total: paging.page_count })} />{pageSuffix}
                                </label>
                                <button type="submit" hidden>{t.backlog.go}</button>
                            </form>
                        ) : null}
                    </Fragment>
                ))}
            </div>
        </nav>
    );
}

export function ArticleSummary(context) {
    const { card } = context;
    return (
        <span class="article-summary">
            <bdi lang="zh">{display(card?.link)}</bdi> {AssessmentChips(context)}
        </span>
    );
}

export function NewsletterDraft(context) {
    const { draft, draft_index, t } = context;
    return (
        <details class="ui-accordion newsletter-code">
            <summary>
                <h3 class="ui-accordion__header">
                    <span id={"newsletter-code-label-" + attribute(draft_index)}>
                        <span lang="zh">{display(draft?.title)}</span>
                        {t.newsletter.generated_source}
                    </span>
                </h3>
            </summary>
            <div class="ui-accordion__content">
                <div class="ui-text-area newsletter-text">
                    <textarea
                        id={"newsletter-text-" + attribute(draft_index)}
                        class="ui-text-area__textarea"
                        aria-labelledby={
                            "newsletter-heading-" +
                            attribute(draft_index) +
                            " newsletter-code-label-" +
                            attribute(draft_index)
                        }
                        lang="zh"
                        dir="ltr"
                        rows="8"
                        spellcheck="false"
                        data-newsletter-wikitext={""}
                        readonly
                    >
                        {display(draft?.text)}
                    </textarea>
                </div>
            </div>
        </details>
    );
}

export function popup(
    context,
    children,
    dialog_id,
    dialog_title,
    return_to,
    class_name = "",
    opened = false,
) {
    const { t } = context;
    return (
        <dialog
            id={attribute(dialog_id)}
            class={
                "ui-dialog page-updates" + (hasContent(class_name) ? " " + attribute(class_name) : "")
            }
            aria-labelledby={attribute(dialog_id) + "-heading"}
            {...(hasContent(opened) ? { open: true } : {})}
        >
            <header class="ui-dialog__header">
                <h3 id={attribute(dialog_id) + "-heading"} class="ui-dialog__header__title">
                    {display(dialog_title)}
                </h3>
                <button
                    type="button"
                    class="ui-button ui-dialog__header__close-button"
                    command="close"
                    commandfor={attribute(dialog_id)}
                    autofocus
                    aria-label={t.ops.close}
                >
                    {"×"}
                </button>
                <noscript>
                    <a href={attribute(return_to)}>{t.ops.close}</a>
                </noscript>
            </header>
            <div class="ui-dialog__body">{display(children)}</div>
        </dialog>
    );
}

export function table_labels(context) {
    return {
        "data-quality-authorship-table": "",
        "data-page-number": attribute(context.t?.quality_analysis?.page_number),
        "data-go-to-page": attribute(context.t?.quality_analysis?.go_to_page),
        "data-first": attribute(context.t?.reports?.first),
        "data-last": attribute(context.t?.reports?.last),
        "data-next": attribute(context.t?.backlog?.next),
        "data-prev": attribute(context.t?.backlog?.previous),
        "data-rows": attribute(context.t?.reports?.rows),
        "data-page-size": attribute(context.t?.reports?.page_size),
        "data-page-status": attribute(context.t?.reports?.page_status),
        "data-sort-caption": attribute(context.t?.quality_authorship?.sort_caption),
    };
}

export function article_table(context, articles, title) {
    const { quality_authorship, t } = context;
    return (
        <div class="quality-authorship-table" {...table_labels(context)} data-default-sort="column3">
            <div class="ui-table">
                <div
                    class="ui-table__table-wrapper table-scroll"
                    tabindex="0"
                    role="region"
                    aria-label={attribute(title)}
                >
                    <table class="ui-table__table quality-data-table quality-author-articles">
                        <caption class="visually-hidden">{display(title)}</caption>
                        <colgroup>
                            <col class="quality-column-ordinal" />
                            <col class="quality-column-title" />
                            <col class="quality-column-grade" />
                            <col class="quality-column-listed" />
                        </colgroup>
                        <thead>
                            <tr>
                                <th scope="col" class="ui-table__table__cell--align-number">
                                    {"#"}
                                </th>
                                <th scope="col">{t.quality_authorship.article}</th>
                                <th scope="col" data-sort-type="number">
                                    {t.quality_authorship.grade}
                                </th>
                                <th scope="col">{t.quality_authorship.listed}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(articles ?? []).map((article, articleIndex) => (
                                <tr
                                    key={articleIndex}
                                    data-matrix-page={attribute(article?.page_id)}
                                    {...(article?.default_selected !== undefined &&
                                    !hasContent(article?.default_selected)
                                        ? {
                                              hidden: true,
                                              "data-cohort": "0",
                                          }
                                        : {})}
                                >
                                    <td class="ui-table__table__cell--align-number">
                                        {display(
                                            article?.display_number !== undefined
                                                ? article?.display_number
                                                : articleIndex + 1,
                                        )}
                                    </td>
                                    <td data-sort={attribute(article?.title_label)}>
                                        <a href={attribute(article?.url)}>
                                            {display(article?.title_label)}
                                        </a>
                                        {hasContent(article?.coauthors_label) ? (
                                            <>
                                                {" "}
                                                <span
                                                    class="quality-authorship-coauthors"
                                                    role="img"
                                                    title={attribute(article?.coauthors_label)}
                                                    aria-label={attribute(article?.coauthors_label)}
                                                >
                                                    <svg
                                                        width="16"
                                                        height="16"
                                                        viewBox="0 0 20 20"
                                                        aria-hidden="true"
                                                        focusable="false"
                                                    >
                                                        <use
                                                            href={iconHref(context, "message-notice")}
                                                        ></use>
                                                    </svg>
                                                </span>
                                            </>
                                        ) : null}
                                    </td>
                                    <td data-sort={attribute(article?.grade_order)}>
                                        {display(article?.grade_label)}
                                    </td>
                                    <td data-sort={attribute(article?.date || "")}>
                                        {hasContent(article?.date) ? (
                                            <>
                                                <OptionalLink
                                                    href={attribute(article?.review_url)}
                                                    title={attribute(t.quality_analysis.review)}
                                                >
                                                    <time datetime={attribute(article?.date)}>
                                                        {display(article?.date_label)}
                                                    </time>
                                                </OptionalLink>
                                                <span class="context">
                                                    {display(quality_authorship?.parenthesis_open)}
                                                    {display(article?.age)}
                                                    {display(quality_authorship?.parenthesis_close)}
                                                </span>
                                            </>
                                        ) : (
                                            <span class="context">
                                                {display(t.quality_analysis.unknown_listing)}
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
    );
}

export function SourceUpdated(context) {
    const { t, updated } = context;
    return hasContent(updated) ? (
        <p class="source-updated">
            {t.snapshot.updated} {Time({ ...context, time: updated?.time })}
        </p>
    ) : null;
}

export function Time(context) {
    const { time } = context;
    return hasContent(time?.known) ? (
        <time datetime={attribute(time?.value)}>{display(time?.label)}</time>
    ) : (
        display(time?.label)
    );
}
