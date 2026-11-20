/** Render shared cards for saved articles, reviews and discussions. */
import { jsx, iconHref, assetUrl, attribute, display, hasContent, OptionalLink } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { SourceUpdated } from "./shared.jsx";

export function ArticleCard(context) {
    const { card, card_index, language_tag, section } = context;
    return (
        <article
            class="ui-card article-card-body"
            aria-labelledby={"article-" + attribute(section?.key) + "-" + attribute(card_index)}
        >
            {hasContent(section?.is_review) ? (
                <a
                    class="review-icon-link ui-card__icon"
                    href={attribute(card?.review_icon_source)}
                    title={attribute(card?.review_icon_label)}
                >
                    {hasContent(card?.review_icon) ? (
                        <img
                            class="review-icon"
                            src={attribute(card?.review_icon)}
                            width="20"
                            height="20"
                            alt={attribute(card?.review_icon_label)}
                        />
                    ) : (
                        <svg
                            class="review-icon"
                            width="20"
                            height="20"
                            viewBox="0 0 20 20"
                            role="img"
                            aria-label={attribute(card?.review_icon_label)}
                            focusable="false"
                        >
                            <title>{display(card?.review_icon_label)}</title>
                            <use href={iconHref(context, card?.review_icon_symbol)}></use>
                        </svg>
                    )}
                </a>
            ) : hasContent(card?.highlight_icon) ? (
                <a
                    class="highlight-icon-link ui-card__icon"
                    href={attribute(card?.highlight_icon?.source)}
                    title={attribute(card?.highlight_icon?.label)}
                >
                    <img
                        class="highlight-icon"
                        src={attribute(card?.highlight_icon?.url)}
                        width="20"
                        height="20"
                        alt={attribute(card?.highlight_icon?.label)}
                    />
                </a>
            ) : hasContent(card?.pageviews_url) ? (
                <img
                    class="article-medal ui-card__icon"
                    src={attribute(
                        assetUrl(
                            context,
                            attribute("assets/icons/medal-") + attribute(card?.rank) + attribute(".svg"),
                        ),
                    )}
                    width="22"
                    height="22"
                    alt={""}
                    aria-hidden="true"
                />
            ) : (
                <span class="article-rank ui-card__icon" aria-hidden="true"></span>
            )}
            <div class="ui-card__text">
                <div class="ui-card__text__title">
                    <h3 id={"article-" + attribute(section?.key) + "-" + attribute(card_index)}>
                        <span class="article-summary">
                            <bdi lang="zh">{display(card?.link)}</bdi>
                        </span>
                    </h3>{" "}
                    {AssessmentChips(context)}
                </div>
                <div class="ui-card__text__description">
                    {!(card?.extract == null) ? (
                        <p class="article-extract">
                            <bdi lang={attribute(card?.extract_language)}>{display(card?.extract)}</bdi>
                        </p>
                    ) : null}
                </div>
                <div class="ui-card__text__supporting-text">
                    {hasContent(card?.review_link) ? (
                        <div class="card-meta review-meta">
                            <span class="card-meta-lead">
                                {display(card?.review_link)}
                                {hasContent(card?.review_dates) ||
                                hasContent(card?.review_counts) ||
                                hasContent(card?.review_section_size)
                                    ? display(language_tag === "en" ? ": " : "：")
                                    : null}
                            </span>
                            {hasContent(card?.review_dates) ||
                            hasContent(card?.review_counts) ||
                            hasContent(card?.review_section_size) ? (
                                <ul class="metadata-items" role="list">
                                    {(card?.review_dates ?? []).map((date, dateIndex) => (
                                        <li key={dateIndex}>
                                            <span class="review-mark" aria-hidden="true">
                                                {display(date?.marker)}
                                            </span>{" "}
                                            <OptionalLink
                                                href={attribute(date?.url)}
                                                title={attribute(date?.label)}
                                            >
                                                <time
                                                    datetime={attribute(date?.value)}
                                                    title={attribute(date?.label)}
                                                    aria-label={attribute(date?.description)}
                                                >
                                                    {display(date?.elapsed)}
                                                </time>
                                            </OptionalLink>
                                        </li>
                                    ))}
                                    {hasContent(card?.review_counts) ? (
                                        <li>
                                            {!(card?.review_counts?.participant_count == null) ? (
                                                <span
                                                    class="review-participants"
                                                    title={attribute(card?.review_counts?.description)}
                                                >
                                                    <span aria-hidden="true">
                                                        {"☺︎ "}
                                                        {display(card?.review_counts?.participant_count)}
                                                    </span>
                                                    <span class="visually-hidden">
                                                        {display(card?.review_counts?.description)}
                                                    </span>
                                                </span>
                                            ) : (
                                                <span class="review-comments">
                                                    {display(card?.review_counts?.description)}
                                                </span>
                                            )}
                                        </li>
                                    ) : null}
                                    {hasContent(card?.review_section_size) ? (
                                        <li>
                                            <span
                                                class="review-section-size"
                                                title={attribute(card?.review_section_size?.description)}
                                            >
                                                {display(card?.review_section_size?.label)}
                                            </span>
                                        </li>
                                    ) : null}
                                </ul>
                            ) : null}
                        </div>
                    ) : hasContent(card?.pageviews_url) ? (
                        <div class="card-meta popularity-meta">
                            <span class="card-meta-lead">
                                <time
                                    datetime={attribute(card?.date?.value)}
                                    title={attribute(card?.date?.value)}
                                >
                                    {display(card?.date?.label)}
                                </time>
                            </span>
                            <ul class="metadata-items" role="list">
                                <li>
                                    <a href={attribute(card?.pageviews_url)} class="pageviews-number">
                                        {display(card?.views)}
                                    </a>
                                </li>
                                {hasContent(card?.site_rank) ? (
                                    <li>
                                        <a class="site-rank" href={attribute(card?.site_rank_url)}>
                                            {display(card?.site_rank)}
                                        </a>
                                    </li>
                                ) : null}
                            </ul>
                        </div>
                    ) : (
                        <ul class="card-meta metadata-items" role="list">
                            {section?.key === "recognized" ? (
                                hasContent(card?.showcase_type) ? (
                                    <li>
                                        <span class="homepage-type">
                                            {display(card?.showcase_type?.description)}
                                        </span>
                                    </li>
                                ) : hasContent(card?.kind) ? (
                                    <li>{display(card?.kind)}</li>
                                ) : null
                            ) : null}
                            {hasContent(card?.date) ||
                            hasContent(card?.scheduled) ||
                            hasContent(card?.date_note) ? (
                                <li>
                                    {display(card?.scheduled)}
                                    {hasContent(card?.date) ? (
                                        <time
                                            datetime={attribute(card?.date?.value)}
                                            title={attribute(card?.date?.value)}
                                        >
                                            {display(card?.date?.label)}
                                        </time>
                                    ) : null}
                                    {hasContent(card?.date_note) ? (
                                        <abbr
                                            class="date-note-marker"
                                            title={attribute(card?.date_note)}
                                            aria-label={attribute(card?.date_note)}
                                        >
                                            {"†"}
                                        </abbr>
                                    ) : null}
                                </li>
                            ) : null}
                            {section?.key !== "recognized" && hasContent(card?.kind) ? (
                                <li>{display(card?.kind)}</li>
                            ) : null}
                        </ul>
                    )}
                </div>
            </div>
        </article>
    );
}

export function ArticleCards(context) {
    const { section } = context;
    return hasContent(section?.empty) ? (
        <div class="ui-message ui-message--notice" aria-live="polite">
            <svg class="ui-icon ui-message__icon" viewBox="0 0 20 20" aria-hidden="true">
                <use href={iconHref(context, "message-notice")}></use>
            </svg>
            <div class="ui-message__content">{display(section?.empty)}</div>
        </div>
    ) : (
        ((ListTag) => (
            <ListTag
                class={
                    "card-grid article-list " +
                    attribute(hasContent(section?.is_review) ? "review-cards" : "highlights")
                }
                role="list"
            >
                {(section?.cards ?? []).map((card, cardIndex) => (
                    <li
                        key={cardIndex}
                        class="article-card"
                        {...(hasContent(card?.rank) && !hasContent(section?.is_review)
                            ? {
                                  value: attribute(card?.rank),
                              }
                            : {})}
                    >
                        {section?.key === "discussions" || section?.is_discussion
                            ? DiscussionCard({
                                  ...context,
                                  card: card,
                                  card_index: cardIndex + 1,
                              })
                            : ArticleCard({
                                  ...context,
                                  card: card,
                                  card_index: cardIndex + 1,
                              })}
                    </li>
                ))}
            </ListTag>
        ))(hasContent(section?.is_review) ? "ul" : "ol")
    );
}

export function AssessmentChips(context) {
    const { card, hide_assessment_chips } = context;
    return hasContent(card?.assessments) && !hasContent(hide_assessment_chips) ? (
        <span class="assessment-chips">
            {(card?.assessments ?? []).map((assessment, assessmentIndex) => (
                <span
                    key={assessmentIndex}
                    class="assessment-chip ui-info-chip ui-info-chip--subtle"
                    data-assessment={attribute(assessment?.dimension)}
                    title={attribute(assessment?.tooltip)}
                >
                    <span class="ui-info-chip__text">{display(assessment?.label)}</span>
                </span>
            ))}
        </span>
    ) : null;
}

export function DiscussionCard(context) {
    const { card, card_index, section } = context;
    return (
        <article
            class="ui-card article-card-body discussion-card"
            aria-labelledby={"article-" + attribute(section?.key) + "-" + attribute(card_index)}
        >
            <span
                class="discussion-activity ui-card__icon"
                data-discussion-activity={attribute(card?.review_activity)}
                role="img"
                title={attribute(card?.review_activity_label)}
                aria-label={attribute(card?.review_activity_label)}
            >
                <svg
                    class="review-icon"
                    width="20"
                    height="20"
                    viewBox="0 0 20 20"
                    aria-hidden="true"
                    focusable="false"
                >
                    <use href={iconHref(context, card?.review_icon_symbol)}></use>
                </svg>
            </span>
            <div class="ui-card__text">
                <div class="ui-card__text__title">
                    <h3 id={"article-" + attribute(section?.key) + "-" + attribute(card_index)}>
                        <span class="article-summary">
                            <bdi lang="zh">{display(card?.link)}</bdi>
                        </span>
                    </h3>{" "}
                    {AssessmentChips(context)}
                </div>
                <div class="ui-card__text__description">
                    <p class="article-extract discussion-extract">
                        <span
                            class="discussion-topic"
                            id={
                                "discussion-topic-" +
                                attribute(section?.key) +
                                "-" +
                                attribute(card_index)
                            }
                        >
                            <bdi lang="zh">{display(card?.discussion_link)}</bdi>
                        </span>
                        {!(card?.extract == null) ? (
                            <bdi class="discussion-opening" lang={attribute(card?.extract_language)}>
                                {display(card?.extract)}
                            </bdi>
                        ) : null}
                    </p>
                </div>
                <div class="ui-card__text__supporting-text">
                    <ul class="card-meta metadata-items" role="list">
                        {(card?.review_dates ?? []).map((date, dateIndex) => (
                            <Fragment key={dateIndex}>
                                <li>
                                    <span class="review-mark" aria-hidden="true">
                                        {display(date?.marker)}
                                    </span>{" "}
                                    <OptionalLink
                                        href={attribute(date?.url)}
                                        title={attribute(date?.label)}
                                    >
                                        <time
                                            datetime={attribute(date?.value)}
                                            title={attribute(date?.label)}
                                            aria-label={attribute(date?.description)}
                                        >
                                            {display(date?.elapsed)}
                                        </time>
                                    </OptionalLink>
                                </li>
                                {hasContent(date?.participants) ? (
                                    <li>
                                        <span
                                            class="review-participants"
                                            title={attribute(date?.participants)}
                                        >
                                            <span aria-hidden="true">
                                                {"☺︎ "}
                                                {display(date?.participant_count)}
                                            </span>
                                            <span class="visually-hidden">
                                                {display(date?.participants)}
                                            </span>
                                        </span>
                                    </li>
                                ) : null}
                            </Fragment>
                        ))}
                        {hasContent(card?.review_section_size) ? (
                            <li>
                                <span
                                    class="discussion-size"
                                    title={attribute(card?.review_section_size?.description)}
                                >
                                    {display(card?.review_section_size?.label)}
                                </span>
                            </li>
                        ) : null}
                    </ul>
                </div>
            </div>
        </article>
    );
}

export function Highlights(context) {
    const { sections } = context;
    return (sections ?? []).map((section, sectionIndex) => (
        <section
            key={sectionIndex}
            class="section-flat report-section"
            aria-labelledby={"homepage-" + attribute(section?.key)}
        >
            <h2 id={"homepage-" + attribute(section?.key)}>{display(section?.title)}</h2>
            {hasContent(section?.description) ? (
                <p class="page-description">{display(section?.description)}</p>
            ) : null}
            {ArticleCards({ ...context, section: section })}
            {SourceUpdated({
                ...context,
                section: section,
                updated: section?.updated,
            })}
        </section>
    ));
}

export function Reviews(context) {
    const { reviews, t } = context;
    return hasContent(reviews) ? (
        <section class="section-flat" id="reviews" aria-labelledby="reviews-heading">
            <h2 id="reviews-heading">{t.reviews.heading}</h2>
            {ArticleCards({ ...context, section: reviews })}
            {SourceUpdated({
                ...context,
                updated: reviews?.updated,
            })}
        </section>
    ) : null;
}
