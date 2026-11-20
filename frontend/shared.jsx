/** Render shared dialogs, timestamps and editor article tables. */
import { jsx, iconHref, attribute, display, hasContent, OptionalLink } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { AssessmentChips } from "./articles.jsx";

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
                                                <OptionalLink href={attribute(article?.listing_url)}>
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
                                        {hasContent(article?.review_url) ? (
                                            <span class="analysis-review">
                                                {display(quality_authorship?.parenthesis_open)}
                                                <a href={attribute(article?.review_url)}>
                                                    {display(t.quality_analysis.review)}
                                                </a>
                                                {display(quality_authorship?.parenthesis_close)}
                                            </span>
                                        ) : null}
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
