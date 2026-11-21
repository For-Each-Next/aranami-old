/** Render draft selections and keep wikitext available as literal text. */
import { Fragment } from "@vue/runtime-dom";
import { jsx, iconHref, attribute, display, hasContent } from "./rendering.js";
import { NewsletterDraft, Time } from "./shared.jsx";

export function NewsletterContents(context) {
    const { drafts, heading } = context;
    return (
        <ul>
            {(drafts ?? []).length ? (
                (drafts ?? []).map((draft, draftIndex) => (
                    <li key={draftIndex}>
                        <a href={"#newsletter-page-" + attribute(draftIndex + 1)}>
                            {display(draft?.heading)}
                        </a>
                    </li>
                ))
            ) : (
                <li>
                    <a href="#main">{display(heading)}</a>
                </li>
            )}
        </ul>
    );
}

export function Newsletter(context) {
    const {
        archived_issue,
        available,
        draft_history,
        drafts,
        introduction,
        issue_choices,
        locale,
        selected_issue,
        t,
    } = context;
    return (
        <div data-newsletter-content={""}>
            <p class="page-description">{display(introduction)}</p>
            <form
                class="newsletter-controls"
                action="/newsletter/"
                method="get"
                data-newsletter-issue-form={""}
            >
                <div class="field ui-field newsletter-issue-field">
                    <div class="ui-label">
                        <label class="ui-label__label" for="newsletter-issue">
                            <span class="ui-label__label__text">{t.newsletter.issue}</span>
                        </label>
                    </div>
                    <div class="ui-field__control newsletter-issue-selection">
                        <select id="newsletter-issue" class="ui-select" name="issue" required>
                            {hasContent(archived_issue) ? (
                                <option value={attribute(selected_issue)} selected disabled hidden>
                                    {display(selected_issue)}
                                    {" ("}
                                    {display(t.newsletter.choice?.archived)}
                                    {")"}
                                </option>
                            ) : null}
                            {(issue_choices ?? []).map((choice, choiceIndex) => (
                                <option
                                    key={choiceIndex}
                                    value={attribute(choice?.value)}
                                    {...(hasContent(choice?.checked) ? { selected: true } : {})}
                                >
                                    {display(choice?.value)}
                                    {" ("}
                                    {display(choice?.label)}
                                    {")"}
                                </option>
                            ))}
                        </select>
                        <noscript>
                            <button
                                type="submit"
                                class="ui-button ui-button--action-default ui-button--weight-normal"
                            >
                                {t.newsletter.issue_view}
                            </button>
                        </noscript>
                    </div>
                </div>
                <input type="hidden" name="lang" value={attribute(locale)} />
            </form>
            <div
                class="ui-message ui-message--warning ui-message--inline"
                role="status"
                hidden
                data-newsletter-load-status={""}
                data-failure={t.newsletter.load_failed}
            >
                <svg class="ui-icon ui-message__icon" viewBox="0 0 20 20" aria-hidden="true">
                    <use href={iconHref(context, "message-notice")}></use>
                </svg>
                <div class="ui-message__content"></div>
            </div>
            <div data-newsletter-result={""}>
                {hasContent(draft_history?.dates) || hasContent(draft_history?.selected) ? (
                    <form class="newsletter-date-controls" action="/newsletter/" method="get">
                        <div class="field ui-field newsletter-date-field">
                            <div class="ui-label">
                                <label
                                    class="ui-label__label"
                                    id="newsletter-date-label"
                                    for="newsletter-data-date"
                                >
                                    <span class="ui-label__label__text">
                                        {display(t.newsletter.history?.date)}
                                    </span>
                                </label>
                            </div>
                            <div class="ui-field__control newsletter-date-selection">
                                <div class="ui-text-input">
                                    <input
                                        class="ui-text-input__input"
                                        id="newsletter-data-date"
                                        name="date"
                                        type="date"
                                        value={attribute(draft_history?.form_date)}
                                        {...(hasContent(draft_history?.minimum)
                                            ? {
                                                  min: attribute(draft_history?.minimum),
                                                  max: attribute(draft_history?.maximum),
                                                  list: "newsletter-saved-dates",
                                              }
                                            : {})}
                                        required
                                    />
                                </div>
                                <noscript>
                                    <button
                                        type="submit"
                                        class="ui-button ui-button--action-default ui-button--weight-normal"
                                    >
                                        {display(t.newsletter.history?.view)}
                                    </button>
                                </noscript>
                            </div>
                        </div>
                        <input type="hidden" name="issue" value={attribute(selected_issue)} />
                        <input type="hidden" name="lang" value={attribute(locale)} />
                        {hasContent(draft_history?.dates) ? (
                            <datalist id="newsletter-saved-dates">
                                {(draft_history?.dates ?? []).map((day, dayIndex) => (
                                    <option key={dayIndex} value={attribute(day)}></option>
                                ))}
                            </datalist>
                        ) : null}
                    </form>
                ) : (
                    <p class="context">{display(t.newsletter.history?.unavailable)}</p>
                )}
                {hasContent(draft_history?.missing) ? (
                    <div class="ui-message ui-message--notice" role="status">
                        <svg class="ui-icon ui-message__icon" viewBox="0 0 20 20" aria-hidden="true">
                            <use href={iconHref(context, "message-notice")}></use>
                        </svg>
                        <div class="ui-message__content">{display(t.newsletter.history?.missing)}</div>
                    </div>
                ) : hasContent(draft_history?.selected) && hasContent(available) ? (
                    <p class="context newsletter-observation">
                        {display(t.newsletter.history?.through)}{" "}
                        <time datetime={attribute(draft_history?.selected)}>
                            {display(draft_history?.selected)}
                        </time>
                        {" · "}
                        {display(t.newsletter.history?.generated)}{" "}
                        {Time({
                            ...context,
                            time: draft_history?.generated,
                        })}
                    </p>
                ) : null}
                {!hasContent(available) && !hasContent(draft_history?.missing) ? (
                    <div class="ui-message ui-message--notice" role="status">
                        <svg class="ui-icon ui-message__icon" viewBox="0 0 20 20" aria-hidden="true">
                            <use href={iconHref(context, "message-notice")}></use>
                        </svg>
                        <div class="ui-message__content">{t.newsletter.unavailable}</div>
                    </div>
                ) : null}
                {hasContent(available)
                    ? (drafts ?? []).map((draft, draftIndex) => (
                          <section
                              key={draftIndex}
                              class="newsletter-draft"
                              id={"newsletter-page-" + attribute(draftIndex + 1)}
                              aria-labelledby={"newsletter-heading-" + attribute(draftIndex + 1)}
                          >
                              <h2 id={"newsletter-heading-" + attribute(draftIndex + 1)}>
                                  {display(draft?.heading)}
                              </h2>
                              {(draft?.charts ?? []).length ? (
                                  <div class="newsletter-charts">
                                      {draft.charts.map((chart) => (
                                          <figure key={chart.filename} lang={attribute(chart.language)}>
                                              <img data-newsletter-chart-src={attribute(chart.url)} alt={attribute(chart.title)} loading="lazy" />
                                              <figcaption>
                                                  <a href={attribute(chart.url)} download={attribute(chart.filename)}>
                                                      {display(chart.title)} · {display(chart.label)}
                                                  </a>
                                                  {hasContent(chart.source_url) ? (
                                                      <>
                                                          {" ("}
                                                          <a href={attribute(chart.source_url)}>{t.newsletter.chart_source}</a>
                                                          {")"}
                                                      </>
                                                  ) : null}
                                              </figcaption>
                                          </figure>
                                      ))}
                                  </div>
                              ) : null}
                              {NewsletterDraft({
                                  ...context,
                                  draft: draft,
                                  draft_index: draftIndex + 1,
                              })}
                              <div class="newsletter-copy-controls">
                                  <button
                                      type="button"
                                      class="ui-button ui-button--action-default ui-button--weight-normal"
                                      data-newsletter-copy={
                                          "newsletter-text-" + attribute(draftIndex + 1)
                                      }
                                      data-copy-success={attribute(t.newsletter.copied)}
                                      data-copy-failure={attribute(t.newsletter.copy_fallback)}
                                      aria-describedby={
                                          "newsletter-copy-status-" + attribute(draftIndex + 1)
                                      }
                                  >
                                      {display(t.newsletter["copy"])}
                                  </button>
                                  <a
                                      class="ui-button ui-button--fake-button ui-button--fake-button--enabled ui-button--action-default ui-button--weight-normal"
                                      href={attribute(draft?.url)}
                                  >
                                      {display(t.newsletter.view_page)}
                                  </a>
                                  <a
                                      class="ui-button ui-button--fake-button ui-button--fake-button--enabled ui-button--action-progressive ui-button--weight-primary"
                                      href={attribute(draft?.edit_url)}
                                  >
                                      {display(t.newsletter.edit_page)}
                                  </a>
                                  <span
                                      id={"newsletter-copy-status-" + attribute(draftIndex + 1)}
                                      role="status"
                                      aria-live="polite"
                                      data-newsletter-status={""}
                                  ></span>
                              </div>
                          </section>
                      ))
                    : null}
            </div>
        </div>
    );
}
