/** Show saved author totals with their article evidence. */
import { jsx, attribute, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { popup, table_labels, article_table } from "./shared.jsx";

export function QualityAuthorshipContents(context) {
    const { t } = context;
    return (
        <ul>
            <li>
                <a href="#quality-authors">{t.quality_authorship.authors}</a>
            </li>
        </ul>
    );
}

export function QualityAuthorship(context) {
    const { quality_authorship, t } = context;
    return (
        <>
            <p>{t.quality_authorship.intro}</p>
            <p>
                {t.quality_authorship.accuracy_prefix}
                <a href={attribute(quality_authorship?.wikiwho_url)}>{"WikiWho"}</a>
                {t.quality_authorship.accuracy_sources}
                <a href={attribute(quality_authorship?.year_reviews_url)}>
                    {t.quality_authorship.year_reviews}
                </a>
                {t.quality_authorship.accuracy_sources_separator}
                <a href={attribute(quality_authorship?.earlier_intro_url)}>
                    {t.quality_authorship.earlier_intro}
                </a>
                {t.quality_authorship.accuracy_end}
            </p>
            <div data-quality-authorship-results={""}>
                <section aria-labelledby="quality-authors">
                    <h2 id="quality-authors">{t.quality_authorship.authors}</h2>
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
                                                <th
                                                    scope="col"
                                                    class="ui-table__table__cell--align-number"
                                                >
                                                    {"#"}
                                                </th>
                                                <th scope="col">
                                                    {display(t.quality_analysis.contributors)}
                                                </th>
                                                <th scope="col" data-sort-type="number">
                                                    {display(t.quality_authorship.contributions)}
                                                </th>
                                                <th scope="col">
                                                    {display(t.quality_authorship.latest_active)}
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {(quality_authorship?.authors ?? []).map(
                                                (author, authorIndex) => (
                                                    <tr key={authorIndex}>
                                                        <td class="ui-table__table__cell--align-number">
                                                            {display(author?.number)}
                                                        </td>
                                                        <td data-sort={attribute(author?.name)}>
                                                            <a href={attribute(author?.url)}>
                                                                {display(author?.name)}
                                                            </a>
                                                            {display(
                                                                quality_authorship?.parenthesis_open,
                                                            )}
                                                            <a href={attribute(author?.talk_url)}>
                                                                {display(t.quality_authorship.talk)}
                                                            </a>
                                                            {display(
                                                                quality_authorship?.parenthesis_close,
                                                            )}
                                                        </td>
                                                        <td data-sort={attribute(author?.credit)}>
                                                            <a
                                                                href={"#" + attribute(author?.popup_id)}
                                                                aria-controls={attribute(
                                                                    author?.popup_id,
                                                                )}
                                                                aria-haspopup="dialog"
                                                            >
                                                                {display(author?.summary)}
                                                            </a>
                                                            {hasContent(author?.quality_summary) ||
                                                            hasContent(author?.featured_summary) ? (
                                                                <>
                                                                    {display(
                                                                        quality_authorship?.parenthesis_open,
                                                                    )}
                                                                    {hasContent(
                                                                        author?.quality_summary,
                                                                    ) ? (
                                                                        <a
                                                                            href={
                                                                                "#" +
                                                                                attribute(
                                                                                    author?.quality_popup_id,
                                                                                )
                                                                            }
                                                                            aria-controls={attribute(
                                                                                author?.quality_popup_id,
                                                                            )}
                                                                            aria-haspopup="dialog"
                                                                        >
                                                                            {display(
                                                                                author?.quality_summary,
                                                                            )}
                                                                        </a>
                                                                    ) : null}
                                                                    {hasContent(
                                                                        author?.quality_summary,
                                                                    ) &&
                                                                    hasContent(author?.featured_summary)
                                                                        ? " | "
                                                                        : null}
                                                                    {hasContent(
                                                                        author?.featured_summary,
                                                                    ) ? (
                                                                        <a
                                                                            href={
                                                                                "#" +
                                                                                attribute(
                                                                                    author?.featured_popup_id,
                                                                                )
                                                                            }
                                                                            aria-controls={attribute(
                                                                                author?.featured_popup_id,
                                                                            )}
                                                                            aria-haspopup="dialog"
                                                                        >
                                                                            {display(
                                                                                author?.featured_summary,
                                                                            )}
                                                                        </a>
                                                                    ) : null}
                                                                    {display(
                                                                        quality_authorship?.parenthesis_close,
                                                                    )}
                                                                </>
                                                            ) : null}
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
                                                                    <a
                                                                        href={attribute(
                                                                            author?.contributions_url,
                                                                        )}
                                                                    >
                                                                        <time
                                                                            datetime={attribute(
                                                                                author?.last_active
                                                                                    ?.value,
                                                                            )}
                                                                            title={attribute(
                                                                                author?.last_active
                                                                                    ?.title,
                                                                            )}
                                                                        >
                                                                            {display(
                                                                                author?.last_active
                                                                                    ?.label,
                                                                            )}
                                                                        </time>
                                                                    </a>
                                                                    <span class="context">
                                                                        {display(
                                                                            quality_authorship?.parenthesis_open,
                                                                        )}
                                                                        {display(
                                                                            author?.last_active?.age,
                                                                        )}
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
                                                ),
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    )}
                </section>
                {(quality_authorship?.authors ?? []).map((author, authorIndex) => (
                    <Fragment key={authorIndex}>
                        {popup(
                            context,
                            article_table(context, author?.articles, author?.dialog_title),
                            author?.popup_id,
                            author?.dialog_title,
                            "#quality-authors",
                        )}
                        {hasContent(author?.quality_summary)
                            ? popup(
                                  context,
                                  article_table(
                                      context,
                                      author?.quality_articles,
                                      author?.quality_dialog_title,
                                  ),
                                  author?.quality_popup_id,
                                  author?.quality_dialog_title,
                                  "#quality-authors",
                              )
                            : null}
                        {hasContent(author?.featured_summary)
                            ? popup(
                                  context,
                                  article_table(
                                      context,
                                      author?.featured_articles,
                                      author?.featured_dialog_title,
                                  ),
                                  author?.featured_popup_id,
                                  author?.featured_dialog_title,
                                  "#quality-authors",
                              )
                            : null}
                    </Fragment>
                ))}
            </div>
        </>
    );
}
