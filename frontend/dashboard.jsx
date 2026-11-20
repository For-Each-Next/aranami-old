/** Build the dashboard from the current saved observations. */
import { jsx, iconHref, attribute, display, hasContent } from "./rendering.js";
import { Fragment } from "@vue/runtime-dom";
import { ArticleCards, Highlights, Reviews } from "./articles.jsx";
import { SourceUpdated } from "./shared.jsx";

export function DashboardContents(context) {
    const { reviews, sections, t } = context;
    return (
        <ul>
            {hasContent(reviews) ? (
                <li>
                    <a href="#reviews">{t.reviews.heading}</a>
                </li>
            ) : null}
            <li>
                <a href="#discussions">{t.reviews.discussions}</a>
            </li>
            {(sections ?? []).map((section, sectionIndex) => (
                <li key={sectionIndex}>
                    <a href={"#homepage-" + attribute(section?.key)}>{display(section?.title)}</a>
                </li>
            ))}
        </ul>
    );
}

export function Dashboard(context) {
    const { discussions, discussions_url, notice, t } = context;
    return (
        <>
            {hasContent(notice) ? (
                <div class="ui-message ui-message--notice" role="status">
                    <svg class="ui-icon ui-message__icon" viewBox="0 0 20 20" aria-hidden="true">
                        <use href={iconHref(context, "message-notice")}></use>
                    </svg>
                    <div class="ui-message__content">{display(notice)}</div>
                </div>
            ) : null}
            {Reviews(context)}
            <section class="section-flat" id="discussions" aria-labelledby="discussions-heading">
                <h2 id="discussions-heading">{t.reviews.discussions}</h2>
                <p class="page-description">
                    {t.discussions.recent_intro}{" "}
                    <a href={attribute(discussions_url)}>{t.discussions.all}</a>
                </p>
                {hasContent(discussions) ? (
                    <>
                        {ArticleCards({ ...context, section: discussions })}
                        {SourceUpdated({
                            ...context,
                            updated: discussions?.updated,
                        })}
                    </>
                ) : null}
            </section>
            {Highlights(context)}
        </>
    );
}
